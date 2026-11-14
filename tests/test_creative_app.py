from soundbar_autoprofile.devices.base import Profile
from soundbar_autoprofile.devices.creative_app import SoundMode, parse_item_name

FACTORY = ("[Movie (00000000-0000-1000-8000-000000000004), Factory, MF8470, "
           "C:\\ProgramData\\Creative\\Movie.json]")
USER = ("[Филми и видео (582a100d-6821-4509-aa0a-aedcb4cfa39b), User, MF8470, "
        "C:\\Users\\x\\AppData\\Local\\Creative\\582a100d.json]")


def test_parse_factory_item():
    m = parse_item_name(FACTORY, ["00000000-0000-1000-8000-000000000004", "Movies", "Onboard"])
    assert m == SoundMode(name="Movies", id="00000000-0000-1000-8000-000000000004", internal="Movie",
                          kind="Factory")


def test_parse_user_item_with_spaces_and_cyrillic():
    m = parse_item_name(USER, ["582a100d-6821-4509-aa0a-aedcb4cfa39b", "Филми и видео", "Onboard"])
    assert (m.name, m.internal, m.kind) == ("Филми и видео", "Филми и видео", "User")


def test_parse_unloaded_item():
    assert parse_item_name("", []) is None


def test_matches_display_internal_and_id_ignoring_case():
    m = parse_item_name(FACTORY, ["00000000-0000-1000-8000-000000000004", "Movies", "Onboard"])
    assert m.matches("movies") and m.matches("MOVIE") and m.matches("00000000-0000-1000-8000-000000000004")
    assert not m.matches("music")


def test_profile_accepts_sound_mode():
    assert Profile.from_dict("x", {"sound_mode": "Gaming"}).sound_mode == "Gaming"
