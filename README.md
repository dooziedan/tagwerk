# Tagwerk

A self-hosted music library manager, built to run in Docker on Unraid next to Navidrome.

> **Status: early development (v0.3).** Scanning and the dashboards work. Editing, Navidrome and online lookups are next on the [roadmap](docs/roadmap.md).

## Features

- ✅ **Library scan:** reads MP3, FLAC, WAV, AIFF, M4A, OGG and Opus (ID3, Vorbis comments, MP4 tags, RIFF INFO), including BPM, key, comment, label, catalog number, ReplayGain and lyrics (embedded or `.lrc`). Read-only, and unchanged files are skipped on rescans.
- ✅ **Two modes**, switchable in the menu:
  - **DJ:** tempo spread, key grid (Camelot, Open Key or musical notation), BPM/key coverage, lossless share and low-bitrate files, missing BPM/key/label/comment.
  - **Collector:** decades, genres, albums, lyrics and ReplayGain coverage, missing album tags.
- ✅ **MusicBrainz checks are optional**, since edits, bootlegs and promos usually aren't on MusicBrainz.

Planned:

- **Tag editing:** one album or one track at a time.
- **MusicBrainz lookup:** tags and cover art filled in automatically, and every value stays editable.
- **Navidrome integration:** Navidrome's stats next to your library's, and a rescan triggered after changes.
- **Safe by design:** changes are staged, shown as *old → new*, and written only when you click Apply. The previous tags are kept so every change can be undone.

## Install on Unraid

1. Open the Unraid **Terminal** (top right `>_` icon) and download the template once:
   ```sh
   wget -O /boot/config/plugins/dockerMan/templates-user/my-tagwerk.xml \
     https://raw.githubusercontent.com/dooziedan/tagwerk/main/unraid/tagwerk.xml
   ```
2. Go to **Docker → Add Container**, choose **Tagwerk** in the *Template* dropdown (under user templates) and fill in:

   | Field | What to enter |
   |---|---|
   | **Music Library** (required) | Your music share, for example `/mnt/user/music`. Use the same folder as your Navidrome container. |
   | App Data | Leave the default `/mnt/user/appdata/tagwerk` |
   | WebUI Port | `8000`, or any free port |
   | PUID / PGID (advanced) | Leave Unraid's defaults `99` / `100` |

3. Click **Apply**, then open the WebUI. The start page checks that both folders are mounted correctly.

> **Back up your music before the first tag write.** Tagwerk keeps the old tags for undo, but a backup is the real safety net.

## Configuration

All settings are environment variables (the fields in the Unraid template):

| Variable | Default | Meaning |
|---|---|---|
| `MUSIC_DIR` | `/music` | Music library path inside the container |
| `CONFIG_DIR` | `/config` | Database and settings |
| `PUID` / `PGID` | `99` / `100` | User and group the app runs as |
| `UMASK` | `022` | Permission mask for new files |

## Documentation

- [Roadmap](docs/roadmap.md): the development phases
- [Architecture](docs/architecture.md): how the app is built
- [Development](docs/development.md): run it locally, tests, releases
- [Decisions](docs/decisions/): why things are the way they are
- [Changelog](CHANGELOG.md)

The REST API is documented at `/docs` on any running instance.

## License

[GNU AGPL-3.0-or-later](LICENSE). You may use, modify and share Tagwerk. If you distribute a modified version, or let others use one over a network, you must make its source code available under the same license.
