"""Reading a perception the way a person would: the in-world words of `world_api` turned into what a scripted brain
weighs (how hungry, what time of day, what food is around and how far). Nothing here reaches past the contract.
"""

from dataclasses import dataclass
from typing import Literal

from app.world_api.models import Perception, Seen

Phase = Literal["night", "morning", "day", "dusk"]
Distance = Literal["here", "near", "close", "off", "far"]

PHASES: dict[str, Phase] = {
    "the middle of the night": "night",
    "the dark before dawn": "night",
    "night": "night",
    "dawn; the sun is rising": "morning",
    "early morning": "morning",
    "mid-morning": "day",
    "around midday; the sun is high": "day",
    "early afternoon": "day",
    "late afternoon": "day",
    "the sun is about to set": "dusk",
    "dusk": "dusk",
}
AFTERNOON = frozenset({"early afternoon", "late afternoon"})
# How filling a piece of each food is, as a person knows from eating it (names as the world says them).
FOOD_VALUE: dict[str, float] = {"rice": 10.0, "dried meat": 8.0, "roots": 6.0, "nuts": 3.0, "berries": 2.0}
FOOD_ONE: dict[str, str] = {
    "rice": "measure of rice",
    "dried meat": "strip of dried meat",
    "roots": "a root",
    "nuts": "a nut",
    "berries": "a berry",
}
AMOUNT: tuple[tuple[str, int], ...] = (
    ("a great", 50),
    ("plenty of", 25),
    ("a handful of", 8),
    ("some", 8),
    ("a few", 2),
    ("a little", 2),
)
RESOURCE_WORDS: tuple[tuple[str, str], ...] = (
    ("berr", "berries"),
    ("root", "roots"),
    ("nut", "nuts"),
    ("reed", "reeds"),
    ("wood", "wood"),
)
NEAR: tuple[tuple[str, Distance], ...] = (
    ("right beside you", "here"),
    ("a few paces", "near"),
    ("close by", "close"),
    ("some way off", "off"),
)


@dataclass(frozen=True)
class Needs:
    """0 fine, 1 a little, 2 clearly, 3 badly (from the body words)."""

    hunger: int
    thirst: int
    tiredness: int

    @classmethod
    def read(cls, feeling: list[str]) -> "Needs":
        words = set(feeling)

        def level(bad: str, clear: str, little: str) -> int:
            return 3 if bad in words else 2 if clear in words else 1 if little in words else 0

        return cls(
            hunger=level("starving", "hungry", "a little hungry"),
            thirst=level("terribly thirsty", "thirsty", "a little thirsty"),
            tiredness=level("exhausted", "tired", "a little tired"),
        )


@dataclass(frozen=True)
class Resource:
    kind: str  # berries, roots, nuts, reeds, wood
    distance: Distance
    plenty: bool


def phase(perception: Perception) -> Phase:
    return PHASES[perception.time]


def afternoon(perception: Perception) -> bool:
    return perception.time in AFTERNOON


def distance(where: str) -> Distance:
    return next((rank for prefix, rank in NEAR if where.startswith(prefix)), "far")


def carried_food(perception: Perception) -> dict[str, int]:
    """Rough counts of the food carried ("a handful of roots" -> roots: 8)."""
    food: dict[str, int] = {}
    for line in perception.you.carrying:
        for name, one in FOOD_ONE.items():
            if line.endswith(f" {name}") or line == one or line.endswith(one):
                count = next((amount for words, amount in AMOUNT if line.startswith(words)), 1)
                food[name] = food.get(name, 0) + count
                break
    return food


def carries(perception: Perception, item: str) -> bool:
    return any(line.endswith(f" {item}") or line.endswith(item.rstrip("s")) for line in perception.you.carrying)


def food_value(food: dict[str, int]) -> float:
    return sum(FOOD_VALUE[name] * count for name, count in food.items())


def resources_in_view(perception: Perception) -> list[Resource]:
    found: list[Resource] = []
    for thing in perception.things:
        if thing.label.endswith("on the ground"):
            continue
        kind = next((name for stem, name in RESOURCE_WORDS if stem in thing.label), None)
        if kind is not None:
            plenty = not thing.label.startswith(("a few", "a little"))
            found.append(Resource(kind, distance(thing.where), plenty))
    return found


def sees_thing(perception: Perception, label: str) -> Seen | None:
    return next((thing for thing in perception.things if thing.label == label), None)


def water_here(perception: Perception) -> bool:
    return any(
        thing.label in ("a river", "a lake", "the well") and distance(thing.where) == "here"
        for thing in perception.things
    )


def water_in_view(perception: Perception) -> bool:
    return any(thing.label in ("a river", "a lake") for thing in perception.things)


def is_name(label: str) -> bool:
    """People you know are seen by name; strangers by how they look ("a man in a straw hat")."""
    return not label.startswith(("a ", "an ", "the "))


def at(perception: Perception, place: str) -> bool:
    return f"at {place}" in perception.place or f"in {place}" in perception.place


def at_home(perception: Perception) -> bool:
    return perception.place.startswith("at your home")


def near(perception: Perception, area: str) -> bool:
    """In or not far from a known place (perception names the nearest known place within a few hundred paces)."""
    return at(perception, area) or f"not far from {area}" in perception.place
