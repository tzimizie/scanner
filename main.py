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
    # Argparse with `required=True` exits with code 2 when no subcommand is
    # given. Show usage hints and pause so a double-click user sees something.
    if len(sys.argv) == 1 and _was_double_clicked():
        print("stockscanner — usage:")
        print("  stockscanner scan                 # screen S&P 500 for setups")
        print("  stockscanner scan --top 10        # show 10 strongest setups")
        print("  stockscanner enter NVDA --shares 50 --price 875.20")
        print("  stockscanner positions            # check open positions")
        print("  stockscanner close NVDA")
        print()
        print("Run it from a cmd window for live output, or pass --help to any")
        print("command for the full option list.")
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
