"""Event types and their typed payloads (06-observability).

The rule: every discrete state change is exactly one event. Continuous per-tick change (positions of walkers,
needs drifting) is covered by the tick's single `tick_summary`. Events carry a per-run sequence number `seq` that
the simulation assigns deterministically; the store gives each a ULID and resolves `cause_seq` to `cause_id`.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.sim.vec import Vec3
from app.world_api.models import ActionName, Outcome, Volume

EventType = Literal[
    "tick_summary",
    "citizen_spawned",
    "perceived",
    "action_started",
    "action_finished",
    "action_interrupted",
    "said",
    "thought",
    "need_changed",
    "injured",
    "died",
    "item_moved",
    "resource_changed",
    "knowledge_changed",
    "animal_spawned",
    "fire_changed",
    "intervention",
    "snapshot",
]
ActorKind = Literal["citizen", "animal", "world", "player", "god"]
Visibility = Literal["public", "private"]
BodyValues = tuple[float, float, float, float]  # hunger, thirst, energy, health
JsonScalar = str | int | float | bool | None


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoutePoint(Payload):
    unit: Vec3  # direction from the planet's centre
    height_m: float  # ground height above sea level


class Moved(Payload):
    position: Vec3
    height_m: float
    cell: int
    heading_deg: float = 0.0  # facing after the move (yaw in the local tangent frame, 0 = south, 180 = north)
    # a walker's planned path ahead, from `position` (its first point) over the next couple of game minutes of
    # walking, so clients can draw the walk between ticks; empty when they're not walking on
    route: list[RoutePoint] = []
    speed_mps: float = 0.0  # ground speed on the current leg, game metres per game second (0 when not walking)


class TickSummary(Payload):
    moved: dict[str, Moved]  # citizens whose position changed this tick
    bodies: dict[str, BodyValues]  # every living citizen's needs after this tick


class CitizenSpawned(Payload):
    id: str
    name: str
    look: str
    appearance: str
    age: int
    group: str
    home: str | None
    position: Vec3
    height_m: float
    cell: int
    body: BodyValues
    places: dict[str, Literal["visited", "rough"]]
    people: list[str]
    role: str = ""
    region: Literal["town", "band_a", "band_b"] = "town"
    skills: list[str] = []
    heading_deg: float = 0.0
    inventory: dict[str, int] = {}  # what they start out carrying


class Perceived(Payload):
    kind: Literal["look_around", "check_self"]
    text: str


class ActionStarted(Payload):
    number: int
    action: ActionName
    args: dict[str, JsonScalar]
    label: str  # destination or thing, in words
    collapsed: bool = False


class ActionEnded(Payload):
    """Payload of both `action_finished` and `action_interrupted`."""

    number: int
    action: ActionName
    outcome: Outcome
    text: str


class Said(Payload):
    words: str
    volume: Volume
    heard_by: list[str]


class NeedChanged(Payload):
    need: Literal["hunger", "thirst", "energy", "health"]
    level: str
    value: float
    worse: bool


class Injured(Payload):
    amount: float
    cause: str


class Died(Payload):
    cause: str


class ItemLocation(Payload):
    """Where items are. `resource` = a cell's wild plants (changed by `resource_changed`); `world` = made by the world
    (a tended field's harvest growing, a store's starting stock); `eaten` = gone."""

    kind: Literal["inventory", "ground", "store", "resource", "eaten", "world"]
    id: str | None = None  # citizen, ground stack or store id
    cell: int | None = None
    position: Vec3 | None = None  # for a ground stack


class ItemMoved(Payload):
    item: str
    count: int
    source: ItemLocation
    destination: ItemLocation


class ResourceChanged(Payload):
    cell: int
    resource: str
    before: int
    after: int


class KnowledgeChanged(Payload):
    about: Literal["place", "person"]
    ref: str  # place or citizen id
    level: Literal["visited", "rough", "known"]


class SnapshotTaken(Payload):
    tick: int


class Intervention(Payload):
    kind: str
    detail: dict[str, JsonScalar]


PAYLOAD_TYPES: dict[EventType, type[Payload]] = {
    "tick_summary": TickSummary,
    "citizen_spawned": CitizenSpawned,
    "perceived": Perceived,
    "action_started": ActionStarted,
    "action_finished": ActionEnded,
    "action_interrupted": ActionEnded,
    "said": Said,
    "need_changed": NeedChanged,
    "injured": Injured,
    "died": Died,
    "item_moved": ItemMoved,
    "resource_changed": ResourceChanged,
    "knowledge_changed": KnowledgeChanged,
    "snapshot": SnapshotTaken,
    "intervention": Intervention,
}  # thought, animal_spawned and fire_changed get payloads with the milestones that emit them


@dataclass(frozen=True)
class EventDraft:
    seq: int
    tick: int
    type: EventType
    actor_kind: ActorKind
    actor_id: str | None
    cell: int | None
    position: Vec3 | None
    visibility: Visibility
    cause_seq: int | None
    payload: Payload

    def __post_init__(self) -> None:
        expected = PAYLOAD_TYPES.get(self.type)
        if expected is None or not isinstance(self.payload, expected):
            raise TypeError(f"{self.type} events carry {expected}, got {type(self.payload).__name__}")
