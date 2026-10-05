"""The Tag fields page: every tag field found in the library, and what Tagwerk does with it."""

from dataclasses import asdict

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import changes, preferences
from app.db import SessionDep
from app.fields import field_detail, field_overview
from app.navigation import with_saved_note
from app.rawtags import SYSTEMS
from app.templating import templates

router = APIRouter()


@router.get("/api/fields", tags=["library"])
def fields_api(session: SessionDep) -> list[dict]:
    """Every tag field in the library with file counts, empty/zero counts and sample values."""
    return [asdict(f) for f in field_overview(session)]


@router.get("/api/fields/detail", tags=["library"])
def field_detail_api(system: str, name: str, session: SessionDep) -> dict:
    """All values of one tag field, plus example files."""
    detail = field_detail(session, system, name)
    if detail is None:
        raise HTTPException(404, "No file has this tag field")
    return asdict(detail)


@router.get("/fields", response_class=HTMLResponse, include_in_schema=False)
def fields_page(
    request: Request,
    session: SessionDep,
    q: str = "",
    system: str = "",
    show: str = "all",  # all, used, ignored
):
    fields = field_overview(session)
    traktor = next((f.files for f in fields if (f.system, f.name) == ("id3", "PRIV:TRAKTOR4")), 0)
    total = len(fields)
    used = sum(1 for f in fields if f.used_as)
    if q:
        fields = [f for f in fields if q.lower() in f.name.lower()]
    if system:
        fields = [f for f in fields if f.system == system]
    if show == "used":
        fields = [f for f in fields if f.used_as]
    elif show == "ignored":
        fields = [f for f in fields if not f.used_as]
    return templates.TemplateResponse(
        request,
        "fields.html",
        {
            "fields": fields,
            "traktor": traktor,  # files with Traktor's private data
            "total": total,
            "used": used,
            "q": q,
            "system": system,
            "show": show,
            "systems": SYSTEMS,
            "prefs": preferences.load(session),
        },
    )


@router.get("/fields/detail", response_class=HTMLResponse, include_in_schema=False)
def field_detail_page(request: Request, session: SessionDep, system: str, name: str):
    detail = field_detail(session, system, name)
    if detail is None:
        raise HTTPException(404, "No file has this tag field")
    return templates.TemplateResponse(
        request,
        "field_detail.html",
        {
            "d": detail,
            "systems": SYSTEMS,
            "prefs": preferences.load(session),
            "private_owner": name.removeprefix("PRIV:")
            if system == "id3" and name.startswith("PRIV:")
            else None,
            "private_about": PRIVATE_OWNERS,
        },
    )


# What some programs keep in private ID3 frames (PRIV:owner), for the field page.
PRIVATE_OWNERS = {
    "TRAKTOR4": "Traktor keeps its waveform, beat grid, cue points and its own copy of the "
    "track info here. Traktor also has them in its collection; without this data it analyses "
    "the file again.",
    "www.amazon.com": "Amazon's download data (an order or file ID).",
    "AverageLevel": "Windows Media Player's loudness value.",
    "PeakValue": "Windows Media Player's peak value.",
}


@router.post("/fields/private/remove", include_in_schema=False)
def remove_private(session: SessionDep, owner: str = Form()):
    """Pending changes that remove this program's private data from every file that has it."""
    count = changes.stage_private_removal(session, owner)
    return RedirectResponse(with_saved_note("/changes", count), status_code=303)
