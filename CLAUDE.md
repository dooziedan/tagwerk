# Tagwerk: notes for Claude

Self-hosted music library manager. Python + FastAPI, deployed as one Docker container on Unraid next to Navidrome.
The owner is learning to code: explain changes in plain language and keep the code easy to read.

## Commands
- Setup: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- Run locally: `.venv/bin/uvicorn app.main:app --reload` (set `MUSIC_DIR`/`CONFIG_DIR` to local folders, e.g. in `.env`)
- Tests: `.venv/bin/pytest`
- Lint/format: `.venv/bin/ruff check . && .venv/bin/ruff format .`
- Container: `docker compose up --build` (http://localhost:8000)
- New migration after model changes: `CONFIG_DIR=dev/config .venv/bin/alembic revision --autogenerate -m "…"`
- Regenerate test audio: `.venv/bin/python tests/fixtures/generate.py` (ffmpeg)

## Rules
- **Never write to music files without the review → apply flow**, and always snapshot old tags first. Develop against a test copy (`dev/music/`), never the real library.
- The music folder is never `chown`ed or bulk-modified by the container.
- Unraid compatibility: PUID/PGID/UMASK (defaults 99/100/022), all config via env vars, data only in `/config`. Reach Navidrome via host IP or Docker network, never `localhost`.
- Schema changes go through Alembic migrations. Never edit an already released migration. `test_migrations_match_models` guards drift.
- Supported formats: MP3, FLAC, WAV, AIFF, M4A, OGG, Opus. Any tag feature must handle all of them (fixtures in `tests/fixtures/`).
- When the tag reader learns new fields, bump `SCAN_VERSION` in `app/scanner.py` so existing rows get re-read.
- New NOT NULL columns need a `server_default` in the migration: real databases already have rows.
- **Everything must run inside the Docker image** (the owner deploys to Unraid). No host tools at runtime; any new library (e.g. audio analysis) goes into the image. ffmpeg is a dev-only tool for generating fixtures.
- Modes (DJ / Collector) only change what is shown and checked, never what is stored ([ADR 0006](docs/decisions/0006-modes.md)). The owner is a DJ: many tracks are edits/bootlegs not on MusicBrainz.
- Scans store tags as found on disk. Flag bad data (`mbid_invalid`, `error`), don't silently fix it.
- Metadata sources implement the shared interface in `app/sources/` (from Phase 4).
- The UI uses the same API routes as `/docs`. No JS build step: Jinja2 + htmx + Pico CSS, vendored in `app/static/`.
- Every user-visible change: update `CHANGELOG.md` (Unreleased). New design decisions: add an ADR in `docs/decisions/`.
- Work on feature branches with PRs; commit or push only when asked. Releases are git tags `vX.Y.Z` (CI publishes the image).
- **Public repo: never put Claude session links (claude.ai/code/session…) or other private URLs/IDs in commits, PR descriptions or files.** Attribution is only `Co-Authored-By: Claude …` in commits and the "Generated with Claude Code" line in PRs.

## Layout
See `docs/architecture.md`. Roadmap and phase status: `docs/roadmap.md`.
