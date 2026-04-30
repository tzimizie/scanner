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
    """Default behavior on a bare double-click: launch the live watcher.

    The window stays open and the scanner keeps polling the S&P 500 every
    5 minutes during market hours, alerting on new breakout candidates as
    they form. Press Ctrl-C in the window to stop."""
    from argparse import Namespace

    from scanner.cli import cmd_watch

    print("=" * 60)
    print("Stock Scanner — live watch mode")
    print("  Polling the S&P 500 every 5 minutes during market hours.")
    print("  New breakout candidates trigger console + toast alerts.")
    print("  Press Ctrl-C in this window to stop.")
    print("=" * 60)
    print()

    args = Namespace(
        interval=5,
        watchlist=None,
        top=10,
        no_notifications=False,
        after_hours=False,
    )
    try:
        return cmd_watch(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    # No arguments → run the live watch mode. The window stays open and the
    # scanner keeps polling. Anyone running from cmd can still pass explicit
    # subcommands and they're unchanged.
    if len(sys.argv) == 1:
        rc = _run_default_workflow()
        # Only pause if the watcher exited because of an error — a clean
        # Ctrl-C exit can close the window directly.
        if rc != 0:
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
