"""Replay: rebuild what spectators see (positions, bodies, actions, items, resources, knowledge) from the nearest
snapshot plus the events after it. The same reducer backs `GET /entities?at=tick`, the citizen pages and the
"every change has an event" test.
"""

import base64
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.observability.events import (
    ActionEnded,
    ActionStarted,
    BodyValues,
    CitizenSpawned,
    Died,
    ItemLocation,
    ItemMoved,
    KnowledgeChanged,
    ResourceChanged,
    TickSummary,
)
from app.sim.items import RESOURCE_INDEX
from app.sim.snapshot import SimSnapshot
from app.sim.state import Region
from app.sim.vec import Vec3


@dataclass
class ReplayCitizen:
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
    role: str = ""
    region: Region = "town"
    heading_deg: float = 0.0
    alive: bool = True
    asleep: bool = False
    cause_of_death: str | None = None
    action: str | None = None
    action_number: int | None = None
    action_label: str = ""
    inventory: dict[str, int] = field(default_factory=dict)
    skills: tuple[str, ...] = ()
    places: dict[str, str] = field(default_factory=dict)  # place id -> visited | rough
    people: set[str] = field(default_factory=set)  # citizens they know
    said_tick: int | None = field(default=None, compare=False)  # last spoke (not in snapshots: a moment's flavour)


@dataclass
class ReplayStack:
    item: str
    count: int
    position: Vec3
    cell: int


@dataclass
class ReplayState:
    tick: int
    citizens: dict[str, ReplayCitizen]
    ground: dict[str, ReplayStack]
    stores: dict[str, dict[str, int]]
    resources: NDArray[np.uint8]

    def same_as(self, other: "ReplayState") -> bool:
        return (
            self.tick == other.tick
            and self.citizens == other.citizens
            and self.ground == other.ground
            and self.stores == other.stores
            and np.array_equal(self.resources, other.resources)
        )


@dataclass(frozen=True)
class ReplayEvent:
    tick: int
    type: str
    actor_id: str | None
    payload: Mapping[str, Any]


def from_snapshot(snapshot: SimSnapshot) -> ReplayState:
    citizens = {}
    for c in snapshot.citizens:
        citizens[c.id] = ReplayCitizen(
            id=c.id,
            name=c.name,
            look=c.look,
            appearance=c.appearance,
            age=c.age,
            group=c.group,
            home=c.home,
            position=c.position,
            height_m=c.height_m,
            cell=c.cell,
            body=(c.body.hunger, c.body.thirst, c.body.energy, c.body.health),
            role=c.role,
            region=c.region,
            heading_deg=c.heading_deg,
            alive=c.body.alive,
            asleep=c.body.asleep,
            cause_of_death=c.body.cause_of_death,
            action=c.action.kind if c.action is not None else None,
            action_number=c.action.number if c.action is not None else None,
            action_label=c.action.label if c.action is not None else "",
            inventory={item: count for item, count in c.inventory.items() if count},
            skills=tuple(c.skills),
            places={place_id: known.level for place_id, known in c.places.items()},
            people=set(c.people),
        )
    resources = np.frombuffer(base64.b64decode(snapshot.resources), dtype=np.uint8)
    return ReplayState(
        tick=snapshot.tick,
        citizens=citizens,
        ground={s.id: ReplayStack(s.item, s.count, s.position, s.cell) for s in snapshot.ground},
        stores={store: dict(items) for store, items in snapshot.stores.items()},
        resources=resources.reshape(-1, snapshot.resource_columns).copy(),
    )


def replay(snapshot: SimSnapshot, events: Iterable[ReplayEvent]) -> ReplayState:
    state = from_snapshot(snapshot)
    for event in events:
        apply_event(state, event)
    return state


def apply_event(state: ReplayState, event: ReplayEvent) -> None:
    kind = event.type
    if kind == "tick_summary":
        summary = TickSummary.model_validate(event.payload)
        state.tick = event.tick
        for citizen_id, moved in summary.moved.items():
            citizen = state.citizens[citizen_id]
            citizen.position, citizen.height_m, citizen.cell = moved.position, moved.height_m, moved.cell
            citizen.heading_deg = moved.heading_deg
        for citizen_id, body in summary.bodies.items():
            state.citizens[citizen_id].body = body
    elif kind == "citizen_spawned":
        spawned = CitizenSpawned.model_validate(event.payload)
        state.citizens[spawned.id] = ReplayCitizen(
            id=spawned.id,
            name=spawned.name,
            look=spawned.look,
            appearance=spawned.appearance,
            age=spawned.age,
            group=spawned.group,
            home=spawned.home,
            position=spawned.position,
            height_m=spawned.height_m,
            cell=spawned.cell,
            body=spawned.body,
            role=spawned.role,
            region=spawned.region,
            heading_deg=spawned.heading_deg,
            inventory={item: count for item, count in spawned.inventory.items() if count},
            skills=tuple(spawned.skills),
            places=dict(spawned.places),
            people=set(spawned.people),
        )
    elif kind == "action_started":
        started = ActionStarted.model_validate(event.payload)
        citizen = state.citizens[_actor(event)]
        citizen.action, citizen.action_number, citizen.action_label = started.action, started.number, started.label
        if started.action == "sleep":
            citizen.asleep = True
    elif kind in ("action_finished", "action_interrupted"):
        ended = ActionEnded.model_validate(event.payload)
        citizen = state.citizens[_actor(event)]
        if ended.number == citizen.action_number:
            if citizen.action == "sleep":
                citizen.asleep = False
            citizen.action, citizen.action_number, citizen.action_label = None, None, ""
    elif kind == "said":
        state.citizens[_actor(event)].said_tick = event.tick
    elif kind == "died":
        died = Died.model_validate(event.payload)
        citizen = state.citizens[_actor(event)]
        citizen.alive, citizen.asleep, citizen.cause_of_death = False, False, died.cause
    elif kind == "item_moved":
        moved_item = ItemMoved.model_validate(event.payload)
        _take(state, moved_item.source, moved_item.item, moved_item.count)
        _put(state, moved_item.destination, moved_item.item, moved_item.count)
    elif kind == "resource_changed":
        changed = ResourceChanged.model_validate(event.payload)
        state.resources[changed.cell, RESOURCE_INDEX[changed.resource]] = changed.after
    elif kind == "knowledge_changed":
        learned = KnowledgeChanged.model_validate(event.payload)
        citizen = state.citizens[_actor(event)]
        if learned.about == "place":
            citizen.places[learned.ref] = learned.level
        else:
            citizen.people.add(learned.ref)


def _actor(event: ReplayEvent) -> str:
    if event.actor_id is None:
        raise ValueError(f"{event.type} event without an actor")
    return event.actor_id


def _take(state: ReplayState, where: ItemLocation, item: str, count: int) -> None:
    if where.kind == "inventory":
        inventory = state.citizens[_id(where)].inventory
        inventory[item] -= count
        if inventory[item] == 0:
            del inventory[item]
    elif where.kind == "ground":
        stack = state.ground[_id(where)]
        stack.count -= count
        if stack.count == 0:
            del state.ground[_id(where)]
    elif where.kind == "store":
        store = state.stores[_id(where)]
        store[item] -= count
        if store[item] == 0:
            del store[item]
    # resources change through their own `resource_changed` event; `world` items come from nowhere


def _put(state: ReplayState, where: ItemLocation, item: str, count: int) -> None:
    if where.kind == "inventory":
        inventory = state.citizens[_id(where)].inventory
        inventory[item] = inventory.get(item, 0) + count
    elif where.kind == "ground":
        stack_id = _id(where)
        if stack_id in state.ground:
            raise ValueError(f"ground stack {stack_id} exists already (things put down always make a new stack)")
        if where.position is None or where.cell is None:
            raise ValueError(f"new ground stack {stack_id} needs a position and cell")
        state.ground[stack_id] = ReplayStack(item, count, where.position, where.cell)
    elif where.kind == "store":
        store = state.stores.setdefault(_id(where), {})
        store[item] = store.get(item, 0) + count


def _id(where: ItemLocation) -> str:
    if where.id is None:
        raise ValueError(f"{where.kind} location without an id")
    return where.id
