# 0002: Single container, Unraid conventions, images on GHCR
Date: 2026-10-03 · Status: Accepted

## Context
The app is self-hosted first and runs on an Unraid server (7.3.x) next to Navidrome, editing the same music share.

## Decision
- **One container**, with no companion services. All state lives in `/config`.
- **Unraid conventions:** `PUID`/`PGID`/`UMASK` env vars (defaults 99/100/022), applied by `docker/entrypoint.sh` with `setpriv`. Only `/config` is chowned, never the music library.
- **The music path is a required template field with no default.** Every installation sets it explicitly.
- **appdata on a pool / exclusive share:** SQLite file locking is unreliable through Unraid's FUSE layer (`/mnt/user` on array disks).
- **Images on GHCR** (`ghcr.io/dooziedan/tagwerk`), built by GitHub Actions. `:edge` comes from `main`, `:X.Y.Z` and `:latest` from version tags. The repository is public, so Unraid can pull without credentials.
- **amd64 only** for now, because Unraid runs on x86-64.

## Consequences
- Installs from the Unraid Docker UI like any Community Applications app, and updates show up automatically.
- Other hosts (plain Docker, compose) work too, but need `PUID`/`PGID` set to their own user.
- arm64 (e.g. Raspberry Pi) can be added later by adding a platform in the workflow.
