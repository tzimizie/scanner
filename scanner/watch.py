"""Continuous scanning loop with deduped alerts.

Polls the universe every `interval_minutes` minutes, runs the breakout
detector, and alerts on each ticker that becomes a candidate (only once per
day). Outside US market hours it sleeps quietly until the next session.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Set
from zoneinfo import ZoneInfo

from .data import fetch_history
from .strategy import BreakoutSignal, find_breakout
from .universe import load_sp500, load_watchlist, normalize_tickers
from .warrior import WarriorSignal, find_warrior_setup


_ET = ZoneInfo("America/New_York")
_IS_WINDOWS = sys.platform == "win32"


@dataclass
class WatchOptions:
    interval_minutes: int = 5
    watchlist: Optional[Path] = None
    top: int = 10
    notify: bool = True
    after_hours: bool = False   # if True, don't skip when market is closed
    strategy: str = "warrior"   # "warrior" or "breakout"


# ---------------------------------------------------------------------------
# Market-hours helpers
# ---------------------------------------------------------------------------

def _now_et() -> datetime:
    return datetime.now(_ET)


def _is_market_hours(now: Optional[datetime] = None) -> bool:
    """Cheap weekday + 9:30am-4:00pm ET check. Skips US public holidays
    detection — those days the scanner just won't find new bars and naturally
    no-ops."""
    n = now or _now_et()
    if n.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    open_dt = n.replace(hour=9, minute=30, second=0, microsecond=0)
    close_dt = n.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_dt <= n <= close_dt


def _seconds_until_market_open(now: Optional[datetime] = None) -> int:
    """Seconds from `now` to the next 9:30am ET on a weekday. Capped at the
    scan interval so we never sleep so long the user can't Ctrl-C."""
    n = now or _now_et()
    target = n.replace(hour=9, minute=30, second=0, microsecond=0)
    if n >= target:
        target = target + timedelta(days=1)
    while target.weekday() >= 5:
        target = target + timedelta(days=1)
    return max(60, int((target - n).total_seconds()))


# ---------------------------------------------------------------------------
# Notification (best-effort, never crashes the loop)
# ---------------------------------------------------------------------------

def _try_windows_toast(title: str, message: str) -> bool:
    """Send a Windows toast if the runtime supports it. Returns True on
    success, False otherwise — the caller falls back to console output."""
    if not _IS_WINDOWS:
        return False
    try:
        # win10toast is the most PyInstaller-friendly option; if not bundled,
        # we silently skip and rely on the console alert.
        from win10toast import ToastNotifier  # type: ignore

        ToastNotifier().show_toast(title, message, duration=5, threaded=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _beep() -> None:
    if not _IS_WINDOWS:
        return
    try:
        import winsound

        winsound.MessageBeep()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# ANSI helpers (colors degrade gracefully in plain terminals)
# ---------------------------------------------------------------------------

_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _enable_windows_ansi() -> None:
    """Flip on virtual-terminal processing so ANSI escapes render in cmd.exe."""
    if not _IS_WINDOWS:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
        # -11 = STD_OUTPUT_HANDLE
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# The main loop
# ---------------------------------------------------------------------------

def _format_breakout(sig: BreakoutSignal) -> str:
    return (
        f"{_GREEN}{sig.ticker:<6}{_RESET} "
        f"entry {sig.entry:.2f}  "
        f"stop {sig.stop:.2f}  "
        f"target {sig.target:.2f}  "
        f"risk {sig.risk_pct * 100:.1f}%  "
        f"vol {sig.volume_multiple:.2f}x  "
        f"score {sig.score:.1f}"
    )


def _format_warrior(sig: WarriorSignal) -> str:
    return (
        f"{_GREEN}{sig.ticker:<6}{_RESET} "
        f"px {sig.last_price:.2f}  "
        f"gap {sig.gap_pct * 100:.1f}%  "
        f"rvol {sig.relative_volume:.2f}x  "
        f"entry {sig.suggested_entry:.2f}  "
        f"stop {sig.suggested_stop:.2f}  "
        f"target {sig.suggested_target:.2f}  "
        f"score {sig.score:.1f}"
    )


def _resolve_universe(opts: WatchOptions) -> list[str]:
    if opts.watchlist:
        tickers = load_watchlist(opts.watchlist)
    else:
        tickers = load_sp500()
    return normalize_tickers(tickers)


def watch(opts: WatchOptions) -> int:
    """Run the watch loop. Returns the exit code (always 0 unless interrupted)."""
    _enable_windows_ansi()

    tickers = _resolve_universe(opts)
    print(
        f"Watching {len(tickers)} tickers with '{opts.strategy}' strategy, "
        f"polling every {opts.interval_minutes} min."
    )
    print(f"Market hours: 9:30–16:00 America/New_York. Press Ctrl-C to stop.")
    if opts.notify:
        print("Alerts: console + Windows toast (best-effort).")
    if opts.strategy == "warrior":
        print(
            f"{_YELLOW}Warrior-style is day-trading only — risk capital and tight stops.{_RESET}"
        )
    print()

    seen_today: Set[str] = set()
    seen_day: Optional[str] = None
    cycle = 0

    try:
        while True:
            cycle += 1
            now = _now_et()
            today = now.strftime("%Y-%m-%d")
            if today != seen_day:
                seen_today.clear()
                seen_day = today

            if not opts.after_hours and not _is_market_hours(now):
                wait = min(opts.interval_minutes * 60, _seconds_until_market_open(now))
                stamp = now.strftime("%H:%M:%S")
                print(
                    f"{_DIM}[{stamp} ET] market closed — sleeping {wait // 60}m{_RESET}"
                )
                _sleep_interruptible(wait)
                continue

            stamp = now.strftime("%H:%M:%S")
            print(f"{_DIM}[{stamp} ET] cycle {cycle}: fetching {len(tickers)} tickers...{_RESET}")

            try:
                bars = fetch_history(tickers)
            except Exception as e:  # noqa: BLE001
                print(f"  {_YELLOW}data fetch failed: {e}{_RESET}")
                _sleep_interruptible(opts.interval_minutes * 60)
                continue

            new_lines, scored_count = _run_strategy(bars, opts.strategy, seen_today)
            new_lines = new_lines[: opts.top]

            if new_lines:
                tickers_alerted = [t for t, _line in new_lines]
                print(
                    f"  {_GREEN}*** {len(new_lines)} new candidate(s) "
                    f"at {stamp} ET ***{_RESET}"
                )
                for _ticker, line in new_lines:
                    print("  " + line)

                if opts.notify:
                    _beep()
                    summary = ", ".join(tickers_alerted[:5])
                    extra = f" (+{len(tickers_alerted) - 5} more)" if len(tickers_alerted) > 5 else ""
                    _try_windows_toast(
                        title=f"Stock Scanner: {len(tickers_alerted)} new setup(s)",
                        message=summary + extra,
                    )
            else:
                print(
                    f"  {_DIM}no new candidates "
                    f"({len(seen_today)} alerted earlier today){_RESET}"
                )

            _sleep_interruptible(opts.interval_minutes * 60)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def _run_strategy(
    bars: dict,
    strategy: str,
    seen_today: Set[str],
) -> tuple[list[tuple[str, str]], int]:
    """Run the chosen strategy across the fetched bars and return formatted
    `(ticker, line)` pairs ranked by score. Mutates `seen_today` to dedupe
    repeat alerts within the same trading day."""
    if strategy == "breakout":
        breakout_signals: list[BreakoutSignal] = []
        for ticker, df in bars.items():
            if ticker in seen_today:
                continue
            try:
                sig = find_breakout(df, ticker)
            except Exception:  # noqa: BLE001
                continue
            if sig is not None:
                breakout_signals.append(sig)
                seen_today.add(ticker)
        breakout_signals.sort(key=lambda s: s.score, reverse=True)
        return [(s.ticker, _format_breakout(s)) for s in breakout_signals], len(breakout_signals)

    # warrior
    warrior_signals: list[WarriorSignal] = []
    for ticker, df in bars.items():
        if ticker in seen_today:
            continue
        try:
            sig = find_warrior_setup(df, ticker)
        except Exception:  # noqa: BLE001
            continue
        if sig is not None:
            warrior_signals.append(sig)
            seen_today.add(ticker)
    warrior_signals.sort(key=lambda s: s.score, reverse=True)
    return [(s.ticker, _format_warrior(s)) for s in warrior_signals], len(warrior_signals)


def _sleep_interruptible(seconds: int) -> None:
    """Sleep in 1-second chunks so Ctrl-C feels responsive."""
    for _ in range(seconds):
        time.sleep(1)
