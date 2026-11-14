"""Entry point of the packaged app (PyInstaller).

No arguments (double-click, autostart) = the tray icon. With arguments it is the normal ``gs5`` command line,
e.g. ``soundbar-autoprofile.exe probe`` or ``soundbar-autoprofile.exe --help``.
"""

import sys


def _attach_console() -> None:
    """The windowed Windows build has no console; print into the one it was started from, if any."""
    if sys.platform != "win32" or (sys.stdout is not None and sys.stderr is not None):
        return
    import ctypes

    if not ctypes.windll.kernel32.AttachConsole(-1):     # ATTACH_PARENT_PROCESS
        return
    try:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        print()     # the prompt has already been printed: start on a fresh line
    except OSError:
        pass


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv != ["tray"]:
        _attach_console()
    from soundbar_autoprofile.cli import main as cli_main

    return cli_main(argv or ["tray"])


if __name__ == "__main__":
    sys.exit(main())
