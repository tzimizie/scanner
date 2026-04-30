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
    """Default behavior on a bare double-click: launch the live watcher
    against Yahoo's "Day Gainers" screen.

    The screen refreshes every cycle so the scanner always tracks the day's
    biggest movers. Each ticker is then run through the Warrior-style filters
    (low-priced, big gap, heavy volume); when one matches the setup, an alert
    fires (console + Windows toast). If the user has explicitly seeded a
    `default.txt` watchlist, that takes precedence over the screen.

    Press Ctrl-C in the window to stop."""
    from argparse import Namespace

    from scanner.cli import cmd_watch
    from scanner.paths import default_watchlist_file

    use_screen = not default_watchlist_file().exists()

    print("=" * 60)
    print("Stock Scanner — live watch mode (Warrior-style)")
    if use_screen:
        print("  Tracking Yahoo's Day Gainers — list refreshes every 5 min.")
        print("  Alerts when a gainer also matches the gap + volume setup.")
    else:
        print(f"  Tracking watchlist: {default_watchlist_file().name}")
    print("  Press Ctrl-C in this window to stop.")
    print("=" * 60)
    print()

    args = Namespace(
        strategy="warrior",
        screen="day_gainers" if use_screen else None,
        screen_count=25,
        list_screens=False,
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
