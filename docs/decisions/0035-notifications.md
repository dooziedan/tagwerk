# 0035: Notifications: what Tagwerk did while you were away
Date: 2026-10-11 · Status: Accepted (reading and clearing changed by [0043](0043-notifications-read-on-opening.md)) · Issue [#61](https://github.com/dooziedan/tagwerk/issues/61)

## Context
More and more of Tagwerk's work happens while the owner isn't looking: the inbox is checked every five minutes and may import tracks on its own (automatic mode, [ADR 0007](0007-import-inbox.md)), deleted inbox files are removed for good after 30 days ([ADR 0011](0011-inbox-duplicates-and-trash.md)), a scan stops when the music folder looks empty, Navidrome may not answer, a source may reject its key, and long jobs (audio analysis, lookups for many tracks) finish minutes after the owner left the page.

Toasts don't fit this: they belong to the page and are shown once, for what the owner just did and saw. Nothing kept what happened while the owner was away.

## Decision
**A place of its own, kept short.** Each notification has a one-line summary, a detailed message, its source (Inbox check, Inbox trash, Scan, Navidrome, Online lookup, Audio analysis), its kind (**needs you** gold, **problem** warning, **done** calm), the time and a link to where the owner acts. Stored in the `notification` table; what the checks remember between runs (problems already reported, the last inbox count, the inbox-trash files already announced) in `notificationstate`.

**The owner chooses** in Settings → Notifications, one switch per topic. A switched-off topic writes nothing at all. The defaults are low on purpose: only what needs the owner or could lose data.

| Topic | Kind | Default |
|---|---|---|
| Inbox trash: files will be removed for good, announced 3 days before (names, date, a link to restore them); checked once a day, each file once, never after removal | needs you | on |
| Inbox needs you: more tracks need help than at the last check (counted only when the inbox check, its lookups and the audio analysis are idle, so a new track waiting for its BPM doesn't count) | needs you | on |
| Scan problems: skipped because the music folder looked empty or missing; files that couldn't be read (each file once) | problem | on |
| Navidrome didn't answer the rescan after a write, or the "has it scanned yet?" check before a final rename | problem | on |
| Online sources: a key rejected (at once; each source says what a rejected key looks like, `Source.key_refused`: HTTP 401/403, AcoustID's HTTP 400 with its error code 4), or a source failing 5 lookups in a row | problem | on |
| Automatic imports: tracks imported on their own, with a link to the History entry | done | off |
| Long jobs finished: audio analysis or online lookups the owner started for at least 10 library tracks | done | off |

**Rules that keep it short:** one entry per job run, never one per track; a check where nothing happened writes nothing; nothing the owner just did and saw (the Settings buttons for Navidrome don't report, toasts stay for page actions); a lasting problem is reported once, and once more when it is fine again (`problem()` and `solved()`); the library trash isn't on the list, only the owner empties it ([ADR 0023](0023-library-trash.md)).

**`notify()` never raises:** a notification that can't be written (e.g. a locked database) is logged, and the scan or import that called carries on.

**Read and removed only by the owner.** *(Changed by [ADR 0043](0043-notifications-read-on-opening.md): the bell's menu lists the unread ones and opens them on the page; opening one reads it; it stays in New until cleared.)* Only **✓ Read** (in the card, the phone menu's detail or an opened entry on the page) or **Mark all as read** marks a notification as read; opening the menu, a card, the page or an entry doesn't. Nothing disappears by itself: unread ones stay in **New**, read ones in **History** until **Clear history**. No timer.

**The bell, designed for the phone first.** Phones: a bell with the unread count in the floating top bar between Changes and the menu; below 430 px only the logo shows, without the word "Tagwerk", so everything fits at 390 px. The bell opens a menu below the bar with the summaries of the unread notifications, newest first ("Nothing new" when empty) and **All** at the bottom; a summary shows its details in place of the list, with **← Back**. Wide screens: the bell sits next to the logo at the top of the side menu, its number on the bell's corner (beside it, the two don't fit the side menu's width); the menu opens as a panel beside it and a summary opens a card hovering next to the panel. Windows too narrow for the side menu behave like the phone. Escape and a click outside close it. From 10 unread on the number reads **9+** ("128" would cover the bell; "9+" is tinier than "99+"), screen readers hear the whole number. No menu entry: the page opens only from **All**. The number keeps up while a page stays open (a quiet check every minute); it just changes, nothing blinks.

**The page** has **New**, grouped by day in the browser's time zone (Today, Yesterday, 12 Oct), with **Mark all as read**, and **History** with **Clear history** (asks first). Entries open in place. Home's "Waiting for you" gets one line when unread "needs you" notifications exist; it opens the bell's menu. The card is reloaded every minute while Home stays open, like the bell's number.

**Built with what's there:** one panel element and a short script (`app/static/bell.js`), htmx for the menu, card and ✓ Read, plain CSS. No Popover API or CSS anchor positioning (too new for the owner's browser), no `color-mix()`. The panel is `position: fixed` outside the side menu, so the side menu's scrolling never cuts it off.

**New topics** add an entry to `TOPICS` in `app/notifications.py` with their default; existing installs get that default too.

**Dates in the owner's time zone:** a date written into a notification ("removed for good on 14 Oct") uses the time zone chosen in Settings → General (Settings offers the browser's); left empty, the container's `TZ` (Unraid sets it for every container; UTC without it). Times shown in the menu and on the page use the browser's time zone.

## Consequences
- The owner learns about lost-data risks (inbox trash), problems that block work (scan, Navidrome, keys) and tracks waiting, without checking each page.
- Every topic is a promise to stay quiet when nothing happened; tests check each one writes exactly one entry when something happened, none when nothing did, and none when switched off.
- Notifications pile up only if the owner never clears the History; that is the owner's choice.
- Later: notifications from the release watch ("Out now: …") and AcoustID, and sending them to the phone (ntfy, Gotify, Unraid), switchable per topic.
