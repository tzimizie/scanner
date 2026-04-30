"""Command-line interface — wires data, strategy, and positions together."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from . import __version__
from .data import fetch_history, fetch_one
from .positions import Position, PositionStore
from .strategy import (
    STOP_PCT,
    RISK_REWARD,
    BreakoutSignal,
    evaluate_position,
    find_breakout,
)
from .universe import load_sp500, load_watchlist, normalize_tickers


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_signals(signals: List[BreakoutSignal], top: int) -> None:
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


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_scan(args: argparse.Namespace) -> int:
    if args.watchlist:
        tickers = load_watchlist(Path(args.watchlist))
    else:
        tickers = load_sp500(force_refresh=args.refresh_universe)
    tickers = normalize_tickers(tickers)
    print(f"Scanning {len(tickers)} ticker(s)...")

    bars = fetch_history(tickers)
    print(f"Fetched data for {len(bars)} ticker(s).")

    signals: List[BreakoutSignal] = []
    for ticker, df in bars.items():
        try:
            sig = find_breakout(df, ticker)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {ticker}: error during analysis: {e}", file=sys.stderr)
            continue
        if sig is not None:
            signals.append(sig)

    print()
    _print_signals(signals, top=args.top)
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

    p_scan = sub.add_parser("scan", help="Screen the universe for breakout setups today.")
    p_scan.add_argument(
        "--watchlist",
        help="Path to a text file with one ticker per line (overrides S&P 500).",
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

    return p


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
