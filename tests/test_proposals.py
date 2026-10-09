# ruff: noqa: E501  (the filename table reads best one case per line)
import pytest

from app.genres import DEFAULT, GenreMap
from app.models import InboxTrack
from app.proposals import parse_filename, propose, still_missing


@pytest.mark.parametrize(
    ("path", "artist", "title", "bpm", "key", "sure"),
    [
        ("Pool/Fisher - Losing It (Extended Mix).mp3", "Fisher", "Losing It (Extended Mix)", None, None, True),
        ("01. Netsky - Rio (feat. Digital Farm Animals).flac", "Netsky", "Rio (feat. Digital Farm Animals)", None, None, True),
        ("03 - Sub Focus ft. Kele - Turn Back Time [Ram Records].mp3", "Sub Focus feat. Kele", "Turn Back Time", None, None, True),
        ("A1. Bicep - Glue [128 Am].flac", "Bicep", "Glue", "128", "Am", True),
        ("Calibre - Mr Right On [174 BPM] [11A].wav", "Calibre", "Mr Right On", "174", "F#m", True),
        ("4 Non Blondes - What's Up.mp3", "4 Non Blondes", "What's Up", None, None, True),
        ("Hybrid_Minds_-_Paint_By_Numbers.m4a", "Hybrid Minds", "Paint By Numbers", None, None, False),
        ("Bootleg Edit 128bpm 8A.wav", None, "Bootleg Edit", "128", "Am", False),
        ("PROMO_unknown_track_final_v2.mp3", None, "PROMO unknown track final v2", None, None, False),
        # Real names from the owner's inbox
        ("Avicii - Addicted To You (Mont Rouge Edit) 124.mp3", "Avicii", "Addicted To You (Mont Rouge Edit)", "124", None, True),
        ("BILLIE JEAN [CARVALHO DRUNK MIX] v2.wav", None, "Billie Jean (Carvalho Drunk Mix) v2", None, None, False),
        ("block_&_crown_-_fall_down_tonight.mp3", "Block & Crown", "Fall Down Tonight", None, None, False),
        ("Joshwa Vs Fisher & Flowdan - Freaks Up (R3wire Mashup) 130.mp3", "Joshwa Vs Fisher & Flowdan", "Freaks Up (R3wire Mashup)", "130", None, True),
        ("DJ SNAKE - TURN DOWN FOR WHAT (VIP MIX).mp3", "DJ Snake", "Turn Down For What (VIP Mix)", None, None, False),
        ("Blink 182 - All The Small Things.mp3", "Blink 182", "All The Small Things", None, None, True),
    ],
)  # fmt: skip
def test_parse_filename(path, artist, title, bpm, key, sure):
    parsed = parse_filename(path)
    assert (parsed.artist, parsed.title, parsed.bpm, parsed.key, parsed.sure) == (
        artist, title, bpm, key, sure
    )  # fmt: skip


def test_genre_map():
    assert DEFAULT.tidy(["DnB"]) == ["Drum & Bass"]
    assert DEFAULT.tidy(["liquid"]) == ["Drum & Bass", "Liquid"]
    assert DEFAULT.tidy(["Neurofunk", "Drum & Bass"]) == ["Drum & Bass", "Neurofunk"]
    assert DEFAULT.tidy(["Deep House"]) == ["House", "Deep House"]
    assert DEFAULT.tidy(["Some New Genre"]) == ["Some New Genre"]  # unknown genres stay as they are
    custom = GenreMap.parse("# comment\nBreaks = Breakbeat\nBreaks > Nu Skool Breaks")
    assert custom.tidy(["nu skool breaks"]) == ["Breaks", "Nu Skool Breaks"]


def inbox(path, **tags) -> InboxTrack:
    return InboxTrack(path=path, format="mp3", size=1, mtime=0, **tags)


def test_untagged_track_gets_values_from_its_filename():
    track = inbox("Pool/Fisher - Losing It (Extended Mix) [126 8A].mp3")
    proposals = {p.field: p for p in propose(track)}
    assert proposals["artist"].value == "Fisher" and proposals["artist"].source == "filename"
    assert proposals["title"].value == "Losing It (Extended Mix)" and proposals["title"].sure
    assert (proposals["bpm"].value, proposals["key"].value) == ("126", "Am")
    assert still_missing(track, list(proposals.values())) == ["Genre", "Cover"]


def test_tags_in_the_file_win_but_get_tidied():
    track = inbox(
        "Wrong Artist - Wrong Title.mp3",
        artist="Sub Focus ft.  Kele",
        title="Turn Back Time",
        genre="DnB; Liquid",
        bpm=174,
        key_camelot="8A",
    )
    proposals = {p.field: p for p in propose(track)}
    assert proposals["artist"].value == "Sub Focus feat. Kele"
    assert proposals["artist"].source == "clean-up"
    assert proposals["genre"].value == "Drum & Bass; Liquid"
    assert "title" not in proposals and "bpm" not in proposals  # nothing to change


def test_nothing_proposed_for_complete_or_unreadable_tracks():
    complete = inbox("x.mp3", artist="A", title="T", genre="House", bpm=124, key_camelot="8A")
    assert propose(complete) == []
    assert propose(inbox("broken.flac", error="unreadable")) == []


def test_title_tags_lose_the_artist_and_bpm_they_repeat():
    track = inbox(
        "Haddaway - What is Love (nocapz. Remix).wav",
        title="Haddaway - What is Love (nocapz. Remix)",
        bpm=130,
    )
    proposals = {p.field: p for p in propose(track)}
    assert proposals["title"].value == "What is Love (nocapz. Remix)"
    assert proposals["title"].reason == "artist removed from title"
    assert proposals["artist"].value == "Haddaway"

    track = inbox("x.mp3", artist="Loud Luxury", title="Body (Zillionaire Edit) 126", bpm=126)
    title = next(p for p in propose(track) if p.field == "title")
    assert (title.value, title.reason) == ("Body (Zillionaire Edit)", "BPM removed from title")

    # A number that isn't the BPM stays: it's part of the title.
    track = inbox("x.mp3", artist="Blink", title="Track 182", bpm=124)
    assert not [p for p in propose(track) if p.field == "title"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Rio (club remix)", "Rio (Club Remix)"),
        ("What Is Love (nocapz. remix)", "What Is Love (nocapz. Remix)"),  # remixer name untouched
        ("Track (radio edit) [vip]", "Track (Radio Edit) [VIP]"),
        ("Tune (re-edit)", "Tune (Re-Edit)"),
        ("Song (feat. X) (dub)", "Song (feat. X) (Dub)"),
        ("Live Forever", "Live Forever"),  # only words inside brackets
        ("Body (extended)", "Body (Extended)"),  # only track types: a mix name too
        ("Rain (Club remix) [Re-edit]", "Rain (Club Remix) [Re-Edit]"),
        ("Hold On (DJ HYPE REMIX)", "Hold On (DJ HYPE REMIX)"),  # CAPITALS on purpose
        ("Fly (the long road)", "Fly (the long road)"),  # no mix word: part of the title
        ("Fly (feat. dub phizix)", "Fly (feat. dub phizix)"),  # an artist, not a dub
        ("Fly (with dub phizix)", "Fly (with dub phizix)"),
    ],
)
def test_mix_types_get_capital_letters(title, expected):
    from app.proposals import capitalise_mix_types

    assert capitalise_mix_types(title) == expected


def test_mix_type_clean_up_is_proposed_for_title_tags():
    track = inbox("x.mp3", artist="Netsky", title="Rio (club remix)")
    title = next(p for p in propose(track) if p.field == "title")
    assert (title.value, title.reason) == ("Rio (Club Remix)", "mix type capitalised")
