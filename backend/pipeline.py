"""
End-to-end decision loop: signals → options → agent → risk gate → execute → autopsy.

Orchestration lives here so FastAPI routes stay thin.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from agent import analyze_candidate
from config import get_settings
from db.models import AutopsyRow, OptionSnapshot, PortfolioStat, SignalRow, Trade
from db.schema import init_db
from earnings import check_earnings_date
from execution import submit_cash_secured_put
from options import fetch_option_chain, select_candidate_puts, target_expiry
from pnl import PortfolioPnL
from risk_engine import RiskGate, RiskVerdict
from signals import latest_signals
from trade_autopsy import AgentDecision, TradeAutopsy, generate_autopsy

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _broadcast(fn: Optional[BroadcastFn], payload: dict[str, Any]) -> None:
    if fn is None:
        return
    payload = {**payload, "timestamp": datetime.utcnow().isoformat()}
    await fn(payload)


class DecisionPipeline:
    def __init__(
        self,
        *,
        session_factory=None,
        risk_gate: Optional[RiskGate] = None,
        dry_run_orders: bool = True,
        use_gemini: bool = True,
    ) -> None:
        self.session_factory = session_factory or init_db()
        self.risk_gate = risk_gate or RiskGate()
        self.dry_run_orders = dry_run_orders
        self.use_gemini = use_gemini
        self.pnl = PortfolioPnL()
        self._contracts_today = 0
        self._contracts_today_date = date.today()

    def _roll_day_counter(self) -> None:
        today = date.today()
        if today != self._contracts_today_date:
            self._contracts_today = 0
            self._contracts_today_date = today

    def open_capital(self) -> float:
        with self.session_factory() as session:
            trades = (
                session.query(Trade)
                .filter(Trade.executed.is_(True), Trade.status == "open")
                .all()
            )
            return sum((t.strike or 0) * t.contracts * 100.0 for t in trades)

    def portfolio_snapshot(self) -> dict[str, Any]:
        with self.session_factory() as session:
            trades = session.query(Trade).filter(Trade.executed.is_(True)).all()
            snap = self.pnl.snapshot(trades, contracts_today=self._contracts_today)
            return snap.to_dict()

    def list_trades(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            trades = (
                session.query(Trade).order_by(Trade.created_at.desc()).limit(limit).all()
            )
            out = []
            for t in trades:
                autopsy = (
                    session.query(AutopsyRow)
                    .filter(AutopsyRow.trade_id == t.id)
                    .order_by(AutopsyRow.created_at.desc())
                    .first()
                )
                out.append(
                    {
                        "trade": {
                            "id": t.id,
                            "ticker": t.ticker,
                            "decision": t.decision,
                            "strike": t.strike,
                            "expiry": t.expiry,
                            "premium": t.premium,
                            "contracts": t.contracts,
                            "executed": t.executed,
                            "order_id": t.order_id,
                            "status": t.status,
                            "confidence": t.confidence,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                        },
                        "autopsy": autopsy.data if autopsy else None,
                    }
                )
            return out

    async def analyze_ticker(
        self,
        ticker: str,
        *,
        contracts: int = 1,
        broadcast: Optional[BroadcastFn] = None,
    ) -> TradeAutopsy:
        """Run the full 5-layer pipeline for one ticker."""
        self._roll_day_counter()
        ticker = ticker.upper().strip()
        settings = get_settings()

        # --- Layer 1: market signals ---
        signals = latest_signals(ticker)
        sig_dict = signals.to_dict()
        await _broadcast(
            broadcast,
            {"type": "signal_fetched", "ticker": ticker, **sig_dict},
        )

        with self.session_factory() as session:
            session.add(
                SignalRow(
                    ticker=ticker,
                    rsi=signals.rsi,
                    momentum=signals.momentum_5d,
                    volume_ratio=signals.volume_ratio,
                    volatility=signals.volatility_20d,
                    last_close=signals.last_close,
                )
            )
            session.commit()

        # --- Options chain + candidate ---
        expiry = target_expiry(settings.default_days_to_expiry)
        await _broadcast(
            broadcast,
            {
                "type": "option_chain_fetch",
                "ticker": ticker,
                "target_expiry": expiry,
            },
        )
        chain = fetch_option_chain(ticker, expiry)
        candidate = select_candidate_puts(
            ticker, signals.history, signals.last_close, chain
        )

        if candidate is None:
            decision = AgentDecision(
                decision="AVOID",
                confidence=0.2,
                reasoning=f"No liquid CSP candidate found for {ticker} near support.",
                supporting_factors=[],
                contradicting_factors=["No qualifying put contract after liquidity filters"],
            )
            risk = RiskVerdict(False, "No candidate to evaluate", failed_rule="no_candidate")
            autopsy = generate_autopsy(
                ticker=ticker,
                decision=decision,
                candidate=None,
                risk=risk,
                contracts=0,
                signals=sig_dict,
            )
            self._persist(autopsy, contracts=0)
            await _broadcast(broadcast, {"type": "trade_autopsy", "data": autopsy.to_dict()})
            return autopsy

        with self.session_factory() as session:
            session.add(
                OptionSnapshot(
                    ticker=ticker,
                    strike=candidate.contract.strike,
                    expiry=candidate.contract.expiry,
                    bid=candidate.contract.bid,
                    ask=candidate.contract.ask,
                    iv=candidate.contract.iv,
                    iv_rank=candidate.iv_rank,
                )
            )
            session.commit()

        await _broadcast(
            broadcast,
            {
                "type": "candidate_selected",
                "ticker": ticker,
                "strike": candidate.contract.strike,
                "expiry": candidate.contract.expiry,
                "mid": candidate.contract.mid,
                "iv_rank": candidate.iv_rank,
            },
        )

        # --- Layer 2: agent ---
        await _broadcast(
            broadcast,
            {
                "type": "agent_thinking",
                "ticker": ticker,
                "message": f"Analyzing CSP candidate at ${candidate.contract.strike}",
            },
        )
        earnings = check_earnings_date(ticker)
        decision = analyze_candidate(
            ticker,
            candidate,
            sig_dict,
            earnings=earnings,
            use_gemini=self.use_gemini,
        )
        await _broadcast(
            broadcast,
            {
                "type": "agent_decision",
                "ticker": ticker,
                "decision": decision.decision,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
            },
        )

        # --- Layer 3: risk gate (always runs; still decisive if SELL_PUT) ---
        premium_total = candidate.contract.mid * 100.0 * contracts
        risk = self.risk_gate.evaluate_trade(
            premium=premium_total,
            strike=candidate.contract.strike,
            contracts=contracts,
            expiry=candidate.contract.expiry,
            earnings_date=earnings,
            open_portfolio_capital=self.open_capital(),
            contracts_today=self._contracts_today,
        )
        await _broadcast(
            broadcast,
            {
                "type": "risk_gate_result",
                "ticker": ticker,
                "approved": risk.approved,
                "reason": risk.reason,
                "failed_rule": risk.failed_rule,
            },
        )

        # --- Layer 4: execution only if dual approval ---
        order_id = None
        executed = False
        if decision.decision == "SELL_PUT" and risk.approved:
            result = submit_cash_secured_put(
                ticker,
                candidate.contract.strike,
                candidate.contract.expiry,
                contracts,
                dry_run=self.dry_run_orders,
                limit_price=candidate.contract.mid,
            )
            executed = result.success
            order_id = result.order_id
            if executed:
                self._contracts_today += contracts
                await _broadcast(
                    broadcast,
                    {
                        "type": "trade_executed",
                        "ticker": ticker,
                        "strike": candidate.contract.strike,
                        "contracts": contracts,
                        "order_id": order_id,
                        "status": result.status,
                    },
                )
            else:
                await _broadcast(
                    broadcast,
                    {
                        "type": "execution_error",
                        "ticker": ticker,
                        "error": result.error,
                    },
                )
        else:
            await _broadcast(
                broadcast,
                {
                    "type": "trade_skipped",
                    "ticker": ticker,
                    "agent_decision": decision.decision,
                    "risk_approved": risk.approved,
                    "reason": risk.reason
                    if decision.decision == "SELL_PUT"
                    else decision.reasoning,
                },
            )

        # --- Layer 5: autopsy always ---
        autopsy = generate_autopsy(
            ticker=ticker,
            decision=decision,
            candidate=candidate,
            risk=risk,
            contracts=contracts if executed else contracts,
            signals=sig_dict,
            executed=executed,
            order_id=order_id,
        )
        # If agent wanted sell but not executed, contracts in position_size still show intended size
        self._persist(autopsy, contracts=contracts if executed else 0)
        await _broadcast(broadcast, {"type": "trade_autopsy", "data": autopsy.to_dict()})
        return autopsy

    def _persist(self, autopsy: TradeAutopsy, contracts: int) -> None:
        with self.session_factory() as session:
            trade = Trade(
                id=autopsy.id,
                ticker=autopsy.ticker,
                decision=autopsy.decision,
                strike=autopsy.strike,
                expiry=autopsy.expiry,
                premium=autopsy.premium,
                contracts=contracts if autopsy.executed else 0,
                executed=autopsy.executed,
                order_id=autopsy.order_id,
                status="open" if autopsy.executed else "rejected",
                confidence=autopsy.confidence,
            )
            session.add(trade)
            session.add(
                AutopsyRow(
                    trade_id=trade.id,
                    data=autopsy.to_dict(),
                    status="EXECUTED" if autopsy.executed else "REJECTED",
                )
            )
            snap = self.pnl.snapshot(
                session.query(Trade).filter(Trade.executed.is_(True)).all(),
                contracts_today=self._contracts_today,
            )
            # include this trade if just executed (already in session)
            session.add(
                PortfolioStat(
                    capital_deployed=snap.capital_deployed,
                    open_pnl=snap.unrealized_pnl,
                    closed_pnl=snap.realized_pnl,
                    note=f"after {autopsy.ticker} {autopsy.decision}",
                )
            )
            session.commit()

    async def scan_watchlist(
        self,
        tickers: Optional[list[str]] = None,
        *,
        broadcast: Optional[BroadcastFn] = None,
        contracts: int = 1,
    ) -> list[TradeAutopsy]:
        settings = get_settings()
        tickers = tickers or settings.watchlist_tickers()
        results: list[TradeAutopsy] = []
        await _broadcast(
            broadcast, {"type": "scan_started", "tickers": tickers}
        )
        for ticker in tickers:
            try:
                autopsy = await self.analyze_ticker(
                    ticker, contracts=contracts, broadcast=broadcast
                )
                results.append(autopsy)
            except Exception as e:
                logger.exception("Scan failed for %s", ticker)
                await _broadcast(
                    broadcast,
                    {"type": "error", "ticker": ticker, "error": str(e)},
                )
        pnl = self.portfolio_snapshot()
        await _broadcast(broadcast, {"type": "pnl_update", **pnl})
        await _broadcast(
            broadcast,
            {
                "type": "scan_completed",
                "count": len(results),
                "executed": sum(1 for r in results if r.executed),
            },
        )
        return results
