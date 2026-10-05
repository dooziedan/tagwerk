"""Where a page's "← Back" leads, and where the user returns to after saving.

Pages pass the origin along explicitly (a ``back`` parameter, or the browser's Referer on the
first step) instead of relying on the browser history, so Back links are predictable and never
loop. Only paths of this app are accepted.
"""

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import Request

# Track and edit pages are never an origin: returning there after an edit would be a detour.
_NOT_AN_ORIGIN = re.compile(r"^/tracks/(\d+|edit)(/|$)")


def back_url(request: Request, *candidates, fallback: str) -> str:
    """The first candidate that is a page of this app, without a leftover "saved" note."""
    for url in candidates:
        if not isinstance(url, str) or not url:
            continue
        parts = urlsplit(url)
        if parts.netloc and parts.netloc != request.url.netloc:
            continue  # another site
        path = parts.path
        if not path.startswith("/") or path.startswith("//") or _NOT_AN_ORIGIN.match(path):
            continue
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "saved"]
        return path + ("?" + urlencode(query) if query else "")
    return fallback


def with_saved_note(url: str, count: int) -> str:
    """The URL with a "saved" note, shown as a short confirmation by base.html."""
    return url + ("&" if "?" in url else "?") + f"saved={count}"


def reload_page(request: Request, response, drop: tuple[str, ...] = ()) -> None:
    """Show the current page again after a job finished (polling partials).

    Swaps only #page (like a boosted link), so the play bar keeps playing; without htmx's
    current URL, falls back to a full reload. ``drop``: query parameters to leave out (e.g. a
    "looking up…" note). The address is replaced, not added to the history, so Back doesn't
    step through the same page.
    """
    current = request.headers.get("HX-Current-URL")
    if not current:
        response.headers["HX-Refresh"] = "true"
        return
    url = urlsplit(current)
    query = urlencode([(k, v) for k, v in parse_qsl(url.query) if k not in drop])
    path = url.path + (f"?{query}" if query else "")
    response.headers["HX-Location"] = json.dumps(
        {
            "path": path,
            "target": "#page",
            "select": "#page",
            "swap": "outerHTML",
            "push": False,
            "replace": path,
        }
    )
