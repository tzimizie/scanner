"""Command-line interface — wires data, strategy, and positions together."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import (
    AccountSettings,
    clear_finnhub_key,
    get_account_settings,
    get_finnhub_key,
    set_account_settings,
    set_finnhub_key,
)
from .data import fetch_history, fetch_one
from .journal import Journal, compute_stats, resolve_pending
from .paths import default_watchlist_file, resolve_watchlist, watchlists_dir
from .positions import Position, PositionStore
from .screeners import SCREENS, list_screens
from .sizing import format_sizing, size_trade
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
STRATEGIES = ("breakout", "warrior")
DEFAULT_STRATEGY = "breakout"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _maybe_sizing_line(entry: float, stop: float, settings: AccountSettings) -> str:
    if not settings.configured:
        return ""
    try:
        sized = size_trade(entry=entry, stop=stop, settings=settings)
    except ValueError:
        return ""
    return "  " + format_sizing(sized, entry=entry, stop=stop)


def _print_breakout_signals(
    signals: List[BreakoutSignal], top: int, settings: AccountSettings
) -> None:
    if not signals:
        print("No breakout candidates today.")
        return

    signals = sorted(signals, key=lambda s: s.score, reverse=True)[:top]
    header = f"{'TICKER':<8}{'ENTRY':>10}{'STOP':>10}{'TARGET':>10}{'RISK%':>8}{'VOLx':>8}{'52W-DIST':>10}"
    print(header)
    print("-" * len(header))
    for s in signals:
        line = (
            f"{s.ticker:<8}"
            f"{s.entry:>10.2f}"
            f"{s.stop:>10.2f}"
            f"{s.target:>10.2f}"
            f"{s.risk_pct * 100:>7.1f}%"
            f"{s.volume_multiple:>8.2f}"
            f"{s.distance_to_high_pct * 100:>9.1f}%"
        )
        line += _maybe_sizing_line(s.entry, s.stop, settings)
        print(line)
    print()
    print(
        f"{len(signals)} candidate(s). Stop = {STOP_PCT * 100:.1f}% "
        f"(or below consolidation low). Target = entry + {RISK_REWARD:.0f}x risk."
    )
    if not settings.configured:
        print(
            "Run `stockscanner config --account-size <USD> --risk-per-trade 1` "
            "to enable position sizing."
        )


def _print_warrior_signals(
    signals: List[WarriorSignal], top: int, settings: AccountSettings
) -> None:
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
        line = (
            f"{s.ticker:<8}"
            f"{s.last_price:>9.2f}"
            f"{s.gap_pct * 100:>7.1f}%"
            f"{s.relative_volume:>7.2f}x"
            f"{s.recent_run_pct * 100:>7.1f}%"
            f"{s.suggested_entry:>9.2f}"
            f"{s.suggested_stop:>9.2f}"
            f"{s.suggested_target:>9.2f}"
        )
        line += _maybe_sizing_line(s.suggested_entry, s.suggested_stop, settings)
        print(line)
    print()
    print(f"{len(signals)} gapper(s). Entry = today's high; stop = today's low; 2:1 R/R target.")
    print("Day-trading style — risk capital only.")


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

    journal = Journal.load()
    today_iso = datetime.utcnow().date().isoformat()
    settings = get_account_settings()

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
                journal.upsert_alert(
                    ticker=sig.ticker,
                    alert_date=today_iso,
                    entry=sig.entry,
                    stop=sig.stop,
                    target=sig.target,
                    strategy="breakout",
                    score=sig.score,
                )
        print()
        _print_breakout_signals(breakout_signals, top=args.top, settings=settings)
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
                journal.upsert_alert(
                    ticker=sig.ticker,
                    alert_date=today_iso,
                    entry=sig.suggested_entry,
                    stop=sig.suggested_stop,
                    target=sig.suggested_target,
                    strategy="warrior",
                    score=sig.score,
                )
        print()
        _print_warrior_signals(warrior_signals, top=args.top, settings=settings)

    journal.save()
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

    settings = get_account_settings()
    if args.shares is not None:
        shares = int(args.shares)
    else:
        if not settings.configured:
            print(
                "Pass --shares N, or configure your account first:\n"
                "  stockscanner config --account-size <USD> --risk-per-trade 1",
                file=sys.stderr,
            )
            return 2
        try:
            sized = size_trade(entry=entry, stop=stop, settings=settings)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        if sized.shares <= 0:
            print(
                "Computed share count is 0 — risk per share too large for your "
                "risk budget. Adjust the stop or per-trade risk %.",
                file=sys.stderr,
            )
            return 2
        shares = sized.shares
        for note in sized.notes:
            print(f"  note: {note}")
        print(
            f"  sizing: {shares} sh, ${sized.notional:,.0f} notional "
            f"({sized.notional_pct_of_account:.1f}% acct), risk ${sized.risk_dollars:,.0f}"
        )

    pos = Position.new(
        ticker=ticker,
        entry_price=entry,
        shares=shares,
        stop=stop,
        target=target,
        notes=args.notes or "",
    )
    store.add(pos)
    store.save()

    # Mark the journal entry as taken if there's a recent matching alert.
    journal = Journal.load()
    today = datetime.utcnow().date().isoformat()
    for window_back in range(0, 10):
        date_str = (
            datetime.utcnow().date().fromordinal(
                datetime.utcnow().date().toordinal() - window_back
            )
        ).isoformat()
        match = next(
            (e for e in journal.entries
             if e.ticker == ticker and e.alert_date == date_str and e.status == "PENDING"),
            None,
        )
        if match:
            match.taken = True
            journal.save()
            break

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
    did_something = False

    if args.finnhub_key:
        set_finnhub_key(args.finnhub_key)
        print("Finnhub API key saved. Real-time quotes enabled in `watch`.")
        did_something = True
    if args.clear_finnhub_key:
        clear_finnhub_key()
        print("Finnhub API key cleared. Watch loop falls back to yfinance.")
        did_something = True

    account_changes = {
        "account_size": args.account_size,
        "risk_per_trade_pct": args.risk_per_trade,
        "max_position_pct": args.max_position,
        "max_daily_loss_pct": args.max_daily_loss,
        "paper_trading": args.paper_trading,
    }
    if any(v is not None for v in account_changes.values()):
        try:
            updated = set_account_settings(**{k: v for k, v in account_changes.items() if v is not None})
        except ValueError as e:
            print(f"Invalid setting: {e}", file=sys.stderr)
            return 2
        print(
            f"Account settings: ${updated.account_size:,.0f} | "
            f"risk {updated.risk_per_trade_pct:.2f}%/trade | "
            f"max position {updated.max_position_pct:.0f}% | "
            f"daily loss limit {updated.max_daily_loss_pct:.1f}% | "
            f"{'paper' if updated.paper_trading else 'live'}"
        )
        did_something = True

    if args.show or not did_something:
        key = get_finnhub_key()
        if key:
            masked = key[:4] + "…" + key[-4:] if len(key) > 8 else "set"
            print(f"Finnhub API key:    {masked} (real-time enabled)")
        else:
            print(f"Finnhub API key:    not set (yfinance, 15-min delayed)")
        s = get_account_settings()
        if s.configured:
            print(f"Account size:       ${s.account_size:,.0f}")
            print(f"Risk per trade:     {s.risk_per_trade_pct:.2f}%")
            print(f"Max position size:  {s.max_position_pct:.0f}%")
            print(f"Daily loss limit:   {s.max_daily_loss_pct:.1f}%")
            print(f"Mode:               {'paper' if s.paper_trading else 'LIVE'}")
        else:
            print(
                f"Account size:       not configured\n"
                f"  → run: stockscanner config --account-size 10000 --risk-per-trade 1"
            )
    return 0


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


def cmd_review(args: argparse.Namespace) -> int:
    """The daily workflow: positions check + new alerts + journal stats.

    Designed to be the only command you run after the close. Combines:
      1. Current open positions with HOLD/EXIT signals
      2. A fresh scan with sized share suggestions
      3. Auto-resolves any pending journal entries against the latest data
      4. Performance summary (last 30 / 90 / all)
    """
    settings = get_account_settings()
    journal = Journal.load()

    print("=" * 64)
    print("DAILY REVIEW")
    print("=" * 64)
    print()

    # 1. Positions
    print("Open positions")
    print("-" * 64)
    pos_args = argparse.Namespace()
    cmd_positions(pos_args)

    # 2. Resolve pending journal entries.
    print()
    print("Journal — auto-resolving pending alerts...")
    transitioned = resolve_pending(journal)
    journal.save()
    if transitioned:
        print(f"  {transitioned} alert(s) resolved this run.")

    # 3. New scan.
    print()
    print(f"New {getattr(args, 'strategy', DEFAULT_STRATEGY)} candidates")
    print("-" * 64)
    scan_args = argparse.Namespace(
        strategy=getattr(args, "strategy", DEFAULT_STRATEGY),
        screen=None,
        screen_count=25,
        watchlist=args.watchlist,
        top=args.top,
        refresh_universe=False,
    )
    cmd_scan(scan_args)

    # 4. Performance summary.
    print()
    print("Performance")
    print("-" * 64)
    journal = Journal.load()  # reload after scan logged new alerts
    for label, window in [("last 30 days", 30), ("last 90 days", 90), ("all time", None)]:
        s = compute_stats(journal, window_days=window)
        if s.total_alerts == 0:
            print(f"  {label:<14}  no alerts yet")
            continue
        print(
            f"  {label:<14}  alerts {s.total_alerts:>3}  "
            f"resolved {s.wins + s.losses + s.breakevens:>3}  "
            f"win {s.win_rate_pct:>5.1f}%  "
            f"avg {s.avg_r_multiple:+.2f}R  "
            f"best {s.best_r:+.2f}R  worst {s.worst_r:+.2f}R"
        )
    if not settings.configured:
        print()
        print("  ⚠  account size not configured — sizing disabled.")
        print("     run: stockscanner config --account-size <USD> --risk-per-trade 1")

    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    """Inspect the journal: recent alerts and their outcomes."""
    journal = Journal.load()
    if args.resolve:
        n = resolve_pending(journal)
        journal.save()
        print(f"Resolved {n} pending entry/entries.")
        return 0

    entries = sorted(journal.entries, key=lambda e: e.alert_date, reverse=True)
    if args.limit:
        entries = entries[: args.limit]

    if not entries:
        print("Journal is empty. Run `stockscanner scan` to log alerts.")
        return 0

    header = (
        f"{'DATE':<11}{'TICKER':<8}{'STRAT':<10}"
        f"{'STATUS':<11}{'R':>7}{'TAKEN':>7}"
    )
    print(header)
    print("-" * len(header))
    for e in entries:
        r = f"{e.r_multiple:+.2f}" if e.r_multiple is not None else "-"
        taken = "yes" if e.taken else ""
        print(
            f"{e.alert_date:<11}{e.ticker:<8}{e.strategy:<10}"
            f"{e.status:<11}{r:>7}{taken:>7}"
        )

    print()
    s = compute_stats(journal)
    if s.wins + s.losses + s.breakevens > 0:
        print(
            f"All-time: {s.win_rate_pct:.1f}% win rate, "
            f"{s.avg_r_multiple:+.2f}R avg, "
            f"best {s.best_r:+.2f}R, worst {s.worst_r:+.2f}R"
        )
    return 0


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
        help="Manage settings: account size, risk %, API keys.",
    )
    # API key
    p_config.add_argument(
        "--finnhub-key",
        help="Save your Finnhub API key for real-time quotes.",
    )
    p_config.add_argument(
        "--clear-finnhub-key",
        action="store_true",
        help="Remove the saved Finnhub API key (fall back to yfinance).",
    )
    # Account / risk settings
    p_config.add_argument(
        "--account-size",
        type=float,
        help="Total account equity in USD. Required for position sizing.",
    )
    p_config.add_argument(
        "--risk-per-trade",
        type=float,
        help="Max % of account at risk per trade (default 1, max 5).",
    )
    p_config.add_argument(
        "--max-position",
        type=float,
        help="Max % of account a single position can use (default 25).",
    )
    p_config.add_argument(
        "--max-daily-loss",
        type=float,
        help="Daily loss circuit breaker as %% of account (default 3).",
    )
    p_config.add_argument(
        "--paper-trading",
        type=lambda v: v.lower() in {"1", "true", "yes", "on"},
        metavar="BOOL",
        help="Mark new positions as paper-tracked (true/false).",
    )
    p_config.add_argument(
        "--show",
        action="store_true",
        help="Show current settings.",
    )
    p_config.set_defaults(func=cmd_config)

    p_review = sub.add_parser(
        "review",
        help="The daily workflow — positions, new alerts, journal stats.",
    )
    p_review.add_argument(
        "--strategy",
        choices=STRATEGIES,
        default=DEFAULT_STRATEGY,
        help="Which strategy's scan to run (default: breakout).",
    )
    p_review.add_argument(
        "--watchlist",
        help="Path or name of a watchlist text file (overrides default).",
    )
    p_review.add_argument(
        "--top", type=int, default=15, help="Max alerts to show in review."
    )
    p_review.set_defaults(func=cmd_review)

    p_journal = sub.add_parser(
        "journal",
        help="Inspect logged alerts and their auto-tracked outcomes.",
    )
    p_journal.add_argument(
        "--limit", type=int, default=30, help="Show the most recent N entries (default 30)."
    )
    p_journal.add_argument(
        "--resolve",
        action="store_true",
        help="Re-check all PENDING entries against latest data and update status.",
    )
    p_journal.set_defaults(func=cmd_journal)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
