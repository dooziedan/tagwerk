"""Advanced tags on a track's edit page: every tag field of the file, to change, add or remove
(ADR 0039).

The edits become pending changes like every other edit (``changes.stage_raw``); app/writer.py
writes them when they are applied, with a snapshot for undo. A field that feeds a Tagwerk
field (TBPM feeds BPM) says so, and when both change, the normal field wins.
"""

from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.id3 import ID3

from app import writer
from app.models import PendingChange
from app.rawtags import SYSTEMS, TagField, fields, used_as
from app.tags import _riff_info_chunks

# Form fields: every value of a field is sent under the change field's name
# ("raw:id3:TXXX:fBPM"), ticked Remove boxes as REMOVE, added fields as NEW_*.
REMOVE = "raw_remove"
NEW_SYSTEM, NEW_NAME, NEW_VALUE = "raw_new_system", "raw_new_name", "raw_new_value"
# How a name typed for a new field is read (writer.new_raw_field), shown under "Add a field".
NAME_HINTS = {
    "id3": "ID3: a name of your own becomes TXXX:NAME; frames like TSRC or COMM:NAME work too.",
    "vorbis": "Vorbis: any name, e.g. MOOD (written in lower case, like Tagwerk lists them).",
    "mp4": "MP4: a name of your own becomes ----:com.apple.iTunes:NAME; atoms like ©grp work too.",
    "riff-info": "RIFF INFO: four letters, e.g. ISFT (software) or ICOP (copyright).",
}


@dataclass
class FileTags:
    """One file's tag fields, as Advanced tags needs them."""

    fields: list[TagField]
    systems: list[str]  # where a new field can go: ["id3"], ["id3", "riff-info"] (WAV), …
    id3_version: int | None = None  # 3 or 4 (3 for a file without tags: Tagwerk adds v2.3)

    @property
    def id3v23(self) -> bool:
        return self.id3_version == 3

    def by_field(self) -> dict[str, TagField]:
        return {writer.raw_field(f.system, f.name): f for f in self.fields}


def read(path: Path) -> FileTags:
    """Every tag field of a file, in full. Raises OSError or a mutagen error when the file
    can't be read."""
    audio = mutagen.File(path)
    if audio is None:
        raise OSError("not a recognized audio file")
    wav = type(audio).__name__ == "WAVE"
    riff = _riff_info_chunks(path) if wav else {}
    system = writer.tag_system(audio)
    version = None
    if system == "id3":
        version = audio.tags.version[1] if isinstance(audio.tags, ID3) else 3
    return FileTags(fields(audio, riff), [system, "riff-info"] if wav else [system], version)


@dataclass
class Row:
    """One field on the edit page."""

    field: str  # the change field, e.g. "raw:id3:TXXX:fBPM"
    system: str
    name: str
    exists: bool  # in the file (else added with a pending change, not written yet)
    in_file: list[str] | None  # its values in the file (None: not there, or not text)
    values: list[str]  # shown in the inputs: a pending change's values, else the file's
    text: bool  # holds text; other fields (pictures, private data …) can only be removed
    single: bool  # holds one value (no "+ value")
    shown: str  # the value as the track page shows it, for fields that aren't text
    used_as: str | None  # the Tagwerk field it feeds, e.g. "BPM"
    pending: PendingChange | None = None
    removing: bool = False  # ticked Remove, or a pending change removes it
    normal_pending: bool = False  # the field it feeds has a pending change, which wins


@dataclass
class Section:
    """Advanced tags of one track: its fields per tag system, and where new ones can go."""

    groups: list[tuple[str, list[Row]]]  # ("ID3v2.4", rows), ("RIFF INFO", rows)
    systems: list[tuple[str, str]]  # ("id3", "ID3") for the "add a field" choice
    new: list[tuple[str, str, str]] = field(default_factory=list)  # typed: system, name, value
    rows: list[Row] = field(default_factory=list)


def section(tags: FileTags, pending: dict[str, PendingChange], form=None) -> Section:
    """The rows for the edit page: the file's fields and pending additions, with pending
    values filled in. ``form``: a sent form shown again (with an error): its values."""
    found = tags.by_field()
    rows = [_row(name, f, pending.get(name)) for name, f in found.items()]
    for name, change in pending.items():  # added with Advanced tags, not written yet
        if name.startswith(writer.RAW) and name not in found:
            rows.append(_row(name, None, change))
    for row in rows:
        row.normal_pending = writer.feeds(row.field) in pending
    order = {system: i for i, system in enumerate(tags.systems)}
    rows.sort(key=lambda r: (order.get(r.system, len(order)), r.name.lower()))
    new = []
    if form is not None:
        removed = set(form.getlist(REMOVE))
        for row in rows:
            row.removing = row.field in removed
            if row.text and row.field in form:
                row.values = [str(v) for v in form.getlist(row.field)]
        new = list(zip(*(form.getlist(k) for k in (NEW_SYSTEM, NEW_NAME, NEW_VALUE)), strict=False))
    groups = []
    for system in dict.fromkeys(r.system for r in rows):
        title = SYSTEMS.get(system, system)
        if system == "id3" and tags.id3_version:
            title = f"ID3v2.{tags.id3_version}"
        groups.append((title, [r for r in rows if r.system == system]))
    systems = [(s, SYSTEMS[s]) for s in tags.systems]
    return Section(groups, systems, new, rows)


def _row(name: str, found: TagField | None, change: PendingChange | None) -> Row:
    """``found``: the field in the file; None for one added with a pending change."""
    system, raw_name = writer.raw_parts(name)
    in_file = found.values if found else None
    values = in_file or [""]
    if change is not None and change.new_value is not None:
        values = writer.raw_values(change.new_value)
    return Row(
        field=name,
        system=system,
        name=raw_name,
        exists=found is not None,
        in_file=in_file,
        values=values,
        text=found is None or found.values is not None,
        single=writer.holds_one_value(system, raw_name),
        shown=found.shown if found else "",
        used_as=used_as(system, raw_name),
        pending=change,
        removing=change is not None and change.new_value is None,
    )


def from_form(form, rows: list[Row], tags: FileTags) -> tuple[dict, list[int], dict[str, str]]:
    """What the Advanced tags part of a sent edit form asks for.

    Returns (values, discard, errors): ``values`` maps change fields to their texts (None:
    remove the field) for ``changes.stage_raw``; ``discard``: pending changes the form takes
    back (a field left as it is in the file); ``errors`` per field (for an added one "raw_new",
    and which row it is in "raw_new_row").
    """
    removed = set(form.getlist(REMOVE))
    values: dict[str, list[str] | None] = {}
    discard: list[int] = []
    for row in rows:
        if row.field in removed:
            values[row.field] = None
            continue
        posted = [str(v).replace("\r\n", "\n") for v in form.getlist(row.field)]
        if not row.text or (row.exists and posted == (row.in_file or [""])):
            if row.pending:  # left as it is in the file: a pending change is taken back
                discard.append(row.pending.id)
            continue
        values[row.field] = posted
    errors: dict[str, str] = {}
    known = {r.field for r in rows}
    typed = zip(*(form.getlist(k) for k in (NEW_SYSTEM, NEW_NAME, NEW_VALUE)), strict=False)
    for row, (system, name, value) in enumerate(typed):
        name, value = str(name), str(value).replace("\r\n", "\n")
        if not name.strip() and not value.strip():
            continue
        try:
            if str(system) not in tags.systems:
                raise ValueError("This file can't hold that kind of tag")
            new = writer.new_raw_field(str(system), name, tags.id3v23)
            if new in known:
                raise ValueError(f"{writer.raw_parts(new)[1]} is already there: change it above")
            if not value.strip():
                raise ValueError("Type a value for the new field")
        except ValueError as exc:
            if "raw_new" not in errors:  # the first one is shown, at its row
                errors |= {"raw_new": str(exc), "raw_new_row": str(row)}
            continue
        known.add(new)
        values[new] = [value]
    return values, discard, errors
