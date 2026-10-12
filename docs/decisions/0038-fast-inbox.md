# 0038: A fast Inbox: what is stored about the tracks is read once, background checks only do what's needed
Date: 2026-10-12 · Status: Accepted

## Context
With 329 tracks in the owner's inbox, opening the Inbox took about 3 seconds, a track's review page about 3.4 seconds and Home about 1.8 seconds. Measured on the owner's server, three causes added up:

- **Every inbox row asked the database again and again.** `_summary()` worked out each track's suggestions, cover, duplicates and better copy. Along the way the stored online answers were read and parsed three times per track (suggestions, cover suggestion, BPM and key hints), each time with a "why this match" text for every candidate that the list never shows, the preferences four times (for the genre map), and the owner's values three times: about a dozen queries per track, 3,962 for a copy of the owner's inbox. Home did the same to show two numbers, and a track's page built the whole list twice (its position and its neighbours) plus its own row a third time.
- **Opening the Inbox started a check** (when the last one was more than 10 seconds ago). That's wanted, since new files show up right away, but after reading the folder the check asked the online lookup and the audio analysis about every inbox track, only to find nearly all of them done. For the lookups alone that was about 3,300 queries, running beside the page that was being built.
- **A trap for later:** when a check was still running as the page arrived, the page showed its progress and built itself again when the check was done, even when it found nothing. Only the slow page hid this: by the time it was built, the check had finished.

## Decision
**The inbox pages read what is stored about the tracks once, for all of them** (`load_known()` in `app/inbox.py`): the owner's values, the online answers (without the "why" texts), the audio analyses, the secret marks and the genre map, a few queries in all. Each row is then worked out from that, without asking the database. The functions on the way (`inbox.review` and `suggestions`, `identify.suggestions` and `cover_suggestion`, `analysis.decide_with`) take what is already loaded; called without it, they read it for that one track, so every other caller works as before. A track's page builds the list once and takes its position, its neighbours and its own row from it.

**The inbox check only queues work that's needed.** `identify.needing_lookup()` decides for the whole inbox in a few queries which tracks a lookup would actually ask a source for (no fresh answer for what Tagwerk would ask now) or download a cover for. It shares those rules with `lookup()`, so the two can't drift apart. The analysis reads all results in one query.

**After a check, the Inbox is built again only when the check changed something** (tracks added, changed or removed, imported or replaced automatically, old files removed from the inbox trash). Otherwise "Check again" comes back with a small "Nothing new".

**A job that ends while the list is read still updates the page.** The page notes which jobs (an inbox check, an import) were running when it read its list. If one ends before the page is sent, the page still asks once more, and is built again (with the "Imported …" message) as if it had waited for the job. A fast page made this race likely: the list read before an import, the page sent just after it.

**A test counts the queries** of the Inbox, a track's page and Home with 3 and with 12 inbox tracks: the numbers must be the same.

Not done, on purpose:
- **No stored summary table** refreshed in the background. Many things feed an inbox row (preferences, the library, online answers, analyses, the owner's values, secret marks, the files on disk). A missed refresh would show wrong numbers, which is worse than slow ones, and reading once is fast enough.
- **No second process.** The server answered other requests in a few milliseconds even while the Inbox was busy. Job state lives in the web process, so it stays one `uvicorn` worker ([architecture](../architecture.md)).
- The check still runs when the Inbox is opened after 10 seconds: it's cheap now.

## Consequences
- On a copy of the owner's inbox (330 tracks, 1,500 library tracks), building the list went from 1.2 s and 3,962 queries to about 0.1 s and 7 queries; a track's page from about 2.2 s to 0.1 s, Home from 1.2 s to 0.03 s. The rows and pages are the same as before.
- New per-track data an inbox row needs must be loaded in `load_known()`, or the query test fails.
- The browser still receives every row (the tabs filter in the browser, so ticks survive switching tabs): about 530 KB for 329 tracks, ~0.4 s to build the page. A lighter page is the next step if it's still too slow.
