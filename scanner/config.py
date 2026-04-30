"""Persisted user settings — API keys and trading-discipline parameters."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from .paths import app_dir


def _config_path():
    return app_dir() / "config.json"


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(cfg: dict) -> None:
    _config_path().write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------------
# Finnhub
# ---------------------------------------------------------------------------

def get_finnhub_key() -> Optional[str]:
    """Resolve the Finnhub API key. The FINNHUB_API_KEY env var wins so CI /
    one-off runs don't have to write to disk."""
    if v := os.environ.get("FINNHUB_API_KEY"):
        return v
    return load_config().get("finnhub_key")


def set_finnhub_key(key: str) -> None:
    cfg = load_config()
    cfg["finnhub_key"] = key.strip()
    save_config(cfg)


def clear_finnhub_key() -> None:
    cfg = load_config()
    cfg.pop("finnhub_key", None)
    save_config(cfg)


# ---------------------------------------------------------------------------
# Account & risk settings — the discipline scaffolding
# ---------------------------------------------------------------------------

@dataclass
class AccountSettings:
    """Trading-discipline parameters used by the position sizer + circuit
    breaker. Defaults are conservative: 1% per-trade risk, 25% max position
    size, 3% daily loss cap."""
    account_size: float = 0.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 25.0
    max_daily_loss_pct: float = 3.0
    paper_trading: bool = True       # treat new positions as paper by default

    @property
    def configured(self) -> bool:
        return self.account_size > 0


def get_account_settings() -> AccountSettings:
    cfg = load_config().get("account", {})
    return AccountSettings(
        account_size=float(cfg.get("account_size", 0.0)),
        risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 1.0)),
        max_position_pct=float(cfg.get("max_position_pct", 25.0)),
        max_daily_loss_pct=float(cfg.get("max_daily_loss_pct", 3.0)),
        paper_trading=bool(cfg.get("paper_trading", True)),
    )


def set_account_settings(
    *,
    account_size: Optional[float] = None,
    risk_per_trade_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    max_daily_loss_pct: Optional[float] = None,
    paper_trading: Optional[bool] = None,
) -> AccountSettings:
    cfg = load_config()
    account = cfg.get("account", {})

    if account_size is not None:
        if account_size < 0:
            raise ValueError("Account size cannot be negative")
        account["account_size"] = float(account_size)
    if risk_per_trade_pct is not None:
        if not 0 < risk_per_trade_pct <= 5:
            raise ValueError("risk_per_trade_pct must be in (0, 5] — anything more is reckless")
        account["risk_per_trade_pct"] = float(risk_per_trade_pct)
    if max_position_pct is not None:
        if not 0 < max_position_pct <= 100:
            raise ValueError("max_position_pct must be in (0, 100]")
        account["max_position_pct"] = float(max_position_pct)
    if max_daily_loss_pct is not None:
        if not 0 < max_daily_loss_pct <= 20:
            raise ValueError("max_daily_loss_pct must be in (0, 20]")
        account["max_daily_loss_pct"] = float(max_daily_loss_pct)
    if paper_trading is not None:
        account["paper_trading"] = bool(paper_trading)

    cfg["account"] = account
    save_config(cfg)
    return get_account_settings()
