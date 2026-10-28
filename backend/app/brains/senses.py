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
FOOD_VALUE: dict[str, float] = {
    "rice": 10.0,
    "dried meat": 8.0,
    "meat": 10.0,
    "fish": 6.0,
    "roots": 6.0,
    "nuts": 3.0,
    "berries": 2.0,
}
FOOD_ONE: dict[str, str] = {  # "dried meat" before "meat": the longer name wins
    "rice": "measure of rice",
    "dried meat": "strip of dried meat",
    "meat": "piece of meat",
    "fish": "a fish",
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


DANGER_WORDS = ("wolf", "wolves", "bear", "lion", "shark")  # animals everyone knows can kill
THREAT_DOING = frozenset({"coming at you", "watching you"})
GAME_WORDS: tuple[tuple[str, str], ...] = (  # (word in what is seen, what a hunter calls it)
    ("deer", "deer"),
    ("elk", "elk"),
    ("antelope", "antelope"),
    ("boar", "boar"),
    ("goat", "goat"),
    ("rabbit", "rabbit"),
    ("hare", "hare"),
    ("duck", "duck"),
)
FIRE_BURNING = frozenset({"a campfire burning", "a fire basket burning"})
FIRE_LOW = frozenset({"a campfire burning low", "embers glowing", "a fire basket burning low", "a fire basket glowing"})
FIRE_COLD = frozenset({"a cold campfire", "a cold fire basket"})
BESIDE = ("right beside you", "a few paces")
FireState = Literal["burning", "low", "out"]


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


def carried_count(perception: Perception, item: str) -> int:
    """About how many of an item they carry ("plenty of wood" -> 25, "a piece of wood" -> 1)."""
    for line in perception.you.carrying:
        if line.endswith(f" {item}"):
            return next((amount for words, amount in AMOUNT if line.startswith(words)), 1)
    return 0


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


def danger(perception: Perception) -> Seen | None:
    """A dangerous animal coming at you or watching you (asleep or far off it's no reason to run)."""
    return next(
        (
            animal
            for animal in perception.animals
            if animal.doing in THREAT_DOING and any(word in animal.label for word in DANGER_WORDS)
        ),
        None,
    )


def game(perception: Perception) -> list[tuple[str, Seen]]:
    """Animals worth hunting in view, nearest first: (what to call it, how it is seen)."""
    found: list[tuple[str, Seen]] = []
    for animal in perception.animals:
        if animal.label.startswith("the remains"):
            continue
        name = next((call for word, call in GAME_WORDS if word in animal.label), None)
        if name is not None:
            found.append((name, animal))
    return found


def fire_here(perception: Perception) -> FireState | None:
    """The state of a fire within a few paces (a cold fire pit counts as out), or None if there's none here."""
    beside = [thing.label for thing in perception.things if thing.where.startswith(BESIDE)]
    if any(label in FIRE_BURNING for label in beside):
        return "burning"
    if any(label in FIRE_LOW for label in beside):
        return "low"
    if any(label in FIRE_COLD or label == "the fire pit" for label in beside):
        return "out"
    return None


def wood_at_hand(perception: Perception) -> bool:
    """Carrying wood, or wood lies on the ground right here."""
    return carries(perception, "wood") or any(
        thing.label.endswith("wood on the ground") and thing.where.startswith("right beside you")
        for thing in perception.things
    )


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
