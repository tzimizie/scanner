"""Warrior Trading-style scanner: low-priced gappers on heavy relative volume.

Models the core of Ross Cameron's methodology — find low-float, low-priced
stocks that are gapping up significantly on volume, then look for a bull-flag
or flat-top continuation. This is a day-trading style, NOT swing trading.

Filters (defaults; tunable in WarriorParams):
  * Last close in [$1, $20]
  * Today gap-up >= 4% from prior close
  * Today's volume >= 5x the 50-day average volume
  * Up on the day (today's close > today's open)

Pattern checks:
  * Recent run: closed up >= 5% over the prior 5 sessions (momentum confirmation)
  * Tight intraday range: (today_high - today_low) / today_open <= 12%
    — keeps us out of stocks already extended

Limitations vs a true Warrior-style scanner:
  * Yahoo Finance free data is ~15-min delayed — by the time you see a setup,
    the move may have already happened.
  * No float-size filter (yfinance .info is slow + unreliable for many small
    caps). Use a curated watchlist of low-float names if you need that filter.
  * No news/catalyst detection.
  * No real-time VWAP or 1-minute pattern detection (would require intraday
    bars per ticker per cycle, which is too slow against the free API).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class WarriorParams:
    min_price: float = 1.0
    max_price: float = 20.0
    min_gap_pct: float = 0.04          # 4% gap from prior close
    min_relative_volume: float = 5.0   # 5x the 50-day avg
    min_recent_run_pct: float = 0.05   # +5% over the prior 5 sessions
    max_intraday_range_pct: float = 0.12


@dataclass
class WarriorSignal:
    ticker: str
    last_price: float
    prior_close: float
    gap_pct: float
    relative_volume: float
    today_volume: float
    fifty_day_avg_volume: float
    recent_run_pct: float
    intraday_range_pct: float
    suggested_entry: float
    suggested_stop: float
    suggested_target: float
    risk_pct: float
    score: float                       # higher = stronger setup


def find_warrior_setup(
    df: pd.DataFrame,
    ticker: str,
    params: Optional[WarriorParams] = None,
) -> Optional[WarriorSignal]:
    """Return a WarriorSignal if today's bar passes the day-trading filters.

    `df` is daily OHLCV indexed by date, oldest first — same shape as
    `find_breakout` consumes, so we can reuse the cached fetch.
    """
    p = params or WarriorParams()
    if df is None or len(df) < 60:
        return None

    df = df.dropna(how="any")
    if df.empty:
        return None

    today = df.iloc[-1]
    last_close = float(today["Close"])
    today_open = float(today["Open"])
    today_high = float(today["High"])
    today_low = float(today["Low"])
    today_volume = float(today["Volume"])

    # 1. Price band — Warrior-style is small/mid caps in this range.
    if not (p.min_price <= last_close <= p.max_price):
        return None

    # 2. Gap up vs. prior close.
    prior_close = float(df["Close"].iloc[-2])
    if prior_close <= 0:
        return None
    gap_pct = (today_open - prior_close) / prior_close
    if gap_pct < p.min_gap_pct:
        return None

    # 3. Relative volume vs. the 50-day average. We use the prior 50 sessions
    # so today's run-rate doesn't dilute the baseline.
    avg_vol_50 = float(df["Volume"].iloc[-51:-1].mean())
    if avg_vol_50 <= 0:
        return None
    relative_volume = today_volume / avg_vol_50
    if relative_volume < p.min_relative_volume:
        return None

    # 4. Up on the day — Warrior trades long-only on green-day momentum.
    if last_close <= today_open:
        return None

    # 5. Tight intraday range — avoids stocks that have already round-tripped
    # or are mid-parabolic blow-off.
    if today_open <= 0:
        return None
    intraday_range_pct = (today_high - today_low) / today_open
    if intraday_range_pct > p.max_intraday_range_pct:
        return None

    # 6. Recent run check — momentum confirmation.
    five_session_close = float(df["Close"].iloc[-6])
    if five_session_close <= 0:
        return None
    recent_run_pct = (last_close - five_session_close) / five_session_close
    if recent_run_pct < p.min_recent_run_pct:
        return None

    # Suggested levels — Cameron-style tight risk:
    #   Entry: today's high (breakout of intraday range)
    #   Stop:  today's low (or 5% below entry, whichever is closer)
    #   Target: 2:1 risk/reward
    entry = today_high
    stop = max(today_low, entry * 0.95)
    if stop >= entry:
        return None
    risk = entry - stop
    target = entry + 2.0 * risk
    risk_pct = risk / entry

    # Score weights big gaps + heavy volume + tight risk.
    score = (gap_pct * 100) * relative_volume / max(risk_pct * 100, 0.5)

    return WarriorSignal(
        ticker=ticker,
        last_price=round(last_close, 2),
        prior_close=round(prior_close, 2),
        gap_pct=round(gap_pct, 4),
        relative_volume=round(relative_volume, 2),
        today_volume=int(today_volume),
        fifty_day_avg_volume=int(avg_vol_50),
        recent_run_pct=round(recent_run_pct, 4),
        intraday_range_pct=round(intraday_range_pct, 4),
        suggested_entry=round(entry, 2),
        suggested_stop=round(stop, 2),
        suggested_target=round(target, 2),
        risk_pct=round(risk_pct, 4),
        score=round(score, 2),
    )
