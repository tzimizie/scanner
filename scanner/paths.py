"""Filesystem locations for cache, positions, etc.

Stored in the user's home directory so the .exe can live anywhere and still
find its state across runs.
"""
from __future__ import annotations

import os
from pathlib import Path


def app_dir() -> Path:
    """Return the per-user data directory, creating it if needed."""
    base = Path(os.path.expanduser("~")) / ".stockscanner"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir() -> Path:
    d = app_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def positions_file() -> Path:
    return app_dir() / "positions.json"


def universe_cache_file() -> Path:
    return cache_dir() / "sp500.json"


def watchlists_dir() -> Path:
    """Where the user's watchlist text files live. We look here first when
    the user passes `--watchlist NAME` so they don't have to type a full path."""
    d = app_dir() / "watchlists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_watchlist_file() -> Path:
    """Auto-loaded by `watch` when no --watchlist is provided. If this file
    exists the scanner uses it instead of the S&P 500."""
    return watchlists_dir() / "default.txt"


def resolve_watchlist(value: str) -> Path:
    """Translate a `--watchlist` argument into a real path.

    Order of resolution:
      1. If the value is an absolute path, use it as-is.
      2. If a file with that name (or that name + .txt) exists in the
         watchlists dir, use that.
      3. If the value exists as a relative path from the current working
         dir, use that (back-compat with the original behavior).
      4. Otherwise raise FileNotFoundError listing the dirs we tried.
    """
    raw = Path(value).expanduser()

    if raw.is_absolute():
        if raw.exists():
            return raw
        raise FileNotFoundError(f"Watchlist not found: {raw}")

    candidates = [
        watchlists_dir() / value,
        watchlists_dir() / f"{value}.txt",
        Path.cwd() / value,
    ]
    for c in candidates:
        if c.exists():
            return c

    tried = "\n".join(f"  - {c}" for c in candidates)
    raise FileNotFoundError(
        f"Watchlist '{value}' not found. Looked in:\n{tried}\n"
        f"Drop the file in {watchlists_dir()} or pass an absolute path."
    )
