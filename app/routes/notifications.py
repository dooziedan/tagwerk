"""Notifications: the bell's menu and card, the Notifications page, and the API (ADR 0035).

Opening the menu, a card, the page or an entry changes nothing. Only ✓ Read and "Mark all as
read" move notifications to the History; only "Clear history" removes read ones.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import notifications
from app.db import SessionDep
from app.models import Notification
from app.templating import templates

router = APIRouter()


# --- API (shown in /docs) -----------------------------------------------------------------------


@router.get("/api/notifications", tags=["notifications"])
def list_api(session: SessionDep, show: Literal["new", "history"] = "new") -> list[Notification]:
    """New (unread) notifications, newest first; or the History (read ones)."""
    return notifications.unread(session) if show == "new" else notifications.history(session)


@router.get("/api/notifications/count", tags=["notifications"])
def count_api(session: SessionDep) -> dict:
    """How many are unread (the bell's number), and how many of them need you."""
    return {
        "unread": notifications.unread_count(session),
        "needs_you": notifications.unread_count(session, "needs_you"),
    }


@router.post("/api/notifications/read-all", tags=["notifications"])
def read_all_api(session: SessionDep) -> dict:
    """Mark all as read: every New notification moves to the History."""
    return {"marked": notifications.mark_all_read(session)}


@router.post("/api/notifications/clear-history", tags=["notifications"])
def clear_history_api(session: SessionDep) -> dict:
    """Clear history: remove the read notifications for good. New ones stay."""
    return {"removed": notifications.clear_history(session)}


@router.get("/api/notifications/{notification_id}", tags=["notifications"])
def one_api(notification_id: int, session: SessionDep) -> Notification:
    """One notification. Reading it doesn't mark it as read."""
    return _get(session, notification_id)


@router.post("/api/notifications/{notification_id}/read", tags=["notifications"])
def read_api(notification_id: int, session: SessionDep) -> Notification:
    """✓ Read: the notification moves to the History."""
    _get(session, notification_id)
    return notifications.mark_read(session, notification_id)


def _get(session, notification_id: int) -> Notification:
    note = session.get(Notification, notification_id)
    if note is None:
        raise HTTPException(404, "No such notification")
    return note


# --- The bell: menu and card (htmx partials) -----------------------------------------------------


@router.get("/partials/notifications/menu", response_class=HTMLResponse, include_in_schema=False)
def menu_partial(request: Request, session: SessionDep):
    """The bell's menu: short summaries of the unread notifications, newest first."""
    return _menu(request, session)


@router.get("/partials/notifications/count", response_class=HTMLResponse, include_in_schema=False)
def count_partial(request: Request):
    """The bell's number, asked for now and then while a page stays open."""
    return templates.TemplateResponse(request, "partials/notification_count.html", {})


@router.get(
    "/partials/notifications/{notification_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def card_partial(request: Request, notification_id: int, session: SessionDep):
    """One notification's details: the card beside the menu (the menu itself on phones)."""
    return templates.TemplateResponse(
        request, "partials/notification_card.html", {"n": _get(session, notification_id)}
    )


@router.post(
    "/partials/notifications/{notification_id}/read",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def read_in_menu(request: Request, notification_id: int, session: SessionDep):
    """✓ Read in the card: back to the menu, without it."""
    _get(session, notification_id)
    notifications.mark_read(session, notification_id)
    return _menu(request, session)


def _menu(request, session):
    return templates.TemplateResponse(
        request, "partials/notification_menu.html", {"items": notifications.unread(session)}
    )


# --- The Notifications page (opened from "All" in the menu) ------------------------------------


@router.get("/notifications", response_class=HTMLResponse, include_in_schema=False)
def notifications_page(request: Request, session: SessionDep):
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {"new": notifications.unread(session), "history": notifications.history(session)},
    )


@router.post("/notifications/read-all", include_in_schema=False)
def read_all(session: SessionDep):
    notifications.mark_all_read(session)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/clear-history", include_in_schema=False)
def clear_history(session: SessionDep):
    notifications.clear_history(session)
    return RedirectResponse("/notifications#history", status_code=303)


@router.post("/notifications/{notification_id}/read", include_in_schema=False)
def read_on_page(notification_id: int, session: SessionDep):
    _get(session, notification_id)
    notifications.mark_read(session, notification_id)
    return RedirectResponse("/notifications", status_code=303)
