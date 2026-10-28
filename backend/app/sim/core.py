"""The simulation's shared core: static world, planner, mutable state and the event outbox.

Perception, actions and the tick loop all work through this object; it is the only place that emits events.
"""

import hashlib
import math
from collections.abc import Callable

from app.observability.events import (
    ActionEnded,
    ActorKind,
    EventDraft,
    EventType,
    ItemLocation,
    ItemMoved,
    KnowledgeChanged,
    Payload,
    Visibility,
)
from app.sim.clock import NIGHT_ALTITUDE_DEG, daylight, sun_altitude_deg, sun_direction
from app.sim.items import ITEMS
from app.sim.navigation import Planner
from app.sim.state import Citizen, GroundStack, KnowledgeLevel, PlaceKnowledge, WorldState
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.sim.world import SimWorld
from app.world_api.models import ActionResult, Outcome

SIGHT_DAY_M = 150.0
SIGHT_NIGHT_M = 20.0
FOREST_SIGHT = 0.4
HILL_SIGHT = 1.3
FOREST_BIOMES = frozenset({"broadleaf_forest", "taiga"})
HILL_BIOMES = frozenset({"hills", "mountain", "volcanic"})
HEARING_M = {"whisper": 3.0, "normal": 30.0, "shout": 150.0}
REACH_M = 3.0
ROUGH_GUESS_M = 60.0  # how far off a place someone was only told about may be
KEPT_RESULTS = 8
KEPT_HEARD = 20

_LEVEL_RANK: dict[KnowledgeLevel, int] = {"rough": 1, "visited": 2}

GiftPolicy = Callable[[Citizen, Citizen, str, int], bool]  # (giver, receiver, item, count) -> accepted


def awake_accepts(giver: Citizen, receiver: Citizen, item: str, count: int) -> bool:  # noqa: ARG001  # a GiftPolicy
    """Until brains decide (M7) and minds (phase B), anyone awake takes what they are handed."""
    return not receiver.body.asleep


class SimCore:
    def __init__(
        self, world: SimWorld, planner: Planner, state: WorldState, accepts_gift: "GiftPolicy | None" = None
    ) -> None:
        self.world = world
        self.accepts_gift: GiftPolicy = accepts_gift or awake_accepts
        self.planner = planner
        self.state = state
        self.outbox: list[EventDraft] = []
        self._sun_tick = -1
        self._sun: Vec3 = (0.0, 0.0, 1.0)

    # --- events ---

    def emit(
        self,
        event_type: EventType,
        payload: Payload,
        *,
        actor: Citizen | None = None,
        actor_kind: ActorKind | None = None,
        visibility: Visibility = "public",
        cause_seq: int | None = None,
    ) -> int:
        seq = self.state.next_seq
        self.state.next_seq += 1
        self.outbox.append(
            EventDraft(
                seq=seq,
                tick=self.state.tick,
                type=event_type,
                actor_kind=actor_kind or ("citizen" if actor is not None else "world"),
                actor_id=actor.id if actor is not None else None,
                cell=actor.cell if actor is not None else None,
                position=actor.position if actor is not None else None,
                visibility=visibility,
                cause_seq=cause_seq,
                payload=payload,
            )
        )
        return seq

    # --- time and light ---

    def sun(self) -> Vec3:
        if self._sun_tick != self.state.tick:
            self._sun = sun_direction(self.state.tick, self.world.town_lon_deg)
            self._sun_tick = self.state.tick
        return self._sun

    def altitude(self, unit: Vec3) -> float:
        return sun_altitude_deg(unit, self.sun())

    def is_night_at(self, unit: Vec3) -> bool:
        return self.altitude(unit) < NIGHT_ALTITUDE_DEG

    def sight_range(self, citizen: Citizen) -> float:
        base = SIGHT_NIGHT_M + (SIGHT_DAY_M - SIGHT_NIGHT_M) * daylight(self.altitude(citizen.position))
        biome = self.world.biome(citizen.cell)
        if biome in FOREST_BIOMES:
            base *= FOREST_SIGHT
        elif biome in HILL_BIOMES:
            base *= HILL_SIGHT
        return base

    # --- citizens ---

    def citizens(self) -> list[Citizen]:
        return [self.state.citizens[cid] for cid in sorted(self.state.citizens)]

    def living(self) -> list[Citizen]:
        return [citizen for citizen in self.citizens() if citizen.body.alive]

    def distance_m(self, a: Vec3, b: Vec3) -> float:
        return self.world.distance_m(a, b)

    def place_at(self, citizen: Citizen, position: Vec3) -> None:
        if position != citizen.position:  # face where they go: yaw 0 = south, 90 = east (180 - compass bearing)
            citizen.heading_deg = round((180.0 - bearing_deg(citizen.position, position)) % 360.0, 2)
        citizen.position = position
        citizen.cell = self.world.nearest_cell(position, citizen.cell)
        citizen.height_m = self.world.ground_height(position, citizen.cell)

    def carried_kg(self, citizen: Citizen) -> float:
        return sum(ITEMS[item].weight_kg * count for item, count in citizen.inventory.items())

    def room_for(self, citizen: Citizen, item: str) -> int:
        """How many more pieces of an item the citizen can carry."""
        spare = citizen.traits.carry_kg - self.carried_kg(citizen)
        return max(0, math.floor(spare / ITEMS[item].weight_kg + 1e-9))

    # --- actions ---

    def record_result(self, citizen: Citizen, number: int, result: ActionResult) -> ActionResult:
        citizen.results[number] = result
        for old in sorted(citizen.results)[:-KEPT_RESULTS]:
            del citizen.results[old]
        return result

    def end_action(self, citizen: Citizen, outcome: Outcome, text: str, cause_seq: int | None = None) -> ActionResult:
        action = citizen.action
        if action is None:
            raise ValueError(f"{citizen.id} has no action to end")
        result = ActionResult(action=action.kind, outcome=outcome, text=text)
        citizen.action = None
        if action.kind == "sleep":
            citizen.body.asleep = False
        self.emit(
            "action_finished" if outcome == "done" else "action_interrupted",
            ActionEnded(number=action.number, action=result.action, outcome=outcome, text=text),
            actor=citizen,
            cause_seq=cause_seq if cause_seq is not None else action.started_seq,
        )
        return self.record_result(citizen, action.number, result)

    # --- knowledge ---

    def learn_place(self, citizen: Citizen, place_id: str, level: KnowledgeLevel, cause_seq: int | None = None) -> bool:
        known = citizen.places.get(place_id)
        if known is not None and _LEVEL_RANK[known.level] >= _LEVEL_RANK[level]:
            return False
        place = self.world.places[place_id]
        guess = place.stand if level == "visited" else self._rough_guess(citizen.id, place_id, place.stand)
        citizen.places[place_id] = PlaceKnowledge(level=level, guess=guess)
        self.emit(
            "knowledge_changed",
            KnowledgeChanged(about="place", ref=place_id, level=level),
            actor=citizen,
            visibility="private",
            cause_seq=cause_seq,
        )
        return True

    def learn_person(self, citizen: Citizen, person_id: str, cause_seq: int | None = None) -> bool:
        if person_id in citizen.people or person_id == citizen.id:
            return False
        citizen.people.add(person_id)
        self.emit(
            "knowledge_changed",
            KnowledgeChanged(about="person", ref=person_id, level="known"),
            actor=citizen,
            visibility="private",
            cause_seq=cause_seq,
        )
        return True

    def _rough_guess(self, citizen_id: str, place_id: str, stand: Vec3) -> Vec3:
        """A fixed wrong-ish spot per (citizen, place): hearsay is imprecise but stable."""
        digest = hashlib.sha256(f"{citizen_id}:{place_id}".encode()).digest()
        bearing = int.from_bytes(digest[:4], "little") / 2**32 * 360
        offset = int.from_bytes(digest[4:8], "little") / 2**32 * ROUGH_GUESS_M
        guess = step_towards(stand, bearing, offset, self.world.radius_m)
        start = self.world.town_point(guess)
        if start is not None and not self.world.town.walk.is_walkable(*start):
            return stand
        return guess

    # --- items ---

    def new_stack(self, item: str, count: int, position: Vec3, cell: int) -> GroundStack:
        stack = GroundStack(id=f"stack-{self.state.next_stack}", item=item, count=count, position=position, cell=cell)
        self.state.next_stack += 1
        self.state.ground[stack.id] = stack
        return stack

    def item_moved(
        self,
        actor: Citizen,
        item: str,
        count: int,
        source: ItemLocation,
        destination: ItemLocation,
        cause_seq: int | None = None,
    ) -> int:
        return self.emit(
            "item_moved",
            ItemMoved(item=item, count=count, source=source, destination=destination),
            actor=actor,
            cause_seq=cause_seq,
        )
