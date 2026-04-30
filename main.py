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
    """Default behavior on a bare double-click: run the daily review.

    Combines (a) exit signals on every open position, (b) a fresh breakout
    scan with sized share counts, and (c) auto-resolved journal stats so
    you can see whether the strategy is working for you.

    Designed to be a once-a-day routine: open it after the close, see your
    day in 30 seconds, decide which (if any) trades to place tomorrow."""
    from argparse import Namespace

    from scanner.cli import cmd_review

    args = Namespace(
        strategy="breakout",
        watchlist=None,
        top=15,
    )
    try:
        return cmd_review(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    # No arguments → run the daily review. Window stays open after so the
    # user can read the output before it closes.
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
