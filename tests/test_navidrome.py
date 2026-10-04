import hashlib
import io
import json
import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest

from app import navidrome
from app.config import Settings


class FakeNavidrome:
    """Answers like Navidrome's Subsonic API; remembers what was asked."""

    def __init__(self, status="ok", error=None):
        self.status, self.error, self.calls = status, error, []

    def __call__(self, url, timeout):
        self.calls.append(url)
        body = {"subsonic-response": {"status": self.status, "version": "1.16.1"}}
        if self.error:
            body["subsonic-response"]["error"] = self.error
        return io.BytesIO(json.dumps(body).encode())


@pytest.fixture
def nd_settings(tmp_path):
    return Settings(
        music_dir=tmp_path,
        config_dir=tmp_path,
        navidrome_url="http://192.168.1.10:4533/",
        navidrome_user="admin",
        navidrome_password="secret",
    )


def test_start_scan_sends_a_salted_token_not_the_password(nd_settings, monkeypatch):
    fake = FakeNavidrome()
    monkeypatch.setattr(navidrome.urllib.request, "urlopen", fake)
    result = navidrome.start_scan(nd_settings)
    assert result.ok and navidrome.last is result
    url = urlsplit(fake.calls[0])
    assert url.path == "/rest/startScan"
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert "secret" not in fake.calls[0]
    assert query["t"] == hashlib.md5(("secret" + query["s"]).encode()).hexdigest()
    assert (query["u"], query["c"], query["f"]) == ("admin", "tagwerk", "json")


@pytest.mark.parametrize(
    ("error", "expected"),
    [({"code": 40, "message": "Wrong username or password"}, "user name or password"),
     ({"code": 50, "message": "not authorized"}, "admin rights")],
)  # fmt: skip
def test_login_problems_are_explained(nd_settings, monkeypatch, error, expected):
    monkeypatch.setattr(navidrome.urllib.request, "urlopen", FakeNavidrome("failed", error))
    result = navidrome.ping(nd_settings)
    assert not result.ok and expected in result.message


def test_unreachable_navidrome(nd_settings, monkeypatch):
    def refuse(url, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(navidrome.urllib.request, "urlopen", refuse)
    result = navidrome.ping(nd_settings)
    assert not result.ok and "not localhost" in result.message


def test_nothing_happens_without_configuration(tmp_path, monkeypatch):
    fake = FakeNavidrome()
    monkeypatch.setattr(navidrome.urllib.request, "urlopen", fake)
    navidrome.rescan_after_write(Settings(music_dir=tmp_path, config_dir=tmp_path), 5)
    assert fake.calls == []


def test_rescan_after_apply(client, settings, music_dir, monkeypatch):
    from app.jobs import scan_job, write_job

    fake = FakeNavidrome()
    monkeypatch.setattr(navidrome.urllib.request, "urlopen", fake)
    monkeypatch.setattr(settings, "navidrome_url", "http://nas:4533")
    monkeypatch.setattr(settings, "navidrome_user", "admin")
    monkeypatch.setattr(settings, "navidrome_password", "secret")

    client.post("/api/scan")
    scan_job.wait(30)
    track = client.get("/api/tracks").json()["tracks"][0]["id"]
    client.post("/api/changes", json={"track_ids": [track], "values": {"label": "New Label"}})
    client.post("/api/changes/apply")
    write_job.wait(30)
    assert len(fake.calls) == 1 and "/rest/startScan" in fake.calls[0]
    assert "Navidrome is rescanning" in client.get("/settings").text


def test_settings_page_explains_the_setup(client):
    page = client.get("/settings").text
    assert "Navidrome URL" in page and "admin rights" in page
