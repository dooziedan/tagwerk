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
    assert 'value="Silent Track"' in form and "Nothing is written yet" in form

    bad = client.post(f"/tracks/{track}/edit", content="title=X&bpm=fast", headers=FORM)
    assert bad.status_code == 422 and "BPM must be a number" in bad.text

    fields = {"title": "Edited", "artist": "Artist One; Artist Two", "album": "Fixture Album",
              "albumartist": "Fixture Artist", "track": "3/12", "disc": "1/2", "date": "2021-05-14",
              "genre": "Electronic", "bpm": "130", "key": "Am", "comment": "Whatsapp Unreleased",
              "label": "Fixture Records", "catalognumber": "FIX001"}  # fmt: skip
    body = "&".join(f"{k}={v.replace(' ', '+').replace(';', '%3B')}" for k, v in fields.items())
    saved = client.post(f"/tracks/{track}/edit", content=body, headers=FORM, follow_redirects=False)
    assert saved.status_code == 303 and saved.headers["location"] == "/tracks?saved=2"
    assert "Saved 2 pending changes" in client.get(saved.headers["location"]).text

    review = client.get("/changes").text
    assert "Silent Track" in review and "Edited" in review and "130" in review
    assert 'Changes</span><span class="count-badge"' in client.get("/").text  # menu badge
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


def test_cover_upload_review_apply_and_undo(client, music_dir):
    from app.covers import find_cover
    from tests.test_writer import PNG

    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.flac"]
    path = music_dir / ALBUM / "tagged.flac"
    old_cover = find_cover(path)

    bad = client.post(
        f"/tracks/{track}/edit",
        data={"cover_action": "replace"},
        files={"cover_file": ("c.gif", b"GIF89a", "image/gif")},
    )
    assert bad.status_code == 422 and "Only JPEG and PNG" in bad.text

    response = client.post(
        f"/tracks/{track}/edit",
        data={"cover_action": "replace"},
        files={"cover_file": ("cover.png", PNG, "image/png")},
    )
    assert response.status_code == 200 and "Cover art" in response.text
    review = client.get("/changes").text
    image_url = re.search(r'src="(/images/[0-9a-f]{64})"', review).group(1)
    assert client.get(image_url).headers["content-type"] == "image/png"
    assert find_cover(path) == old_cover  # not written before apply

    client.post("/changes/apply", data={"backup": "on"})
    write_job.wait(30)
    assert find_cover(path) == (PNG, "image/png")

    changeset = client.get("/api/changesets").json()[0]["id"]
    client.post(f"/changes/history/{changeset}/undo")
    write_job.wait(30)
    assert find_cover(path) == old_cover


def test_remove_cover_from_several_tracks(client, music_dir):
    ids = scanned(client)
    picked = [ids[f"{ALBUM}/tagged.mp3"], ids[f"{ALBUM}/tagged.m4a"]]
    form = client.get("/tracks/edit", params={"ids": picked}).text
    assert "2 of 2 have cover art" in form
    client.post("/tracks/edit", data={"ids": picked, "cover_action": "remove"})
    client.post("/changes/apply", data={"backup": "on"})
    write_job.wait(30)
    for name in ("tagged.mp3", "tagged.m4a"):
        assert not read_file(music_dir / ALBUM / name).has_cover


def test_saving_returns_to_the_page_the_user_came_from(client):
    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.flac"]
    came_from = "/tracks?genre=Electronic&sort=bpm"
    form = client.get(
        f"/tracks/edit?ids={track}", headers={"referer": f"http://testserver{came_from}"}
    )
    assert f'name="back" value="{came_from}' in form.text.replace("&amp;", "&")
    saved = client.post(
        "/tracks/edit",
        data={"ids": [track], "change_label": "on", "label": "Back Label", "back": came_from},
        follow_redirects=False,
    )
    assert saved.headers["location"] == came_from + "&saved=1"


def test_back_url_never_leaves_the_app(client):
    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.flac"]
    for evil in ("https://evil.example/x", "//evil.example/x", "javascript:alert(1)"):
        saved = client.post(
            f"/tracks/{track}/edit", data={"label": "Safe", "back": evil}, follow_redirects=False
        )
        assert saved.headers["location"].startswith("/tracks?saved=")


def test_page_titles_are_plain_text(client):
    """A <script> inside <title> is shown as text and never runs (v0.6.1 bug in the track list)."""
    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.flac"]
    pages = ["/", "/tracks", "/albums", "/artists", "/fields", "/changes", "/changes/history",
             "/settings", "/inbox", f"/tracks/{track}", f"/tracks/{track}/edit"]  # fmt: skip
    for page in pages:
        title = re.search(r"<title>(.*?)</title>", client.get(page).text, re.S).group(1)
        assert "<" not in title, page


def test_back_leads_to_where_the_track_was_opened(client):
    ids = scanned(client)
    track = ids[f"{ALBUM}/tagged.flac"]
    origin = "/tracks?genre=Electronic"
    page = client.get(f"/tracks/{track}", headers={"referer": f"http://testserver{origin}"})
    html = page.text.replace("&amp;", "&")
    assert f'<a href="{origin}">← Back</a>' in html
    edit_link = re.search(r'href="(/tracks/\d+/edit\?back=[^"]+)"', html).group(1)
    form = client.get(edit_link).text.replace("&amp;", "&")
    assert f'name="back" value="{origin}"' in form
    # "← Back" on the edit form returns to the track page, which still knows its origin.
    cancel = re.search(r'<a href="([^"]+)">← Back</a>', form).group(1)
    assert cancel.startswith(f"/tracks/{track}?back=")
    assert f'<a href="{origin}">← Back</a>' in client.get(cancel).text.replace("&amp;", "&")
    # After saving: back to the list the track was opened from.
    saved = client.post(
        f"/tracks/{track}/edit", data={"label": "X", "back": origin}, follow_redirects=False
    )
    assert re.fullmatch(re.escape(origin) + r"&saved=\d+", saved.headers["location"])


def test_only_ticked_changes_are_applied_or_discarded(client, music_dir):
    ids = scanned(client)
    mp3, flac = ids[f"{ALBUM}/tagged.mp3"], ids[f"{ALBUM}/tagged.flac"]
    client.post("/api/changes", json={"track_ids": [mp3, flac], "values": {"comment": "Ticked"}})
    client.post("/api/changes", json={"track_ids": [mp3], "values": {"label": "Kept"}})
    pending = {
        (p["path"].rsplit("/", 1)[-1], c["field"]): c["id"]
        for p in client.get("/api/changes").json()
        for c in p["changes"]
    }
    page = client.get("/changes").text
    assert page.count('name="change"') == 3 and "Apply 3 changes to 2 files" in page

    # Nothing ticked: nothing happens.
    form = {"backup": "on", "ticked": "1"}
    none = client.post("/changes/apply", data=form, follow_redirects=False)
    assert none.headers["location"] == "/changes?error=none"

    ticked = [pending["tagged.mp3", "comment"], pending["tagged.flac", "comment"]]
    client.post("/changes/apply", data={"backup": "on", "ticked": "1", "change": ticked})
    write_job.wait(30)
    assert read_file(music_dir / ALBUM / "tagged.mp3").comment == "Ticked"
    assert read_file(music_dir / ALBUM / "tagged.mp3").label != "Kept"  # unticked: not written
    assert [c["field"] for p in client.get("/api/changes").json() for c in p["changes"]] == [
        "label"
    ]

    # Discard only the ticked ones too.
    client.post("/api/changes", json={"track_ids": [flac], "values": {"label": "Other"}})
    flac_label = next(
        c["id"]
        for p in client.get("/api/changes").json()
        for c in p["changes"]
        if p["path"].endswith(".flac")
    )
    client.post("/changes/discard", data={"ticked": "1", "change": [flac_label]})
    left = [(p["path"].rsplit("/", 1)[-1], c["field"]) for p in client.get("/api/changes").json()
            for c in p["changes"]]  # fmt: skip
    assert left == [("tagged.mp3", "label")]


def test_the_api_applies_chosen_changes(client, music_dir):
    ids = scanned(client)
    mp3 = ids[f"{ALBUM}/tagged.mp3"]
    client.post("/api/changes", json={"track_ids": [mp3], "values": {"comment": "A", "label": "B"}})
    changes = client.get("/api/changes").json()[0]["changes"]
    comment = next(c["id"] for c in changes if c["field"] == "comment")
    assert client.post("/api/changes/apply", json={"change_ids": [comment]}).status_code == 202
    write_job.wait(30)
    info = read_file(music_dir / ALBUM / "tagged.mp3")
    assert info.comment == "A" and info.label != "B"
    assert client.post("/api/changes/apply").status_code == 202  # no body: all the rest
    write_job.wait(30)
    assert read_file(music_dir / ALBUM / "tagged.mp3").label == "B"
