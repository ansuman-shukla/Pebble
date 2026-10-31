"""Event types and their typed payloads (06-observability).

The rule: every discrete state change is exactly one event. Continuous per-tick change (positions of walkers,
needs drifting) is covered by the tick's single `tick_summary`. Events carry a per-run sequence number `seq` that
the simulation assigns deterministically; the store gives each a ULID and resolves `cause_seq` to `cause_id`.
"""

from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from app.sim.locomotion import Gait
from app.sim.state import AnimalActivity, FireKind
from app.sim.vec import Vec3
from app.world_api.models import ActionName, Driver, GestureKind, Outcome, PriceWord, Sentence, Volume

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
    # world v1 (10-world-v1 §6.3)
    "node_changed",
    "tree_felled",
    "trespassed",
    "stole",
    "bought",
    "sold",
    "crafted",
    "spoiled",
    "tool_broke",
    "tax_assessed",
    "tax_paid",
    "tax_overdue",
    "ledger",
    "prices_changed",
    "accused",
    "seized",
    "released",
    "confined",
    "judged",
    "sentence_served",
    "standing_changed",
    "leader_changed",
    "bell_rang",
    "tended",
    "gestured",
    "goal_set",
]
WORLD_V1_TYPES: tuple[EventType, ...] = get_args(EventType)[get_args(EventType).index("node_changed") :]
ActorKind = Literal["citizen", "animal", "world", "player", "god"]
Visibility = Literal["public", "private"]
BodyValues = tuple[float, float, float, float]  # hunger, thirst, energy, health
JsonScalar = str | int | float | bool | None
AnimalGait = Literal["walk", "trot", "run", "stalk", "swim"]  # trot: an animal's sustained speed (10 §4.6)
TargetKind = Literal["person", "animal", "node", "store", "structure", "fire", "stack", "place", "direction"]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoutePoint(Payload):
    unit: Vec3  # direction from the planet's centre
    height_m: float  # ground height above sea level
    # game seconds after the tick's start the mover is here (None in runs recorded before routes were timed, whose
    # routes start at `position` and are walked at `speed_mps`)
    t_s: float | None = None


class Moved(Payload):
    position: Vec3
    height_m: float
    cell: int
    heading_deg: float = 0.0  # facing after the move (yaw in the local tangent frame, 0 = south, 180 = north)
    # how to draw the move: the path from where the mover stood when the tick began (its first point, t_s 0) through
    # `position`, then on along their plan for a couple of game minutes while they keep at it, timed by t_s
    route: list[RoutePoint] = []
    speed_mps: float = 0.0  # ground speed where the route starts, game metres per game second
    gait: Gait = "walk"  # how they went (run while fleeing or at `pace: "run"`, stalk on a hunt)


class Target(Payload):
    """What an action is about, for spectators (a person, an animal, a node, a store, a place...)."""

    kind: TargetKind
    id: str | None = None  # citizen, animal, node, store, structure, fire or ground stack id; None for a direction
    name: str  # in neutral words ("Kenji", "a deer", "the well", "north")
    position: Vec3 | None = None


class AnimalPose(Payload):
    position: Vec3
    height_m: float
    cell: int
    heading_deg: float
    activity: AnimalActivity
    # how to draw the move, the same rule as a citizen's `Moved` (D100): from where it stood when the tick began
    # through `position`, then on along its plan while it keeps at it, timed by t_s; empty when it didn't move
    route: list[RoutePoint] = []
    speed_mps: float = 0.0
    gait: AnimalGait = "walk"
    goal: str = ""  # what it is after, in words ("grazing", "fleeing the wolf", "stalking the deer")
    target: Target | None = None  # its quarry, its threat or the waterhole it heads for


class TickSummary(Payload):
    moved: dict[str, Moved]  # citizens whose position changed this tick
    bodies: dict[str, BodyValues]  # every living citizen's needs after this tick
    animals: dict[str, AnimalPose] = {}  # animals whose position, facing or activity changed this tick


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
    rank: int = 2  # 10 §3.2: 1 child .. 5 lord
    titles: list[Literal["lord", "samurai", "ashigaru", "leader"]] = []
    family: dict[str, str] = {}  # kin by citizen id: what that person is to them ("mate", "parent's sibling")
    bonds: dict[str, int] = {}  # citizen id -> their bond beyond kin (-100..100), as the cast gives it


class AnimalSpawned(Payload):
    """A new member of a group: a dead one's replacement (`replaces` = the remains it clears away)."""

    id: str
    kind: str
    group: str
    position: Vec3
    height_m: float
    cell: int
    heading_deg: float
    replaces: str | None = None


class FireChanged(Payload):
    """A fire was lit, fed, burned down a level or went out (a campfire's first event creates it)."""

    id: str
    kind: FireKind
    lit: bool
    strength: float  # 0 out, 1/3 embers, 2/3 low, 1 burning
    position: Vec3
    height_m: float
    cell: int


class Perceived(Payload):
    kind: Literal["look_around", "check_self"]
    text: str


class ActionStarted(Payload):
    number: int
    action: ActionName
    args: dict[str, JsonScalar]
    label: str  # destination or thing, in words
    collapsed: bool = False
    target: Target | None = None  # what it is about, for spectators (set by actions that resolve one)


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
    cause: str  # "violence" (a person's attack: `attacker`), "animal attack", ...
    attacker: str | None = None  # the citizen or animal that struck


class Died(Payload):
    cause: str  # "violence" (`attacker`), "starvation", "dehydration", "hunted", "killed by a wolf", ...
    attacker: str | None = None  # the citizen or animal whose blow killed


class ItemLocation(Payload):
    """Where items are. `resource` = a node's stock (id: the node, changed by `node_changed`; runs before nodes: a
    cell's wild plants or fish, changed by `resource_changed`); `world` = made by the world (a store's starting
    stock); `animal` = taken from a hunted animal (id); `eaten` and `fire` (id: the fire it burns in) = gone."""

    kind: Literal["inventory", "ground", "store", "resource", "eaten", "world", "animal", "fire"]
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


# --- world v1 (10-world-v1 §6.3). Unless said otherwise the event's actor is the citizen who did it; ids name
# citizens, nodes, stores and households; `deeds` and `judgement` refer to earlier events by their seq. ---


class NodeChanged(Payload):
    """A node's stock changed (taken, regrown, harvested, replanted; replaces `resource_changed`)."""

    node: str
    kind: str  # node kind (berry_bush, tree, rice_paddy, ...)
    item: str  # what it yields
    before: int
    after: int
    stage: str  # drawn stage after the change (node_stages.yaml)


class TreeFelled(Payload):
    node: str
    yaw_deg: float  # the way the trunk falls (yaw in the local tangent frame, like headings)
    logs: int
    stack: str | None = None  # the ground stack the logs land in at the trunk


class Took(Payload):
    item: str
    count: int


class Trespassed(Payload):
    """Once per entry (walls, castle at night) or per take (ground: poaching, `took`)."""

    kind: Literal["walls", "castle", "ground"]
    owner: str  # the group whose walls, castle or ground it is (town, band_a, band_b)
    place: str  # in words ("the castle town", "the Lord's woods", "band A's ground")
    took: Took | None = None
    witnesses: list[str] = []


class Stole(Payload):
    """The actor is the thief."""

    owner: str  # the owning household or group
    store: str
    item: str
    count: int
    witnesses: list[str] = []  # citizens who had the thief in view that tick


class Traded(Payload):
    """Payload of `bought` (the actor buys from the stall) and `sold` (the actor sells to it): one sale each."""

    item: str
    count: int
    lots: int
    coins: int  # paid (bought) or received (sold) in all
    stall: str  # the stall's store id
    merchant: str  # the stall's owner


class Crafted(Payload):
    recipe: str
    item: str
    count: int
    station: str | None = None  # the structure crafted at (forge, fire pit, loom, drying rack)


class Spoiled(Payload):
    """At the holder's local dawn: what went off (one event per holder)."""

    holder: str  # citizen or store id
    holder_kind: Literal["inventory", "store"]
    items: dict[str, int]  # item -> count lost


class ToolBroke(Payload):
    item: str  # spear, stone axe, iron sickle, pack, ...
    use: Literal["hunt", "fell", "harvest", "carry", "craft"]


class TaxChange(Payload):
    """Payload of `tax_assessed` (owed grew), `tax_paid` (owed shrank) and `tax_overdue` (owed past its time):
    `rice` and `coins` are this change (overdue: the arrears), `owed_*` what the household owes after it."""

    household: str
    rice: int = 0
    coins: int = 0
    owed_rice: int = 0
    owed_coins: int = 0
    days: int = 0  # tax_overdue: days in arrears


class Ledger(Payload):
    """Daily per citizen at local midnight (the scoreboard's daily facts)."""

    coins: int
    wealth_mon: int  # coins + town value of the inventory + an equal share of the household chest
    income_24h: int
    spent_24h: int
    owed_rice: int = 0
    owed_coins: int = 0


class PricesChanged(Payload):
    """An item's price word at the stall changed (actor: world)."""

    stall: str
    item: str
    word: PriceWord
    before: PriceWord
    lot: int
    sell: int  # mon per lot the stall sells for
    buy: int  # mon per lot it pays


class Accused(Payload):
    person: str
    to: str
    deeds: list[int]  # seqs of the deed events passed on


class Seized(Payload):
    """A seizure attempt by the actor: `held` when it succeeded."""

    person: str
    held: bool
    helpers: list[str] = []


class Released(Payload):
    """The actor (held or confined) is free again."""

    cause: Literal["judged", "timeout", "seizer_down"]
    by: str | None = None  # the seizer or judge


class Confined(Payload):
    """The actor is confined (the gaol, or tied at the band's fire) until `until_tick` or judged."""

    place: str
    until_tick: int
    by: str | None = None


class Judged(Payload):
    person: str
    sentence: Sentence
    fine_mon: int = 0
    confine_h: float = 0.0
    deeds: list[int] = []  # seqs of the deeds judged
    arrears: bool = False  # judged for the household's overdue tax


class SentenceServed(Payload):
    """The actor's sentence is done (fine paid in full, confinement over)."""

    sentence: Sentence
    judgement: int | None = None  # seq of the `judged` event


class StandingChanged(Payload):
    """The actor's standing with `group` changed (a deed seen or heard of, the dawn drift)."""

    group: str
    before: int
    after: int
    word: str  # the standing word after ("well regarded")
    cause: str  # theft, poaching, trespass, assault, killing, sale, gift, tended, served, accusation, leader, drift
    deed: int | None = None  # seq of the event that moved it


class LeaderChanged(Payload):
    """`group` has a new lord or leader (actor: the new one)."""

    group: str
    title: Literal["lord", "leader"]
    previous: str | None = None
    cause: Literal["standing", "death", "succession"]


class BellRang(Payload):
    kind: Literal["dawn", "noon", "dusk"]


class Tended(Payload):
    person: str
    health: float  # health the tended person gained


class Gestured(Payload):
    kind: GestureKind
    to: str | None = None
    seen_by: list[str] = []


class GoalSet(Payload):
    """Spectator-only: what the actor is after and why (never perceived by others)."""

    text: str
    driver: Driver


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
    "animal_spawned": AnimalSpawned,
    "fire_changed": FireChanged,
    "snapshot": SnapshotTaken,
    "intervention": Intervention,
    "node_changed": NodeChanged,
    "tree_felled": TreeFelled,
    "trespassed": Trespassed,
    "stole": Stole,
    "bought": Traded,
    "sold": Traded,
    "crafted": Crafted,
    "spoiled": Spoiled,
    "tool_broke": ToolBroke,
    "tax_assessed": TaxChange,
    "tax_paid": TaxChange,
    "tax_overdue": TaxChange,
    "ledger": Ledger,
    "prices_changed": PricesChanged,
    "accused": Accused,
    "seized": Seized,
    "released": Released,
    "confined": Confined,
    "judged": Judged,
    "sentence_served": SentenceServed,
    "standing_changed": StandingChanged,
    "leader_changed": LeaderChanged,
    "bell_rang": BellRang,
    "tended": Tended,
    "gestured": Gestured,
    "goal_set": GoalSet,
}  # thought gets its payload with phase B


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
