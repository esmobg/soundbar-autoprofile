"""macOS detection with mocked command output; runs on any OS."""

import json
from types import SimpleNamespace

import pytest

from soundbar_autoprofile.detect import macos
from soundbar_autoprofile.detect.parsing import (
    mac_window_is_fullscreen,
    media_app_label,
    parse_media_control,
    parse_nowplaying_cli,
)


@pytest.mark.parametrize("bundle, label", [
    ("com.spotify.client", "Spotify (com.spotify.client)"),
    ("com.apple.Music", "Apple Music (com.apple.Music)"),
    ("com.apple.TV", "Apple TV (com.apple.TV)"),
    ("com.google.Chrome", "Chrome (com.google.Chrome)"),
    ("org.mozilla.firefox", "Firefox (org.mozilla.firefox)"),
    ("com.apple.Safari", "Safari (com.apple.Safari)"),
    ("org.videolan.vlc", "VLC (org.videolan.vlc)"),
    ("com.colliderli.iina", "IINA (com.colliderli.iina)"),
    ("com.example.unknown", "com.example.unknown"),
])
def test_bundle_labels(bundle, label):
    assert media_app_label(bundle) == label


def test_media_control_playing():
    out = json.dumps({"bundleIdentifier": "com.spotify.client", "playing": True, "title": "Song",
                      "artist": "Band", "album": "LP", "artworkData": "AAAA"})
    assert parse_media_control(out) == {"playing": True, "app": "Spotify (com.spotify.client)", "title": "Song",
                                        "artist": "Band", "type": "music"}


def test_media_control_browser_and_video_app():
    chrome = parse_media_control(json.dumps({"bundleIdentifier": "com.google.Chrome", "playing": True,
                                             "title": "Cat video", "artist": "Cats"}))
    assert chrome["type"] == "" and chrome["app"].startswith("Chrome")
    tv = parse_media_control(json.dumps({"bundleIdentifier": "com.apple.TV", "playing": True, "title": "Film"}))
    assert tv["type"] == "video"
    # web apps report the browser as parent
    parent = parse_media_control(json.dumps({"bundleIdentifier": "com.apple.WebKit.GPU", "playing": True,
                                             "parentApplicationBundleIdentifier": "com.apple.Safari"}))
    assert parent["app"].startswith("Safari")


def test_media_control_paused_null_and_garbage():
    assert parse_media_control(json.dumps({"bundleIdentifier": "x", "playing": False}))["playing"] is False
    assert parse_media_control(json.dumps({"bundleIdentifier": "x", "playbackRate": 1}))["playing"] is True
    assert parse_media_control("null") is None
    assert parse_media_control("") is None
    assert parse_media_control("error: something") is None


def test_nowplaying_cli():
    assert parse_nowplaying_cli("Song\nBand\n1\n") == {"playing": True, "app": "", "title": "Song",
                                                         "artist": "Band", "type": ""}
    assert parse_nowplaying_cli("Song\nBand\n0")["playing"] is False
    assert parse_nowplaying_cli("null\nnull\nnull") is None
    assert parse_nowplaying_cli("") is None


def test_fullscreen_from_window_bounds():
    screens = [(1512, 982), (2560, 1440)]
    full = {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 2560, "Height": 1440}}
    zoomed = {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 1512, "Height": 945}}
    menubar = {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 25, "kCGWindowBounds": {"Width": 1512, "Height": 982}}
    other = {"kCGWindowOwnerPID": 8, "kCGWindowLayer": 0, "kCGWindowBounds": {"Width": 1512, "Height": 982}}
    assert mac_window_is_fullscreen([zoomed, full], 7, screens)
    assert not mac_window_is_fullscreen([zoomed, menubar, other], 7, screens)


# --- the detector with fake commands -----------------------------------------------------------------------
def _detector(monkeypatch, tools, outputs, running=()):
    monkeypatch.setattr(macos.shutil, "which", lambda name: f"/opt/bin/{name}" if name in tools else None)
    calls = []

    def run(cmd, timeout=3):
        calls.append(cmd)
        key = cmd[0].rsplit("/", 1)[-1]
        if key == "osascript":
            key = "osascript:" + next((app for app in ("Spotify", "Music", "System Events") if app in cmd[2]), "")
        return outputs.get(key, "")

    monkeypatch.setattr(macos, "_run", run)
    monkeypatch.setattr(macos.psutil, "process_iter",
                        lambda attrs: [SimpleNamespace(info={"name": n}) for n in running])
    return macos.MacDetector(), calls


def test_media_control_is_used_first(monkeypatch):
    d, calls = _detector(monkeypatch, {"media-control"}, {
        "media-control": json.dumps({"bundleIdentifier": "com.google.Chrome", "playing": True, "title": "Trailer"}),
        "osascript:Spotify": "playing\tSong\tBand",
    }, running=["Spotify"])
    a = d.read()
    assert a.media_playing and a.media_app == "Chrome (com.google.Chrome)" and a.media_title == "Trailer"
    assert not any("Spotify" in " ".join(c) for c in calls)


def test_media_control_says_nothing_plays(monkeypatch):
    outputs = {"media-control": "null", "osascript:Spotify": "playing\tx\ty"}
    d, calls = _detector(monkeypatch, {"media-control"}, outputs, running=["Spotify"])
    assert not d.read().media_playing
    assert not any("Spotify" in " ".join(c) for c in calls)


def test_applescript_fallback_never_launches_players(monkeypatch):
    d, calls = _detector(monkeypatch, set(), {"osascript:Music": "playing\tSong\tBand",
                                              "osascript:Spotify": "playing\tOther\tX"}, running=["Music"])
    a = d.read()
    assert (a.media_app, a.media_title, a.media_artist, a.media_type) == ("Music", "Song", "Band", "music")
    assert not any("Spotify" in " ".join(c) for c in calls)    # Spotify is not running, so it is not asked


def test_nowplaying_cli_fallback(monkeypatch):
    d, _ = _detector(monkeypatch, {"nowplaying-cli"}, {"nowplaying-cli": "Song\nBand\n1"})
    a = d.read()
    assert a.media_playing and a.media_title == "Song"


def test_read_never_raises(monkeypatch):
    d, _ = _detector(monkeypatch, {"media-control"}, {})

    def boom(*a, **k):
        raise RuntimeError("broken")

    monkeypatch.setattr(macos.psutil, "process_iter", boom)
    monkeypatch.setattr(d, "_frontmost", boom)
    assert not d.read().media_playing


def test_osascript_player_parsing():
    assert macos.parse_osascript_player("Spotify", "") is None
    assert macos.parse_osascript_player("Spotify", "playing\tSong")["artist"] == ""
