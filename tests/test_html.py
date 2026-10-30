"""Pages must have balanced HTML: since pages are swapped in place (hx-boost), everything sits
in <div id="page">, and one stray closing tag would close it early and lose the rest of the
page on the next swap."""

import shutil
from html.parser import HTMLParser

import pytest
from sqlmodel import Session, select

from app.inbox import scan_inbox
from app.models import InboxTrack, Track
from app.scanner import ScanProgress, scan_library
from tests.conftest import FIXTURES

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
VOID |= {"track", "wbr", "path", "circle", "rect", "line", "polyline", "polygon", "use", "stop"}
OPTIONAL_END = {"p", "li", "tr", "td", "th", "option", "thead", "tbody", "tfoot", "dt", "dd"}


class TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.open: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.open and self.open[-1] != tag and self.open[-1] in OPTIONAL_END:
            self.open.pop()
        if self.open and self.open[-1] == tag:
            self.open.pop()
        else:
            where = self.open[-1] if self.open else "nothing"
            self.problems.append(f"line {self.getpos()[0]}: </{tag}> while <{where}> is open")


@pytest.fixture
def pages(client, engine, settings):
    scan_library(engine, settings.music_dir, ScanProgress())
    settings.import_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.flac", settings.import_dir / "a.flac")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        ids = [t.id for t in session.exec(select(Track)).all()][:2]
        inbox_id = session.exec(select(InboxTrack)).first().id
    one = ids[0]
    return [
        "/", "/tracks", f"/tracks/{one}", f"/tracks/{one}/edit",
        f"/tracks/edit?ids={ids[0]}&ids={ids[1]}", "/albums", "/artists", "/fields", "/final",
        "/inbox", f"/inbox/{inbox_id}", "/changes", "/changes/history", "/settings", "/duplicates",
    ]  # fmt: skip


def test_every_page_has_balanced_tags(client, pages):
    for url in pages:
        response = client.get(url)
        assert response.status_code == 200, url
        checker = TagChecker()
        checker.feed(response.text)
        assert checker.problems == [], url
        assert checker.open == [], url


def test_form_error_page_has_balanced_tags(client, pages, engine):
    with Session(engine) as session:
        ids = [t.id for t in session.exec(select(Track)).all()][:2]
    response = client.post("/tracks/edit", data={"ids": [str(i) for i in ids], "back": "/tracks"})
    assert response.status_code == 422
    checker = TagChecker()
    checker.feed(response.text)
    assert checker.problems == []


def test_the_phone_menu_has_every_page_of_the_sidebar(client, monkeypatch):
    """Narrow windows and phones only have the top bar's menu: it must reach every page the
    sidebar does (it used to be a separate list that missed Inbox, Changes and API)."""
    import re

    from app import templating

    for shown in (False, True):
        globals_ = templating.templates.env.globals
        monkeypatch.setitem(globals_, "releasomat_shown", lambda shown=shown: shown)
        html = client.get("/").text
        side = html.split('<aside class="side"', 1)[1].split("</aside>", 1)[0]
        menu = html.split('<details class="dropdown top-menu">', 1)[1].split("</details>", 1)[0]
        links = lambda part: re.findall(r'<a class="[^"]*" href="([^"]+)"', part)  # noqa: E731
        assert links(menu) == links(side)
        assert {"/inbox", "/changes", "/docs", "/settings"} <= set(links(menu))
        assert ("/releasomat" in links(menu)) is shown
        groups = re.findall(r'<li class="menu-group">(\w+)</li>', menu)
        assert groups == ["Library", "Work", "Tools", "System"]
