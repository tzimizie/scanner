"""Position sizer — translates a trade idea + risk settings into share count.

The most common way retail accounts blow up isn't picking bad stocks; it's
oversizing good ones. This module enforces fixed-fractional risk per trade so
a single losing trade can't take more than the configured % of account
equity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .config import AccountSettings


@dataclass
class SizedTrade:
    shares: int
    risk_dollars: float            # how much you stand to lose if stop hits
    notional: float                # shares * entry_price
    notional_pct_of_account: float
    capped_by: Optional[str]       # None, "risk", "position", or "shares-zero"
    notes: list[str]


def size_trade(
    *,
    entry: float,
    stop: float,
    settings: AccountSettings,
) -> SizedTrade:
    """Return a SizedTrade given entry/stop and the user's account settings.

    Raises ValueError on invalid inputs; otherwise always returns a result —
    even if the answer is "0 shares" with an explanation in `notes`.
    """
    if entry <= 0:
        raise ValueError("Entry price must be positive")
    if stop >= entry:
        raise ValueError("Stop must be below entry for a long position")
    if not settings.configured:
        raise ValueError(
            "Account size is not configured. Run "
            "`stockscanner config --account-size <USD>` first."
        )

    notes: list[str] = []
    capped_by: Optional[str] = None

    risk_per_share = entry - stop
    risk_budget = settings.account_size * (settings.risk_per_trade_pct / 100)
    shares_by_risk = math.floor(risk_budget / risk_per_share)

    max_notional = settings.account_size * (settings.max_position_pct / 100)
    shares_by_position = math.floor(max_notional / entry)

    shares = min(shares_by_risk, shares_by_position)
    if shares == shares_by_position < shares_by_risk:
        capped_by = "position"
        notes.append(
            f"Capped at {settings.max_position_pct:.0f}% max position size "
            f"(${max_notional:,.0f}). Risk budget would have allowed "
            f"{shares_by_risk} shares."
        )
    elif shares > 0:
        capped_by = "risk"

    if shares <= 0:
        capped_by = "shares-zero"
        notes.append(
            "Computed share count is zero. Either the per-share risk is too "
            "large for your risk budget, or the entry exceeds your max "
            "position size."
        )

    notional = shares * entry
    return SizedTrade(
        shares=int(shares),
        risk_dollars=round(shares * risk_per_share, 2),
        notional=round(notional, 2),
        notional_pct_of_account=(
            round(notional / settings.account_size * 100, 2)
            if settings.account_size > 0
            else 0.0
        ),
        capped_by=capped_by,
        notes=notes,
    )


def format_sizing(trade: SizedTrade, *, entry: float, stop: float) -> str:
    """Compact one-liner for printing alongside an alert."""
    if trade.shares <= 0:
        return f"sizing: 0 shares ({'; '.join(trade.notes) or 'unviable'})"
    return (
        f"size {trade.shares} sh  "
        f"notional ${trade.notional:,.0f} ({trade.notional_pct_of_account:.1f}% acct)  "
        f"risk ${trade.risk_dollars:,.0f}"
    )