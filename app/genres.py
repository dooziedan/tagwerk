"""The genre map: spelling variants and subgenres -> main genre.

DJs file tracks by a main genre (the first value of the genre tag, which also picks the folder)
and keep the subgenre after it: ``Drum & Bass; Liquid``. The map lets Tagwerk
- unify spellings: ``DnB`` -> ``Drum & Bass``
- add the main genre to a track tagged only with a subgenre: ``Liquid`` -> ``Drum & Bass; Liquid``
- match store categories from online lookups: ``Jungle/Drum'n'bass`` -> ``Drum & Bass``
- know a genre's tempo, which settles half or double time: Drum & Bass is 174, never 87
  (app/tempo.py, ADR 0041)

The map is plain text, one rule per line; a genre may have several lines (Settings → Genre map):
    Drum & Bass = DnB, D&B, Drum and Bass     (spelling variants)
    Drum & Bass > Liquid, Neurofunk, Jungle   (subgenres)
    Drum & Bass: 160-185 BPM                  (tempo; subgenres share it)
Lookups are dictionary checks: no database, no network.
"""

import re
from dataclasses import dataclass, field
from functools import cached_property, lru_cache

DEFAULT_MAP = """\
Drum & Bass = DnB, D&B, D'n'B, Drum and Bass, Drum'n'Bass, Drum 'n' Bass, Drum N Bass
Drum & Bass = Drum&Bass, Drumnbass
Drum & Bass > Liquid, Liquid Funk, Liquid Drum & Bass, Neurofunk, Jump Up, Jungle
Drum & Bass > Dancefloor, Halftime, Rollers
House > Deep House, Funky House, Afro House, Soulful House, Jackin House, Progressive House
House > Bass House, Lo-Fi House, Organic House
Techno > Melodic Techno, Hard Techno, Peak Time Techno, Minimal Techno, Industrial Techno
Trance > Psytrance, Psy-Trance, Psy Trance, Progressive Trance, Uplifting Trance
Dubstep > Riddim, Brostep
Hip-Hop = Hip Hop, HipHop, Hip-Hop/Rap, Rap/Hip Hop
R&B = RnB, R'n'B, Rhythm and Blues, Rhythm & Blues
UK Garage = UKG, UK Garage / Bassline
Tech House = Techhouse
Nu Disco = Nu-Disco, Nudisco, Nu Disco / Disco
Drum & Bass: 160-185 BPM
Dubstep: 135-150 BPM
Footwork: 150-165 BPM
Juke: 150-165 BPM
Hardstyle: 145-160 BPM
Hip-Hop: 70-115 BPM
Rap: 70-115 BPM
R&B: 70-115 BPM
House: 110-150 BPM
Tech House: 110-150 BPM
Techno: 110-150 BPM
Trance: 110-150 BPM
Garage: 110-150 BPM
UK Garage: 110-150 BPM
Disco: 110-150 BPM
Nu Disco: 110-150 BPM
Electro: 110-150 BPM
Minimal: 110-150 BPM
Progressive: 110-150 BPM
"""

# "Drum & Bass: 160-185 BPM" (BPM optional, "160 - 185" fine).
_TEMPO_RULE = re.compile(r"^(.+?):\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:bpm)?$", re.I)


@dataclass
class GenreMap:
    spelling: dict[str, str] = field(default_factory=dict)  # lower-case variant -> genre
    main: dict[str, str] = field(default_factory=dict)  # lower-case subgenre -> main genre
    # Genre as written -> its usual BPM range, e.g. "Drum & Bass" -> (160, 185)
    tempo: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "GenreMap":
        result = cls()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if rule := _TEMPO_RULE.match(line):
                low, high = sorted((float(rule[2]), float(rule[3])))
                result.tempo[rule[1].strip()] = (low, high)
                continue
            for sep, target in (("=", result.spelling), (">", result.main)):
                if sep in line:
                    name, _, rest = line.partition(sep)
                    name = name.strip()
                    for item in rest.split(","):
                        if item.strip():
                            target[item.strip().lower()] = name
                    if sep == ">":
                        # subgenres are spelled as listed
                        for item in rest.split(","):
                            if item.strip():
                                result.spelling.setdefault(item.strip().lower(), item.strip())
                    break
        return result

    @staticmethod
    def rule_count(text: str) -> int:
        """How many rules the text has (lines that aren't empty or a # comment)."""
        lines = (line.strip() for line in text.splitlines())
        return sum(1 for line in lines if line and not line.startswith("#"))

    @staticmethod
    def problems(text: str) -> list[int]:
        """Line numbers that are neither a spelling rule (=), a subgenre rule (>) nor a tempo
        rule (Genre: 160-185 BPM)."""
        bad = []
        for number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#") or _TEMPO_RULE.match(line):
                continue
            sep = "=" if "=" in line else ">" if ">" in line else None
            if sep is None or not line.split(sep)[0].strip():
                bad.append(number)
        return bad

    def canonical(self, genre: str) -> str:
        return self.spelling.get(genre.strip().lower(), genre.strip())

    def key(self, genre: str) -> str:
        """What all spellings of a genre share: "Drum and Bass", "DnB" -> "drum & bass".

        Lower case only for A-Z, like SQLite's LIKE, so counts and the track list agree.
        """
        return "".join(c.lower() if c.isascii() else c for c in self.canonical(genre))

    def spellings(self, genre: str) -> list[str]:
        """Every spelling of a genre: ``Drum & Bass`` -> Drum & Bass, dnb, d&b, drum and bass, …"""
        name = self.canonical(genre)
        variants = [v for v, target in self.spelling.items() if target.lower() == name.lower()]
        return list(dict.fromkeys([name, *variants]))

    def tidy(self, genres: list[str]) -> list[str]:
        """Unified spelling, main genre first: ["DnB", "liquid"] -> ["Drum & Bass", "Liquid"]."""
        tidy = list(dict.fromkeys(self.canonical(g) for g in genres if g.strip()))
        if tidy:
            main = self.main.get(tidy[0].lower())
            if main:
                tidy = [main] + [g for g in tidy if g != main]  # the main genre goes first
        return tidy

    def main_genre(self, genre: str) -> str | None:
        """The main genre the map files a genre under: "DnB", "Liquid" -> "Drum & Bass".
        None when the map doesn't know the genre."""
        name = self.canonical(genre)
        if name.lower() in self.main:
            return self.main[name.lower()]
        known = {g.lower(): g for g in (*self.spelling.values(), *self.main.values())}
        return known.get(name.lower())

    def match(self, genre: str) -> str:
        """A genre from an online source, ready for the tag: "DnB" -> "Drum & Bass",
        "Liquid" -> "Drum & Bass; Liquid".

        Stores send their own categories, sometimes several genres in one: iTunes'
        "Jungle/Drum'n'bass". When the map doesn't know the whole name but knows every part,
        and all parts belong to the same main genre, the match is that main genre
        ("Drum & Bass"): the category means "one of these", not that the track is Jungle.
        Anything else is tidied like any genre.
        """
        whole = genre.strip().lower()
        parts = [part for part in genre.split("/") if part.strip()]
        if len(parts) > 1 and whole not in self.spelling and whole not in self.main:
            mains = {self.main_genre(part) for part in parts}
            if len(mains) == 1 and None not in mains:
                return mains.pop()
        return "; ".join(self.tidy([genre]))

    @cached_property
    def _tempo_by_name(self) -> dict[str, tuple[float, float]]:
        return {name.lower(): tempo for name, tempo in self.tempo.items()}

    @cached_property
    def _tempo_words(self) -> list[tuple[str, tuple[float, float]]]:
        """Every spelling and subgenre of a genre with a tempo, longest first."""
        words = {}
        for name, tempo in self.tempo.items():
            for spelling in self.spellings(name):
                words.setdefault(spelling.lower(), tempo)
        for sub, main in self.main.items():
            if main.lower() in self._tempo_by_name:
                words.setdefault(sub, self._tempo_by_name[main.lower()])
        return sorted(words.items(), key=lambda w: -len(w[0]))

    def tempo_of(self, genre: str | None) -> tuple[str, tuple[float, float]] | None:
        """(genre, BPM range) for the first genre of a tag that has a usual tempo:
        "Liquid; Dubstep" -> ("Liquid", (160, 185)), as Liquid is drum & bass.

        A genre has a tempo when its spelling, or the main genre the map files it under, has
        a tempo rule. Store categories like "Melodic House & Techno" match a tempo genre
        they contain as a whole word ("House"); "Electronic" is not "Electro"."""
        for part in re.split(r"[;,/]", genre or ""):
            part = part.strip()
            if not part:
                continue
            for name in (self.canonical(part), self.main_genre(part)):
                if name and name.lower() in self._tempo_by_name:
                    return part, self._tempo_by_name[name.lower()]
            for word, tempo in self._tempo_words:
                if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", part, re.I):
                    return part, tempo
        return None


DEFAULT = GenreMap.parse(DEFAULT_MAP)


@lru_cache(maxsize=8)
def from_text(text: str) -> GenreMap:
    """The owner's genre map (Settings → Genre map); the built-in one when empty. A map
    without any tempo rule (saved before Tagwerk knew them) keeps the built-in tempos."""
    if not text.strip():
        return DEFAULT
    result = GenreMap.parse(text)
    if not result.tempo:
        result.tempo = dict(DEFAULT.tempo)
    return result


def with_tempos(text: str) -> str:
    """The map as Settings shows it: the built-in one when empty; an own map saved before
    tempo rules existed gets the built-in tempo rules added, so the owner sees and can change
    the tempos it uses (from_text)."""
    if not text.strip():
        return DEFAULT_MAP
    if GenreMap.parse(text).tempo:
        return text
    tempos = [line for line in DEFAULT_MAP.splitlines() if _TEMPO_RULE.match(line)]
    return text.rstrip("\n") + "\n" + "\n".join(tempos) + "\n"


def active(session) -> GenreMap:
    """The genre map in use, from the preferences."""
    from app import preferences  # preferences imports the database layer

    return from_text(preferences.load(session).genre_map)
