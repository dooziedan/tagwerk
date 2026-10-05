"""The setup wizard (first start) and the choices it shares with Settings.

Every choice made here can be changed later in Settings; both use the same `apply_choices`,
so a value means the same thing in both places.
"""

from collections import Counter
from dataclasses import replace
from pathlib import PurePosixPath

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import genres, naming, navidrome, preferences, writer
from app.config import SettingsDep, get_settings
from app.db import SessionDep
from app.inbox import review
from app.keys import NOTATIONS
from app.models import InboxTrack, Track
from app.preferences import AUTOMATIONS, LAYOUTS, MODES, Preferences
from app.routes.system import setup_status
from app.templating import templates

router = APIRouter()

# The wizard's steps, in order: (key, title)
STEPS = [
    ("welcome", "Welcome"),
    ("style", "How you work"),
    ("folders", "Import folders"),
    ("automation", "Independence"),
    ("final", "Final tracks"),
    ("done", "Done"),
]
STEP_KEYS = [key for key, _ in STEPS]


def apply_choices(prefs: Preferences, step: str, form) -> tuple[Preferences, dict[str, str]]:
    """Read one group of choices from a form (wizard step or Settings section)."""
    errors: dict[str, str] = {}
    if step == "style":
        prefs = replace(
            prefs,
            mode=form.get("mode", prefs.mode),
            key_notation=form.get("key_notation", prefs.key_notation),
        )
    elif step == "folders":
        layout = form.get("folder_layout", prefs.folder_layout)
        pattern = str(form.get("folder_pattern", prefs.folder_pattern)).strip()
        if layout == "custom":
            try:
                naming.check(pattern, folders=True)
            except naming.PatternError as exc:
                errors["folder_pattern"] = str(exc)
        picked = [str(g) for g in form.getlist("genre_folders")]
        extra = [g.strip() for g in str(form.get("more_genres", "")).split(",") if g.strip()]
        prefs = replace(
            prefs,
            folder_layout=layout,
            folder_pattern=pattern or prefs.folder_pattern,
            genre_folders=list(dict.fromkeys(picked + extra)),
        )
    elif step == "automation":
        prefs = replace(
            prefs,
            automation=form.get("automation", prefs.automation),
            remove_traktor_on_import=form.get("remove_traktor_on_import") == "on",
        )
    elif step == "final":
        pattern = str(form.get("filename_pattern", prefs.filename_pattern)).strip()
        try:
            naming.check(pattern)
        except naming.PatternError as exc:
            errors["filename_pattern"] = str(exc)
        prefs = replace(
            prefs, rename_on_final=form.get("rename_on_final") == "on", filename_pattern=pattern
        )
    return prefs, errors


def examples(session: Session, prefs: Preferences, limit: int = 3) -> list[dict]:
    """A few real tracks (inbox first, then library) to preview patterns with."""
    found = []
    for track in session.exec(select(InboxTrack).where(InboxTrack.error.is_(None)).limit(limit)):
        values = {f.field: f.value for f in review(session, track, list(writer.EDITABLE))}
        found.append({"name": PurePosixPath(track.path).name, "values": values})
    if len(found) < limit:
        query = select(Track).where(Track.title.is_not(None)).limit(limit - len(found))
        for track in session.exec(query):
            values = {f: writer.current_value(track, f) for f in writer.EDITABLE}
            found.append({"name": PurePosixPath(track.path).name, "values": values})
    return found


def preview(session: Session, prefs: Preferences, kind: str) -> list[tuple[str, str]]:
    """(original filename, result) for the example tracks: the folder or the final name."""
    genre_map = genres.from_text(prefs.genre_map)
    existing = naming.existing_folders(get_settings().music_dir)
    result = []
    for ex in examples(session, prefs):
        values = naming.values_for(ex["values"], genre_map, prefs.key_notation)
        suffix = PurePosixPath(ex["name"]).suffix
        if kind == "folder":
            folder = naming.folder(
                prefs.folder_layout, prefs.folder_pattern, values, prefs.genre_folders, existing
            )
            result.append((ex["name"], f"{folder}/{ex['name']}"))
        else:
            result.append((ex["name"], naming.filename(prefs.filename_pattern, values, suffix)))
    return result


def main_genres(session: Session, prefs: Preferences, limit: int = 16) -> list[tuple[str, int]]:
    """The most common main genres in the library and inbox, to offer as genre folders."""
    genre_map = genres.from_text(prefs.genre_map)
    counts: Counter[str] = Counter()
    values = list(session.exec(select(Track.genre).where(Track.genre.is_not(None))))
    values += session.exec(select(InboxTrack.genre).where(InboxTrack.genre.is_not(None)))
    for value in values:
        tidy = genre_map.tidy(str(value).split(";"))
        if tidy:
            counts[tidy[0]] += 1
    for chosen in prefs.genre_folders:  # chosen ones always show up
        counts.setdefault(chosen, 0)
    return counts.most_common(limit + len(prefs.genre_folders))


def choices_context(session: Session, prefs: Preferences) -> dict:
    """What the shared choice templates need (wizard and Settings)."""
    return {
        "layouts": LAYOUTS,
        "automations": AUTOMATIONS,
        "modes": MODES,
        "notations": NOTATIONS,
        "placeholders": naming.PLACEHOLDERS,
        "folder_placeholders": sorted(naming.FOLDER_PLACEHOLDERS),
        "main_genres": main_genres(session, prefs),
        "folder_preview": preview(session, prefs, "folder"),
        "file_preview": preview(session, prefs, "file"),
    }


# --- Wizard pages ---------------------------------------------------------------------------


@router.get("/setup", response_class=HTMLResponse, include_in_schema=False)
def setup_page(request: Request, session: SessionDep, settings: SettingsDep, step: str = "welcome"):
    prefs = preferences.load(session)
    return _page(request, session, settings, prefs, step if step in STEP_KEYS else "welcome", {})


@router.post("/setup/skip", include_in_schema=False)
def setup_skip(session: SessionDep):
    """Use the defaults; everything can be changed in Settings."""
    preferences.save(session, replace(preferences.load(session), setup_done=True))
    return RedirectResponse("/", status_code=303)


@router.post("/setup/{step}", include_in_schema=False)
async def setup_save(request: Request, step: str, session: SessionDep, settings: SettingsDep):
    if step not in STEP_KEYS:
        return RedirectResponse("/setup", status_code=303)
    form = await request.form()
    prefs, errors = apply_choices(preferences.load(session), step, form)
    if errors:
        return _page(request, session, settings, prefs, step, errors, status_code=422)
    if step == "done":
        prefs = replace(
            prefs,
            setup_done=True,
            backup_confirmed=prefs.backup_confirmed or form.get("backup") == "on",
        )
        preferences.save(session, prefs)
        return RedirectResponse("/", status_code=303)
    preferences.save(session, prefs)
    following = STEP_KEYS[STEP_KEYS.index(step) + 1]
    return RedirectResponse(f"/setup?step={following}", status_code=303)


@router.get("/setup/preview", response_class=HTMLResponse, include_in_schema=False)
def setup_preview(request: Request, session: SessionDep, kind: str = "file"):
    """Live preview while typing a pattern (wizard and Settings)."""
    params = request.query_params
    prefs, errors = apply_choices(
        preferences.load(session), "folders" if kind == "folder" else "final", params
    )
    return templates.TemplateResponse(
        request,
        "partials/pattern_preview.html",
        {
            "rows": [] if errors else preview(session, prefs, kind),
            "error": next(iter(errors.values()), None),
        },
    )


def _page(request, session, settings, prefs, step, errors, status_code=200):
    index = STEP_KEYS.index(step)
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "prefs": prefs,
            "step": step,
            "steps": STEPS,
            "index": index,
            "back": STEP_KEYS[index - 1] if index > 0 else None,
            "errors": errors,
            "status": setup_status(request, settings),
            "inbox_ready": settings.import_dir.is_dir(),
            "import_dir": settings.import_dir,
            "navidrome_ready": navidrome.configured(settings),
            "navidrome_library": settings.navidrome_library,
            **choices_context(session, prefs),
        },
        status_code=status_code,
    )
