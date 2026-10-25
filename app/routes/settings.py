"""The Settings page and the preferences API.

Sections: General (key notation, effects, time zone), Import, Genre map, BPM ranges, Final
tracks, Online lookups, Notifications, Navidrome, and Releasomat (only when it is set up, ADR
0044). Each section is its own form; after saving, the page comes back with ``?saved=<section>``
and scrolls to it.
"""

from dataclasses import fields, replace
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import analysis, area, genres, identify, navidrome, notifications, preferences, tempo
from app.config import Settings, SettingsDep
from app.db import SessionDep, get_engine
from app.forms import read_form
from app.genres import DEFAULT_MAP, GenreMap
from app.jobs import run_now, scan_job
from app.keys import NOTATIONS
from app.navigation import back_url
from app.preferences import EFFECTS, Preferences, PreferencesDep
from app.routes.setup import apply_choices, choices_context
from app.templating import templates

router = APIRouter()


@router.get("/api/settings", tags=["settings"])
def get_settings(prefs: PreferencesDep) -> Preferences:
    return prefs


@router.put("/api/settings", tags=["settings"])
def put_settings(update: dict, session: SessionDep) -> Preferences:
    """Change the preferences that are sent; all others stay as they are.

    Unknown names are ignored; invalid values fall back to their defaults.
    """
    known = {f.name for f in fields(Preferences)}
    current = preferences.load(session)
    return preferences.save(
        session, replace(current, **{k: v for k, v in update.items() if k in known})
    )


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(
    request: Request,
    prefs: PreferencesDep,
    settings: SettingsDep,
    session: SessionDep,
    saved: str = "",
):
    return _settings_page(request, prefs, settings, session, saved=saved)


def _settings_page(request, prefs, settings, session, saved="", errors=None, genre_text=None,
                   bpm_rows=None, status_code=200):  # fmt: skip
    genre_text = genre_text if genre_text is not None else (prefs.genre_map or DEFAULT_MAP)
    genre_map = genres.of(prefs)
    if bpm_rows is None:
        bpm_rows = [
            {"genre": name, "low": _number(low), "high": _number(high)}
            for name, (low, high) in sorted(
                tempo.ranges_of(prefs.bpm_ranges).items(), key=lambda r: (r[1], r[0].lower())
            )
        ]
    for row in bpm_rows:  # subgenres share their main genre's range
        row["subgenres"] = genre_map.subgenres(row["genre"]) if row["genre"] else []
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            **choices_context(session, prefs),
            "errors": errors or {},
            "genre_text": genre_text,
            "genre_rules": GenreMap.rule_count(genre_text),
            "genre_map_custom": bool(prefs.genre_map),
            "bpm_rows": bpm_rows,
            "bpm_custom": prefs.bpm_ranges is not None,
            "bpm_limits": tempo.RANGE_LIMITS,
            "prefs": prefs,
            "notations": NOTATIONS,
            "effects": EFFECTS,
            "time_zones": preferences.time_zones(),
            "container_zone": preferences.container_zone(),
            "saved": saved,
            "online": [
                {
                    "name": cls.name,
                    "label": cls.label,
                    "on": cls.name in prefs.online_sources,
                    "ready": cls(settings).configured(),
                    "needs": cls.needs,
                }
                for cls in identify.SOURCES
            ],
            "topics": _topics(settings, prefs),
            "navidrome": {
                "configured": navidrome.configured(settings),
                "url": settings.navidrome_url,
                "user": settings.navidrome_user,
                "library": settings.navidrome_library,
                "last": navidrome.last,
            },
            "releasomat": area.overview(session, settings, prefs),
        },
        status_code=status_code,
    )


def _topics(settings: Settings, prefs: Preferences) -> dict:
    """The notification switches shown: Releasomat's only when Releasomat is set up."""
    shown = dict(notifications.TOPICS)
    if not area.configured(settings, prefs):
        shown.pop("releasomat")
    return shown


@router.post("/settings/choices/{section}", include_in_schema=False)
async def save_choices(request: Request, section: str, session: SessionDep, settings: SettingsDep):
    """Settings sections that match wizard steps: Import (folders + independence), Final."""
    form = await read_form(request)
    prefs, errors = preferences.load(session), {}
    for step in {"import": ["folders", "automation"], "final": ["final"]}.get(section, []):
        prefs, step_errors = apply_choices(prefs, step, form)
        errors.update(step_errors)
    if errors:
        return _settings_page(request, prefs, settings, session, errors=errors, status_code=422)
    preferences.save(session, prefs)
    return RedirectResponse(f"/settings?saved={section}", status_code=303)


@router.post("/settings/genres", include_in_schema=False)
async def save_genre_map(request: Request, session: SessionDep, settings: SettingsDep):
    """The genre map as plain text; "reset" goes back to the built-in one."""
    form = await read_form(request)
    prefs = preferences.load(session)
    text = "" if form.get("reset") else str(form.get("genre_map", "")).replace("\r\n", "\n")
    bad = GenreMap.problems(text)
    if bad:
        lines = ", ".join(str(n) for n in bad)
        rules = "“Genre = variant, …”, “Genre > subgenre, …” or “Genre: 160-185 BPM”"
        errors = {"genre_map": f"Line {lines}: use {rules}."}
        return _settings_page(request, prefs, settings, session, errors=errors, genre_text=text,
                              status_code=422)  # fmt: skip
    if text.strip() == DEFAULT_MAP.strip():
        text = ""  # the built-in map: stored as empty, so it keeps up with updates
    preferences.save(session, replace(prefs, genre_map=text))
    return RedirectResponse("/settings?saved=genres", status_code=303)


@router.post("/settings/bpm", include_in_schema=False)
async def save_bpm_ranges(request: Request, session: SessionDep, settings: SettingsDep):
    """BPM ranges, one row per genre (genre_0, low_0, high_0, …) plus an empty row to add one.
    "remove" leaves a row out, a row without a genre is left out too; "reset" goes back to the
    built-in ranges. Afterwards the library's BPM decisions are worked out again."""
    form = await read_form(request)
    prefs = preferences.load(session)
    rows, removed = [], str(form.get("remove", ""))
    keys = sorted({k.split("_", 1)[1] for k in form if k.startswith("genre_")},
                  key=lambda k: (k == "new", int(k) if k.isdigit() else 0))  # fmt: skip
    for key in keys:
        row = {f: str(form.get(f"{f}_{key}", "")).strip() for f in ("genre", "low", "high")}
        if key != removed and any(row.values()):
            rows.append(row)
    if form.get("reset"):
        ranges = None
    else:
        ranges, problem = _read_ranges(rows)
        if problem:
            return _settings_page(request, prefs, settings, session, errors={"bpm": problem},
                                  bpm_rows=rows, status_code=422)  # fmt: skip
    preferences.save(session, replace(prefs, bpm_ranges=ranges))
    # BPM decisions follow the ranges right away; while a job runs, after it (jobs.py)
    run_now(lambda: analysis.refresh_all(get_engine(settings.database_url)))
    return RedirectResponse("/settings?saved=bpm", status_code=303)


def _read_ranges(rows: list[dict]) -> tuple[dict, str | None]:
    """The form's rows as BPM ranges, or what's wrong with them (one message)."""
    low_limit, high_limit = tempo.RANGE_LIMITS
    ranges, seen = {}, {}
    for row in rows:
        name = row["genre"]
        if not name:
            return {}, f"Give the range {row['low']}-{row['high']} BPM a genre."
        try:
            low, high = sorted((float(row["low"].replace(",", ".")),
                                float(row["high"].replace(",", "."))))  # fmt: skip
        except ValueError:
            return {}, f"{name}: enter the lowest and the highest BPM, like 160 and 185."
        if low < low_limit or high > high_limit:
            return {}, f"{name}: BPM ranges go from {low_limit} to {high_limit}."
        if name.lower() in seen:
            return {}, f"{name} is listed twice: keep one row for it."
        seen[name.lower()] = name
        ranges[name] = [low, high]
    return ranges, None


def _number(value: float) -> str:
    """160.0 -> "160", 87.5 -> "87.5" for the form."""
    return f"{value:g}"


@router.post("/settings/online", include_in_schema=False)
async def save_online(request: Request, session: SessionDep):
    """Which online sources to ask about inbox tracks."""
    form = await read_form(request)
    names = {cls.name for cls in identify.SOURCES}
    chosen = [str(n) for n in form.getlist("online_sources") if n in names]
    preferences.save(session, replace(preferences.load(session), online_sources=chosen))
    return RedirectResponse("/settings?saved=online", status_code=303)


@router.post("/settings/notifications", include_in_schema=False)
async def save_notifications(request: Request, session: SessionDep, settings: SettingsDep):
    """Which topics may write notifications: a switched-off topic writes nothing. A topic that
    isn't shown (Releasomat, not set up) keeps its switch."""
    form = await read_form(request)
    prefs = preferences.load(session)
    shown = _topics(settings, prefs)
    chosen = {
        name: name in form.getlist("topics") if name in shown else prefs.notifications[name]
        for name in notifications.TOPICS
    }
    preferences.save(session, replace(prefs, notifications=chosen))
    return RedirectResponse("/settings?saved=notifications", status_code=303)


@router.post("/hints/{key}", include_in_schema=False)
def hide_hint(request: Request, key: str, session: SessionDep):
    """ "Don't show again" under a message (macros.html → hint). The API way is PUT
    /api/settings with ``hidden_hints``."""
    prefs = preferences.load(session)
    if key in preferences.HINTS and key not in prefs.hidden_hints:
        preferences.save(session, replace(prefs, hidden_hints=[*prefs.hidden_hints, key]))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")  # htmx puts nothing in the message's place
    back = back_url(request, request.headers.get("referer"), fallback="/")
    return RedirectResponse(back, status_code=303)


@router.post("/settings/setup-again", include_in_schema=False)
def setup_again(session: SessionDep):
    preferences.save(session, replace(preferences.load(session), setup_done=False))
    return RedirectResponse("/setup", status_code=303)


@router.post("/settings/navidrome/{action}", include_in_schema=False)
def navidrome_action(action: str, settings: SettingsDep):
    """Settings buttons: test the connection, or rescan now."""
    if action == "rescan":
        navidrome.start_scan(settings)
    else:
        navidrome.ping(settings)
    return RedirectResponse("/settings#navidrome", status_code=303)


@router.post("/api/navidrome/rescan", tags=["settings"])
def navidrome_rescan_api(settings: SettingsDep) -> dict:
    """Ask Navidrome to rescan the library now (needs NAVIDROME_URL, _USER, _PASSWORD)."""
    result = navidrome.start_scan(settings)
    return {"ok": result.ok, "message": result.message}


class AreaChoice(BaseModel):
    folder: str  # the folder RELEASOMAT_FOLDER names, as GET /api/releasomat/area shows it


@router.get("/api/releasomat/area", tags=["settings"])
def releasomat_area_api(session: SessionDep, settings: SettingsDep, prefs: PreferencesDep):
    """The Releasomat folder (ADR 0044): the one ``RELEASOMAT_FOLDER`` names, its check, the one
    kept out of the library, and what keeping it out would take out of Tagwerk's lists."""
    return area.overview(session, settings, prefs)


@router.post("/api/releasomat/area", tags=["settings"])
def keep_out_api(choice: AreaChoice, session: SessionDep, settings: SettingsDep) -> dict:
    """Keep the Releasomat folder out of the library (the owner's one confirming click). The
    files stay untouched; a scan starts to take its tracks out of Tagwerk's lists."""
    try:
        folder = area.keep_out(session, settings, choice.folder)
    except area.FolderProblem as exc:
        raise HTTPException(409, str(exc)) from None
    return {"kept_out": folder, "scan_started": scan_job.start(settings)}


@router.delete("/api/releasomat/area", tags=["settings"])
def treat_as_library_api(session: SessionDep, settings: SettingsDep) -> dict:
    """Treat the Releasomat folder as library again: a scan starts to read its files in."""
    area.treat_as_library(session)
    return {"kept_out": None, "scan_started": scan_job.start(settings)}


@router.post("/settings/releasomat/{action}", include_in_schema=False)
async def releasomat_action(
    request: Request, action: str, session: SessionDep, settings: SettingsDep
):
    """Settings → Releasomat: keep the folder out (``keep-out``), or treat it as library
    again (``library``). Both start a scan, so the lists change right away."""
    if action == "keep-out":
        form = await read_form(request)
        try:
            area.keep_out(session, settings, str(form.get("folder", "")))
        except area.FolderProblem as exc:
            prefs = preferences.load(session)
            return _settings_page(
                request, prefs, settings, session, errors={"releasomat": str(exc)},
                status_code=422,
            )  # fmt: skip
        saved = "releasomat-out"
    else:
        area.treat_as_library(session)
        saved = "releasomat-library"
    if not scan_job.start(settings):
        saved += "-later"  # a job is running: the next scan does it
    return RedirectResponse(f"/settings?saved={saved}#releasomat", status_code=303)


@router.post("/settings", include_in_schema=False)
async def save_settings_form(request: Request, prefs: PreferencesDep, session: SessionDep):
    form = await _form(request)
    updated = replace(
        prefs,
        key_notation=form.get("key_notation", prefs.key_notation),
        effects=form.get("effects", prefs.effects),
        time_zone=form.get("time_zone", ""),
    )
    preferences.save(session, updated)
    return RedirectResponse("/settings?saved=general", status_code=303)


async def _form(request: Request) -> dict[str, str]:
    """Read a simple HTML form (one value per field) without extra dependencies."""
    body = (await request.body()).decode()
    return {key: values[0] for key, values in parse_qs(body).items()}
