"""Linux detection with mocked command output; runs on any OS."""

import json

import pytest

from soundbar_autoprofile.detect import linux
from soundbar_autoprofile.detect.parsing import (
    PLAYERCTL_SEP,
    guess_media_type,
    parse_hyprctl_activewindow,
    parse_pactl_monitor_sources,
    parse_pactl_source_outputs,
    parse_playerctl,
    parse_sway_tree,
    xprop_is_fullscreen,
)


def _pc(*fields):
    return PLAYERCTL_SEP.join(fields)


def test_playerctl_first_playing_player():
    out = "\n".join([
        _pc("spotify", "Paused", "Old song", "Band", "spotify:track:1", ""),
        _pc("firefox.instance_1_42", "Playing", "Cat video - YouTube", "Cats", "/org/mpris/MediaPlayer2/firefox", ""),
    ])
    m = parse_playerctl(out)
    assert m["app"] == "Firefox" and m["title"] == "Cat video - YouTube"
    assert m["type"] == ""          # a browser with an "artist" is not necessarily music


def test_playerctl_nothing_playing():
    assert parse_playerctl(_pc("spotify", "Paused", "x", "y", "", "")) is None
    assert parse_playerctl("") is None


@pytest.mark.parametrize("player, url, trackid, artist, expected", [
    ("spotify", "", "spotify:track:1", "Band", "music"),
    ("vlc", "file:///home/u/film.mkv", "", "", "video"),
    ("vlc", "file:///home/u/song.flac", "", "Band", "music"),
    ("mpv", "", "", "", "video"),
    ("celluloid", "", "", "", "video"),
    ("chromium", "https://www.youtube.com/watch?v=abc", "", "Channel", "video"),
    ("chromium", "https://music.youtube.com/watch?v=abc", "", "Band", "music"),
    ("firefox", "", "", "Channel", ""),
    ("some-player", "", "/org/videolan/video/1", "", "video"),
    ("some-player", "", "", "Band", "music"),
    ("some-player", "", "", "", ""),
])
def test_media_type_guess(player, url, trackid, artist, expected):
    assert guess_media_type(player, url, trackid, artist) == expected


def test_xprop_fullscreen():
    assert xprop_is_fullscreen("_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN, _NET_WM_STATE_FOCUSED")
    assert not xprop_is_fullscreen("_NET_WM_STATE(ATOM) = _NET_WM_STATE_MAXIMIZED_VERT")
    assert not xprop_is_fullscreen("_NET_WM_STATE:  not found.")


def test_hyprctl_new_and_old_format():
    new = parse_hyprctl_activewindow(json.dumps({"class": "mpv", "title": "film.mkv", "pid": 42, "fullscreen": 2}))
    assert new == {"app": "mpv", "title": "film.mkv", "pid": 42, "fullscreen": True}
    assert parse_hyprctl_activewindow(json.dumps({"class": "x", "fullscreen": 1}))["fullscreen"] is False
    old = parse_hyprctl_activewindow(json.dumps({"class": "x", "fullscreen": True, "fullscreenMode": 0}))
    assert old["fullscreen"] is True
    assert parse_hyprctl_activewindow(json.dumps({"class": "x", "fullscreen": True, "fullscreenMode": 1}))[
        "fullscreen"] is False
    assert parse_hyprctl_activewindow("{}") is None           # no window focused
    assert parse_hyprctl_activewindow("Invalid") is None


def test_sway_tree_focused_window():
    tree = {"type": "root", "nodes": [{"type": "output", "nodes": [{"type": "workspace", "nodes": [
        {"type": "con", "focused": False, "app_id": "foot", "name": "shell", "pid": 1},
    ], "floating_nodes": [
        {"type": "floating_con", "focused": True, "app_id": None, "name": "Elden Ring", "pid": 77,
         "fullscreen_mode": 1, "window_properties": {"class": "eldenring.exe"}},
    ]}]}]}
    w = parse_sway_tree(json.dumps(tree))
    assert w == {"app": "eldenring.exe", "title": "Elden Ring", "pid": 77, "fullscreen": True}
    assert parse_sway_tree(json.dumps({"type": "root", "nodes": []})) is None
    assert parse_sway_tree("") is None


SOURCES = "\n".join([
    "0\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED",
    "1\talsa_input.usb-Blue_Yeti-00.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tRUNNING",
])

SOURCE_OUTPUTS = """Source Output #91
\tDriver: PipeWire
\tSource: 1
\tProperties:
\t\tapplication.name = "Firefox"
\t\tmedia.name = "AudioCallbackDriver"
\t\tapplication.process.binary = "firefox"

Source Output #92
\tSource: 0
\tProperties:
\t\tapplication.name = "OBS"

Source Output #93
\tSource: 1
\tProperties:
\t\tapplication.name = "PulseAudio Volume Control"
\t\tmedia.name = "Peak detect"

Source Output #94
\tSource: 1
\tProperties:
\t\tapplication.process.binary = "zoom"
"""


def test_pactl_skips_monitors_and_meters():
    monitors = parse_pactl_monitor_sources(SOURCES)
    assert monitors == {"0"}
    assert parse_pactl_source_outputs(SOURCE_OUTPUTS, monitors) == ["Firefox", "zoom"]
    assert parse_pactl_source_outputs("", monitors) == []


# --- the detector with fake commands -----------------------------------------------------------------------
def _fake_run(outputs):
    calls = []

    def run(*cmd):
        calls.append(cmd)
        return outputs.get(cmd[:2], outputs.get(cmd[:1], ""))

    return run, calls


def test_detector_x11(monkeypatch):
    for k in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK"):
        monkeypatch.delenv(k, raising=False)
    run, calls = _fake_run({
        ("playerctl",): _pc("vlc", "Playing", "film.mkv", "", "/org/videolan/vlc/playlist/3", "file:///f.mkv"),
        ("xdotool", "getactivewindow"): "12345",
        ("xdotool", "getwindowname"): "film.mkv - VLC media player",
        ("xdotool", "getwindowpid"): "4242",
        ("xprop",): "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN",
        ("pactl", "list"): "",
    })
    monkeypatch.setattr(linux, "_run", run)
    monkeypatch.setattr(linux, "_comm", lambda pid: "vlc" if str(pid) == "4242" else "")
    a = linux.LinuxDetector().read()
    assert a.media_playing and a.media_app == "VLC" and a.media_type == "video"
    assert (a.foreground_app, a.foreground_title, a.fullscreen) == ("vlc", "film.mkv - VLC media player", True)
    assert ("xprop", "-id", "12345", "_NET_WM_STATE") in calls


def test_detector_hyprland_does_not_use_xdotool(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc")
    monkeypatch.delenv("SWAYSOCK", raising=False)
    run, calls = _fake_run({("hyprctl",): json.dumps({"class": "steam_app_1", "title": "Game", "pid": 9,
                                                       "fullscreen": 2})})
    monkeypatch.setattr(linux, "_run", run)
    monkeypatch.setattr(linux, "_comm", lambda pid: "")
    a = linux.LinuxDetector().read()
    assert (a.foreground_app, a.foreground_title, a.fullscreen) == ("steam_app_1", "Game", True)
    assert not any(c[0] == "xdotool" for c in calls)


def test_detector_kde_wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    for k in ("HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK"):
        monkeypatch.delenv(k, raising=False)
    run, _ = _fake_run({
        ("kdotool", "getactivewindow"): "{0b1c}",
        ("kdotool", "getwindowname"): "Document - Kate",
        ("kdotool", "getwindowpid"): "77",
        ("kdotool", "getwindowclassname"): "org.kde.kate",
    })
    monkeypatch.setattr(linux, "_run", run)
    monkeypatch.setattr(linux, "_comm", lambda pid: "kate")
    a = linux.LinuxDetector().read()
    assert (a.foreground_app, a.foreground_title, a.fullscreen) == ("kate", "Document - Kate", False)


def test_detector_mic(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def run(*cmd):
        if cmd[:3] == ("pactl", "list", "source-outputs"):
            return SOURCE_OUTPUTS
        if cmd[:3] == ("pactl", "list", "short"):
            return SOURCES
        return ""

    monkeypatch.setattr(linux, "_run", run)
    a = linux.LinuxDetector().read()
    assert a.mic_in_use and a.mic_apps == ["Firefox", "zoom"]


def test_detector_never_raises(monkeypatch):
    def boom(*cmd):
        raise RuntimeError("broken tool")

    monkeypatch.setattr(linux, "_run", boom)
    a = linux.LinuxDetector().read()
    assert not a.media_playing and not a.mic_in_use


def test_run_missing_tool_returns_empty():
    assert linux._run("definitely-not-a-real-tool-xyz", "--version") == ""
