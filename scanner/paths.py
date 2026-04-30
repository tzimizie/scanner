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
