# Architecture

## Overview

```
 Browser ──HTTP──► FastAPI app (one container)
                      │
                      ├─ pages (Jinja2 + htmx)  ─┐ same routes, documented at /docs
                      ├─ REST API               ─┘
                      ├─ SQLite DB  ──────────► /config/tagwerk.db
                      ├─ tag reader/writer ───► /music  (mutagen)
                      ├─ metadata sources ────► MusicBrainz, Cover Art Archive, … (internet)
                      └─ Navidrome client ────► Navidrome (Subsonic API, via host IP)
```

## The change flow (core design)

Files are never modified directly from a form or a lookup:

1. **Scan:** read tags from files into the database (the "current file state").
2. **Edit / Lookup:** manual edits and source results become *pending changes* in the database.
3. **Review:** a diff shows old → new per field and file.
4. **Apply:** tags are written. The old tags are saved first as a snapshot, which makes undo possible.
5. **Sync:** Navidrome is asked to rescan.

## Code layout

| Path | Purpose | Since |
|---|---|---|
| `app/main.py` | Creates the FastAPI app, registers routes | 0.1 |
| `app/config.py` | Settings from environment variables | 0.1 |
| `app/templates/`, `app/static/` | HTML pages; vendored Pico CSS and htmx | 0.1 |
| `app/db.py`, `app/models.py`, `app/migrations/` | Database tables and Alembic migrations (run on every start) | 0.2 |
| `app/tags.py` | Reads ID3 / Vorbis / MP4 / RIFF INFO into one set of fields ([ADR 0005](decisions/0005-reading-tags.md)) | 0.2 |
| `app/scanner.py` | Walks the music folder, updates the `track` table, skips unchanged files | 0.2 |
| `app/stats.py` | Dashboard numbers, computed with SQL from `track` | 0.2 |
| `app/routes/` | Pages and API, one module per feature (`system`, `dashboard`, `scan`) | 0.2 |
| `app/templating.py` | Jinja2 setup and display filters (sizes, durations) | 0.2 |
| `app/navidrome.py` | Subsonic API client | Phase 3 |
| `app/sources/` | Metadata sources behind one interface (`base.py`) | Phase 4 |
| `app/jobs.py` | Background jobs in a thread, progress kept in memory (scan; later lookup, apply) | 0.2 |
| `docker/entrypoint.sh` | Applies PUID/PGID/UMASK, then starts the app | 0.1 |
| `unraid/tagwerk.xml` | Unraid container template | 0.1 |

## Runtime

- One process: `uvicorn` serving FastAPI. No external services.
- Database: SQLite at `/config/tagwerk.db` in WAL mode, so the dashboard can read during a scan.
- Data model so far: one `track` row per audio file. Artists and albums are derived from it.
- Persistent state lives only in `/config`. The container can be deleted and recreated at any time.
- Runs as `PUID:PGID` (Unraid: `99:100`). Only `/config` is chowned on start, never `/music`.
