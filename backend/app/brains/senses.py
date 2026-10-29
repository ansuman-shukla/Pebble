"""Reading a perception the way a person would: the in-world words of `world_api` turned into what a scripted brain
weighs (how hungry, what time of day, what food is around and how far). Nothing here reaches past the contract.
"""

from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import JsonValue

from app.world_api.models import Compass, Nearness, Perception, ResourceName, Seen, SelfView, TimeOfDay

Phase = Literal["night", "morning", "day", "dusk"]
Distance = Literal["here", "near", "close", "off", "far"]

PHASES: dict[TimeOfDay, Phase] = {
    "pre-dawn": "night",
    "night": "night",
    "dawn": "morning",
    "early morning": "morning",
    "mid-morning": "day",
    "midday": "day",
    "early afternoon": "day",
    "late afternoon": "day",
    "sunset": "dusk",
    "dusk": "dusk",
}
AFTERNOON: frozenset[TimeOfDay] = frozenset({"early afternoon", "late afternoon"})
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
DISTANCE: dict[Nearness, Distance] = {
    "right beside you": "here",
    "a few paces": "near",
    "close by": "close",
    "some way off": "off",
    "in the distance": "far",
    "far away": "far",
}


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
FIRE_STATES: dict[str, "FireState"] = {  # how a fire is told burning (its `doing`)
    "burning": "burning",
    "burning low": "low",
    "glowing embers": "low",
    "cold": "out",
}
FireState = Literal["burning", "low", "out"]


@dataclass(frozen=True)
class Resource:
    kind: ResourceName
    distance: Distance
    plenty: bool


def phase(perception: Perception) -> Phase:
    return PHASES[perception.time_of_day]


def afternoon(perception: Perception) -> bool:
    return perception.time_of_day in AFTERNOON


def beside(seen: Seen) -> bool:
    """Right beside you or a few paces off: close enough to sit by or put something down at."""
    return DISTANCE[seen.nearness] in ("here", "near")


def carried_food(you: SelfView) -> dict[str, int]:
    """Rough counts of the food carried ("a handful of roots" -> roots: 8)."""
    food: dict[str, int] = {}
    for line in you.carrying:
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
    """Wild plants in view (a plant's words say whether there's plenty: "a few nuts on the trees" is not)."""
    return [
        Resource(thing.resource, DISTANCE[thing.nearness], not thing.label.startswith(("a few", "a little")))
        for thing in perception.things
        if thing.resource is not None
    ]


def fire_in_view(perception: Perception) -> Seen | None:
    return next((thing for thing in perception.things if thing.kind == "fire"), None)


def water_here(perception: Perception) -> bool:
    return any(thing.kind == "water" and DISTANCE[thing.nearness] == "here" for thing in perception.things)


def water_in_view(perception: Perception) -> bool:
    return any(thing.kind == "water" for thing in perception.things)


def water_way(perception: Perception) -> Compass | None:
    """Which way the nearest fresh water in view lies ("close by to the north" -> north); None if none is in view."""
    water = next((thing for thing in perception.things if thing.kind == "water"), None)
    if water is None:
        return None
    return next((way for way in get_args(Compass) if water.where.endswith(f"to the {way}")), None)


def compass_word(note: JsonValue) -> Compass | None:
    """A direction a brain noted down, read back."""
    return next((way for way in get_args(Compass) if way == note), None)


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
    """How the best fire within a few paces burns ("out" for a cold one), or None if there's no fire here."""
    states = [
        FIRE_STATES.get(thing.doing or "cold", "out")
        for thing in perception.things
        if thing.kind == "fire" and beside(thing)
    ]
    for state in ("burning", "low", "out"):
        if state in states:
            return state
    return None


def wood_at_hand(perception: Perception) -> bool:
    """Carrying wood, or wood lies on the ground close at hand (a fire's woodpile)."""
    return carries(perception, "wood") or any(
        thing.label.endswith("wood on the ground") and beside(thing) for thing in perception.things
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
