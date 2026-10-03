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

## Checks

```sh
.venv/bin/pytest                 # tests
.venv/bin/ruff check .           # lint
.venv/bin/ruff format .          # format
```

CI runs the same checks on every push and pull request.

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
