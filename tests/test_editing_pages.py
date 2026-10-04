import re

from app.jobs import scan_job, write_job
from app.tags import read_file

ALBUM = "Fixture Artist/Fixture Album"
FORM = {"content-type": "application/x-www-form-urlencoded"}


def scanned(client):
    client.post("/api/scan")
    scan_job.wait(30)
    return {t["path"]: t["id"] for t in client.get("/api/tracks").json()["tracks"]}


def test_single_edit_review_apply_and_undo(client, music_dir):
    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.mp3"]

    form = client.get(f"/tracks/{track}/edit").text
    assert 'value="Silent Track"' in form and "pending changes" in form

    bad = client.post(f"/tracks/{track}/edit", content="title=X&bpm=fast", headers=FORM)
    assert bad.status_code == 422 and "BPM must be a number" in bad.text

    fields = {"title": "Edited", "artist": "Artist One; Artist Two", "album": "Fixture Album",
              "albumartist": "Fixture Artist", "track": "3/12", "disc": "1/2", "date": "2021-05-14",
              "genre": "Electronic", "bpm": "130", "key": "Am", "comment": "Whatsapp Unreleased",
              "label": "Fixture Records", "catalognumber": "FIX001"}  # fmt: skip
    body = "&".join(f"{k}={v.replace(' ', '+').replace(';', '%3B')}" for k, v in fields.items())
    saved = client.post(f"/tracks/{track}/edit", content=body, headers=FORM, follow_redirects=False)
    assert saved.status_code == 303 and saved.headers["location"] == "/changes?staged=2"

    review = client.get("/changes").text
    assert "Silent Track" in review and "Edited" in review and "130" in review
    assert ">Changes <span" in client.get("/").text  # menu badge
    assert read_file(music_dir / ALBUM / "tagged.mp3").title == "Silent Track"  # not written yet

    # First apply needs the backup confirmation.
    refused = client.post("/changes/apply", content="", headers=FORM, follow_redirects=False)
    assert refused.headers["location"] == "/changes?error=backup"
    client.post("/changes/apply", content="backup=on", headers=FORM)
    write_job.wait(30)
    assert read_file(music_dir / ALBUM / "tagged.mp3").title == "Edited"
    assert "No pending changes" in client.get("/changes").text
    assert client.get("/api/settings").json()["backup_confirmed"] is True

    history = client.get("/changes/history").text
    changeset = re.search(r'/changes/history/(\d+)"', history).group(1)
    assert "Title, BPM" in history
    assert "Edited" in client.get(f"/changes/history/{changeset}").text

    client.post(f"/changes/history/{changeset}/undo")
    write_job.wait(30)
    assert read_file(music_dir / ALBUM / "tagged.mp3").title == "Silent Track"
    assert "undone" in client.get("/changes/history").text


def test_batch_edit_only_changes_ticked_fields(client, music_dir):
    ids = scanned(client)
    picked = [ids[f"{ALBUM}/tagged.flac"], ids[f"{ALBUM}/tagged.m4a"]]
    page = client.get("/tracks/edit", params={"ids": picked}).text
    assert "Edit 2 tracks" in page and 'value="Fixture Records"' in page  # shared value shown

    nothing = client.post(
        "/tracks/edit", content=f"ids={picked[0]}&ids={picked[1]}&label=Z", headers=FORM
    )
    assert nothing.status_code == 422 and "Tick" in nothing.text

    body = f"ids={picked[0]}&ids={picked[1]}&change_label=on&label=Batch+Label&title=ignored"
    client.post("/tracks/edit", content=body, headers=FORM)
    pending = client.get("/api/changes").json()
    assert len(pending) == 2
    assert {c["field"] for p in pending for c in p["changes"]} == {"label"}


def test_edit_all_matching_tracks(client):
    scanned(client)
    page = client.get("/tracks/edit", params={"format": "flac", "all": "true"}).text
    assert "Edit 2 tracks" in page  # tagged.flac and discogs-ids.flac


def test_api_flow(client, music_dir):
    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.opus"]
    assert (
        client.post("/api/changes", json={"track_ids": [track], "values": {"bpm": "x"}}).status_code
        == 422
    )
    assert client.post(
        "/api/changes", json={"track_ids": [track], "values": {"bpm": "140"}}
    ).json() == {"pending": 1}
    assert client.post("/api/changes/apply").status_code == 202
    write_job.wait(30)
    assert client.get("/api/changes/job").json()["written"] == 1
    assert read_file(music_dir / ALBUM / "tagged.opus").bpm == 140.0
    changeset = client.get("/api/changesets").json()[0]["id"]
    assert client.post(f"/api/changesets/{changeset}/undo").status_code == 202
    write_job.wait(30)
    assert read_file(music_dir / ALBUM / "tagged.opus").bpm == 126.0


def test_track_list_has_selection_and_track_page_has_edit(client):
    ids = scanned(client)
    assert 'name="ids"' in client.get("/tracks").text
    assert "Edit tags" in client.get(f"/tracks/{ids[f'{ALBUM}/tagged.mp3']}").text
