"""Who a brain is living as: the identity a mind would get in its prompt (name, role, region, home ground, and who
among the people they know holds a title)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.world_api.models import Compass

Routine = Literal[
    "lord",
    "samurai",
    "merchant",
    "farmer",
    "weaver",
    "town_child",
    "townsperson",
    "monk",
    "night_watch",
    "smith",
    "digger",
    "band_leader",
    "healer",
    "hunter",
    "gatherer",
    "band_child",
]
ROLE_ROUTINES: tuple[tuple[str, Routine], ...] = (  # first keyword found in the role picks the routine
    ("lord", "lord"),
    ("samurai", "samurai"),
    ("ashigaru", "night_watch"),
    ("merchant", "merchant"),
    ("weaver", "weaver"),
    ("farmer's child", "town_child"),
    ("farmer", "farmer"),
    ("smith", "smith"),
    ("digger", "digger"),
    ("monk", "monk"),
    ("leader", "band_leader"),
    ("healer", "healer"),
    ("hunter", "hunter"),
)

Title = Literal["lord", "samurai", "ashigaru", "leader"]
TITLES: dict[Title, int] = {"lord": 5, "samurai": 4, "leader": 4, "ashigaru": 3}  # rank of each title (10 §3.2)
BOW_RANK = 4  # the lord, samurai and band leaders are bowed to by those they outrank


def highest(titles: Iterable[Title]) -> Title | None:
    return max(titles, key=TITLES.__getitem__, default=None)


def known_titles(people: Iterable[tuple[str, Iterable[Title]]]) -> tuple[tuple[str, Title], ...]:
    """Of the people someone knows, (name, the titles they hold), those who hold one, by name, with its highest."""
    return tuple(sorted((name, title) for name, held in people if (title := highest(held)) is not None))


@dataclass(frozen=True)
class Ground:
    """A way from camp a band's food lies, and how many short walks on past the long walk out it stays clear of the
    dens the band knows of."""

    way: Compass
    legs: int


@dataclass(frozen=True)
class Spot:
    """A named place out in the band's land they know (a hotspot, 10 §1.2): how far it lies from camp, what can be
    taken there (its nodes' items, most first: "berries", "fish", "flint"), how much wild food it holds when full
    (berries, nuts and roots, pieces), the game whose hunting ground it is, and whose ground it is if claimed."""

    name: str  # as said mid-sentence and walked to ("the River marsh")
    metres: float
    goods: tuple[str, ...] = ()
    food: int = 0
    game: tuple[str, ...] = ()
    claim: Literal["town", "band_a", "band_b"] | None = None


@dataclass(frozen=True)
class BrainProfile:
    citizen_id: str
    name: str
    role: str
    region: Literal["town", "band_a", "band_b"]
    home_area: str  # the name of their home ground as they know it ("The castle town", "Band A camp")
    skills: tuple[str, ...] = ()  # what they know how to do ("hunting", "fire")
    titled: tuple[tuple[str, Title], ...] = ()  # people they know who hold a title ("Masanori", "lord")
    titles: tuple[Title, ...] = ()  # the titles they hold themselves
    granary: bool = False  # town folk the lord's granary feeds (his household, and those he grants rice, §2.6)
    honesty: float = 0.5  # 0-1 (§3.1 traits): an honest starving soul is slower to take what isn't theirs
    # bands: the ways from camp their land's food lies, beyond the thin home ring (10 §1.2), most first
    grounds: tuple[Ground, ...] = ()
    # town households (10 §1.4, §2.7): mouths fed from its chest, paddies it farms, and this citizen's share of its
    # dues a day, settled on court day (0: a child, or a household that owes none)
    household: int = 1
    paddies: int = 0
    dues: int = 0
    spots: tuple[Spot, ...] = ()  # bands: the hotspots they know, nearest first
    ring_ways: tuple[Compass, ...] = ()  # bands: the ways from camp the home ring's food lies, most first
    # band hunters: the hunting grounds they know in the order they take them, day by day (each hunter of a band
    # starts at a different one, so they spread over the herds)
    hunting_grounds: tuple[str, ...] = ()
    # band hunters with no ground of their own but the grass round camp: their turn among the band's hunters (turn,
    # of), so one hunts it a day and its one herd isn't taken down
    hunt_turn: tuple[int, int] = (0, 1)

    def bows_to(self, name: str) -> bool:
        """They hold a title bowed to (lord, samurai, band leader) that outranks yours."""
        theirs = dict(self.titled).get(name)
        own = highest(self.titles)
        return theirs is not None and TITLES[theirs] >= BOW_RANK and TITLES[theirs] > (TITLES[own] if own else 0)

    def officer(self, name: str) -> bool:
        """They hold a title: someone to bring a wrong to (the lord, a samurai, an ashigaru, a band leader)."""
        return name in dict(self.titled)

    @property
    def routine(self) -> Routine:
        role = self.role.lower()
        found = next((routine for word, routine in ROLE_ROUTINES if word in role), None)
        if found is not None:
            return found
        if self.region == "town":
            return "town_child" if "child" in role else "townsperson"
        return "band_child" if "child" in role else "gatherer"
