"""What Tagwerk would change on an inbox track, worked out from its filename and tags.

Pure functions, no storage: proposals are recalculated whenever they're shown (string work,
microseconds per track). Tags already in the file win; a proposal only fills an empty field or
tidies an existing value. Every proposal says where it comes from and whether Tagwerk is
**sure** or the owner should **check** it.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app import writer
from app.genres import DEFAULT, GenreMap
from app.keys import to_camelot


@dataclass
class Proposal:
    field: str  # a key of writer.EDITABLE
    value: str  # in the form's format, e.g. "Am", "Drum & Bass; Liquid"
    current: str | None  # the value in the file now
    source: str  # "filename" or "clean-up"
    sure: bool  # False: plausible, but the owner should check it
    reason: str = ""  # what a clean-up changes, e.g. "spacing", "genre spelling"

    @property
    def label(self) -> str:
        return writer.EDITABLE[self.field]


@dataclass
class ParsedName:
    artist: str | None = None
    title: str | None = None
    bpm: str | None = None
    key: str | None = None
    sure: bool = False  # the name had the clear "Artist - Title" shape


# --- Filenames ------------------------------------------------------------------------------

_TRACK_NUMBER = re.compile(r"^(?:\d{1,3}\s*[.)]|\d{1,3}\s+-|[A-D]\d\s*[.)-]|\d{2,3}\s)\s*")
_BPM = re.compile(r"[\[(]?\b(\d{2,3}(?:[.,]\d+)?)\s*bpm\b[\])]?", re.I)
_BRACKETS = re.compile(r"\[([^\]]*)\]")  # [128 8A], [Liquid], [Label] ...
_CAMELOT = re.compile(r"^(?:1[0-2]|[1-9])[AB]$", re.I)
_SPLIT = re.compile(r"\s+[-–—]\s+")
_FEAT = re.compile(r"(?<![\w.])(?:ft\.?|feat\.?|featuring)(?=\s)", re.I)
# Words that make a bracket part of the title: "[Carvalho Drunk Mix]" -> "(Carvalho Drunk Mix)".
_MIX_WORDS = re.compile(
    r"\b(?:mix|edit|remix|rmx|vip|bootleg|mashup|rework|refix|flip|dub|version|remake|blend"
    r"|intro|extended|radio|clean|dirty|acapella|instrumental)\b",
    re.I,
)
_TRAILING_NUMBER = re.compile(r"^(.*\S)\s+(\d{2,3}(?:[.,]\d+)?)$")  # "Body (Zillionaire Edit) 126"
# Track types inside brackets, always written with a capital letter (MusicBrainz writes
# "(Club remix)"; DJs and stores write "(Club Remix)"). Values: how the word is written.
MIX_TYPES = {
    w.lower(): w
    for w in [
        "Mix",
        "Remix",
        "Edit",
        "Re-Edit",
        "Bootleg",
        "Rework",
        "Refix",
        "Flip",
        "Dub",
        "Version",
        "Remake",
        "Blend",
        "Mashup",
        "Intro",
        "Outro",
        "Extended",
        "Radio",
        "Club",
        "Original",
        "Clean",
        "Dirty",
        "Instrumental",
        "Acapella",
        "Vocal",
        "Short",
        "Long",
        "Remaster",
        "Remastered",
        "Live",
        "Cut",
        "Reprise",
        "VIP",
        "RMX",
    ]
}
_BRACKETED = re.compile(r"[(\[][^()\[\]]*[)\]]")
# Kept as written when a name in CAPITALS or lower case gets normal capitalisation.
_KEEP_CASE = {"dj", "vip", "mc", "uk", "usa", "ep", "lp", "ii", "iii", "iv", "rmx", "feat."}


def parse_filename(path: str) -> ParsedName:
    """Artist, title, BPM and key from names like "01. Artist - Title (Extended Mix) [128 8A]"."""
    name = PurePosixPath(path).stem
    result = ParsedName()
    underscores = " " not in name and "_" in name
    if underscores:
        name = name.replace("_", " ")
    name = _TRACK_NUMBER.sub("", " ".join(name.split()))

    bpm = _BPM.search(name)
    if bpm:
        value = float(bpm.group(1).replace(",", "."))
        if 60 <= value <= 200:
            result.bpm = f"{value:g}"
        name = name[: bpm.start()] + name[bpm.end() :]

    def bracket(match: re.Match) -> str:
        """Square brackets hold a mix name ("[Carvalho Drunk Mix]": kept as "(...)") or extras
        ("[128 8A]", "[Ram Records]": BPM/key are taken, the rest is dropped)."""
        if _MIX_WORDS.search(match.group(1)):
            return f"({match.group(1).strip()})"
        for word in match.group(1).split():
            if _CAMELOT.match(word) or (len(word) <= 3 and to_camelot(word)):
                result.key = result.key or writer.normalize("key", word)
            elif re.fullmatch(r"\d{2,3}", word) and 60 <= int(word) <= 200:
                result.bpm = result.bpm or word
        return ""

    name = _BRACKETS.sub(bracket, name)
    trailing_key = re.search(r"\s((?:1[0-2]|[1-9])[AB])$", name)  # "... 128bpm 8A"
    if trailing_key:
        result.key = result.key or writer.normalize("key", trailing_key.group(1))
        name = name[: trailing_key.start()]
    name = re.sub(r"\(\s*\)|\[\s*\]", "", name)  # brackets left empty
    name = tidy_text(name.strip(" -–—_."))
    number = _TRAILING_NUMBER.match(name)  # "Artist - Title (Edit) 124": a BPM after the mix name
    if number and number.group(1).endswith(")") and 60 <= float(number.group(2)) <= 200:
        result.bpm = result.bpm or number.group(2)
        name = number.group(1)
    recased = _normal_case(name)

    recased = capitalise_mix_types(recased)
    parts = _SPLIT.split(recased, maxsplit=1)
    if len(parts) == 2 and all(parts):
        result.artist, result.title = parts
        result.sure = not underscores and recased == name
    elif recased:
        result.title = recased  # no artist in the name: only a guess
    return result


def _normal_case(text: str) -> str:
    """ "BILLIE JEAN (CARVALHO MIX)" or "fall down tonight" -> "Billie Jean (Carvalho Mix)".

    Only for names written entirely in capitals or lower case; mixed case is left alone.
    """
    letters = [c for c in re.sub(r"\bv\d+\b", "", text, flags=re.I) if c.isalpha()]  # not "v2"
    if not letters or not (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
        return text

    def word(w: str) -> str:
        core = w.strip("()[]")
        if core.lower() in _KEEP_CASE:
            return w.replace(core, core.upper() if core.lower() != "feat." else "feat.")
        if re.fullmatch(r"v\d+", core, re.I):  # version marker "v2"
            return w.lower()
        return re.sub(r"[A-Za-z]", lambda m: m.group(0).upper(), w.lower(), count=1)

    return " ".join(word(w) for w in text.split())


def _tidy_title(track, artist: str | None) -> tuple[str, list[str]]:
    """A title tag without stray extras: "Haddaway - What is Love" or "Body (Edit) 126"."""
    title, reasons = tidy_text(track.title), []
    if title != track.title:
        reasons.append(_text_reason(track.title))
    typed = capitalise_mix_types(title)
    if typed != title:
        title = typed
        reasons.append("mix type capitalised")
    if artist and title.lower().startswith(artist.lower()) and _SPLIT.match(title[len(artist) :]):
        title = _SPLIT.split(title, maxsplit=1)[1]
        reasons.append("artist removed from title")
    number = _TRAILING_NUMBER.match(title)
    if number and track.bpm and abs(float(number.group(2).replace(",", ".")) - track.bpm) < 1:
        title = number.group(1)
        reasons.append("BPM removed from title")
    return title, reasons


def _text_reason(value: str) -> str:
    return "spacing" if " ".join(value.split()) != value else '"feat." spelling'


def capitalise_mix_types(title: str) -> str:
    """ "Rio (club remix) [vip]" -> "Rio (Club Remix) [VIP]". Remixer names stay as written."""

    def fix(match: re.Match) -> str:
        return re.sub(
            r"[\w'-]+",
            lambda w: MIX_TYPES.get(w.group(0).lower(), w.group(0)),
            match.group(0),
        )

    return _BRACKETED.sub(fix, title)


def tidy_text(value: str) -> str:
    """Single spaces, and "ft." / "featuring" written as "feat."."""
    return _FEAT.sub("feat.", " ".join(value.split()))


# --- Proposals ------------------------------------------------------------------------------


def propose(track, genres: GenreMap = DEFAULT) -> list[Proposal]:
    """Proposals for one inbox track, in form order."""
    if track.error:
        return []
    found: dict[str, Proposal] = {}

    def add(field: str, value: str | None, source: str, sure: bool, reason: str = "") -> None:
        if not value or field in found:
            return
        try:
            value = writer.normalize(field, value)
        except ValueError:
            return
        current = writer.current_value(track, field)
        if value and value != current:
            found[field] = Proposal(field, value, current, source, sure, reason)

    name = parse_filename(track.path)

    # Clean-up of values already in the file comes first: the file's tags win.
    if track.title:
        title, reasons = _tidy_title(track, track.artist or name.artist)
        add("title", title, "clean-up", True, ", ".join(reasons))
        if not track.artist and title != tidy_text(track.title):
            add("artist", name.artist or track.title.split(" - ")[0], "clean-up", True,
                "taken from the title")  # fmt: skip
    for field in ("artist", "albumartist", "album", "label"):
        value = getattr(track, field)
        if value:
            add(field, tidy_text(value), "clean-up", True, _text_reason(value))
    if track.genre:
        before = [g.strip() for g in track.genre.split(";") if g.strip()]
        after = genres.tidy(before)
        if len(after) > len(before):
            reason = "main genre added"
        elif [g.lower() for g in after] != [genres.canonical(g).lower() for g in before]:
            reason = "main genre first"
        else:
            reason = "genre spelling"
        add("genre", "; ".join(after), "clean-up", True, reason)

    # The filename fills what's still empty.
    if not track.artist:
        add("artist", name.artist, "filename", name.sure)
    if not track.title:
        add("title", name.title, "filename", name.sure)
    if not track.bpm:
        add("bpm", name.bpm, "filename", True)
    if not track.key_camelot:
        add("key", name.key, "filename", True)

    order = list(writer.EDITABLE)
    return sorted(found.values(), key=lambda p: order.index(p.field))


def still_missing(track, proposals: list[Proposal]) -> list[str]:
    """What the track lacks even after the proposals (shown as "still missing")."""
    if track.error:
        return ["Unreadable"]
    proposed = {p.field for p in proposals}
    checks = {
        "Title": track.title or "title" in proposed,
        "Artist": track.artist or "artist" in proposed,
        "Genre": track.genre or "genre" in proposed,
        "BPM": track.bpm or "bpm" in proposed,
        "Key": track.key_camelot or "key" in proposed,
        "Cover": track.has_cover,
    }
    return [name for name, ok in checks.items() if not ok]
