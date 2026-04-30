"""Open-position tracking, persisted as JSON in the user's app dir."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List

from .paths import positions_file


@dataclass
class Position:
    ticker: str
    entry_price: float
    shares: int
    stop: float
    target: float
    opened_at: str
    peak_close: float                # tracks the highest close since entry for trailing stop
    notes: str = ""

    @classmethod
    def new(
        cls,
        *,
        ticker: str,
        entry_price: float,
        shares: int,
        stop: float,
        target: float,
        notes: str = "",
    ) -> "Position":
        return cls(
            ticker=ticker.upper(),
            entry_price=float(entry_price),
            shares=int(shares),
            stop=float(stop),
            target=float(target),
            opened_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            peak_close=float(entry_price),
            notes=notes,
        )


@dataclass
class PositionStore:
    positions: List[Position] = field(default_factory=list)

    @classmethod
    def load(cls) -> "PositionStore":
        path = positions_file()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            return cls(positions=[Position(**p) for p in data.get("positions", [])])
        except (json.JSONDecodeError, TypeError, OSError):
            return cls()

    def save(self) -> None:
        path = positions_file()
        path.write_text(
            json.dumps(
                {"positions": [asdict(p) for p in self.positions]},
                indent=2,
            )
        )

    def by_ticker(self) -> Dict[str, Position]:
        return {p.ticker: p for p in self.positions}

    def add(self, pos: Position) -> None:
        existing = self.by_ticker()
        if pos.ticker in existing:
            raise ValueError(f"Position for {pos.ticker} already exists")
        self.positions.append(pos)

    def remove(self, ticker: str) -> Position:
        ticker = ticker.upper()
        for i, p in enumerate(self.positions):
            if p.ticker == ticker:
                return self.positions.pop(i)
        raise KeyError(f"No open position for {ticker}")

    def update_peak(self, ticker: str, last_close: float) -> None:
        for p in self.positions:
            if p.ticker == ticker.upper() and last_close > p.peak_close:
                p.peak_close = float(last_close)
                return
