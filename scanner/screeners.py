"""Dynamic universes pulled from Yahoo Finance's predefined screeners.

Yahoo exposes a public, unauthenticated screener API that powers their
"Most Actives", "Day Gainers", etc. pages. We use it directly here — it's
considerably more stable than the yfinance wrapper, and it gives the watch
loop a self-refreshing universe that follows the stocks actually moving today
instead of a static watchlist that gets stale.

The screen IDs below are the ones most useful for Warrior-style day trading
(price-momentum + volume). Yahoo supports many more — see
https://finance.yahoo.com/screener/predefined for the full list.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import requests

log = logging.getLogger("scanner.screeners")

_BASE_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_TIMEOUT_SECONDS = 8

# Per-screen result cache so the watch loop can call this every cycle without
# hammering Yahoo. ~60s is a good tradeoff between freshness and API load.
_DEFAULT_TTL_SECONDS = 60


@dataclass
class _CacheEntry:
    fetched_at: float
    tickers: List[str]


_cache: dict[str, _CacheEntry] = {}


# Curated list shown to the user via `--list-screens`. The screen IDs map
# directly to Yahoo's `scrIds` query parameter.
SCREENS: dict[str, str] = {
    "most_actives": "Heaviest US trading volume today",
    "day_gainers": "Biggest % gainers today",
    "day_losers": "Biggest % losers today",
    "small_cap_gainers": "Small-cap names up the most today",
    "most_shorted_stocks": "Highest short interest (squeeze candidates)",
    "aggressive_small_caps": "High-growth small caps",
    "growth_technology_stocks": "Growth-bias tech names",
    "undervalued_growth_stocks": "Growth at a reasonable price",
}


def list_screens() -> list[tuple[str, str]]:
    return sorted(SCREENS.items())


def fetch_screen(
    screen_id: str,
    *,
    count: int = 25,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> List[str]:
    """Return a list of tickers from Yahoo's predefined screen, cached briefly.

    `screen_id` is one of the keys in `SCREENS` (or any valid Yahoo `scrIds`).
    Returns an empty list if Yahoo is unreachable — callers should treat that
    as "no universe this cycle, retry next time" rather than crashing.
    """
    cached = _cache.get(screen_id)
    now = time.time()
    if cached and now - cached.fetched_at < ttl_seconds:
        return list(cached.tickers)

    params = {"scrIds": screen_id, "count": str(count), "start": "0"}
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    try:
        response = requests.get(
            _BASE_URL, params=params, headers=headers, timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        log.debug("Screener request failed: %s", e)
        return list(cached.tickers) if cached else []

    if not response.ok:
        log.debug("Screener HTTP %s: %s", response.status_code, response.text[:200])
        return list(cached.tickers) if cached else []

    try:
        payload = response.json()
    except ValueError:
        return list(cached.tickers) if cached else []

    tickers = _extract_tickers(payload)
    if not tickers:
        # Empty payload — keep the previous cache instead of clobbering it
        # so a transient empty response doesn't kill an active watch session.
        return list(cached.tickers) if cached else []

    _cache[screen_id] = _CacheEntry(fetched_at=now, tickers=tickers)
    return list(tickers)


def _extract_tickers(payload: dict) -> List[str]:
    try:
        results = payload["finance"]["result"]
    except (KeyError, TypeError):
        return []
    if not results:
        return []

    quotes = results[0].get("quotes", []) or []
    out: List[str] = []
    seen: set[str] = set()
    for q in quotes:
        sym = q.get("symbol")
        if not sym:
            continue
        sym = str(sym).upper()
        if sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out
