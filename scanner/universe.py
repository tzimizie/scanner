"""Stock universe management — S&P 500 by default, watchlist override."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, List

import pandas as pd

from .paths import universe_cache_file

# Cache the S&P 500 list for a week — membership rarely changes day to day and
# we want the scanner to work offline.
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

_FALLBACK_TICKERS = [
    # Mega-caps as a last-resort fallback if Wikipedia is unreachable on first run.
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "AVGO", "JPM",
    "LLY", "V", "UNH", "XOM", "MA", "COST", "JNJ", "HD", "PG", "ORCL",
    "ABBV", "BAC", "WMT", "KO", "MRK", "CVX", "NFLX", "AMD", "PEP", "ADBE",
]


def _fetch_sp500_from_wikipedia() -> List[str]:
    # `pandas.read_html` parses the constituents table; column "Symbol" holds the
    # tickers. Yahoo uses dashes for class shares (e.g. BRK-B, BF-B) while
    # Wikipedia uses dots — translate.
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df = tables[0]
    raw = df["Symbol"].astype(str).tolist()
    return [t.replace(".", "-").strip().upper() for t in raw if t.strip()]


def load_sp500(*, force_refresh: bool = False) -> List[str]:
    """Return the S&P 500 ticker list, using a 7-day on-disk cache."""
    cache = universe_cache_file()
    if not force_refresh and cache.exists():
        try:
            payload = json.loads(cache.read_text())
            if time.time() - payload.get("fetched_at", 0) < _CACHE_TTL_SECONDS:
                return payload["tickers"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    try:
        tickers = _fetch_sp500_from_wikipedia()
    except Exception:
        # Don't fail the whole scan if Wikipedia is down — fall back to whatever
        # cached list we have, then to the hardcoded mega-caps.
        if cache.exists():
            try:
                return json.loads(cache.read_text())["tickers"]
            except Exception:
                pass
        return list(_FALLBACK_TICKERS)

    cache.write_text(json.dumps({"fetched_at": time.time(), "tickers": tickers}))
    return tickers


def load_watchlist(path: Path) -> List[str]:
    """Load tickers from a text file, one per line, ignoring blanks and `#` comments."""
    tickers: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line.upper())
    if not tickers:
        raise ValueError(f"Watchlist {path} contained no tickers")
    return tickers


def normalize_tickers(tickers: Iterable[str]) -> List[str]:
    """Strip, upper-case, and dedupe while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        clean = t.strip().upper().replace(".", "-")
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out
