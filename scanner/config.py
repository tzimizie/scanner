"""Persisted user settings (API keys, etc.) stored in the app dir."""
from __future__ import annotations

import json
import os
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
