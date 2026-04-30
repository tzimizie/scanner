"""Entry point for both `python main.py` and the PyInstaller .exe build."""
import sys
import traceback

from scanner.cli import main


_IS_WINDOWS = sys.platform == "win32"


def _pause(prompt: str = "\nPress Enter to close...") -> None:
    """Block until Enter so a Windows console window doesn't vanish before
    the user can read what happened. No-op on non-Windows."""
    if not _IS_WINDOWS:
        return
    try:
        input(prompt)
    except EOFError:
        pass


def _run_default_workflow() -> int:
    """Default behavior on a bare double-click: check open positions, then
    scan the S&P 500 for new breakouts. Most users want this every day."""
    from argparse import Namespace

    from scanner.cli import cmd_positions, cmd_scan

    print("=" * 60)
    print("Stock Scanner — running default workflow")
    print("  1) check open positions for exit signals")
    print("  2) screen the S&P 500 for breakout setups")
    print("=" * 60)
    print()

    try:
        print("--- Open positions ---")
        cmd_positions(Namespace())

        print()
        print("--- Breakout candidates ---")
        cmd_scan(Namespace(watchlist=None, top=25, refresh_universe=False))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    # No arguments → assume a Windows double-click and run the default
    # workflow so the user gets something useful. From cmd you can still pass
    # explicit subcommands and they're unchanged.
    if len(sys.argv) == 1:
        rc = _run_default_workflow()
        _pause()
        sys.exit(rc)

    # Otherwise, run the requested subcommand. Always pause on Windows when
    # something went wrong so the error message is readable before the
    # console closes — `_was_double_clicked` heuristics turned out to be
    # unreliable on some Windows setups.
    try:
        sys.exit(main() or 0)
    except SystemExit as e:
        if e.code is not None and e.code != 0:
            _pause()
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception:  # noqa: BLE001 - top-level safety net
        traceback.print_exc()
        _pause()
        sys.exit(1)
