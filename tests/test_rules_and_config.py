import pytest

from soundbar_autoprofile import config
from soundbar_autoprofile.detect import Activity
from soundbar_autoprofile.rules import Engine, Rule, choose

CFG = config.parse(config.default_config_text(), "defaults")


def pick(**kw):
    return choose(Activity(**kw), CFG.rules, CFG.default_profile)[0]


def test_default_config_is_valid():
    assert set(CFG.profiles) >= {"music", "movie", "work", "game", "default"}
    assert CFG.rules


@pytest.mark.parametrize("activity, expected", [
    (dict(media_playing=True, media_app="Spotify.exe", media_title="Song", media_artist="Band"), "music"),
    (dict(media_playing=True, media_app="VideoLAN.VLC", media_title="film.mkv"), "movie"),
    (dict(media_playing=True, media_app="chrome", media_type="video"), "movie"),
    (dict(media_playing=True, media_app="chrome", media_title="Netflix"), "movie"),
    (dict(media_playing=True, media_app="chrome", media_title="Cat video", foreground_app="chrome.exe",
          fullscreen=True), "movie"),
    (dict(mic_in_use=True, media_playing=True, media_app="Spotify.exe"), "work"),
    (dict(foreground_app="Code.exe"), "work"),
    (dict(foreground_app="WINWORD.EXE"), "work"),
    (dict(foreground_app="eldenring.exe", fullscreen=True), "game"),
    (dict(foreground_app="eldenring.exe", fullscreen=True, media_playing=True, media_app="Spotify.exe"), "game"),
    (dict(foreground_app="explorer.exe"), "default"),
    (dict(), "default"),
    # normalised media_app names from the detectors ("Friendly (raw id)")
    (dict(media_playing=True, media_app="Firefox (308046B0AF4A39CB)", media_title="Cat video - YouTube",
          media_artist="Cats", foreground_app="firefox.exe", fullscreen=True), "movie"),
    (dict(media_playing=True, media_app="Media Player (Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic)",
          media_title="Song", media_artist="Band", media_type="music"), "music"),
    (dict(media_playing=True, media_app="Films & TV (Microsoft.ZuneVideo_8wekyb3d8bbwe!Microsoft.ZuneVideo)",
          media_title="holiday.mp4"), "movie"),
    (dict(media_playing=True, media_app="Spotify (SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify)",
          media_title="Song"), "music"),
    (dict(media_playing=True, media_app="Netflix (4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App)"), "movie"),
    (dict(media_playing=True, media_app="Apple TV (com.apple.TV)", media_title="Film"), "movie"),
    (dict(media_playing=True, media_app="Edge (MSEdge)", media_title="Podcast"), "music"),
    (dict(media_playing=True, media_app="VLC", media_title="film.mkv", foreground_app="vlc"), "movie"),
    (dict(media_playing=True, media_app="Firefox", media_title="Cat video", foreground_app="chromium",
          fullscreen=True), "movie"),
    (dict(foreground_app="totem", fullscreen=True), "default"),
])
def test_default_rules(activity, expected):
    assert pick(**activity) == expected


def test_rule_with_unknown_condition_is_rejected():
    with pytest.raises(ValueError, match="unknown condition"):
        Rule.from_dict({"profile": "x", "when": {"colour": "red"}})


def test_undefined_profile_is_rejected():
    with pytest.raises(ValueError, match="undefined profile"):
        config.parse("profiles: {a: {}}\ndefault_profile: a\nrules: [{profile: b, when: {mic_in_use: true}}]")


def test_unknown_profile_setting_is_rejected():
    with pytest.raises(ValueError, match="unknown setting"):
        config.parse("profiles: {a: {volume: 3}}\ndefault_profile: a")


def test_engine_applies_first_decision_immediately_then_waits_for_hold():
    e = Engine(CFG.rules, "default", hold=3, media_grace=0)
    assert e.step(Activity(foreground_app="Code.exe"), 0).switch_to == "work"
    assert e.step(Activity(media_playing=True, media_app="Spotify"), 1).switch_to is None
    assert e.step(Activity(media_playing=True, media_app="Spotify"), 3.9).switch_to is None
    assert e.step(Activity(media_playing=True, media_app="Spotify"), 4.0).switch_to == "music"


def test_engine_ignores_short_blips():
    e = Engine(CFG.rules, "default", hold=3, media_grace=0)
    e.step(Activity(foreground_app="Code.exe"), 0)
    e.step(Activity(foreground_app="explorer.exe"), 1)          # alt-tab for a second
    assert e.step(Activity(foreground_app="Code.exe"), 2).switch_to is None
    assert e.step(Activity(foreground_app="explorer.exe"), 3).switch_to is None
    assert e.current == "work"


def test_media_grace_keeps_music_through_a_pause():
    e = Engine(CFG.rules, "default", hold=3, media_grace=15)
    e.step(Activity(media_playing=True, media_app="Spotify"), 0)
    for t in range(1, 15):
        assert e.step(Activity(foreground_app="explorer.exe"), t).switch_to is None
    assert e.current == "music"
    e.step(Activity(foreground_app="explorer.exe"), 16)
    assert e.step(Activity(foreground_app="explorer.exe"), 19).switch_to == "default"


def test_force_none_reapplies():
    e = Engine(CFG.rules, "default")
    e.step(Activity(), 0)
    e.force(None)
    assert e.step(Activity(), 1).switch_to == "default"
