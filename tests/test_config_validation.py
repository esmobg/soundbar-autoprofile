"""Config mistakes must fail at load time (``gs5 config check``), not in the running daemon."""

from __future__ import annotations

import pytest

from soundbar_autoprofile import config
from soundbar_autoprofile.detect import Activity
from soundbar_autoprofile.devices.base import Profile
from soundbar_autoprofile.rules import Rule

BASE = """
default_profile: d
profiles:
  d: {}
"""


def parse(extra: str = "", profiles: str = "", rules: str = ""):
    text = BASE + profiles
    if rules:
        text += "rules:\n" + rules
    return config.parse(text + extra, "test.yaml")


def rule(**kw):
    return Rule.from_dict({"profile": "d", **kw})


# ----- rules

def test_bad_regex_names_rule_field_and_pattern():
    with pytest.raises(ValueError, match=r"rule 'broken', when\.media_app: invalid regular expression '\(spotify'"):
        rule(name="broken", when={"media_app": "(spotify"})


def test_bad_regex_in_a_list_and_in_unless():
    with pytest.raises(ValueError, match=r"unless\.foreground_app: invalid regular expression '\[a-'"):
        rule(when={"fullscreen": True}, unless={"foreground_app": ["ok", "[a-"]})


def test_bad_regex_is_reported_with_the_source_file():
    with pytest.raises(ValueError, match=r"^test\.yaml: rule"):
        parse(rules="  - {profile: d, when: {media_title: '*'}}\n")


@pytest.mark.parametrize("value", ["yes", "true", 1, None, ["true"]])
def test_boolean_fields_need_real_booleans(value):
    with pytest.raises(ValueError, match=r"when\.media_playing: needs true or false"):
        rule(when={"media_playing": value})


def test_yaml_no_as_media_app_is_rejected_with_a_hint():
    # YAML 1.1 reads an unquoted `no` as False
    with pytest.raises(ValueError, match=r"when\.media_app: needs a text pattern.*quote"):
        parse(rules="  - {profile: d, when: {media_app: no}}\n")
    assert parse(rules="  - {profile: d, when: {media_app: \"no\"}}\n").rules[0].matches(Activity(media_app="NO"))


@pytest.mark.parametrize("value", [None, True, 2048, [], ["ok", None], {"a": 1}])
def test_text_fields_need_text_or_a_list_of_text(value):
    with pytest.raises(ValueError, match="needs a text pattern"):
        rule(when={"foreground_title": value})


@pytest.mark.parametrize("when", [None, {}])
def test_rule_without_when_can_never_match(when):
    with pytest.raises(ValueError, match="can never match"):
        rule(name="x", when=when)
    with pytest.raises(ValueError, match="can never match"):
        Rule.from_dict({"profile": "d"})


def test_rule_shape_errors():
    with pytest.raises(ValueError, match="must be a mapping"):
        Rule.from_dict(["profile", "d"])
    with pytest.raises(ValueError, match="unknown key"):
        rule(when={"fullscreen": True}, unles={"mic_in_use": True})
    with pytest.raises(ValueError, match="when must be a mapping"):
        rule(when=["fullscreen"])


def test_patterns_are_compiled_once_and_match_case_insensitively():
    r = rule(when={"media_app": ["spot", "vlc"]})
    assert all(isinstance(p.pattern, str) for p in r._when["media_app"])
    assert r.matches(Activity(media_app="SPOTIFY"))
    assert r.matches(Activity(media_app="VideoLAN.VLC"))
    assert not r.matches(Activity(media_app="chrome"))


def test_empty_values_are_matched_too():
    # a pattern is searched in the value even when the value is empty, so "^$" means "empty"
    r = rule(when={"media_playing": True, "media_type": "^$"})
    assert r.matches(Activity(media_playing=True, media_type=""))
    assert not r.matches(Activity(media_playing=True, media_type="video"))
    # an empty list (no app uses the microphone) is matched as one empty value
    no_mic_apps = rule(when={"mic_apps": "^$"})
    assert no_mic_apps.matches(Activity(mic_apps=[]))
    assert not no_mic_apps.matches(Activity(mic_apps=["Teams.exe"]))
    # an ordinary pattern still does not match an empty value
    assert not rule(when={"media_app": "spotify"}).matches(Activity(media_app=""))


# ----- profiles

def test_unquoted_rgb_number_is_rejected_with_a_hint():
    with pytest.raises(ValueError, match=r"profile 'p': rgb colour 112233 was read as a number; quote it"):
        parse(profiles="  p: {rgb: 112233}\n")


def test_octal_rgb_is_rejected():
    # YAML 1.1 reads 001100 as the octal number 576
    with pytest.raises(ValueError, match="read as a number"):
        parse(profiles="  p: {rgb: 001100}\n")


def test_rgb_in_a_list_must_be_quoted_too():
    with pytest.raises(ValueError, match="read as a number"):
        parse(profiles="  p: {rgb: [\"ffffff\", 123456, \"ffffff\", \"ffffff\", \"ffffff\", \"ffffff\", \"ffffff\"]}\n")


@pytest.mark.parametrize("rgb", ["fff", "gg0000", "#12345", "", [], True])
def test_bad_rgb_strings(rgb):
    with pytest.raises(ValueError, match="rgb"):
        Profile.from_dict("p", {"rgb": rgb})


def test_good_rgb_values():
    assert Profile.from_dict("p", {"rgb": "#FFaa00"}).rgb == "#FFaa00"
    seven = ["112233"] * 7
    assert parse(profiles=f"  p: {{rgb: {seven}}}\n").profiles["p"].rgb == seven


def test_rgb_list_length_must_fit_the_gs5():
    with pytest.raises(ValueError, match="rgb needs 1 colour or 7"):
        parse(profiles="  p: {rgb: [\"112233\", \"445566\"]}\n")


@pytest.mark.parametrize("value", ["50%", "50", True, -1, 101, 100.5, [50]])
def test_bad_brightness(value):
    with pytest.raises(ValueError, match="brightness must be a number from 0 to 100"):
        Profile.from_dict("p", {"brightness": value})


def test_brightness_percent_in_yaml():
    with pytest.raises(ValueError, match=r"brightness .* got '50%'"):
        parse(profiles="  p: {brightness: 50%}\n")


def test_good_brightness():
    assert Profile.from_dict("p", {"brightness": 0}).brightness == 0
    assert Profile.from_dict("p", {"brightness": 100}).brightness == 100
    assert Profile.from_dict("p", {"brightness": 42.4}).brightness == 42


@pytest.mark.parametrize("key, value", [("superwide", "on"), ("lighting", "off"), ("lighting", 0),
                                        ("sound_mode", 3), ("sound_mode", ""), ("eq", True)])
def test_setting_types(key, value):
    with pytest.raises(ValueError, match=key):
        Profile.from_dict("p", {key: value})


@pytest.mark.parametrize("frame, message", [
    ("05 6a zz", "not valid hex"),
    ("05 6a 0", "not valid hex"),
    ("06 6a 2c", "must start with the report id 05"),
    ("05" + " 00" * 64, "65 bytes, the limit is 64"),
    (56, "quoted hex strings"),
])
def test_bad_frames(frame, message):
    with pytest.raises(ValueError, match=message):
        Profile.from_dict("p", {"frames": [frame]})


def test_good_frames():
    p = Profile.from_dict("p", {"frames": ["05 6a 2c 01 00 01", "056a2c0100" + "00" * 59]})
    assert len(p.frames) == 2
    assert Profile.from_dict("p", {"frames": "05 6a 2c 01 00 01"}).frames == ["05 6a 2c 01 00 01"]


def test_null_settings_mean_leave_as_is():
    assert Profile.from_dict("p", {"rgb": None, "brightness": None}) == Profile("p")


def test_profile_must_be_a_mapping():
    with pytest.raises(ValueError, match="needs a mapping"):
        parse(profiles="  p: loud\n")


# ----- top level

@pytest.mark.parametrize("key, value, message", [
    ("poll_seconds", 0, "poll_seconds must be more than 0"),
    ("poll_seconds", -1, "poll_seconds must be more than 0"),
    ("hold_seconds", -1, "hold_seconds must be 0 or more"),
    ("media_grace_seconds", -0.5, "media_grace_seconds must be 0 or more"),
    ("keepalive_seconds", -1, "keepalive_seconds must be 0 or more"),
    ("poll_seconds", "1s", "poll_seconds must be a number"),
    ("hold_seconds", True, "hold_seconds must be a number"),
])
def test_bad_timings(key, value, message):
    with pytest.raises(ValueError, match=message):
        parse(f"{key}: {value!r}\n".replace("'", '"'))


def test_zero_timings_are_allowed():
    cfg = parse("hold_seconds: 0\nmedia_grace_seconds: 0\nkeepalive_seconds: 0\npoll_seconds: 0.5\n")
    assert (cfg.hold_seconds, cfg.media_grace_seconds, cfg.keepalive_seconds, cfg.poll_seconds) == (0, 0, 0, 0.5)


def test_unknown_device():
    with pytest.raises(ValueError, match="unknown device 'gs6'; supported: gs5"):
        parse("device: gs6\n")


def test_unknown_top_level_keys_are_warnings():
    cfg = parse("poll_second: 2\ncolour: red\n")
    assert len(cfg.warnings) == 2
    assert cfg.warnings[0].startswith("test.yaml: unknown setting 'poll_second' is ignored")
    assert "did you mean 'poll_seconds'" in cfg.warnings[0]
    assert "unknown setting 'colour'" in cfg.warnings[1]
    assert parse().warnings == []


def test_undefined_default_profile_is_named():
    with pytest.raises(ValueError, match="default_profile refers to undefined profile 'nope'"):
        config.parse("default_profile: nope\nprofiles: {a: {}}\n")
    with pytest.raises(ValueError, match="default_profile refers to undefined profile 'default'"):
        config.parse("profiles: {a: {}}\n")


def test_undefined_rule_profile_lists_the_defined_ones():
    with pytest.raises(ValueError, match=r"rules refer to undefined profile\(s\): b; defined: d"):
        parse(rules="  - {profile: b, when: {mic_in_use: true}}\n")


@pytest.mark.parametrize("text", ["- a\n- b\n", "just text\n", "42\n"])
def test_top_level_must_be_a_mapping(text):
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        config.parse(text, "x.yaml")


def test_profiles_and_rules_shapes():
    with pytest.raises(ValueError, match="profiles must be a mapping"):
        config.parse("profiles: [a, b]\n")
    with pytest.raises(ValueError, match="rules must be a list"):
        parse("rules: {profile: d}\n")


def test_empty_config_needs_a_default_profile():
    with pytest.raises(ValueError, match="default_profile"):
        config.parse("")


def test_bundled_defaults_load_cleanly():
    cfg = config.parse(config.default_config_text(), "defaults")
    assert cfg.warnings == []

