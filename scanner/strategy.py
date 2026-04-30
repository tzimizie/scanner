"""Breakout detection logic.

Setup: price within 5% of 52-week high, last 20 days tight, volume contracting.
Entry: today closes above the prior 20-day high on volume >= 1.5x 50-day average,
       AND today's close is above the 50-day SMA.
Stop:   max(entry * 0.925, prior 20-day low).
Target: entry + 3 * (entry - stop).

Exits (any one triggers):
  * stop hit (today's low <= stop)
  * target hit (today's high >= target)
  * close < 20-day SMA
  * trailing stop: close <= peak_close_since_entry * (1 - TRAIL_PCT)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

# Setup tuning knobs
NEAR_HIGH_PCT = 0.05          # within 5% of 52-week high
CONSOLIDATION_DAYS = 20
CONSOLIDATION_MAX_RANGE = 0.12  # (high - low) / close ≤ 12% over consolidation
VOLUME_BREAKOUT_MULTIPLE = 1.5
STOP_PCT = 0.075              # 7.5% initial stop
RISK_REWARD = 3.0
TRAIL_PCT = 0.075             # trailing stop: 7.5% off peak close


@dataclass
class BreakoutSignal:
    ticker: str
    entry: float
    stop: float
    target: float
    risk_pct: float            # (entry - stop) / entry
    fifty_two_week_high: float
    distance_to_high_pct: float
    volume_multiple: float     # today's vol / 50-day avg
    score: float               # higher = stronger setup


@dataclass
class ExitDecision:
    action: str                # "HOLD" or "EXIT"
    reason: str                # human-readable
    last_close: float
    pnl_pct: float


def find_breakout(df: pd.DataFrame, ticker: str) -> Optional[BreakoutSignal]:
    """Return a BreakoutSignal if today's bar qualifies, else None.

    `df` is a daily OHLCV DataFrame indexed by date, oldest first.
    """
    if df is None or len(df) < 252:
        return None

    df = df.dropna(how="any")
    if df.empty:
        return None

    today = df.iloc[-1]
    close_today = float(today["Close"])
    vol_today = float(today["Volume"])

    last_252 = df.tail(252)
    fifty_two_week_high = float(last_252["High"].max())
    if fifty_two_week_high <= 0:
        return None

    distance_to_high = (fifty_two_week_high - close_today) / fifty_two_week_high
    if distance_to_high > NEAR_HIGH_PCT:
        return None

    consolidation = df.iloc[-(CONSOLIDATION_DAYS + 1) : -1]  # last 20 bars BEFORE today
    if len(consolidation) < CONSOLIDATION_DAYS:
        return None

    consol_high = float(consolidation["High"].max())
    consol_low = float(consolidation["Low"].min())
    consol_close_avg = float(consolidation["Close"].mean())
    if consol_close_avg <= 0:
        return None
    consol_range = (consol_high - consol_low) / consol_close_avg
    if consol_range > CONSOLIDATION_MAX_RANGE:
        return None

    avg_vol_50 = float(df["Volume"].tail(50).mean())
    avg_vol_20 = float(df["Volume"].tail(20).mean())
    if avg_vol_50 <= 0:
        return None
    # Volume contracting during consolidation suggests selling pressure has dried up.
    if avg_vol_20 >= avg_vol_50:
        return None

    # Entry trigger: close above prior consolidation high on a volume surge.
    prior_close_high = float(consolidation["Close"].max())
    if close_today <= prior_close_high:
        return None
    volume_multiple = vol_today / avg_vol_50
    if volume_multiple < VOLUME_BREAKOUT_MULTIPLE:
        return None

    # Trend filter: don't fight the 50-day MA.
    sma_50 = float(df["Close"].tail(50).mean())
    if close_today < sma_50:
        return None

    entry = close_today
    stop_pct = entry * (1 - STOP_PCT)
    stop = max(stop_pct, consol_low * 0.999)  # whichever stop is higher = smaller risk
    if stop >= entry:
        return None
    risk = entry - stop
    target = entry + RISK_REWARD * risk
    risk_pct = risk / entry

    # Score: bigger volume surge + tighter stop = stronger setup.
    score = volume_multiple * (1 / max(risk_pct, 0.01))

    return BreakoutSignal(
        ticker=ticker,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        risk_pct=round(risk_pct, 4),
        fifty_two_week_high=round(fifty_two_week_high, 2),
        distance_to_high_pct=round(distance_to_high, 4),
        volume_multiple=round(volume_multiple, 2),
        score=round(score, 2),
    )


def evaluate_position(
    df: pd.DataFrame,
    *,
    entry_price: float,
    stop: float,
    target: float,
    peak_since_entry: float,
) -> ExitDecision:
    """Decide HOLD or EXIT for an open position. The caller updates `peak_since_entry`."""
    if df is None or df.empty:
        return ExitDecision(
            action="HOLD",
            reason="no data available",
            last_close=entry_price,
            pnl_pct=0.0,
        )

    today = df.iloc[-1]
    last_close = float(today["Close"])
    today_low = float(today["Low"])
    today_high = float(today["High"])
    pnl_pct = (last_close - entry_price) / entry_price

    sma_20 = float(df["Close"].tail(20).mean())
    trail_stop = peak_since_entry * (1 - TRAIL_PCT)

    if today_low <= stop:
        return ExitDecision("EXIT", f"stop hit ({stop:.2f})", last_close, pnl_pct)
    if today_high >= target:
        return ExitDecision("EXIT", f"target hit ({target:.2f})", last_close, pnl_pct)
    if last_close < sma_20:
        return ExitDecision(
            "EXIT", f"closed below 20-day MA ({sma_20:.2f})", last_close, pnl_pct
        )
    if last_close <= trail_stop and peak_since_entry > entry_price:
        return ExitDecision(
            "EXIT",
            f"trailing stop hit ({trail_stop:.2f}, off peak {peak_since_entry:.2f})",
            last_close,
            pnl_pct,
        )

    return ExitDecision(
        "HOLD",
        f"above stop {stop:.2f}, target {target:.2f}, 20MA {sma_20:.2f}",
        last_close,
        pnl_pct,
    )
