"""Entry point for both `python main.py` and the PyInstaller .exe build."""
import sys
import traceback

from scanner.cli import main


def _was_double_clicked() -> bool:
    """Best-effort: when launched via Explorer there's no parent terminal, so
    the console window will close as soon as we exit. We detect that and pause
    on errors / no-args so the user can read the message."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # GetConsoleProcessList returns the count of processes attached to the
        # console. If we're the only one, the console belongs to us and will
        # vanish when we exit.
        processes = (ctypes.c_ulong * 4)()
        count = kernel32.GetConsoleProcessList(processes, 4)
        return count <= 1
    except Exception:  # noqa: BLE001
        return False


def _pause_if_needed() -> None:
    if _was_double_clicked():
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass


if __name__ == "__main__":
    double_clicked = _was_double_clicked()

    # When double-clicked with no arguments, default to a scan (with both the
    # market screen AND any open positions checked) — that's what the user
    # actually wants 99% of the time. Anyone running from cmd can still pass
    # explicit subcommands.
    if len(sys.argv) == 1 and double_clicked:
        print("=" * 60)
        print("Stock Scanner — running default workflow:")
        print("  1) check open positions for exit signals")
        print("  2) screen the S&P 500 for breakout setups")
        print("=" * 60)
        print()
        try:
            from scanner.cli import cmd_positions, cmd_scan
            from argparse import Namespace

            print("--- Open positions ---")
            cmd_positions(Namespace())

            print()
            print("--- Breakout candidates ---")
            cmd_scan(Namespace(watchlist=None, top=25, refresh_universe=False))
        except KeyboardInterrupt:
            print("\nInterrupted.")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        _pause_if_needed()
        sys.exit(0)

    try:
        sys.exit(main() or 0)
    except SystemExit:
        # argparse and explicit sys.exit() — already an int code, just pause.
        _pause_if_needed()
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception:  # noqa: BLE001 - top-level safety net
        traceback.print_exc()
        _pause_if_needed()
        sys.exit(1)
