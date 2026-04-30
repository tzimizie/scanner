"""Yahoo Finance data fetching with light caching.

We pull a year of daily bars per ticker, which is enough for a 252-day high
plus all moving averages.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("scanner.data")

_LOOKBACK_DAYS = 380  # ~18 months: 252 trading days + buffer for warmup


def fetch_history(tickers: List[str], *, batch_size: int = 50) -> Dict[str, pd.DataFrame]:
    """Fetch ~18 months of daily OHLCV for each ticker.

    yfinance batches multi-ticker downloads into a single HTTP request — using a
    moderate batch size (~50) keeps us well under Yahoo's URL length limits while
    avoiding per-symbol round-trips. Returns one DataFrame per ticker, indexed
    by date, with columns: Open, High, Low, Close, Volume.
    """
    if not tickers:
        return {}

    out: Dict[str, pd.DataFrame] = {}
    for start in range(0, len(tickers), batch_size):
        batch = tickers[start : start + batch_size]
        try:
            raw = yf.download(
                tickers=" ".join(batch),
                period=f"{_LOOKBACK_DAYS}d",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as e:  # noqa: BLE001 - yfinance raises a variety of types
            log.warning("Batch download failed for %s: %s", batch, e)
            continue

        for ticker in batch:
            df = _extract_one(raw, ticker)
            if df is not None and not df.empty:
                out[ticker] = df

        # Tiny pause between batches to be polite to Yahoo.
        time.sleep(0.2)

    return out


def fetch_one(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch a single ticker (used for live position checks)."""
    try:
        df = yf.download(
            tickers=ticker,
            period=f"{_LOOKBACK_DAYS}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Single-ticker download failed for %s: %s", ticker, e)
        return None

    if df is None or df.empty:
        return None
    df = df.dropna(how="any")
    return df if not df.empty else None


def _extract_one(raw: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    if raw is None or raw.empty:
        return None
    # Single-ticker downloads come back without a top-level ticker column.
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker not in raw.columns.levels[0]:
            return None
        df = raw[ticker]
    else:
        df = raw

    df = df.dropna(how="any")
    if df.empty:
        return None
    return df
