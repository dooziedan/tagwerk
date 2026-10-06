"""Screenshot Tagwerk's main pages in Chromium, Firefox and WebKit (Safari's engine).

Checks every page in both themes, light and dark (via the browser's prefers-color-scheme,
so the "follow system" path is tested), on desktop and phone width. Browser errors from
the pages are listed at the end; the script fails if there are any.

Runs in Playwright's official Docker image, so no browsers or libraries are needed on the
host (WebKit doesn't run natively on every Linux):

    docker run --rm --network host -v "$PWD:/work" -w /work \\
        --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        mcr.microsoft.com/playwright/python:v1.63.0-noble \\
        sh -c "pip install -q --user playwright==1.63.0 &&
               python scripts/screenshots.py http://localhost:8000 dev/shots"

(--user makes the screenshots belong to you instead of root.)

Point it at a Tagwerk instance with a scanned library (e.g. `docker compose up`).
Note: it changes the instance's Theme and Appearance settings while it runs and sets them
back to "calm" / "follow system" at the end.
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ENGINES = ("chromium", "firefox", "webkit")
SCHEMES = ("light", "dark")
DEVICES = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 390, "height": 844}}
STYLES = ("calm", "pop")


def put_settings(base: str, **changes) -> None:
    with urllib.request.urlopen(f"{base}/api/settings") as r:
        current = json.load(r)
    request = urllib.request.Request(
        f"{base}/api/settings",
        data=json.dumps({**current, **changes}).encode(),
        headers={"content-type": "application/json"},
        method="PUT",
    )
    urllib.request.urlopen(request).close()


def first_track_id(base: str, query: str = "") -> int | None:
    with urllib.request.urlopen(f"{base}/api/tracks?{query}") as r:
        tracks = json.load(r)["tracks"]
    return tracks[0]["id"] if tracks else None


def first_inbox_id(base: str) -> int | None:
    with urllib.request.urlopen(f"{base}/api/inbox") as r:
        tracks = [t for t in json.load(r) if not t["error"]]
    return tracks[0]["id"] if tracks else None


def main(base: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    track = first_track_id(base)
    pages = {
        "dashboard": "/",
        "tracks": "/tracks",
        "fields": "/fields",
        "settings": "/settings",
        "changes": "/changes",
        "setup": "/setup",
        "final": "/final",
    }
    if track:
        pages["track"] = f"/tracks/{track}"
        pages["convert"] = f"/convert?ids={track}"
    # Pages that only have something to show in some libraries (BPM/key from the audio, IDs).
    for name, flag in (("track-audio", "audio_bpm_octave"), ("track-ids", "invalid_mbid")):
        if flagged := first_track_id(base, f"flag={flag}"):
            pages[name] = f"/tracks/{flagged}"
            pages[f"tracks-{flag}"] = f"/tracks?flag={flag}"
    pages["inbox"] = "/inbox"
    inbox = first_inbox_id(base)
    if inbox:
        pages["inbox-track"] = f"/inbox/{inbox}"

    errors: list[str] = []
    count = 0
    with sync_playwright() as p:
        for style in STYLES:
            put_settings(base, style=style, appearance="system", mode="dj")
            for engine in ENGINES:
                browser = getattr(p, engine).launch()
                for scheme in SCHEMES:
                    for device, viewport in DEVICES.items():
                        context = browser.new_context(viewport=viewport, color_scheme=scheme)
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda e, where=f"{engine}/{style}/{scheme}": errors.append(
                                f"{where}: {e}"
                            ),
                        )
                        for name, path in pages.items():
                            page.goto(base + path, wait_until="networkidle")
                            page.screenshot(
                                path=out / f"{name}-{style}-{scheme}-{device}-{engine}.png",
                                full_page=device == "desktop",
                            )
                            count += 1
                        context.close()
                browser.close()
                print(f"{style:5} {engine:9} done", flush=True)
    put_settings(base, style="calm", appearance="system")

    print(f"{count} screenshots in {out}")
    for error in errors:
        print("ERROR", error)
    return 1 if errors else 0


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    sys.exit(main(base_url.rstrip("/"), Path(sys.argv[2] if len(sys.argv) > 2 else "dev/shots")))
