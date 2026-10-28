"""The mutable world state: citizens, items, resource counters and random streams (plain dataclasses).

Everything here is in a snapshot (`app.sim.snapshot`); nothing else in the simulation changes over time.
"""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from app.core.rng import Rng
from app.sim.navigation import Route
from app.sim.vec import Vec3
from app.world_api.models import ActionName, ActionResult, Volume

AgeGroup = Literal["child", "teen", "young_adult", "middle_aged", "elder"]
KnowledgeLevel = Literal["visited", "rough"]
JsonScalar = str | int | float | bool | None
RNG_STREAMS = ("ecology", "actions")


@dataclass(frozen=True)
class AgeTraits:
    speed: float
    strength: float
    carry_kg: float
    need_rate: float  # hunger and thirst multiplier


# 02-simulation; need rates are ours (the doc names the effect but gives no numbers).
AGE_GROUPS: dict[AgeGroup, AgeTraits] = {
    "child": AgeTraits(speed=0.7, strength=0.3, carry_kg=5.0, need_rate=0.8),
    "teen": AgeTraits(speed=1.0, strength=0.7, carry_kg=15.0, need_rate=1.1),
    "young_adult": AgeTraits(speed=1.0, strength=1.0, carry_kg=25.0, need_rate=1.0),
    "middle_aged": AgeTraits(speed=0.9, strength=0.9, carry_kg=25.0, need_rate=1.0),
    "elder": AgeTraits(speed=0.6, strength=0.5, carry_kg=10.0, need_rate=0.9),
}


def age_group(age: int) -> AgeGroup:
    if age < 5:
        raise ValueError(f"v0 has no citizens younger than 5 (got {age})")
    if age <= 12:
        return "child"
    if age <= 17:
        return "teen"
    if age <= 30:
        return "young_adult"
    if age <= 50:
        return "middle_aged"
    return "elder"


@dataclass
class Body:
    hunger: float = 0.0
    thirst: float = 0.0
    energy: float = 100.0
    health: float = 100.0
    asleep: bool = False
    alive: bool = True
    cause_of_death: str | None = None
    levels: tuple[int, int, int, int] = (0, 0, 0, 0)  # need levels last reported (hunger, thirst, energy, health)


@dataclass
class PlaceKnowledge:
    level: KnowledgeLevel
    guess: Vec3  # where the citizen thinks it is (exact once visited)


@dataclass
class Heard:
    tick: int
    seq: int  # the `said` event
    speaker_id: str
    who: str  # how the hearer named the speaker when they spoke ("someone" if out of sight)
    words: str
    volume: Volume
    origin: Vec3


@dataclass
class ActionState:
    number: int
    kind: ActionName
    started_tick: int
    started_seq: int
    args: dict[str, JsonScalar]
    until_tick: int | None = None
    route: Route | None = None
    leg: int = 0
    along_m: float = 0.0
    goal: Vec3 | None = None  # where a walk is heading (moves with a followed person)
    target_id: str | None = None  # a person or ground stack the action is about
    item: str | None = None
    amount: int = 0
    label: str = ""  # how the result names the destination or thing
    collapsed: bool = False


@dataclass
class Citizen:
    id: str
    name: str
    look: str
    appearance: str  # how strangers see them ("a young woman in an indigo robe")
    age: int
    group: AgeGroup
    home: str | None  # structure id
    position: Vec3
    cell: int
    height_m: float
    body: Body = field(default_factory=Body)
    inventory: dict[str, int] = field(default_factory=dict)
    places: dict[str, PlaceKnowledge] = field(default_factory=dict)
    people: set[str] = field(default_factory=set)
    action: ActionState | None = None
    next_action: int = 1
    results: dict[int, ActionResult] = field(default_factory=dict)
    heard: list[Heard] = field(default_factory=list)
    in_view: set[str] = field(default_factory=set)  # people seen at the end of the last tick

    @property
    def traits(self) -> AgeTraits:
        return AGE_GROUPS[self.group]


@dataclass
class GroundStack:
    id: str
    item: str
    count: int
    position: Vec3
    cell: int


@dataclass
class WorldState:
    tick: int
    next_seq: int
    next_stack: int
    citizens: dict[str, Citizen]
    ground: dict[str, GroundStack]
    stores: dict[str, dict[str, int]]  # structure id -> items (filled by M7's town economy)
    resources: NDArray[np.uint8]  # (cells, len(RESOURCES)) wild plant counters
    rngs: dict[str, Rng]
