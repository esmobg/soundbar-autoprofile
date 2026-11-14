# PyInstaller spec: one windowed executable that is the tray app (no arguments) and the full `gs5` CLI.
#
#   pip install ".[tray]" pyinstaller
#   pyinstaller --noconfirm --clean packaging/gs5.spec
#
# Output: dist/soundbar-autoprofile.exe (Windows), dist/soundbar-autoprofile.app (macOS),
# dist/soundbar-autoprofile (Linux).
import importlib.util
import sys
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
NAME = "soundbar-autoprofile"
sys.path.insert(0, str(ROOT))

from soundbar_autoprofile import __version__  # noqa: E402


def available(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


hidden = [
    "soundbar_autoprofile.tray",
    "soundbar_autoprofile.daemon",
    "hid",              # hidapi, imported lazily by the GS5 driver
    "pystray",
    "PIL.Image",
    "PIL.ImageDraw",
]
if sys.platform == "win32":
    hidden += ["soundbar_autoprofile.detect.windows", "pystray._win32", "pystray._util.win32"]
    hidden += collect_submodules("winrt")      # media sessions (WinRT projections are imported lazily)
    hidden += ["soundbar_autoprofile.devices.creative_app"]
    if available("uiautomation"):              # Creative App sound modes (optional, imported lazily)
        hidden += ["uiautomation", "comtypes", "comtypes.client", "comtypes.stream"]
elif sys.platform == "darwin":
    hidden += ["soundbar_autoprofile.detect.macos", "pystray._darwin", "AppKit", "Foundation", "objc"]
else:
    hidden += ["soundbar_autoprofile.detect.linux", "pystray._xorg"]
    if available("gi"):     # a real menu needs GTK + (Ayatana)AppIndicator from the system's PyGObject
        hidden += ["pystray._appindicator", "pystray._gtk", "pystray._util.gtk", "pystray._util.notify_dbus",
                   "gi.repository.Gtk", "gi.repository.GLib", "gi.repository.GObject"]
        for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
            hidden.append(f"gi.repository.{ns}")


def make_icon_file():
    """The app icon: the tray icon's orange circle."""
    try:
        from soundbar_autoprofile.tray import make_icon

        out = Path(tempfile.mkdtemp(prefix="gs5-icon-"))
        img = make_icon((0xFF, 0x5A, 0x00), size=256)
        if sys.platform == "win32":
            path = out / "icon.ico"
            img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        elif sys.platform == "darwin":
            path = out / "icon.icns"
            img.resize((512, 512)).save(path)
        else:
            return None
        return str(path)
    except Exception as e:      # an icon is nice to have, not worth failing the build for
        print(f"warning: no app icon: {e}")
        return None


icon = make_icon_file()

a = Analysis(
    [str(ROOT / "packaging" / "soundbar_autoprofile_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "soundbar_autoprofile" / "default_config.yaml"), "soundbar_autoprofile")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # an .app bundle without a Dock icon (menu bar only)
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, upx=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=icon,
        bundle_identifier="io.github.esmobg.soundbar-autoprofile",
        version=__version__,
        info_plist={
            "LSUIElement": True,
            "CFBundleShortVersionString": __version__,
            "NSAppleEventsUsageDescription": "Reads what Spotify / Music is playing to pick the sound profile.",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=NAME,
        console=False,      # windowed: no console window behind the tray icon
        upx=False,
        icon=icon,
    )
