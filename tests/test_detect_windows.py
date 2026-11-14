"""Windows detection with fake SMTC sessions and a fake registry; runs on any OS."""

import sys
from types import SimpleNamespace

import pytest

from soundbar_autoprofile.detect import Activity, windows
from soundbar_autoprofile.detect.parsing import (
    friendly_app_name,
    is_windows_shell,
    media_app_label,
    mic_nonpackaged_name,
)


@pytest.mark.parametrize("aumid, label", [
    ("Chrome", "Chrome"),
    ("MSEdge", "Edge (MSEdge)"),
    ("308046B0AF4A39CB", "Firefox (308046B0AF4A39CB)"),
    ("Firefox", "Firefox"),
    ("Spotify.exe", "Spotify (Spotify.exe)"),
    ("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "Spotify (SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify)"),
    ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic",
     "Media Player (Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic)"),
    ("Microsoft.ZuneVideo_8wekyb3d8bbwe!Microsoft.ZuneVideo",
     "Films & TV (Microsoft.ZuneVideo_8wekyb3d8bbwe!Microsoft.ZuneVideo)"),
    ("VideoLAN.VLC_paz6r1rewnh0a!App", "VLC (VideoLAN.VLC_paz6r1rewnh0a!App)"),
    ("vlc.exe", "VLC (vlc.exe)"),
    ("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App", "Apple Music (AppleInc.AppleMusicWin_nzyj5cx40ttqa!App)"),
    ("AppleInc.AppleTVWin_nzyj5cx40ttqa!App", "Apple TV (AppleInc.AppleTVWin_nzyj5cx40ttqa!App)"),
    ("iTunes.exe", "iTunes (iTunes.exe)"),
    ("4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App", "Netflix (4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App)"),
    ("AmazonVideo.PrimeVideo_pwbj9vvecjh7j!App", "Prime Video (AmazonVideo.PrimeVideo_pwbj9vvecjh7j!App)"),
    ("Opera.1749950689", "Opera (Opera.1749950689)"),
    ("Brave.ZQDLS6GZUAZQE6UZIDZM3QHVXQ", "Brave (Brave.ZQDLS6GZUAZQE6UZIDZM3QHVXQ)"),
    ("foobar2000.exe", "foobar2000 (foobar2000.exe)"),
    ("SomeUnknownApp.exe", "SomeUnknownApp.exe"),
    ("", ""),
])
def test_aumid_labels(aumid, label):
    assert media_app_label(aumid) == label


def test_hashed_aumid_uses_taskbar_ids():
    assert friendly_app_name("ABCDEF0123456789", {"ABCDEF0123456789": "Thunderbird"}) == "Thunderbird"
    assert friendly_app_name("abcdef0123456789") == "Firefox"
    assert friendly_app_name("NOTAHASH12345678") == ""


def test_shell_processes_and_mic_names():
    assert is_windows_shell("Explorer.EXE") and is_windows_shell("LockApp.exe")
    assert not is_windows_shell("eldenring.exe")
    assert mic_nonpackaged_name("C:#Program Files#Zoom#bin#Zoom.exe") == "Zoom.exe"


# --- SMTC with fakes -------------------------------------------------------------------------------------------
def _session(aumid, status=4, ptype=None, title="", artist="", props_type=None, props_error=None):
    async def props():
        if props_error:
            raise props_error
        return SimpleNamespace(title=title, artist=artist, playback_type=props_type)

    return SimpleNamespace(source_app_user_model_id=aumid,
                           get_playback_info=lambda: SimpleNamespace(playback_status=status, playback_type=ptype),
                           try_get_media_properties_async=props)


class _Manager:
    def __init__(self, sessions, current=None, broken=False):
        self.sessions, self.current, self.broken = sessions, current, broken

    def get_sessions(self):
        if self.broken:
            raise OSError("RPC server unavailable")
        return self.sessions

    def get_current_session(self):
        return self.current


def _detector(*managers):
    d = windows.WindowsDetector()
    queue = list(managers)

    async def request():
        return queue.pop(0)

    d._request_manager = request
    d._mozilla_hash_names = lambda app_id: {}
    return d


def _media(d):
    a = Activity()
    d._read_media(a)
    return a


def test_playing_session_is_reported_with_friendly_name():
    s = _session("308046B0AF4A39CB", ptype=2, title="Cat video - YouTube", artist="Cats")
    d = _detector(_Manager([_session("Spotify.exe", status=5), s]))
    a = _media(d)
    d.close()
    assert a.media_playing and a.media_app == "Firefox (308046B0AF4A39CB)"
    assert (a.media_title, a.media_artist, a.media_type) == ("Cat video - YouTube", "Cats", "video")


def test_current_session_wins_and_type_falls_back_to_properties():
    spotify = _session("Spotify.exe", ptype=1, title="Song")
    vlc = _session("VideoLAN.VLC", props_type=2, title="film.mkv")
    d = _detector(_Manager([spotify, vlc], current=vlc))
    a = _media(d)
    d.close()
    assert a.media_app == "VLC (VideoLAN.VLC)" and a.media_type == "video"


def test_nothing_playing():
    d = _detector(_Manager([_session("Chrome", status=5)]))
    assert not _media(d).media_playing
    d.close()


def test_properties_error_keeps_the_session():
    d = _detector(_Manager([_session("Chrome", props_error=OSError("busy"))]))
    a = _media(d)
    d.close()
    assert a.media_playing and a.media_app == "Chrome" and a.media_title == ""


class _NoMediaType:
    """playback_type fails the way it does without the winrt-Windows.Media projection installed."""

    playback_status = 4
    title, artist = "Song", "Band"

    @property
    def playback_type(self):
        raise ImportError("No module named 'winrt.windows.media'")


def test_playback_type_error_keeps_title_and_artist():
    async def props():
        return _NoMediaType()

    s = SimpleNamespace(source_app_user_model_id="Spotify.exe", get_playback_info=_NoMediaType,
                        try_get_media_properties_async=props)
    d = _detector(_Manager([s]))
    a = _media(d)
    d.close()
    assert a.media_playing and a.media_app == "Spotify (Spotify.exe)"
    assert (a.media_title, a.media_artist, a.media_type) == ("Song", "Band", "")


def test_dead_manager_is_recreated_in_the_same_read():
    d = _detector(_Manager([], broken=True), _Manager([_session("Spotify.exe", title="Song")]))
    a = _media(d)
    assert a.media_playing and a.media_title == "Song"
    d.close()


def test_read_never_raises_and_works_after_close(monkeypatch):
    d = _detector(_Manager([], broken=True), _Manager([], broken=True), _Manager([_session("Chrome")]))
    monkeypatch.setattr(d, "_read_foreground", lambda a: (_ for _ in ()).throw(OSError("no desktop")))
    monkeypatch.setattr(d, "_read_mic", lambda a: None)
    assert d.read().media_playing is False         # both attempts fail, no exception
    d.close()
    assert d.read().media_app == "Chrome"          # a closed detector gets a new event loop
    d.close()


def test_timeout_does_not_hang(monkeypatch):
    import asyncio

    monkeypatch.setattr(windows, "_MEDIA_TIMEOUT", 0.05)

    class Slow(_Manager):
        def get_sessions(self):
            return [SimpleNamespace(source_app_user_model_id="Chrome",
                                    get_playback_info=lambda: SimpleNamespace(playback_status=4, playback_type=None),
                                    try_get_media_properties_async=lambda: asyncio.sleep(10))]

    d = _detector(Slow([]), Slow([]))
    assert not _media(d).media_playing
    d.close()


# --- registry with a fake winreg -----------------------------------------------------------------------------
class _FakeWinreg:
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = "HKCU", "HKLM"

    def __init__(self, tree):
        self.tree = tree   # {hive: nested dict}; leaves dict values are registry values

    class _Key:
        def __init__(self, node):
            self.node = node

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, parent, path):  # noqa: N802 - winreg API
        node = self.tree[parent] if isinstance(parent, str) else parent.node
        for part in path.split("\\"):
            node = node.get("keys", {}).get(part)
            if node is None:
                raise OSError(path)
        return self._Key(node)

    def EnumKey(self, key, i):  # noqa: N802
        names = list(key.node.get("keys", {}))
        if i >= len(names):
            raise OSError
        return names[i]

    def EnumValue(self, key, i):  # noqa: N802
        items = list(key.node.get("values", {}).items())
        if i >= len(items):
            raise OSError
        return items[i][0], items[i][1], 1

    def QueryValueEx(self, key, name):  # noqa: N802
        try:
            return key.node["values"][name], 4
        except KeyError:
            raise OSError(name) from None


def _path(path, leaf):
    node = leaf
    for part in reversed(path.split("\\")):
        node = {"keys": {part: node}}
    return node


def test_mic_apps_from_consent_store(monkeypatch):
    using = {"values": {"LastUsedTimeStart": 133, "LastUsedTimeStop": 0}}
    stopped = {"values": {"LastUsedTimeStart": 133, "LastUsedTimeStop": 140}}
    mic = {"keys": {
        "Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe": using,
        "MicrosoftTeams_8wekyb3d8bbwe": stopped,
        "NonPackaged": {"keys": {"C:#Program Files#Zoom#bin#Zoom.exe": using,
                                 "C:#Apps#discord.exe": stopped}},
    }}
    monkeypatch.setattr(windows, "winreg", _FakeWinreg({"HKCU": _path(windows._MIC_KEY, mic)}))
    assert windows.read_mic_apps() == ["Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe", "Zoom.exe"]
    d = windows.WindowsDetector()
    a = Activity()
    d._read_mic(a)
    assert a.mic_in_use and a.mic_apps == ["Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe", "Zoom.exe"]


def test_mic_without_registry_key(monkeypatch):
    monkeypatch.setattr(windows, "winreg", _FakeWinreg({"HKCU": {}}))
    assert windows.read_mic_apps() == []
    monkeypatch.setattr(windows, "winreg", None)
    assert windows.read_mic_apps() == []


def test_taskbar_ids(monkeypatch):
    mozilla = {"keys": {
        "Firefox": {"keys": {"TaskBarIDs": {"values": {r"C:\Program Files\Mozilla Firefox": "308046B0AF4A39CB"}}}},
        "Thunderbird": {"keys": {"TaskBarIDs": {"values": {r"C:\Program Files\Thunderbird": "d78bf5dd33499ec2"}}}},
        "Firefox Nightly": {},
    }}
    monkeypatch.setattr(windows, "winreg", _FakeWinreg({"HKLM": _path("Software\\Mozilla", mozilla), "HKCU": {}}))
    ids = windows.read_taskbar_ids()
    assert ids == {"308046B0AF4A39CB": "Firefox", "D78BF5DD33499EC2": "Thunderbird"}
    assert media_app_label("D78BF5DD33499EC2", ids) == "Thunderbird (D78BF5DD33499EC2)"


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real Windows APIs")
def test_real_detector_smoke():
    d = windows.WindowsDetector()
    try:
        a = d.read()
    finally:
        d.close()
    assert isinstance(a, Activity)
