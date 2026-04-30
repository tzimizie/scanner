"""Command-line interface — wires data, strategy, and positions together."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import clear_finnhub_key, get_finnhub_key, set_finnhub_key
from .data import fetch_history, fetch_one
from .paths import default_watchlist_file, resolve_watchlist, watchlists_dir
from .positions import Position, PositionStore
from .screeners import SCREENS, list_screens
from .strategy import (
    STOP_PCT,
    RISK_REWARD,
    BreakoutSignal,
    evaluate_position,
    find_breakout,
)
from .universe import load_sp500, load_watchlist, normalize_tickers
from .warrior import WarriorSignal, find_warrior_setup
from .watch import WatchOptions, watch


# Available strategy keys for the `--strategy` flag.
STRATEGIES = ("warrior", "breakout")
DEFAULT_STRATEGY = "warrior"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_breakout_signals(signals: List[BreakoutSignal], top: int) -> None:
    if not signals:
        print("No breakout candidates today.")
        return

    signals = sorted(signals, key=lambda s: s.score, reverse=True)[:top]
    header = f"{'TICKER':<8}{'ENTRY':>10}{'STOP':>10}{'TARGET':>10}{'RISK%':>8}{'VOLx':>8}{'52W-DIST':>10}"
    print(header)
    print("-" * len(header))
    for s in signals:
        print(
            f"{s.ticker:<8}"
            f"{s.entry:>10.2f}"
            f"{s.stop:>10.2f}"
            f"{s.target:>10.2f}"
            f"{s.risk_pct * 100:>7.1f}%"
            f"{s.volume_multiple:>8.2f}"
            f"{s.distance_to_high_pct * 100:>9.1f}%"
        )
    print()
    print(f"{len(signals)} candidate(s). Stop = {STOP_PCT * 100:.1f}% (or below consolidation low).")
    print(f"Target = entry + {RISK_REWARD:.0f} x initial risk. Place orders the next session.")


def _print_warrior_signals(signals: List[WarriorSignal], top: int) -> None:
    if not signals:
        print("No Warrior-style gappers right now.")
        return

    signals = sorted(signals, key=lambda s: s.score, reverse=True)[:top]
    header = (
        f"{'TICKER':<8}{'PRICE':>9}{'GAP%':>8}{'RVOL':>8}"
        f"{'5D%':>8}{'ENTRY':>9}{'STOP':>9}{'TARGET':>9}"
    )
    print(header)
    print("-" * len(header))
    for s in signals:
        print(
            f"{s.ticker:<8}"
            f"{s.last_price:>9.2f}"
            f"{s.gap_pct * 100:>7.1f}%"
            f"{s.relative_volume:>7.2f}x"
            f"{s.recent_run_pct * 100:>7.1f}%"
            f"{s.suggested_entry:>9.2f}"
            f"{s.suggested_stop:>9.2f}"
            f"{s.suggested_target:>9.2f}"
        )
    print()
    print(f"{len(signals)} gapper(s). Entry = today's high; stop = today's low; 2:1 R/R target.")
    print("Day-trading style — risk capital only. Past performance != future results.")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_scan(args: argparse.Namespace) -> int:
    strategy = getattr(args, "strategy", DEFAULT_STRATEGY)

    if args.screen:
        from .screeners import fetch_screen
        if args.screen not in SCREENS:
            print(
                f"Unknown screen '{args.screen}'. Run `stockscanner scan --list-screens`.",
                file=sys.stderr,
            )
            return 2
        print(f"Pulling Yahoo screen '{args.screen}' ({SCREENS[args.screen]})...")
        tickers = fetch_screen(args.screen, count=args.screen_count)
        if not tickers:
            print("Screen returned no tickers (Yahoo may be throttling). Try again.")
            return 1
        print(f"Loaded {len(tickers)} tickers from screen.")
    elif args.watchlist:
        tickers = load_watchlist(resolve_watchlist(args.watchlist))
    elif default_watchlist_file().exists():
        tickers = load_watchlist(default_watchlist_file())
        print(f"Using default watchlist: {default_watchlist_file()}")
    else:
        tickers = load_sp500(force_refresh=args.refresh_universe)
    tickers = normalize_tickers(tickers)
    print(f"Scanning {len(tickers)} ticker(s) with '{strategy}' strategy...")

    bars = fetch_history(tickers)
    print(f"Fetched data for {len(bars)} ticker(s).")

    if strategy == "breakout":
        breakout_signals: List[BreakoutSignal] = []
        for ticker, df in bars.items():
            try:
                sig = find_breakout(df, ticker)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {ticker}: error during analysis: {e}", file=sys.stderr)
                continue
            if sig is not None:
                breakout_signals.append(sig)
        print()
        _print_breakout_signals(breakout_signals, top=args.top)
    else:
        warrior_signals: List[WarriorSignal] = []
        for ticker, df in bars.items():
            try:
                sig = find_warrior_setup(df, ticker)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {ticker}: error during analysis: {e}", file=sys.stderr)
                continue
            if sig is not None:
                warrior_signals.append(sig)
        print()
        _print_warrior_signals(warrior_signals, top=args.top)

    return 0


def cmd_enter(args: argparse.Namespace) -> int:
    store = PositionStore.load()
    ticker = args.ticker.upper()

    entry = float(args.price)
    if args.stop is not None:
        stop = float(args.stop)
    else:
        stop = round(entry * (1 - STOP_PCT), 2)
    if args.target is not None:
        target = float(args.target)
    else:
        risk = entry - stop
        if risk <= 0:
            print("Stop must be below entry price.", file=sys.stderr)
            return 2
        target = round(entry + RISK_REWARD * risk, 2)

    pos = Position.new(
        ticker=ticker,
        entry_price=entry,
        shares=int(args.shares),
        stop=stop,
        target=target,
        notes=args.notes or "",
    )
    store.add(pos)
    store.save()
    print(
        f"Recorded {pos.shares} shares of {pos.ticker} @ {pos.entry_price:.2f} "
        f"(stop {pos.stop:.2f}, target {pos.target:.2f})."
    )
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    store = PositionStore.load()
    try:
        pos = store.remove(args.ticker)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1
    store.save()
    print(f"Closed {pos.ticker} (was {pos.shares} @ {pos.entry_price:.2f}).")
    return 0


def cmd_watchlists(args: argparse.Namespace) -> int:
    """List/manage local watchlists in ~/.stockscanner/watchlists/."""
    wl_dir = watchlists_dir()
    print(f"Watchlists folder: {wl_dir}")

    if args.install_sample:
        sample = _bundled_sample_watchlist()
        if sample is None:
            print("  ! Bundled sample not found in this build.")
            return 1
        target = wl_dir / "warrior_lowfloat.txt"
        target.write_text(sample.read_text())
        print(f"  Installed: {target}")
        # Also point default.txt at it so double-click picks it up automatically.
        default = default_watchlist_file()
        if not default.exists():
            default.write_text(sample.read_text())
            print(f"  Set as default: {default}")
        return 0

    files = sorted(wl_dir.glob("*.txt"))
    if not files:
        print("  (empty)")
        print()
        print("Drop a .txt file with one ticker per line into that folder, then run:")
        print("  stockscanner watch --watchlist <name>")
        print()
        print("Or run `stockscanner watchlists --install-sample` to copy the bundled "
              "warrior_lowfloat.txt as a starter (also becomes the double-click default).")
        return 0

    default = default_watchlist_file()
    for f in files:
        marker = "  (default)" if f.resolve() == default.resolve() else ""
        line_count = sum(
            1 for line in f.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        print(f"  {f.name:<30} {line_count:>4} tickers{marker}")
    return 0


def _bundled_sample_watchlist() -> Optional[Path]:
    """Locate the sample watchlist whether we're running from source or from
    a PyInstaller --onefile build."""
    # PyInstaller extracts bundled data to sys._MEIPASS at runtime.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "sample_watchlists" / "warrior_lowfloat.txt"
        if candidate.exists():
            return candidate
    # Source / dev tree
    candidate = Path(__file__).resolve().parent.parent / "sample_watchlists" / "warrior_lowfloat.txt"
    return candidate if candidate.exists() else None


def cmd_config(args: argparse.Namespace) -> int:
    if args.finnhub_key:
        set_finnhub_key(args.finnhub_key)
        print("Finnhub API key saved. Real-time quotes are now enabled in `watch`.")
        return 0
    if args.clear_finnhub_key:
        clear_finnhub_key()
        print("Finnhub API key cleared. Watch loop will fall back to yfinance.")
        return 0
    if args.show:
        key = get_finnhub_key()
        if key:
            masked = key[:4] + "…" + key[-4:] if len(key) > 8 else "set"
            print(f"Finnhub API key: {masked} (real-time enabled)")
        else:
            print("No Finnhub API key configured. Watch loop uses yfinance (15-min delayed).")
        return 0

    print("Nothing to do. Use --finnhub-key, --clear-finnhub-key, or --show.")
    return 2


def cmd_watch(args: argparse.Namespace) -> int:
    screen = None
    if args.screen:
        if args.screen not in SCREENS:
            print(
                f"Unknown screen '{args.screen}'. Run `stockscanner watch --list-screens`.",
                file=sys.stderr,
            )
            return 2
        screen = args.screen

    if args.watchlist and screen:
        print("Pass either --watchlist or --screen, not both.", file=sys.stderr)
        return 2

    if args.watchlist:
        watchlist_path: Optional[Path] = resolve_watchlist(args.watchlist)
    elif screen is None and default_watchlist_file().exists():
        watchlist_path = default_watchlist_file()
    else:
        watchlist_path = None

    opts = WatchOptions(
        interval_minutes=int(args.interval),
        watchlist=watchlist_path,
        screen=screen,
        screen_count=int(args.screen_count),
        top=int(args.top),
        notify=not args.no_notifications,
        after_hours=bool(args.after_hours),
        strategy=getattr(args, "strategy", DEFAULT_STRATEGY),
    )
    return watch(opts)


def _print_screens() -> None:
    print("Available Yahoo predefined screens:")
    print()
    for sid, desc in list_screens():
        print(f"  {sid:<28} {desc}")
    print()
    print("Use one with: stockscanner watch --screen day_gainers")


def cmd_positions(args: argparse.Namespace) -> int:
    store = PositionStore.load()
    if not store.positions:
        print("No open positions.")
        return 0

    print(f"Checking {len(store.positions)} position(s)...")
    print()
    header = f"{'TICKER':<8}{'ACTION':<8}{'LAST':>9}{'P/L%':>9}{'STOP':>9}{'TARGET':>9}  REASON"
    print(header)
    print("-" * len(header))

    dirty = False
    for pos in list(store.positions):
        df = fetch_one(pos.ticker)
        if df is None:
            print(f"{pos.ticker:<8}{'?':<8}{'-':>9}{'-':>9}"
                  f"{pos.stop:>9.2f}{pos.target:>9.2f}  no data")
            continue

        last_close = float(df["Close"].iloc[-1])
        if last_close > pos.peak_close:
            store.update_peak(pos.ticker, last_close)
            dirty = True

        decision = evaluate_position(
            df,
            entry_price=pos.entry_price,
            stop=pos.stop,
            target=pos.target,
            peak_since_entry=max(pos.peak_close, last_close),
        )
        print(
            f"{pos.ticker:<8}"
            f"{decision.action:<8}"
            f"{decision.last_close:>9.2f}"
            f"{decision.pnl_pct * 100:>8.1f}%"
            f"{pos.stop:>9.2f}"
            f"{pos.target:>9.2f}  {decision.reason}"
        )

    if dirty:
        store.save()
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stockscanner",
        description="Breakout scanner with systematic entry / exit rules.",
    )
    p.add_argument("--version", action="version", version=f"stockscanner {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="One-shot screen of the universe.")
    p_scan.add_argument(
        "--strategy",
        choices=STRATEGIES,
        default=DEFAULT_STRATEGY,
        help=(
            "warrior = Cameron-style gappers (low-priced, big gap, heavy volume); "
            "breakout = multi-week consolidation breakouts. Default: warrior."
        ),
    )
    p_scan.add_argument(
        "--screen",
        help=(
            "Pull the universe live from a Yahoo predefined screen "
            "(day_gainers, most_actives, small_cap_gainers, ...). "
            "Run --list-screens for the full list."
        ),
    )
    p_scan.add_argument(
        "--screen-count",
        type=int,
        default=25,
        help="How many tickers to pull from the screen (default 25).",
    )
    p_scan.add_argument(
        "--watchlist",
        help="Path or name of a watchlist text file (overrides default).",
    )
    p_scan.add_argument(
        "--top", type=int, default=25, help="Show only the top N candidates by score."
    )
    p_scan.add_argument(
        "--refresh-universe",
        action="store_true",
        help="Re-fetch the S&P 500 list from Wikipedia, ignoring the 7-day cache.",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_enter = sub.add_parser("enter", help="Record a new open position.")
    p_enter.add_argument("ticker")
    p_enter.add_argument("--shares", type=int, required=True)
    p_enter.add_argument("--price", type=float, required=True, help="Fill price.")
    p_enter.add_argument("--stop", type=float, help="Override default 7.5%% stop.")
    p_enter.add_argument("--target", type=float, help="Override default 3R target.")
    p_enter.add_argument("--notes", default="")
    p_enter.set_defaults(func=cmd_enter)

    p_close = sub.add_parser("close", help="Remove a position from the tracker.")
    p_close.add_argument("ticker")
    p_close.set_defaults(func=cmd_close)

    p_pos = sub.add_parser(
        "positions", help="Check exit signals for every open position."
    )
    p_pos.set_defaults(func=cmd_positions)

    p_watch = sub.add_parser(
        "watch",
        help="Run continuously, polling on an interval and alerting on new setups.",
    )
    p_watch.add_argument(
        "--strategy",
        choices=STRATEGIES,
        default=DEFAULT_STRATEGY,
        help=(
            "warrior = Cameron-style gappers (low-priced, big gap, heavy volume); "
            "breakout = multi-week consolidation breakouts. Default: warrior."
        ),
    )
    p_watch.add_argument(
        "--screen",
        help=(
            "Pull the universe live from a Yahoo predefined screen and refresh "
            "it every cycle. Best fit for day-trading: --screen day_gainers."
        ),
    )
    p_watch.add_argument(
        "--screen-count",
        type=int,
        default=25,
        help="How many tickers to pull from the screen each cycle (default 25).",
    )
    p_watch.add_argument(
        "--list-screens",
        action="store_true",
        help="Print the available screen names and exit.",
    )
    p_watch.add_argument(
        "--interval", type=int, default=5, help="Minutes between scans (default 5)."
    )
    p_watch.add_argument(
        "--watchlist",
        help="Path or name of a watchlist text file (mutually exclusive with --screen).",
    )
    p_watch.add_argument(
        "--top", type=int, default=10, help="Max alerts to print per cycle."
    )
    p_watch.add_argument(
        "--no-notifications",
        action="store_true",
        help="Disable Windows toast / beep alerts (console output only).",
    )
    p_watch.add_argument(
        "--after-hours",
        action="store_true",
        help="Keep scanning outside US market hours (otherwise we sleep until open).",
    )

    def _watch_dispatch(args: argparse.Namespace) -> int:
        if args.list_screens:
            _print_screens()
            return 0
        return cmd_watch(args)

    p_watch.set_defaults(func=_watch_dispatch)

    p_wl = sub.add_parser(
        "watchlists",
        help="List local watchlists or install the bundled sample.",
    )
    p_wl.add_argument(
        "--install-sample",
        action="store_true",
        help="Copy the bundled warrior_lowfloat.txt into the watchlists folder.",
    )
    p_wl.set_defaults(func=cmd_watchlists)

    p_config = sub.add_parser(
        "config",
        help="Manage settings (Finnhub API key, etc.)",
    )
    p_config.add_argument(
        "--finnhub-key",
        help="Save your Finnhub API key for real-time quotes.",
    )
    p_config.add_argument(
        "--clear-finnhub-key",
        action="store_true",
        help="Remove the saved Finnhub API key (fall back to yfinance).",
    )
    p_config.add_argument(
        "--show",
        action="store_true",
        help="Show current settings (key is masked).",
    )
    p_config.set_defaults(func=cmd_config)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
