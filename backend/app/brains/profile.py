"""Who a brain is living as: the identity a mind would get in its prompt (name, role, region, home ground, and who
among the people they know holds a title)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Routine = Literal[
    "lord",
    "samurai",
    "merchant",
    "farmer",
    "weaver",
    "town_child",
    "townsperson",
    "monk",
    "band_leader",
    "healer",
    "hunter",
    "gatherer",
    "band_child",
]
ROLE_ROUTINES: tuple[tuple[str, Routine], ...] = (  # first keyword found in the role picks the routine
    ("lord", "lord"),
    ("samurai", "samurai"),
    ("ashigaru", "samurai"),  # stub until the night watch: the samurai's rounds of the gates
    ("merchant", "merchant"),
    ("weaver", "weaver"),
    ("farmer's child", "town_child"),
    ("farmer", "farmer"),
    ("smith", "townsperson"),  # stubs until their trades: errands between the well and the market
    ("digger", "townsperson"),
    ("monk", "monk"),
    ("leader", "band_leader"),
    ("healer", "healer"),
    ("hunter", "hunter"),
)

Title = Literal["lord", "samurai", "ashigaru", "leader"]
TITLES: dict[Title, int] = {"lord": 5, "samurai": 4, "leader": 4, "ashigaru": 3}  # rank of each title (10 §3.2)
BOW_RANK = 4  # the lord, samurai and band leaders are bowed to by those they outrank


def title_of(role: str) -> Title | None:
    """The title a role holds, by its words ("samurai retainer" -> samurai, "band leader" -> leader)."""
    words = role.lower()
    return next((title for title in TITLES if title in words), None)


def known_titles(people: Iterable[tuple[str, str]]) -> tuple[tuple[str, Title], ...]:
    """Of the people someone knows, (name, role), those who hold a title, by name."""
    return tuple(sorted((name, title) for name, role in people if (title := title_of(role)) is not None))


@dataclass(frozen=True)
class BrainProfile:
    citizen_id: str
    name: str
    role: str
    region: Literal["town", "band_a", "band_b"]
    home_area: str  # the name of their home ground as they know it ("The castle town", "Band A camp")
    skills: tuple[str, ...] = ()  # what they know how to do ("hunting", "fire")
    titled: tuple[tuple[str, Title], ...] = ()  # people they know who hold a title ("Masanori", "lord")
    granary: bool = False  # town folk the lord's granary feeds (his household, and those he grants rice, §2.6)
    honesty: float = 0.5  # 0-1 (§3.1 traits): an honest starving soul is slower to take what isn't theirs

    def bows_to(self, name: str) -> bool:
        """They hold a title bowed to (lord, samurai, band leader) that outranks yours."""
        theirs = dict(self.titled).get(name)
        own = title_of(self.role)
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
