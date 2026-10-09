# Development

## First-time setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pre-commit install      # optional: lint automatically before each commit
```

Create a test library and never develop against your real music:

```sh
mkdir -p dev/music dev/config
cp -r "/path/to/a/few/albums" dev/music/
```

`dev/` is git-ignored.

## Run

Without Docker (auto-reloads on code changes):

```sh
MUSIC_DIR=dev/music CONFIG_DIR=dev/config .venv/bin/uvicorn app.main:app --reload
```

With Docker, the same way it runs on Unraid:

```sh
docker compose up --build
```

Then open http://localhost:8000 (API docs at http://localhost:8000/docs).

## Database changes

The app migrates its database on start. After changing `app/models.py`, create a migration and commit it:

```sh
CONFIG_DIR=dev/config .venv/bin/alembic upgrade head          # bring your dev DB up to date first
CONFIG_DIR=dev/config .venv/bin/alembic revision --autogenerate -m "add rating column"
```

Review the generated file in `app/migrations/versions/`. A test fails if the models and migrations ever drift apart. Never edit a migration that was already released.

## Test audio files

`tests/fixtures/` holds tiny tagged files in every supported format, made by `tests/fixtures/generate.py` (needs ffmpeg). Regenerate them only when adding cases. Tests never go online: `tests/conftest.py` blocks the sources' HTTP, and `tests/fixtures/online/` holds saved answers for the source tests.

## Checks

```sh
.venv/bin/pytest                 # tests
.venv/bin/ruff check .           # lint
.venv/bin/ruff format .          # format
```

CI runs the same checks on every push and pull request.

## Checking the look in all browsers

Every release that changes the interface: run `docker compose up`, scan, then

```sh
docker run --rm --network host -v "$PWD:/work" -w /work \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    mcr.microsoft.com/playwright/python:v1.63.0-noble \
    sh -c "pip install -q --user playwright==1.63.0 && python scripts/screenshots.py http://localhost:8000 dev/shots"
```

It saves screenshots of every main page to `dev/shots/` (Chromium, Firefox, WebKit × desktop/phone) and fails on browser errors. See [design.md](design.md) for the rules.

## Screenshots for the README

The README never shows real music (the repository is public). A made-up showcase library has
invented artists, generated covers and silent audio:

```sh
.venv/bin/python scripts/showcase_library.py dev/showcase
docker run -d --name tagwerk-showcase -p 8005:8000 -e PUID=$(id -u) -e PGID=$(id -g) \
    -v "$PWD/dev/showcase/music:/music" -v "$PWD/dev/showcase/config:/config" \
    -v "$PWD/dev/showcase/import:/import" tagwerk:dev
```

Finish the setup, scan, then run `scripts/readme_screenshots.py` in the Playwright
image (see its docstring). The JPEGs land in `docs/screenshots/`.

## Speed with a big library

```sh
.venv/bin/python scripts/benchmark.py            # 20,000 made-up tracks
.venv/bin/python scripts/benchmark.py --tracks 50000
```

Builds a made-up library database (no audio files) in a temporary folder and prints how long
every main page takes, plus the time to find duplicates and to rework BPM/key decisions after a
scan. Run it after changing queries on Home, Statistics or the track list.

## Workflow

1. Create a branch: `git switch -c feature/short-name`
2. Commit, push, open a pull request. CI must pass.
3. Merge to `main`. This publishes `ghcr.io/dooziedan/tagwerk:edge`.

## Releasing

1. Move the `Unreleased` entries in `CHANGELOG.md` to a new version section.
2. Bump `version` in `pyproject.toml`.
3. Commit, then tag and push:
   ```sh
   git tag v0.2.0 && git push origin v0.2.0
   ```
4. CI publishes `:0.2.0`, `:0.2` and `:latest`. Unraid shows "update available".

Versions follow semantic versioning. While the version is `0.x`, breaking changes can happen in minor versions and are noted in the changelog.

## Testing on Unraid before a release

Set the template's Repository to `ghcr.io/dooziedan/tagwerk:edge` to run the latest `main` build.
