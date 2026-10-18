"""Notifications: the bell's menu, the Notifications page, and the API (ADR 0035, 0043).

The bell's menu lists the unread notifications. Clicking one opens it on the page; opening an
entry there, or ✓ in the menu, marks it as read. It stays in "New" on the page until the owner
clears it (× or "Clear all"), then it is in the History until "Clear history". Opening the menu
or the page marks nothing: GET routes never change anything.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import notifications
from app.db import SessionDep
from app.models import Notification
from app.templating import templates

router = APIRouter()

# The menu shows the newest unread ones; "All" opens the page with every one.
MENU_SIZE = 20


# --- API (shown in /docs) -----------------------------------------------------------------------


@router.get("/api/notifications", tags=["notifications"])
def list_api(session: SessionDep, show: Literal["new", "history"] = "new") -> list[Notification]:
    """New (not cleared, read or not), newest first; or the History (cleared ones)."""
    return notifications.current(session) if show == "new" else notifications.history(session)


@router.get("/api/notifications/count", tags=["notifications"])
def count_api(session: SessionDep) -> dict:
    """How many are unread (the bell's number), and how many of them need you."""
    return {
        "unread": notifications.unread_count(session),
        "needs_you": notifications.unread_count(session, "needs_you"),
    }


@router.post("/api/notifications/read-all", tags=["notifications"])
def read_all_api(session: SessionDep) -> dict:
    """Mark all as read: the bell's number goes to zero; everything stays in New."""
    return {"marked": notifications.mark_all_read(session)}


@router.post("/api/notifications/clear-all", tags=["notifications"])
def clear_all_api(session: SessionDep) -> dict:
    """Clear all: every notification in New moves to the History."""
    return {"cleared": notifications.clear_all(session)}


@router.post("/api/notifications/clear-history", tags=["notifications"])
def clear_history_api(session: SessionDep) -> dict:
    """Clear history: remove the cleared notifications for good. New ones stay."""
    return {"removed": notifications.clear_history(session)}


@router.get("/api/notifications/{notification_id}", tags=["notifications"])
def one_api(notification_id: int, session: SessionDep) -> Notification:
    """One notification. Reading it here doesn't mark it as read."""
    return _get(session, notification_id)


@router.post("/api/notifications/{notification_id}/read", tags=["notifications"])
def read_api(notification_id: int, session: SessionDep) -> Notification:
    """Mark as read (what opening it on the page does). It stays in New until cleared."""
    _get(session, notification_id)
    return notifications.mark_read(session, notification_id)


@router.post("/api/notifications/{notification_id}/unread", tags=["notifications"])
def unread_api(notification_id: int, session: SessionDep) -> Notification:
    """Mark as unread: counts on the bell again; a cleared one comes back to New."""
    _get(session, notification_id)
    return notifications.mark_unread(session, notification_id)


@router.post("/api/notifications/{notification_id}/clear", tags=["notifications"])
def clear_api(notification_id: int, session: SessionDep) -> Notification:
    """Clear: the notification moves from New to the History."""
    _get(session, notification_id)
    return notifications.clear(session, notification_id)


def _get(session, notification_id: int) -> Notification:
    note = session.get(Notification, notification_id)
    if note is None:
        raise HTTPException(404, "No such notification")
    return note


# --- The bell: menu (htmx partials) -------------------------------------------------------------


@router.get("/partials/notifications/menu", response_class=HTMLResponse, include_in_schema=False)
def menu_partial(request: Request, session: SessionDep):
    """The bell's menu: the newest unread notifications."""
    return _menu(request, session)


@router.get("/partials/notifications/count", response_class=HTMLResponse, include_in_schema=False)
def count_partial(request: Request):
    """The bell's number, asked for now and then while a page stays open."""
    return templates.TemplateResponse(request, "partials/notification_count.html", {})


@router.post(
    "/partials/notifications/read-all", response_class=HTMLResponse, include_in_schema=False
)
def read_all_in_menu(request: Request, session: SessionDep):
    notifications.mark_all_read(session)
    return _menu(request, session)


@router.post(
    "/partials/notifications/{notification_id}/read",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def read_in_menu(request: Request, notification_id: int, session: SessionDep):
    """✓ in the menu: read, so it leaves the menu (it stays in New on the page)."""
    _get(session, notification_id)
    notifications.mark_read(session, notification_id)
    return _menu(request, session)


def _menu(request, session):
    items = notifications.unread(session)
    return templates.TemplateResponse(
        request,
        "partials/notification_menu.html",
        {"items": items[:MENU_SIZE], "total": len(items)},
    )


# --- The Notifications page (opened from "All" in the menu) ------------------------------------
# Its buttons are plain forms; the page comes back where it was (data-keep-place in base.html).


@router.get("/notifications", response_class=HTMLResponse, include_in_schema=False)
def notifications_page(request: Request, session: SessionDep, open: int | None = None):
    """``open``: the notification clicked in the bell's menu, shown opened. The page's script
    marks it as read (a GET changes nothing)."""
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {
            "new": notifications.current(session),
            "history": notifications.history(session),
            "opened": open,
        },
    )


@router.post("/notifications/read-all", include_in_schema=False)
def read_all(session: SessionDep):
    notifications.mark_all_read(session)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/clear-all", include_in_schema=False)
def clear_all(session: SessionDep):
    notifications.clear_all(session)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/clear-history", include_in_schema=False)
def clear_history(session: SessionDep):
    notifications.clear_history(session)
    return RedirectResponse("/notifications#history", status_code=303)


@router.post("/notifications/{notification_id}/{action}", include_in_schema=False)
def act_on_page(notification_id: int, action: Literal["clear", "unread"], session: SessionDep):
    """An entry's Clear (×) or Mark as unread. (Opening an entry sends the API's /read.)"""
    _get(session, notification_id)
    if action == "clear":
        notifications.clear(session, notification_id)
    else:
        notifications.mark_unread(session, notification_id)
    return RedirectResponse("/notifications", status_code=303)
