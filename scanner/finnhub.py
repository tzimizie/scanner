"""Finnhub real-time quote client.

Only the free-tier `/quote` endpoint is used here. It returns:
    c   = current price
    o   = today's open
    h   = today's high
    l   = today's low
    pc  = previous close
    t   = timestamp

Note: free-tier `/quote` does NOT include volume. The watch loop combines
this real-time price snapshot with a yfinance-sourced (15-min delayed)
historical baseline that supplies the 50-day average volume needed for the
relative-volume filter.

Free-tier rate limit: 60 calls / minute. We cap ourselves at 55 to leave
headroom for retries and clock skew.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger("scanner.finnhub")

_BASE_URL = "https://finnhub.io/api/v1"
_RATE_LIMIT_PER_MINUTE = 55
_CALL_WINDOW_SECONDS = 60


@dataclass
class LiveQuote:
    symbol: str
    current: float
    open: float
    high: float
    low: float
    previous_close: float
    timestamp: int

    @classmethod
    def from_payload(cls, symbol: str, data: dict) -> Optional["LiveQuote"]:
        # Finnhub returns 0/null for symbols it doesn't recognize.
        if not data or float(data.get("c") or 0) <= 0:
            return None
        try:
            return cls(
                symbol=symbol,
                current=float(data["c"]),
                open=float(data.get("o") or 0),
                high=float(data.get("h") or 0),
                low=float(data.get("l") or 0),
                previous_close=float(data.get("pc") or 0),
                timestamp=int(data.get("t") or 0),
            )
        except (TypeError, ValueError):
            return None


class FinnhubClient:
    def __init__(self, token: str):
        if not token:
            raise ValueError("Finnhub token must be a non-empty string")
        self._token = token
        self._session = requests.Session()
        self._call_times: deque[float] = deque()

    def _throttle(self) -> None:
        """Sleep just enough to stay under the per-minute call cap."""
        now = time.time()
        while self._call_times and now - self._call_times[0] >= _CALL_WINDOW_SECONDS:
            self._call_times.popleft()

        if len(self._call_times) >= _RATE_LIMIT_PER_MINUTE:
            wait = _CALL_WINDOW_SECONDS - (now - self._call_times[0]) + 0.05
            if wait > 0:
                time.sleep(wait)
            # Drain the window after waking.
            now = time.time()
            while self._call_times and now - self._call_times[0] >= _CALL_WINDOW_SECONDS:
                self._call_times.popleft()

        self._call_times.append(time.time())

    def quote(self, symbol: str) -> Optional[LiveQuote]:
        self._throttle()
        try:
            response = self._session.get(
                f"{_BASE_URL}/quote",
                params={"symbol": symbol, "token": self._token},
                timeout=5,
            )
        except requests.RequestException as e:
            log.debug("Finnhub request error for %s: %s", symbol, e)
            return None

        if response.status_code == 401:
            raise PermissionError(
                "Finnhub returned 401 Unauthorized — your API key is invalid or expired."
            )
        if response.status_code == 429:
            # Rate-limited despite our throttling — back off briefly.
            time.sleep(2)
            return None
        if not response.ok:
            log.debug(
                "Finnhub HTTP %s for %s: %s",
                response.status_code,
                symbol,
                response.text[:200],
            )
            return None

        try:
            data = response.json()
        except ValueError:
            return None
        return LiveQuote.from_payload(symbol, data)
