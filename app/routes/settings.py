"""Preferences: mode (DJ / Collector), key notation, MusicBrainz visibility."""

from dataclasses import replace
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import navidrome, preferences
from app.config import SettingsDep
from app.db import SessionDep
from app.keys import NOTATIONS
from app.preferences import APPEARANCES, MODES, STYLES, Preferences, PreferencesDep
from app.templating import templates

router = APIRouter()


@router.get("/api/settings", tags=["settings"])
def get_settings(prefs: PreferencesDep) -> Preferences:
    return prefs


@router.put("/api/settings", tags=["settings"])
def put_settings(update: Preferences, session: SessionDep) -> Preferences:
    """Replace all preferences. Unknown values fall back to their defaults."""
    return preferences.save(session, update)


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(
    request: Request, prefs: PreferencesDep, settings: SettingsDep, saved: bool = False
):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
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
                "last": navidrome.last,
            },
        },
    )


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
