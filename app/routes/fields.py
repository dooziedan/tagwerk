"""The Tag fields page: every tag field found in the library, and what Tagwerk does with it."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import preferences
from app.db import SessionDep
from app.fields import field_detail, field_overview
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
        {"d": detail, "systems": SYSTEMS, "prefs": preferences.load(session)},
    )
