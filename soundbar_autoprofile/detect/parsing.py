"""Pure helpers for the detectors: app-name normalisation and parsing of tool output.

Nothing here touches the OS, so it can be imported and tested on any platform.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

# --- media app names -----------------------------------------------------------------------------------------
# (regex searched in the raw id, case-insensitive) -> friendly name. First match wins, so specific ids come
# before generic ones. Raw ids are Windows AppUserModelIDs (SMTC), macOS bundle ids and Linux MPRIS names.
_APP_NAMES: list[tuple[str, str]] = [
    # Microsoft Store apps and Windows inbox players
    (r"Microsoft\.ZuneVideo", "Films & TV"),
    (r"Microsoft\.ZuneMusic|Microsoft\.Media\.Player", "Media Player"),
    (r"^wmplayer(\.exe)?$", "Windows Media Player"),
    (r"SpotifyAB\.SpotifyMusic|^spotify(\.exe)?$|com\.spotify\.client", "Spotify"),
    (r"AppleInc\.AppleMusicWin|^com\.apple\.Music$|^AppleMusic", "Apple Music"),
    (r"AppleInc\.AppleTVWin|^com\.apple\.TV$", "Apple TV"),
    (r"AppleInc\.iTunes|^itunes(\.exe)?$|^com\.apple\.iTunes$", "iTunes"),
    (r"\.Netflix_|^netflix|com\.netflix", "Netflix"),
    (r"PrimeVideo|com\.amazon\.aiv", "Prime Video"),
    (r"AmazonMobileLLC\.AmazonMusic|^amazon ?music|com\.amazon\.music", "Amazon Music"),
    (r"Disney\.|com\.disney", "Disney+"),
    (r"TIDAL|com\.tidal", "TIDAL"),
    (r"Deezer", "Deezer"),
    (r"plexinc|^plex", "Plex"),
    (r"Kodi|org\.xbmc", "Kodi"),
    (r"YouTubeMusic|youtube[-_ ]?music", "YouTube Music"),
    # video / music players
    (r"VideoLAN\.VLC|^vlc(\.exe)?$|org\.videolan\.vlc", "VLC"),
    (r"^mpv(\.exe)?$|io\.mpv", "mpv"),
    (r"mpc-hc|mpc-be", "MPC"),
    (r"potplayer", "PotPlayer"),
    (r"colliderli\.iina|^iina$", "IINA"),
    (r"QuickTimePlayer|^quicktime", "QuickTime Player"),
    (r"foobar2000", "foobar2000"),
    (r"musicbee", "MusicBee"),
    (r"^aimp", "AIMP"),
    # browsers (Chromium-based AUMIDs are e.g. "Chrome", "MSEdge", "Brave.<hash>", "Opera.<hash>")
    (r"^MSEdge|^Microsoft\.?Edge|com\.microsoft\.edgemac", "Edge"),
    (r"^Chrome|com\.google\.Chrome|^google-chrome|^chrome(\.exe)?$", "Chrome"),
    (r"^chromium|org\.chromium", "Chromium"),
    (r"firefox|org\.mozilla\.(firefox|nightly)", "Firefox"),
    (r"librewolf", "LibreWolf"),
    (r"waterfox", "Waterfox"),
    (r"brave", "Brave"),
    (r"opera", "Opera"),
    (r"vivaldi", "Vivaldi"),
    (r"company\.thebrowser|^arc$", "Arc"),
    (r"com\.apple\.Safari|^safari", "Safari"),
]
_APP_RES = [(re.compile(p, re.IGNORECASE), name) for p, name in _APP_NAMES]

# Firefox's AppUserModelID is a 16 hex digit hash of its install folder (e.g. "308046B0AF4A39CB").
_HASH_ID = re.compile(r"^[0-9A-F]{16}$", re.IGNORECASE)
# MPRIS bus names of browsers with several instances: "firefox.instance_1_23", "chromium.instance4242"
_INSTANCE_SUFFIX = re.compile(r"\.instance[_\d]*$", re.IGNORECASE)


def friendly_app_name(raw: str, hash_names: Mapping[str, str] | None = None) -> str:
    """Short, human name for a media app id, or "" when it is not known.

    ``hash_names`` maps hashed AUMIDs (upper case) to a product name, read from Mozilla's ``TaskBarIDs``.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if _HASH_ID.match(raw):
        return (hash_names or {}).get(raw.upper(), "Firefox")   # unknown hash: almost always Firefox
    raw = _INSTANCE_SUFFIX.sub("", raw)
    for rx, name in _APP_RES:
        if rx.search(raw):
            return name
    return ""


def media_app_label(raw: str, hash_names: Mapping[str, str] | None = None) -> str:
    """``"Friendly (raw id)"``, so rules can match either the friendly name or the raw id.

    Unknown ids are kept as they are, and the raw id is not repeated when it already is the friendly name.
    """
    raw = (raw or "").strip()
    name = friendly_app_name(raw, hash_names)
    if not name:
        return raw
    if name.lower() == raw.lower():
        return name
    return f"{name} ({raw})"


# --- media type ------------------------------------------------------------------------------------------------
_VIDEO_PLAYERS = re.compile(
    r"vlc|mpv|mpc|potplayer|kodi|plex|netflix|disney|prime ?video|stremio|iina|quicktime|apple ?tv|films & tv|"
    r"totem|showtime|celluloid|smplayer|haruna|dragon|clapper|parole|mplayer|jellyfin|infuse|xine|gnome-videos|"
    r"^videos$|^tv$",
    re.IGNORECASE)
_MUSIC_PLAYERS = re.compile(
    r"spotify|apple music|itunes|amazon music|tidal|deezer|youtube music|foobar2000|musicbee|aimp|rhythmbox|"
    r"clementine|strawberry|elisa|lollypop|amarok|audacious|quodlibet|cmus|mpd|ncspot|spotifyd|cider|"
    r"g4music|gapless|tauon|deadbeef|sayonara|museeks|^music$",
    re.IGNORECASE)
_BROWSERS = re.compile(r"chrome|chromium|edge|firefox|librewolf|waterfox|brave|opera|vivaldi|\barc\b|safari|"
                       r"epiphany|falkon|qutebrowser|plasma-browser-integration|^zen", re.IGNORECASE)
_VIDEO_EXT = re.compile(r"\.(mkv|mp4|m4v|avi|mov|webm|wmv|flv|mpe?g|m2ts|mts|ts|vob|ogv|3gp)(\?|#|$)",
                        re.IGNORECASE)
_AUDIO_EXT = re.compile(r"\.(mp3|flac|ogg|oga|opus|m4a|aac|wav|wma|alac|aiff?|ape|wv|mka)(\?|#|$)", re.IGNORECASE)
_VIDEO_SITES = re.compile(
    r"^https?://([^/]*\.)?(youtube\.com/(watch|shorts|live)|youtu\.be/|netflix\.com|vimeo\.com|twitch\.tv|"
    r"disneyplus\.com|primevideo\.com|hbomax\.com|max\.com|tv\.apple\.com|dailymotion\.com|crunchyroll\.com)",
    re.IGNORECASE)
_MUSIC_SITES = re.compile(r"^https?://([^/]*\.)?(music\.youtube\.com|open\.spotify\.com|soundcloud\.com|"
                          r"bandcamp\.com|deezer\.com|tidal\.com|music\.apple\.com)", re.IGNORECASE)


def is_video_player(name: str) -> bool:
    return bool(name and _VIDEO_PLAYERS.search(name))


def is_browser(name: str) -> bool:
    return bool(name and _BROWSERS.search(name))


def guess_media_type(player: str, url: str = "", trackid: str = "", artist: str = "") -> str:
    """"video", "music" or "" from what an MPRIS / now-playing source tells about the track."""
    url = url or ""
    if _MUSIC_SITES.search(url) or _AUDIO_EXT.search(url):
        return "music"
    if _VIDEO_SITES.search(url) or _VIDEO_EXT.search(url):
        return "video"
    if trackid and re.search(r"video", trackid, re.IGNORECASE):
        return "video"
    if is_video_player(player):
        return "video"
    if _MUSIC_PLAYERS.search(player or ""):
        return "music"
    if is_browser(player):
        return ""        # a browser tab can be anything; YouTube puts the channel into "artist"
    return "music" if artist else ""


# --- Windows -------------------------------------------------------------------------------------------------
# processes whose window may cover the whole screen without being a full-screen app
WINDOWS_SHELL_PROCESSES = frozenset({
    "explorer.exe", "lockapp.exe", "searchhost.exe", "searchapp.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "textinputhost.exe", "logonui.exe", "screenclippinghost.exe",
})


def is_windows_shell(process_name: str) -> bool:
    return (process_name or "").lower() in WINDOWS_SHELL_PROCESSES


def mic_nonpackaged_name(key_name: str) -> str:
    """ConsentStore ``NonPackaged`` sub-key ("C:#Program Files#App#app.exe") -> "app.exe"."""
    return key_name.replace("#", "\\").replace("/", "\\").rsplit("\\", 1)[-1]


# --- Linux ---------------------------------------------------------------------------------------------------
PLAYERCTL_SEP = "\x1f"
PLAYERCTL_FORMAT = PLAYERCTL_SEP.join(
    ["{{playerName}}", "{{status}}", "{{title}}", "{{artist}}", "{{mpris:trackid}}", "{{xesam:url}}"])


def parse_playerctl(out: str) -> dict[str, str] | None:
    """First playing player from ``playerctl -a metadata --format PLAYERCTL_FORMAT``, or None."""
    for line in (out or "").splitlines():
        name, status, title, artist, trackid, url = (line.split(PLAYERCTL_SEP) + [""] * 6)[:6]
        if status.strip() != "Playing":
            continue
        name = name.strip()
        return {
            "player": name,
            "app": media_app_label(_INSTANCE_SUFFIX.sub("", name)),
            "title": title,
            "artist": artist,
            "type": guess_media_type(_INSTANCE_SUFFIX.sub("", name), url, trackid, artist),
        }
    return None


def xprop_is_fullscreen(out: str) -> bool:
    """``xprop -id <wid> _NET_WM_STATE`` output contains the full-screen atom."""
    return "_NET_WM_STATE_FULLSCREEN" in (out or "")


def _json(text: str) -> Any:
    try:
        return json.loads(text) if text and text.strip() else None
    except ValueError:
        return None


def parse_hyprctl_activewindow(out: str) -> dict[str, Any] | None:
    """``hyprctl activewindow -j`` -> {"app", "title", "pid", "fullscreen"}."""
    d = _json(out)
    if not isinstance(d, dict) or not d:
        return None
    fs = d.get("fullscreen", 0)
    if isinstance(fs, bool):                 # Hyprland < 0.41: bool + fullscreenMode (0 full, 1 maximised)
        full = fs and d.get("fullscreenMode", 0) != 1
    else:                                    # newer: 0 none, 1 maximised, 2 full-screen, 3 both
        try:
            full = bool(int(fs) & 2)
        except (TypeError, ValueError):
            full = False
    return {"app": str(d.get("class") or d.get("initialClass") or ""), "title": str(d.get("title") or ""),
            "pid": _int(d.get("pid")), "fullscreen": full}


def parse_sway_tree(out: str) -> dict[str, Any] | None:
    """``swaymsg -t get_tree`` -> the focused window as {"app", "title", "pid", "fullscreen"}."""
    root = _json(out)
    if not isinstance(root, dict):
        return None
    stack = [root]
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        if n.get("focused") and n.get("type") in ("con", "floating_con"):
            props = n.get("window_properties") or {}
            return {"app": str(n.get("app_id") or props.get("class") or ""), "title": str(n.get("name") or ""),
                    "pid": _int(n.get("pid")), "fullscreen": bool(n.get("fullscreen_mode"))}
        stack.extend(n.get("nodes") or [])
        stack.extend(n.get("floating_nodes") or [])
    return None


def _int(v: Any) -> int | None:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


def parse_pactl_monitor_sources(out: str) -> set[str]:
    """Indexes of monitor sources (what is being played, not a microphone) from ``pactl list short sources``."""
    idx = set()
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].endswith(".monitor"):
            idx.add(parts[0].strip())
    return idx


# level meters, not recordings
_PACTL_IGNORED_MEDIA = re.compile(r"peak detect|volume control|pavucontrol", re.IGNORECASE)


def parse_pactl_source_outputs(out: str, monitor_sources: Iterable[str] = ()) -> list[str]:
    """App names recording from a real source in ``pactl list source-outputs`` (monitors and meters skipped)."""
    monitors = set(monitor_sources)
    apps: list[str] = []
    for block in re.split(r"\n(?=Source Output #)", out or ""):
        if not block.strip():
            continue
        props: dict[str, str] = {}
        source = ""
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("Source:"):
                source = s.split(":", 1)[1].strip()
            elif " = " in s:
                k, v = s.split(" = ", 1)
                props[k.strip()] = v.strip().strip('"')
        if source in monitors:
            continue
        name = props.get("application.name") or props.get("application.process.binary") or ""
        if not name or _PACTL_IGNORED_MEDIA.search(f"{name} {props.get('media.name', '')}"):
            continue
        if name not in apps:
            apps.append(name)
    return apps


# --- macOS ---------------------------------------------------------------------------------------------------
def parse_media_control(out: str) -> dict[str, Any] | None:
    """``media-control get`` JSON (``null`` when nothing is loaded) -> {"playing", "app", "title", "artist", "type"}.

    ``playing`` is a bool in media-control; ``playbackRate`` > 0 is accepted as well.
    """
    d = _json(out)
    if not isinstance(d, dict):
        return None
    playing = d.get("playing")
    if playing is None:
        try:
            playing = float(d.get("playbackRate") or 0) > 0
        except (TypeError, ValueError):
            playing = False
    bundle = str(d.get("parentApplicationBundleIdentifier") or d.get("bundleIdentifier") or "")
    title, artist = str(d.get("title") or ""), str(d.get("artist") or "")
    friendly = friendly_app_name(bundle)
    mtype = guess_media_type(friendly or bundle, artist=artist)
    if not mtype and d.get("isMusicApp") is True:
        mtype = "music"
    return {"playing": bool(playing), "app": media_app_label(bundle), "title": title, "artist": artist,
            "type": mtype}


NOWPLAYING_CLI_PROPS = ("title", "artist", "playbackRate")


def parse_nowplaying_cli(out: str) -> dict[str, Any] | None:
    """``nowplaying-cli get title artist playbackRate``: one value per line, "null" when missing."""
    lines = (out or "").splitlines()
    if len(lines) < len(NOWPLAYING_CLI_PROPS):
        return None
    vals = ["" if v.strip() == "null" else v.strip() for v in lines[:len(NOWPLAYING_CLI_PROPS)]]
    title, artist, rate = vals
    if not (title or artist):
        return None
    try:
        playing = float(rate or 0) > 0
    except ValueError:
        playing = False
    # nowplaying-cli does not say which app is playing
    return {"playing": playing, "app": "", "title": title, "artist": artist, "type": ""}


def mac_window_is_fullscreen(windows: Iterable[Mapping[str, Any]], pid: int,
                             screens: Iterable[tuple[float, float]]) -> bool:
    """Does a normal-layer window of ``pid`` cover a whole screen (menu bar included)?

    ``windows`` are CGWindowListCopyWindowInfo dicts; ``screens`` are (width, height) of each display. A zoomed
    window leaves the menu bar visible, so it does not count.
    """
    sizes = list(screens)
    for w in windows:
        if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer", 0) != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        width, height = float(b.get("Width", 0)), float(b.get("Height", 0))
        if any(width >= sw and height >= sh for sw, sh in sizes):
            return True
    return False
