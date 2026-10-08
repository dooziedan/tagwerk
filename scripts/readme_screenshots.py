"""Screenshots for the README, taken from the made-up showcase library (no real music).

    .venv/bin/python scripts/showcase_library.py dev/showcase   # once
    # run Tagwerk on dev/showcase (port 8005), finish the setup, scan; then:
    docker run --rm --network host -v "$PWD:/work" -w /work --user "$(id -u):$(id -g)" \\
        -e HOME=/tmp mcr.microsoft.com/playwright/python:v1.63.0-noble \\
        sh -c "pip install -q --user playwright==1.63.0 &&
               python scripts/readme_screenshots.py http://localhost:8005"

Saves JPEGs (small enough for the repository) to docs/screenshots/.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def first(base: str, path: str):
    with urllib.request.urlopen(base + path) as response:
        return json.load(response)


def main(base: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    track = first(base, "/api/tracks?flag=set_ready&format=mp3")["tracks"][0]["id"]
    request = urllib.request.Request(base + "/api/inbox/scan", method="POST")
    urllib.request.urlopen(request).close()  # read the inbox before its page is shown
    time.sleep(5)
    pages = {"home": "/", "statistics": "/stats", "track": f"/tracks/{track}",
             "duplicates": "/duplicates", "inbox": "/inbox"}  # fmt: skip
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="dark")
        for name, path in pages.items():
            page.goto(base + path)
            page.wait_for_timeout(1500)  # covers, fonts, the sky
            page.screenshot(path=OUT / f"{name}.jpg", type="jpeg", quality=82)
            print("saved", name)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8005")
