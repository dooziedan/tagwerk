"""The Releasomat client (app/releasomat.py) and the connection in Settings (ADR 0044, step 2).
Answers come from tests/fixtures/online/releasomat_*.json, saved from a real Releasomat."""

import logging
import shutil
import urllib.error

import pytest
from sqlmodel import Session

from app import area, releasomat
from app.config import Settings, get_settings
from app.sources.base import USER_AGENT
from tests.conftest import FIXTURES
from tests.fake_releasomat import KEY, URL, FakeReleasomat, saved


@pytest.fixture
def rm_settings(tmp_path):
    return Settings(music_dir=tmp_path, config_dir=tmp_path, releasomat_url=URL + "/",
                    releasomat_api_key=KEY)  # fmt: skip


@pytest.fixture
def fake(monkeypatch):
    fake = FakeReleasomat()
    monkeypatch.setattr(releasomat.urllib.request, "urlopen", fake)
    return fake


def test_info_and_files(rm_settings, fake):
    about = releasomat.info(rm_settings)
    assert (about.integration_api, about.folder) == (1, "Releasomat")
    folder, found = releasomat.files(rm_settings)
    assert folder == "Releasomat" and len(found) == 5
    glue = found[0]
    assert (glue.id, glue.path, glue.format) == (1, "Bicep/Bicep - Glue.aiff", "aiff")
    assert glue.wanted["bpm"] == 129.0 and glue.wanted["key"] == "C Minor"
    assert [p.name for p in glue.playlists] == ["Beatport Top 100", "Weekly Exploration"]
    assert glue.playlists[0].url.endswith("/playlists/2")


def test_the_key_goes_only_into_the_header(rm_settings, fake, caplog):
    caplog.set_level(logging.DEBUG)
    releasomat.info(rm_settings)
    request = fake.requests[0]
    assert request.full_url == f"{URL}/api/integration/info"  # no key, no double slash
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert request.get_header("User-agent") == USER_AGENT
    assert KEY not in caplog.text and "Releasomat GET info: 200" in caplog.text


def test_a_post_sends_paths_and_sizes_and_reads_each_answer(rm_settings, fake):
    fake.answers["adopt"] = saved("adopt")
    answers = releasomat.adopt(rm_settings, [
        {"path": "Netsky/Netsky - Rio.aiff", "size": 9576, "id": 4, "extra": "not sent"},
        {"path": "Bicep/Bicep - Glue.aiff", "size": 1},
        {"path": "Nobody/Nothing.mp3", "size": 5, "id": None},
    ])  # fmt: skip
    assert fake.sent("adopt") == [{"files": [
        {"path": "Netsky/Netsky - Rio.aiff", "size": 9576, "id": 4},
        {"path": "Bicep/Bicep - Glue.aiff", "size": 1},
        {"path": "Nobody/Nothing.mp3", "size": 5},
    ]}]  # fmt: skip
    assert [a.ok for a in answers] == [True, False, False]
    assert answers[0].status == "adopted" and answers[0].id == 4
    assert "another size" in answers[1].reason
    assert "doesn't know a file" in answers[2].reason


def test_returned_sends_why(rm_settings, fake):
    fake.answers["returned"] = saved("returned")
    [answer] = releasomat.returned(rm_settings, [{"path": "Netsky/Netsky - Rio.aiff", "id": 4}],
                                   "move_failed")  # fmt: skip
    assert answer.ok and answer.status == "done"
    assert fake.sent("returned")[0]["why"] == "move_failed"


def test_refused_deletes_say_why(rm_settings, fake):
    fake.answers["delete"] = saved("delete_refused")
    answers = releasomat.delete(rm_settings, [{"path": "a"}, {"path": "b", "size": 3}])
    assert [a.ok for a in answers] == [False, False]
    assert "Send the file's size" in answers[0].reason


@pytest.mark.parametrize(
    "answer, code, words",
    [
        (401, "wrong_key", "rejected the key"),
        (403, "integration_off", "integration for Tagwerk is off"),
        (404, "too_old", "update Releasomat"),
        (500, "error", "Releasomat answered: error 500"),
        (urllib.error.URLError("Connection refused"), "unreachable", "not localhost"),
        (TimeoutError("timed out"), "unreachable", "didn't answer"),
        ({"integration_api": 2, "folder": "x"}, "too_new", "update Tagwerk"),
        ({"hello": "world"}, "bad_answer", "doesn't answer like Releasomat"),
    ],
)
def test_failures_are_explained(rm_settings, fake, answer, code, words):
    fake.answers["info"] = answer
    with pytest.raises(releasomat.ReleasomatError) as error:
        releasomat.info(rm_settings)
    assert error.value.code == code and words in error.value.message
    assert KEY not in error.value.message


def test_an_unknown_call_on_a_new_releasomat_isnt_too_old(rm_settings, fake):
    fake.answers["info"] = urllib.error.HTTPError(  # the integration's own 404 shape
        "x",
        404,
        "x",
        {},
        __import__("io").BytesIO((FIXTURES / "online" / "releasomat_not_found.json").read_bytes()),
    )
    with pytest.raises(releasomat.ReleasomatError) as error:
        releasomat.info(rm_settings)
    assert error.value.code == "error" and "Not Found" in error.value.message


def test_a_post_with_a_missing_answer_is_a_bad_answer(rm_settings, fake):
    fake.answers["discarded"] = {"integration_api": 1, "files": []}
    with pytest.raises(releasomat.ReleasomatError, match="doesn't answer like"):
        releasomat.discarded(rm_settings, [{"path": "a", "size": 1}])


def test_nothing_is_asked_without_address_and_key(tmp_path, fake):
    settings = Settings(music_dir=tmp_path, config_dir=tmp_path, releasomat_url=URL)
    assert not releasomat.configured(settings)
    with pytest.raises(releasomat.ReleasomatError) as error:
        releasomat.info(settings)
    assert error.value.code == "not_set_up" and fake.requests == []


# --- The connection in Settings ---------------------------------------------------------------


@pytest.fixture
def connected(monkeypatch, fake, music_dir):
    """RELEASOMAT_URL and _API_KEY set; the five saved files in /music/Releasomat."""
    for item in saved("files")["files"]:
        target = music_dir / "Releasomat" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * item["size"])
    monkeypatch.setenv("RELEASOMAT_URL", URL)
    monkeypatch.setenv("RELEASOMAT_API_KEY", KEY)
    get_settings.cache_clear()
    releasomat.last = None
    yield fake
    releasomat.last = None


def test_test_connection_finds_the_files_and_remembers_the_folder(client, engine, connected):
    page = client.get("/settings").text
    assert 'id="releasomat"' in page and "Test connection" in page
    assert "Keep this folder out" not in page  # the folder isn't known yet
    assert client.post("/api/releasomat/test").json() == {
        "ok": True,
        "message": "Connected to Releasomat 0.0.1. It saves into “Releasomat”. "
        f"5 of 5 Releasomat files found in {get_settings().music_dir.as_posix()}/Releasomat.",
    }
    with Session(engine) as session:
        assert area.reported(session) == "Releasomat"
    connected.answers["info"] = 503  # Releasomat down: the folder is still known
    page = client.get("/settings").text
    assert "as Releasomat reports it" in page and "Keep this folder out of the library" in page
    assert KEY not in page


def test_files_missing_from_the_folder_are_reported(client, connected, music_dir):
    shutil.rmtree(music_dir / "Releasomat")
    (music_dir / "Releasomat").mkdir()
    result = client.post("/api/releasomat/test").json()
    assert not result["ok"] and "None of its 5 Releasomat files" in result["message"]


def test_a_failed_test_is_shown(client, connected):
    connected.answers["info"] = 401
    client.post("/settings/releasomat/test")
    page = client.get("/settings").text
    assert "Releasomat rejected the key" in page


def test_the_api_key_alone_shows_nothing(client, monkeypatch):
    monkeypatch.setenv("RELEASOMAT_API_KEY", KEY)
    get_settings.cache_clear()
    assert "Releasomat" not in client.get("/settings").text


def test_releasomat_folder_wins_over_the_reported_one(client, engine, connected, music_dir,
                                                       monkeypatch):  # fmt: skip
    shutil.copytree(music_dir / "Releasomat", music_dir / "Downloads")
    monkeypatch.setenv("RELEASOMAT_FOLDER", "Downloads")
    get_settings.cache_clear()
    result = client.post("/api/releasomat/test").json()
    assert result["ok"] and "/Downloads." in result["message"]
    with Session(engine) as session:
        assert area.proposed(get_settings(), session) == "Downloads"
