# 0001: Python, FastAPI, SQLite, server-rendered pages with htmx
Date: 2026-10-03 · Status: Accepted

## Context
The owner is new to programming. The app must read and write tags in MP3, FLAC, WAV and AIFF, serve a web UI, and run as one self-hosted container. The library has under 10,000 tracks.

## Decision
- **Python + FastAPI.** Python has the best tagging library (mutagen) and is beginner-friendly. FastAPI is typed and documents its own API at `/docs`.
- **SQLite** (via SQLModel, with Alembic migrations). One file in `/config` with no database server. That's plenty for under 10k tracks.
- **Jinja2 + htmx + Pico CSS**, stored in the repo (vendored). No JavaScript build step and no CDN dependency, so it works offline.

## Consequences
- Simple to run, back up (copy one folder) and learn.
- A very large library (100k+ tracks) or many simultaneous users would need a closer look at SQLite. Postgres could be added later behind SQLModel.
- A richer UI later (e.g. a JS framework) could use the existing API without changing the backend.
