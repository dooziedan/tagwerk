# 0043: Notifications: the bell holds the unread ones, the page keeps them until cleared
Date: 2026-10-18 · Status: Accepted · Issue [#93](https://github.com/dooziedan/tagwerk/issues/93) · Changes [ADR 0035](0035-notifications.md)

## Context
ADR 0035 let only **✓ Read** or **Mark all as read** mark a notification as read, and a read one left the menu and New at once for the History. So after opening a notification and reading it in full, the owner still had to press ✓ Read, and pressing it made the notification disappear from the page they had just read it on.

A first draft kept read notifications in the bell's menu too, and opened their details in a card beside it. The owner found that the summary alone already says enough to decide: open it, or mark it as read and move on. So the menu stays a short list of what's new, and the details live on the page.

## Decision
**Two steps: read, then cleared.** A notification has `read_at` and, new, `cleared_at`.

- **The bell's menu lists only the unread ones**, newest first, at most 20 ("All 25 new" opens the page with every one). No card and no details in the menu.
  - **A click on a summary** opens the Notifications page with that notification opened and in view; opening it marks it as read.
  - **✓ on a row** marks it as read right there: it leaves the menu (it stays in New on the page). **Mark all read** does it for all of them.
  - Opening the menu marks nothing.
- **The page's New** holds every notification not cleared yet, read or not. Unread ones have a gold dot before the summary (screen readers hear "Unread:"); read ones are quieter (softer ink, the kind's icon dimmed). Opening an entry marks it as read.
- **Clear (×)** on each entry in New moves it to the **History**; **Clear all** moves every one. Clearing an unread one reads it too. Nothing asks first: a cleared one is still in the History.
- **The History** holds cleared notifications until **Clear history** (asks first), as before. It has no buttons of its own: it is a record, not a to-do list.
- **Mark as unread** on a read entry in New counts it on the bell again (and puts it back in the menu), for something to deal with later. It is what Gmail, GitHub and most mail and notification lists offer. A "move back from the History" button was left out: few apps have one, and nothing in the History needs acting on.
- **✓ Read is gone** from the page: opening does it.
- **The tab's title** starts with the unread number, "(3) Inbox · Tagwerk", like other web apps, so a pinned tab shows it. It follows the bell's number (the check every minute).
- **Nothing outside the browser** for now: no browser or phone push. Those stay planned ([ADR 0035](0035-notifications.md), Later).

**GET never changes anything.** The menu's link is `/notifications?open=<id>`; the page's script marks it as read with `POST /api/notifications/{id}/read` (also sent when an entry is opened) and drops `?open=` from the address. `GET /api/notifications/{id}` stays without side effects.

**API:** `GET /api/notifications` returns New (not cleared, read or not; each with `read_at`), `?show=history` the cleared ones. New: `POST /api/notifications/{id}/clear`, `POST /api/notifications/{id}/unread`, `POST /api/notifications/clear-all`.

**Existing installs:** the migration sets `cleared_at = read_at` for notifications already read, so the History stays as it was.

## Consequences
- Reading a notification is one step; the bell only ever shows what's new.
- The owner tidies up New when they like, with × or Clear all; until then it can hold many read notifications, which is the owner's choice.
- `Notification.read_at` decides the bell (its number and its menu) and the dot; `cleared_at` decides New vs History.
