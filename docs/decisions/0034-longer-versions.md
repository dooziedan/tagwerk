# 0034: Longer versions: Beatport, Discogs tracklists, and recognising club mixes
Date: 2026-10-11 · Status: Accepted · Changes part of [0014](0014-online-identification.md)

## Context
DJs play the long versions. Billy Kenny's "Take Me To Church" is 4:09 on iTunes, Deezer and MusicBrainz, but the Original Mix the owner buys on Beatport is 5:26. Tagwerk's scoring rightly refused the 4:09 results (a different edit), so it found nothing to check a club version against: none of the sources sold it.

Where long versions can be found (checked 2026-10-11 with this track and the D&B reference tracks):
- **Beatport** has every one of them, each version with its own length, mix name, BPM, key, genre, label and ISRC; its keys matched the owner-confirmed keys of all four reference tracks. Its API is only for approved partners (no keys for individuals), but the public search page carries the results as JSON. Beatport's terms (updated 2026-10-08) allow personal, non-commercial use and have no clause against automated reading; robots.txt allows every page.
- **Discogs** often lists the digital release with each version and its length (Fisher "Losing It": Radio Edit 2:43, Original 4:08, Extended 6:40); fewer recent D&B releases. Tagwerk already asks Discogs, but only read the search, which has no tracks.
- **Deezer, iTunes, MusicBrainz** mostly have the radio edit. Deezer's search with a length range no longer works.
- **Traxsource, Juno Download** refuse requests that don't come from a browser. Spotify, Apple Music and TIDAL need developer accounts and mostly carry the streaming edits too.

## Decision
- **Beatport becomes a source** (`app/sources/beatport.py`): one request to the public search page per lookup, two seconds apart, no account. It reads the page's JSON and translates every track found there: title with the mix name ("Take Me to Church (Original Mix)"), artists without Beatport's tell-apart marks ("FISHER (OZ)" → "FISHER"), release, date, genre, label, catalog number (not when it is a barcode), BPM, key, length and cover. When the page can't be read, the source says "Beatport changed its page" instead of guessing. On by default for new installs; existing installs switch it on in Settings → Online lookups.
- **Discogs reads the tracklist** of its two best releases (one request each): every track whose title starts with the file's title, without brackets, becomes its own candidate with its own title and length. It is the same answer that gives the artist IDs and the Discogs track ID ([ADR 0033](0033-discogs-track-ids.md)), asked once per lookup; when it fails, the release's search answer stays, without versions. Discogs' tell-apart numbers ("Fisher (16)") are dropped from artists.
- **"(Original Mix)" and "(Original)" mean the plain title** when candidates are scored: stores call the plain version that. Not for IDs: a Discogs track ID found without a length still needs exactly the same title ([ADR 0033](0033-discogs-track-ids.md)).
- **Recognising a longer version** (`identify.longer_version`): when some sources only have the same track (same title apart from version words, same artist) more than 10 s shorter than the file (a source that also has a longer version doesn't count), the Online sources card says so ("Longer version") and names the sources that list a version of the file's length, with its mix name: "MusicBrainz, Deezer and iTunes only have a 4:09 version. Discogs and Beatport list this 5:26 version (Original Mix)." Without such a source it says "maybe an extended or club mix; no source lists this length yet". Other remixes don't count as shorter versions. Version words are only the generic ones at the end of a title (original, extended, radio, club, single, album, short, mix, edit, version): stores use them loosely (Beatport's "Original Mix" is often the long one, a "Radio Mix" is usually the "Radio Edit"), so the length decides, not the name. A remixer's or editor's name keeps a title apart.
- Values follow the usual rules (ADR 0014): only the matching version's values are used, and a value is sure when two sources agree. In the example Beatport and Discogs agree on label, genre and year.
- **BPM and key**: Beatport's key joins the filename and the tag as a hint for the audio analysis (ADR 0017), like the stores' BPM already did. A library track whose audio was analysed gets **no BPM staged from online sources**: two stores agreeing on 87 doesn't make a drum & bass track 87 BPM; the audio decides, with the stores as hints.

## Consequences
- Club versions bought on Beatport are now found and confirmed; edits and bootlegs still aren't.
- Beatport may change its page at any time; then the source shows an error until Tagwerk is updated, and the other sources work on. If Beatport ever offers API keys to individuals, the source switches to the API.
- A lookup takes a few seconds longer (Beatport plus two Discogs tracklists).
- Only artist and title leave the server, as before.
