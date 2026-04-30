"""Trade journal — every alert the scanner fires, plus its outcome.

Two reasons this exists:

1. **Honest performance data**. The scanner can claim to find good setups,
   but only the journal can answer "if I'd taken every alert in the last
   60 days, would I be profitable?" That answer is the most important
   feedback loop in trading; everything else is opinion.

2. **Discipline**. Knowing every alert is being recorded — including the
   ones you skipped — discourages cherry-picking after the fact.

Auto-resolution: each time the journal runs, every still-PENDING entry is
checked against subsequent price action. We mark it WIN if target hit,
LOSS if stop hit, BREAKEVEN if neither hit within `STALE_DAYS`.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Optional

import pandas as pd

from .data import fetch_one
from .paths import app_dir


JOURNAL_FILE = "journal.json"
STALE_DAYS = 30  # mark as BREAKEVEN if neither stop nor target hit within this window


@dataclass
class JournalEntry:
    ticker: str
    alert_date: str             # ISO YYYY-MM-DD
    entry: float
    stop: float
    target: float
    risk_per_share: float
    strategy: str               # "breakout" or "warrior"
    score: float

    # Outcome (filled by resolver)
    status: str = "PENDING"     # PENDING | WIN | LOSS | BREAKEVEN
    resolved_date: Optional[str] = None
    resolved_price: Optional[float] = None
    r_multiple: Optional[float] = None
    days_to_resolve: Optional[int] = None

    # Whether the user actually took the trade (vs. paper-tracking only)
    taken: bool = False
    notes: str = ""

    def key(self) -> str:
        return f"{self.ticker}@{self.alert_date}"


def _journal_path():
    return app_dir() / JOURNAL_FILE


@dataclass
class Journal:
    entries: list[JournalEntry] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Journal":
        path = _journal_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
            return cls(entries=[JournalEntry(**e) for e in raw.get("entries", [])])
        except (json.JSONDecodeError, TypeError, OSError):
            return cls()

    def save(self) -> None:
        _journal_path().write_text(
            json.dumps(
                {"entries": [asdict(e) for e in self.entries]},
                indent=2,
            )
        )

    def by_key(self) -> dict[str, JournalEntry]:
        return {e.key(): e for e in self.entries}

    def upsert_alert(
        self,
        *,
        ticker: str,
        alert_date: str,
        entry: float,
        stop: float,
        target: float,
        strategy: str,
        score: float,
    ) -> JournalEntry:
        """Add a new alert if we haven't seen this (ticker, date) combo."""
        key = f"{ticker}@{alert_date}"
        existing = self.by_key().get(key)
        if existing is not None:
            return existing

        new_entry = JournalEntry(
            ticker=ticker,
            alert_date=alert_date,
            entry=float(entry),
            stop=float(stop),
            target=float(target),
            risk_per_share=round(entry - stop, 4),
            strategy=strategy,
            score=float(score),
        )
        self.entries.append(new_entry)
        return new_entry

    def pending(self) -> list[JournalEntry]:
        return [e for e in self.entries if e.status == "PENDING"]

    def resolved(self) -> list[JournalEntry]:
        return [e for e in self.entries if e.status != "PENDING"]


# ---------------------------------------------------------------------------
# Auto-resolution
# ---------------------------------------------------------------------------

def resolve_pending(journal: Journal) -> int:
    """For every PENDING entry, fetch price history since the alert and decide
    its outcome. Returns the number of entries that transitioned out of
    PENDING this call."""
    transitioned = 0
    today = datetime.utcnow().date()

    for entry in journal.pending():
        try:
            alert_dt = datetime.strptime(entry.alert_date, "%Y-%m-%d").date()
        except ValueError:
            continue

        days_since = (today - alert_dt).days
        if days_since < 1:
            continue  # need at least one bar after the alert

        df = fetch_one(entry.ticker)
        if df is None or df.empty:
            continue

        # Bars strictly AFTER the alert date.
        try:
            after = df.loc[df.index.date > alert_dt]
        except Exception:  # noqa: BLE001
            continue

        if after.empty:
            if days_since >= STALE_DAYS:
                _mark(entry, "BREAKEVEN", today, df["Close"].iloc[-1], days_since)
                transitioned += 1
            continue

        target_hit_idx = after.index[after["High"] >= entry.target]
        stop_hit_idx = after.index[after["Low"] <= entry.stop]

        target_first = target_hit_idx[0] if len(target_hit_idx) else None
        stop_first = stop_hit_idx[0] if len(stop_hit_idx) else None

        # Whichever happened first — if both happen on the same bar we
        # pessimistically assume the stop hit first.
        if target_first is not None and (stop_first is None or target_first < stop_first):
            _mark(
                entry,
                "WIN",
                target_first.date() if hasattr(target_first, "date") else today,
                entry.target,
                (target_first.date() - alert_dt).days if hasattr(target_first, "date") else days_since,
            )
            transitioned += 1
        elif stop_first is not None:
            _mark(
                entry,
                "LOSS",
                stop_first.date() if hasattr(stop_first, "date") else today,
                entry.stop,
                (stop_first.date() - alert_dt).days if hasattr(stop_first, "date") else days_since,
            )
            transitioned += 1
        elif days_since >= STALE_DAYS:
            _mark(entry, "BREAKEVEN", today, float(df["Close"].iloc[-1]), days_since)
            transitioned += 1

    return transitioned


def _mark(
    entry: JournalEntry,
    status: str,
    resolved_date,
    resolved_price: float,
    days: int,
) -> None:
    entry.status = status
    entry.resolved_date = (
        resolved_date.isoformat() if isinstance(resolved_date, (datetime,)) else
        str(resolved_date)
    )
    entry.resolved_price = float(resolved_price)
    entry.days_to_resolve = int(days)

    risk = entry.risk_per_share or (entry.entry - entry.stop)
    if risk <= 0:
        entry.r_multiple = 0.0
        return
    if status == "WIN":
        entry.r_multiple = round((entry.target - entry.entry) / risk, 2)
    elif status == "LOSS":
        entry.r_multiple = round(-1.0, 2)
    else:  # BREAKEVEN
        entry.r_multiple = round((resolved_price - entry.entry) / risk, 2)


# ---------------------------------------------------------------------------
# Stats summary
# ---------------------------------------------------------------------------

@dataclass
class JournalStats:
    total_alerts: int
    pending: int
    wins: int
    losses: int
    breakevens: int
    win_rate_pct: float
    avg_r_multiple: float
    expectancy_r: float          # average R per trade including BE
    best_r: float
    worst_r: float


def compute_stats(journal: Journal, *, window_days: Optional[int] = None) -> JournalStats:
    today = datetime.utcnow().date()
    entries: Iterable[JournalEntry] = journal.entries
    if window_days:
        cutoff = today - timedelta(days=window_days)
        entries = [
            e for e in entries
            if datetime.strptime(e.alert_date, "%Y-%m-%d").date() >= cutoff
        ]

    entries = list(entries)
    pending = sum(1 for e in entries if e.status == "PENDING")
    wins = sum(1 for e in entries if e.status == "WIN")
    losses = sum(1 for e in entries if e.status == "LOSS")
    breakevens = sum(1 for e in entries if e.status == "BREAKEVEN")
    resolved = wins + losses + breakevens

    rs = [e.r_multiple for e in entries if e.r_multiple is not None]
    avg_r = round(sum(rs) / len(rs), 2) if rs else 0.0
    expectancy = avg_r  # same definition with our R-based scoring

    return JournalStats(
        total_alerts=len(entries),
        pending=pending,
        wins=wins,
        losses=losses,
        breakevens=breakevens,
        win_rate_pct=round(wins / resolved * 100, 1) if resolved else 0.0,
        avg_r_multiple=avg_r,
        expectancy_r=expectancy,
        best_r=round(max(rs), 2) if rs else 0.0,
        worst_r=round(min(rs), 2) if rs else 0.0,
    )