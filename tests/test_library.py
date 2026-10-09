import shutil
from urllib.parse import parse_qs, urlsplit

import pytest
from mutagen.flac import FLAC
from sqlmodel import Session

from app.jobs import scan_job
from app.library import FLAGS, MISSING, TrackFilter, find_tracks, list_albums, list_artists
from app.preferences import Preferences
from app.scanner import ScanProgress, scan_library
from app.stats import HEAT_AXES, heatmap, library_stats
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"


def scan(engine, music_dir):
    scan_library(engine, music_dir, ScanProgress())


def find(engine, **filters):
    with Session(engine) as session:
        return find_tracks(session, TrackFilter(**filters))


def filter_from_url(url: str) -> TrackFilter:
    """Turn a dashboard link like /tracks?missing=BPM back into a TrackFilter."""
    params = {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}
    for numeric in ("bpm_min", "bpm_max", "length_min", "length_max"):
        if numeric in params:
            params[numeric] = float(params[numeric])
    for whole in ("decade", "year"):
        if whole in params:
            params[whole] = int(params[whole])
    return TrackFilter(**params)


def test_every_dashboard_number_matches_its_track_list(engine, music_dir):
    """Clicking a number on the dashboard must show exactly that many tracks."""
    scan(engine, music_dir)
    with Session(engine) as session:
        stats = library_stats(session, Preferences(show_musicbrainz=True))
        bars = stats.missing + stats.formats + stats.genres + stats.bpm
        bars += [cell for cell in stats.keys if cell.url]
        bars += stats.growth + stats.growth_years + stats.lengths + stats.labels
        bars += stats.top_artists + stats.set_ready_genres
        # Every cell of the heat map, for every pair of axes.
        for rows in HEAT_AXES:
            for cols in HEAT_AXES:
                if rows != cols:
                    grid = heatmap(session, rows, cols)
                    bars += [cell for line in grid.cells for cell in line]
        checked = 0
        for bar in bars:
            if not bar.url:
                continue
            listed = find_tracks(session, filter_from_url(bar.url)).total
            assert listed == bar.count, f"{bar.url}: dashboard {bar.count}, list {listed}"
            checked += 1
    assert checked >= 40


def test_flags_match_dashboard_counts(engine, music_dir):
    path = music_dir / ALBUM / "tagged.flac"
    audio = FLAC(path)
    audio["bpm"] = "0"
    audio.save()
    scan(engine, music_dir)
    with Session(engine) as session:
        stats = library_stats(session, Preferences())
        for flag, expected in {
            "bpm_zero": stats.bpm_zero,
            "lossless": stats.lossless,
            "low_bitrate": stats.low_bitrate,
            "untagged": stats.untagged,
            "bpm_and_key": stats.with_bpm_and_key,
            "audio_bpm_octave": stats.audio_bpm_octave,
            "audio_bpm_differs": stats.audio_bpm_differs,
            "audio_key_differs": stats.audio_key_differs,
            "not_analysed": stats.not_analysed,
            "duplicate": stats.duplicates,
        }.items():
            assert find_tracks(session, TrackFilter(flag=flag)).total == expected, flag
    assert stats.bpm_zero == 1


def test_genre_filter_matches_single_genres_in_multi_genre_tags(engine, music_dir):
    for name, genre in (("a", "House;Techno"), ("b", "Deep House; House"), ("c", "Tech House")):
        path = music_dir / "Unsorted" / f"{name}.flac"
        shutil.copy(FIXTURES / "tagged.flac", path)
        audio = FLAC(path)
        audio["genre"] = genre
        audio.save()
    scan(engine, music_dir)
    paths = {t.path for t in find(engine, genre="House").tracks}
    assert paths == {"Unsorted/a.flac", "Unsorted/b.flac"}  # not "Tech House" or "Deep House"


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"q": "silent"}, 7),  # title
        ({"q": "fixture records"}, 7),  # label
        ({"q": "riff-info"}, 1),  # path
        ({"format": "opus"}, 1),
        ({"missing": "BPM"}, 3),
        ({"key": "8A"}, 7),
        ({"bpm_min": 125, "bpm_max": 130}, 7),
        ({"bpm_min": 130}, 0),
        ({"decade": 1990}, 1),
        ({"folder": "Unsorted"}, 2),
        ({"folder": "Unsorted/"}, 2),
        ({"albumartist": "Fixture Artist", "album": "Fixture Album"}, 7),
        ({"albumartist": "Info Artist"}, 1),  # no album artist tag: falls back to artist
        ({"field": "riff-info:ICMT"}, 1),
        ({"field": "vorbis:bpm", "value": "126"}, 3),
        ({"field": "vorbis:bpm", "value": "999"}, 0),
    ],
)
def test_filters(engine, music_dir, filters, expected):
    scan(engine, music_dir)
    assert find(engine, **filters).total == expected


def test_missing_and_flag_names_are_all_filterable(engine, music_dir):
    scan(engine, music_dir)
    for name in MISSING:
        find(engine, missing=name)
    for name in FLAGS:
        find(engine, flag=name)


def test_sorting_puts_empty_values_last(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        up = find_tracks(session, TrackFilter(), sort="bpm").tracks
        down = find_tracks(session, TrackFilter(), sort="bpm", desc=True).tracks
    assert up[0].bpm == 126.0 and up[-1].bpm is None
    assert down[-1].bpm is None


def test_pagination(engine, music_dir, monkeypatch):
    monkeypatch.setattr("app.library.PER_PAGE", 4)
    scan(engine, music_dir)
    with Session(engine) as session:
        pages = [find_tracks(session, TrackFilter(), sort="path", page=p) for p in (1, 2, 3, 99)]
    assert [len(p.tracks) for p in pages[:3]] == [4, 4, 2]
    assert pages[0].pages == 3
    assert pages[3].page == 3  # out of range -> last page
    assert len({t.id for p in pages[:3] for t in p.tracks}) == 10


def test_chips_remove_one_filter_each():
    f = TrackFilter(q="x", key="8A", field="id3:TBPM", value="0")
    chips = dict(f.chips("musical"))
    assert "Key: Am" in chips
    assert "key=" not in chips["Key: Am"] and "q=x" in chips["Key: Am"]
    assert "field=" not in chips["Field: TBPM"] and "value=" not in chips["Field: TBPM"]


def test_artists_and_albums(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        artists = {a.name: a for a in list_artists(session)}
        albums = list_albums(session)
    assert (artists["Fixture Artist"].tracks, artists["Fixture Artist"].albums) == (7, 1)
    assert "Info Artist" in artists
    fixture = next(a for a in albums if a.album == "Fixture Album")
    assert (fixture.tracks, fixture.year, fixture.has_cover) == (7, 2021, True)
    assert "flac" in fixture.formats


def test_pages_render(client):
    client.post("/api/scan")
    scan_job.wait(timeout=30)

    page = client.get("/tracks").text
    assert "10 tracks" in page and ">BPM<" in page and ">Key<" in page

    filtered = client.get("/tracks", params={"missing": "BPM", "q": "tagged"}).text
    assert "Missing: BPM" in filtered and "Search: tagged" in filtered and "1 track" in filtered

    track_id = client.get("/api/tracks", params={"q": "tagged.mp3"}).json()["tracks"][0]["id"]
    page = client.get(f"/tracks/{track_id}").text
    assert "Silent Track" in page and "TBPM" in page and "Fixture Records" in page
    assert client.get("/tracks/999999").status_code == 404

    assert "Fixture Artist" in client.get("/artists").text
    assert "Fixture Album" in client.get("/albums", params={"artist": "Fixture Artist"}).text
    assert client.get("/api/albums").json()[0]["album"]

    dashboard = client.get("/stats").text
    assert 'href="/tracks?missing=' in dashboard and 'href="/tracks?format=' in dashboard


def test_cover_endpoint(client, music_dir):
    client.post("/api/scan")
    scan_job.wait(timeout=30)
    tracks = {t["path"]: t["id"] for t in client.get("/api/tracks").json()["tracks"]}

    embedded = client.get(f"/tracks/{tracks[f'{ALBUM}/tagged.opus']}/cover")
    assert embedded.status_code == 200 and embedded.headers["content-type"] == "image/png"
    assert client.get(f"/tracks/{tracks['Unsorted/untagged.mp3']}/cover").status_code == 404

    # A cover.jpg next to the file is used when nothing is embedded.
    (music_dir / "Unsorted" / "Cover.JPG").write_bytes(b"\xff\xd8 fake jpeg")
    sidecar = client.get(f"/tracks/{tracks['Unsorted/untagged.mp3']}/cover")
    assert sidecar.status_code == 200 and sidecar.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize(
    ("part", "whole", "digits", "expected"),
    [
        (1497, 1500, 0, 99),  # 99.8 %: three missing is not 100 %
        (1500, 1500, 0, 100),
        (1, 1500, 0, 1),  # 0.07 %: one is not 0 %
        (0, 1500, 0, 0),
        (1499, 1500, 1, 99.9),
        (1, 3000, 1, 0.1),
        (1, 2, 0, 50),
        (5, 0, 0, 0),
    ],
)
def test_percentages_never_round_to_100_or_0_while_not_exact(part, whole, digits, expected):
    from app.percent import percent

    assert percent(part, whole, digits) == expected
