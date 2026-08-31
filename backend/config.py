"""Application settings and constants for TrendHunter AI backend."""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config. Risk limits live here so call sites never hardcode ad hoc overrides."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # APIs
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_cli_path: str = "alpaca"

    # App
    database_url: str = "sqlite:///./trendhunter.db"
    # Include lower-priced names so CSP notional can fit max_position_capital ($5k ⇒ strike ≲ $50)
    watchlist: str = "AAPL,MSFT,F"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Risk gate — deterministic defaults (1:8 premium/max-loss)
    min_premium_ratio: float = 0.125
    max_position_capital: float = 5000.0
    max_portfolio_capital: float = 50000.0
    max_contracts_per_day: int = 3

    # Options selection
    default_days_to_expiry: int = 14
    min_option_premium: float = 0.10
    max_bid_ask_spread_pct: float = 0.05
    strike_offset_pct: float = 0.05  # prefer strikes ~5% below spot / near support

    # CLI
    cli_timeout_seconds: int = 60
    cli_retries: int = 3

    @field_validator("min_premium_ratio")
    @classmethod
    def ratio_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("min_premium_ratio must be positive")
        return v

    def watchlist_tickers(self) -> List[str]:
        return [t.strip().upper() for t in self.watchlist.split(",") if t.strip()]

    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Module-level convenience for simple imports
settings = get_settings()
