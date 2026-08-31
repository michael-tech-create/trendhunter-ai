"""SQLAlchemy ORM models for signals, trades, autopsies, portfolio."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String, index=True)
    rsi: Mapped[float] = mapped_column(Float)
    momentum: Mapped[float] = mapped_column(Float)
    volume_ratio: Mapped[float] = mapped_column(Float)
    volatility: Mapped[float] = mapped_column(Float)
    last_close: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class OptionSnapshot(Base):
    __tablename__ = "option_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String, index=True)
    strike: Mapped[float] = mapped_column(Float)
    expiry: Mapped[str] = mapped_column(String)
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    iv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iv_rank: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String, index=True)
    decision: Mapped[str] = mapped_column(String)
    strike: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expiry: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    premium: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contracts: Mapped[int] = mapped_column(Integer, default=0)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open|closed|rejected
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AutopsyRow(Base):
    __tablename__ = "autopsies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    trade_id: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="RECORDED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PortfolioStat(Base):
    __tablename__ = "portfolio"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    capital_deployed: Mapped[float] = mapped_column(Float, default=0.0)
    open_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    closed_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
