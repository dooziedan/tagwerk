"""Preferences: mode (DJ / Collector), key notation, MusicBrainz visibility."""

from dataclasses import fields, replace
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import navidrome, preferences
from app.config import SettingsDep
from app.db import SessionDep
from app.genres import DEFAULT_MAP, GenreMap
from app.keys import NOTATIONS
from app.preferences import APPEARANCES, MODES, STYLES, Preferences, PreferencesDep
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
    saved: bool = False,
):
    return _settings_page(request, prefs, settings, session, saved=saved)


def _settings_page(request, prefs, settings, session, saved=False, errors=None, genre_text=None,
                   status_code=200):  # fmt: skip
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            **choices_context(session, prefs),
            "errors": errors or {},
            "genre_text": genre_text
            if genre_text is not None
            else (prefs.genre_map or DEFAULT_MAP),
            "genre_map_custom": bool(prefs.genre_map),
            "prefs": prefs,
            "modes": MODES,
            "notations": NOTATIONS,
            "styles": STYLES,
            "appearances": APPEARANCES,
            "saved": saved,
            "navidrome": {
                "configured": navidrome.configured(settings),
                "url": settings.navidrome_url,
                "user": settings.navidrome_user,
                "library": settings.navidrome_library,
                "last": navidrome.last,
            },
        },
        status_code=status_code,
    )


@router.post("/settings/choices/{section}", include_in_schema=False)
async def save_choices(request: Request, section: str, session: SessionDep, settings: SettingsDep):
    """Settings sections that match wizard steps: Import (folders + independence), Final."""
    form = await request.form()
    prefs, errors = preferences.load(session), {}
    for step in {"import": ["folders", "automation"], "final": ["final"]}.get(section, []):
        prefs, step_errors = apply_choices(prefs, step, form)
        errors.update(step_errors)
    if errors:
        return _settings_page(request, prefs, settings, session, errors=errors, status_code=422)
    preferences.save(session, prefs)
    return RedirectResponse(f"/settings?saved=true#{section}", status_code=303)


@router.post("/settings/genres", include_in_schema=False)
async def save_genre_map(request: Request, session: SessionDep, settings: SettingsDep):
    """The genre map as plain text; "reset" goes back to the built-in one."""
    form = await request.form()
    prefs = preferences.load(session)
    text = "" if form.get("reset") else str(form.get("genre_map", "")).replace("\r\n", "\n")
    bad = GenreMap.problems(text)
    if bad:
        lines = ", ".join(str(n) for n in bad)
        errors = {"genre_map": f"Line {lines}: use “Genre = variant, …” or “Genre > subgenre, …”."}
        return _settings_page(request, prefs, settings, session, errors=errors, genre_text=text,
                              status_code=422)  # fmt: skip
    if text.strip() == DEFAULT_MAP.strip():
        text = ""  # the built-in map: stored as empty, so it keeps up with updates
    preferences.save(session, replace(prefs, genre_map=text))
    return RedirectResponse("/settings?saved=true#genres", status_code=303)


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


@router.post("/settings", include_in_schema=False)
async def save_settings_form(request: Request, prefs: PreferencesDep, session: SessionDep):
    form = await _form(request)
    updated = replace(
        prefs,
        mode=form.get("mode", prefs.mode),
        key_notation=form.get("key_notation", prefs.key_notation),
        show_musicbrainz=form.get("show_musicbrainz") == "on",  # unchecked boxes aren't sent
        style=form.get("style", prefs.style),
        appearance=form.get("appearance", prefs.appearance),
    )
    preferences.save(session, updated)
    return RedirectResponse("/settings?saved=true", status_code=303)


@router.post("/settings/mode", include_in_schema=False)
async def switch_mode(request: Request, prefs: PreferencesDep, session: SessionDep):
    """The DJ / Collector switch in the menu. Returns to the page it was clicked on."""
    form = await _form(request)
    preferences.save(session, replace(prefs, mode=form.get("mode", prefs.mode)))
    back = request.headers.get("referer", "/")
    return RedirectResponse(back if back.startswith(str(request.base_url)) else "/", 303)


async def _form(request: Request) -> dict[str, str]:
    """Read a simple HTML form (one value per field) without extra dependencies."""
    body = (await request.body()).decode()
    return {key: values[0] for key, values in parse_qs(body).items()}
