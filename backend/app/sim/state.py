"""The mutable world state: citizens, items, resource counters and random streams (plain dataclasses).

Everything here is in a snapshot (`app.sim.snapshot`); nothing else in the simulation changes over time. Each later
system keeps its own state in `WorldState.systems` (described by a `System`), so systems never add fields here.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue

from app.core.rng import Rng
from app.sim.navigation import Route
from app.sim.vec import Vec3
from app.sim.world import SimWorld
from app.world_api.models import ActionName, ActionResult, Volume

AgeGroup = Literal["child", "teen", "young_adult", "middle_aged", "elder"]
KnowledgeLevel = Literal["visited", "rough"]
Region = Literal["town", "band_a", "band_b"]
JsonScalar = str | int | float | bool | None
AnimalActivity = Literal["idle", "grazing", "walking", "running", "hunting", "sleeping", "dead"]
FireKind = Literal["pit", "basket", "campfire"]


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
    label: str = ""  # the destination or thing in neutral words, for spectators ("home", "the well")
    destination: str = ""  # where a walk is heading in the walker's own words ("your home")
    collapsed: bool = False
    store_id: str | None = None  # the storehouse an eat or work action takes from or puts into


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
    role: str = ""
    region: Region = "town"
    skills: tuple[str, ...] = ()
    heading_deg: float = 0.0  # facing: yaw in the local tangent frame, 0 = south, 90 = east, 180 = north
    body: Body = field(default_factory=Body)
    inventory: dict[str, int] = field(default_factory=dict)
    places: dict[str, PlaceKnowledge] = field(default_factory=dict)
    people: set[str] = field(default_factory=set)
    action: ActionState | None = None
    next_action: int = 1
    results: dict[int, ActionResult] = field(default_factory=dict)
    heard: list[Heard] = field(default_factory=list)
    in_view: set[str] = field(default_factory=set)  # people seen at the end of the last tick
    animals_in_view: set[str] = field(default_factory=set)  # animal groups seen at the end of the last tick
    threats: set[str] = field(default_factory=set)  # predators stalking them at the end of the last tick

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
class Animal:
    id: str  # "<kind>:<number>"; ids of citizens never contain a colon
    kind: str  # a species (app.sim.fauna), the spectator registry's kind name
    group: str
    position: Vec3
    cell: int
    height_m: float  # ground or water surface
    heading_deg: float = 0.0  # yaw in the local tangent frame like citizens' (0 = south, 90 = east)
    activity: AnimalActivity = "idle"
    alive: bool = True
    health: float = 100.0
    hunger: float = 0.0  # predators: 0 fed .. 100 starving
    goal: Vec3 | None = None  # where it is walking, running or swimming to
    pace_m: float = 0.0  # metres per tick towards the goal
    until: int = 0  # the tick it reconsiders what it is doing
    target: str | None = None  # a predator's quarry (an animal or a citizen id) while hunting
    bites: int = 0  # attacks on its current quarry
    died_tick: int | None = None


@dataclass
class AnimalGroup:
    id: str
    kind: str
    home: int  # the cell at the centre of its range
    size: int  # its soft cap: dead members are replaced up to this many
    members: list[str] = field(default_factory=list)  # one animal per slot (alive, or its remains until replaced)
    goal: Vec3 | None = None  # where the group is heading (members spread around it)
    next_move: int = 0  # the tick the group picks its next goal


@dataclass
class Fire:
    id: str  # a hearth's structure/placement id, or "fire:<number>" for a campfire made anywhere
    kind: FireKind
    position: Vec3
    cell: int
    height_m: float
    fuel: int = 0  # minutes of burning left
    lit: bool = False
    level: int = 0  # 0 out, 1 embers, 2 low, 3 burning (what spectators and perception see)


@dataclass
class WorldState:
    tick: int
    seed: int
    next_seq: int
    next_stack: int
    citizens: dict[str, Citizen]
    ground: dict[str, GroundStack]
    stores: dict[str, dict[str, int]]  # storehouse or field id -> items
    resources: NDArray[np.uint8]  # (cells, len(RESOURCES)) wild plant counters
    rngs: dict[str, Rng]  # the random streams drawn from so far, by name (see `rng`)
    regrow: dict[str, int] = field(default_factory=dict)  # "cell:resource" -> tick it grows one more
    notes: dict[str, dict[str, JsonValue]] = field(default_factory=dict)  # scripted brains' working memory
    animals: dict[str, Animal] = field(default_factory=dict)
    groups: dict[str, AnimalGroup] = field(default_factory=dict)
    fires: dict[str, Fire] = field(default_factory=dict)
    next_animal: int = 1
    next_fire: int = 1
    systems: dict[str, object] = field(default_factory=dict)  # each registered system's state, by system name

    def rng(self, stream: str) -> Rng:
        """The random stream `<system>.<purpose>` (10-world-v1 §6.5): every roll draws from its own stream, so a new
        roll never shifts the numbers another one draws. Seeded from the run's seed and the name on first use."""
        found = self.rngs.get(stream)
        if found is None:
            found = self.rngs[stream] = Rng.for_subsystem(self.seed, stream)
        return found


@dataclass(frozen=True)
class System[S]:
    """A system that keeps its own state (10-world-v1 §6.5): its name, the version of its snapshot block, and how to
    make, dump and load that state. Per-citizen and per-animal data lives in it too, keyed by id."""

    name: str
    version: int  # bump when the dumped form changes: a snapshot holding another version starts a new run (D58)
    new: Callable[[SimWorld], S]  # the state a new run starts with
    dump: Callable[[S], JsonValue]  # plain JSON; sets sorted, so equal states dump equal
    load: Callable[[JsonValue], S]

    def of(self, state: WorldState) -> S:
        return cast(S, state.systems[self.name])
