"""The genre map: spelling variants and subgenres -> main genre.

DJs file tracks by a main genre (the first value of the genre tag, which also picks the folder)
and keep the subgenre after it: ``Drum & Bass; Liquid``. The map lets Tagwerk
- unify spellings: ``DnB`` -> ``Drum & Bass``
- add the main genre to a track tagged only with a subgenre: ``Liquid`` -> ``Drum & Bass; Liquid``

The map is plain text, one rule per line; a genre may have several lines (editable in
Settings later):
    Drum & Bass = DnB, D&B, Drum and Bass     (spelling variants)
    Drum & Bass > Liquid, Neurofunk, Jungle   (subgenres)
Lookups are dictionary checks: no database, no network.
"""

from dataclasses import dataclass, field
from functools import lru_cache

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
"""


@dataclass
class GenreMap:
    spelling: dict[str, str] = field(default_factory=dict)  # lower-case variant -> genre
    main: dict[str, str] = field(default_factory=dict)  # lower-case subgenre -> main genre

    @classmethod
    def parse(cls, text: str) -> "GenreMap":
        result = cls()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
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
        """Line numbers that are neither a spelling rule (=) nor a subgenre rule (>)."""
        bad = []
        for number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            sep = "=" if "=" in line else ">" if ">" in line else None
            if sep is None or not line.split(sep)[0].strip():
                bad.append(number)
        return bad

    def canonical(self, genre: str) -> str:
        return self.spelling.get(genre.strip().lower(), genre.strip())

    def tidy(self, genres: list[str]) -> list[str]:
        """Unified spelling, main genre first: ["DnB", "liquid"] -> ["Drum & Bass", "Liquid"]."""
        tidy = list(dict.fromkeys(self.canonical(g) for g in genres if g.strip()))
        if tidy:
            main = self.main.get(tidy[0].lower())
            if main:
                tidy = [main] + [g for g in tidy if g != main]  # the main genre goes first
        return tidy


DEFAULT = GenreMap.parse(DEFAULT_MAP)


@lru_cache(maxsize=8)
def from_text(text: str) -> GenreMap:
    """The owner's genre map (Settings → Genre map); the built-in one when empty."""
    return GenreMap.parse(text) if text.strip() else DEFAULT


def active(session) -> GenreMap:
    """The genre map in use, from the preferences."""
    from app import preferences  # preferences imports the database layer

    return from_text(preferences.load(session).genre_map)
