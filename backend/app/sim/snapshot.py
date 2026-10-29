"""Snapshots: the whole mutable state as JSON (resumable), and a canonical hash of it.

Sets are stored sorted and the hash dumps with sorted keys, so equal states hash equal whatever their history. Each
registered system (`app.sim.systems`) stores its state in its own block with its own version.
"""

import base64
import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, JsonValue

from app.core.rng import Rng
from app.sim.state import (
    ActionState,
    AgeGroup,
    Animal,
    AnimalGroup,
    Body,
    Citizen,
    Fire,
    GroundStack,
    Heard,
    PlaceKnowledge,
    Region,
    System,
    WorldState,
)
from app.sim.systems import REGISTRY
from app.sim.vec import Vec3
from app.world_api.models import ActionResult

# 5: world v1 item kinds (spears by material, coins); 4: the seed and the systems' blocks; 3: animals, groups, fires,
# fish stocks; 2: identities, regrowth, brain notes
SNAPSHOT_VERSION = 5


class _Snap(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitizenSnap(_Snap):
    id: str
    name: str
    look: str
    appearance: str
    age: int
    group: AgeGroup
    home: str | None
    position: Vec3
    cell: int
    height_m: float
    role: str
    region: Region
    skills: list[str]
    heading_deg: float
    body: Body
    inventory: dict[str, int]
    places: dict[str, PlaceKnowledge]
    people: list[str]
    action: ActionState | None
    next_action: int
    results: dict[int, ActionResult]
    heard: list[Heard]
    in_view: list[str]
    animals_in_view: list[str]
    threats: list[str]


class SystemSnap(_Snap):
    version: int
    data: JsonValue


class SimSnapshot(_Snap):
    version: int = SNAPSHOT_VERSION
    seed: int
    tick: int
    next_seq: int
    next_stack: int
    citizens: list[CitizenSnap]
    ground: list[GroundStack]
    stores: dict[str, dict[str, int]]
    resources: str  # base64 of uint8 (cells, resources), row-major
    resource_columns: int
    rngs: dict[str, str]  # stream -> state as a decimal string (64-bit)
    regrow: dict[str, int]
    notes: dict[str, dict[str, JsonValue]]
    animals: list[Animal]
    groups: list[AnimalGroup]
    fires: list[Fire]
    next_animal: int
    next_fire: int
    systems: dict[str, SystemSnap]


def resumable(snapshot: Mapping[str, Any], systems: tuple[System[Any], ...] = REGISTRY.systems) -> bool:
    """Whether this simulation can continue from a stored snapshot: the same snapshot version, and a block of the
    same version for exactly the registered systems."""
    blocks = snapshot.get("systems")
    if not isinstance(blocks, dict):
        return False
    return _same_versions(
        snapshot.get("version"), {name: block.get("version") for name, block in blocks.items()}, systems
    )


def _same_versions(version: object, blocks: Mapping[str, object], systems: tuple[System[Any], ...]) -> bool:
    return version == SNAPSHOT_VERSION and dict(blocks) == {system.name: system.version for system in systems}


def take_snapshot(state: WorldState, systems: tuple[System[Any], ...] = REGISTRY.systems) -> SimSnapshot:
    """A snapshot that shares no mutable objects with the live state."""
    if set(state.systems) != {system.name for system in systems}:
        raise ValueError(f"the state holds systems {sorted(state.systems)}, not the registered ones")
    state_citizens = copy.deepcopy(state.citizens)
    citizens = [
        CitizenSnap(
            id=c.id,
            name=c.name,
            look=c.look,
            appearance=c.appearance,
            age=c.age,
            group=c.group,
            home=c.home,
            position=c.position,
            cell=c.cell,
            height_m=c.height_m,
            role=c.role,
            region=c.region,
            skills=list(c.skills),
            heading_deg=c.heading_deg,
            body=c.body,
            inventory=dict(sorted(c.inventory.items())),
            places=dict(sorted(c.places.items())),
            people=sorted(c.people),
            action=c.action,
            next_action=c.next_action,
            results=dict(sorted(c.results.items())),
            heard=list(c.heard),
            in_view=sorted(c.in_view),
            animals_in_view=sorted(c.animals_in_view),
            threats=sorted(c.threats),
        )
        for _, c in sorted(state_citizens.items())
    ]
    resources = np.ascontiguousarray(state.resources, dtype=np.uint8)
    return SimSnapshot(
        seed=state.seed,
        tick=state.tick,
        next_seq=state.next_seq,
        next_stack=state.next_stack,
        citizens=citizens,
        ground=[copy.deepcopy(stack) for _, stack in sorted(state.ground.items())],
        stores={store: dict(sorted(items.items())) for store, items in sorted(state.stores.items())},
        resources=base64.b64encode(resources.tobytes()).decode("ascii"),
        resource_columns=resources.shape[1],
        rngs={name: str(rng.state) for name, rng in sorted(state.rngs.items())},
        regrow=dict(sorted(state.regrow.items())),
        notes=copy.deepcopy({cid: dict(sorted(notes.items())) for cid, notes in sorted(state.notes.items())}),
        animals=[copy.deepcopy(animal) for _, animal in sorted(state.animals.items())],
        groups=[copy.deepcopy(group) for _, group in sorted(state.groups.items())],
        fires=[copy.deepcopy(fire) for _, fire in sorted(state.fires.items())],
        next_animal=state.next_animal,
        next_fire=state.next_fire,
        systems={
            system.name: SystemSnap(version=system.version, data=copy.deepcopy(system.dump(system.of(state))))
            for system in sorted(systems, key=lambda system: system.name)
        },
    )


def restore(snapshot: SimSnapshot, systems: tuple[System[Any], ...] = REGISTRY.systems) -> WorldState:
    """A live state that shares no mutable objects with the snapshot."""
    snapshot = snapshot.model_copy(deep=True)
    blocks = {name: block.version for name, block in snapshot.systems.items()}
    if not _same_versions(snapshot.version, blocks, systems):
        raise ValueError(f"snapshot version {snapshot.version} with system blocks {blocks} is not this simulation's")
    resources = np.frombuffer(base64.b64decode(snapshot.resources), dtype=np.uint8)
    citizens = {
        snap.id: Citizen(
            id=snap.id,
            name=snap.name,
            look=snap.look,
            appearance=snap.appearance,
            age=snap.age,
            group=snap.group,
            home=snap.home,
            position=snap.position,
            cell=snap.cell,
            height_m=snap.height_m,
            role=snap.role,
            region=snap.region,
            skills=tuple(snap.skills),
            heading_deg=snap.heading_deg,
            body=snap.body,
            inventory=dict(snap.inventory),
            places=dict(snap.places),
            people=set(snap.people),
            action=snap.action,
            next_action=snap.next_action,
            results=dict(snap.results),
            heard=list(snap.heard),
            in_view=set(snap.in_view),
            animals_in_view=set(snap.animals_in_view),
            threats=set(snap.threats),
        )
        for snap in snapshot.citizens
    }
    return WorldState(
        tick=snapshot.tick,
        seed=snapshot.seed,
        next_seq=snapshot.next_seq,
        next_stack=snapshot.next_stack,
        citizens=citizens,
        ground={stack.id: stack for stack in snapshot.ground},
        stores={store: dict(items) for store, items in snapshot.stores.items()},
        resources=resources.reshape(-1, snapshot.resource_columns).copy(),
        rngs={name: Rng(int(value)) for name, value in snapshot.rngs.items()},
        regrow=dict(snapshot.regrow),
        notes={cid: dict(notes) for cid, notes in snapshot.notes.items()},
        animals={animal.id: animal for animal in snapshot.animals},
        groups={group.id: group for group in snapshot.groups},
        fires={fire.id: fire for fire in snapshot.fires},
        next_animal=snapshot.next_animal,
        next_fire=snapshot.next_fire,
        systems={system.name: system.load(snapshot.systems[system.name].data) for system in systems},
    )


def canonical_json(snapshot: SimSnapshot) -> str:
    return json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def state_hash(state: WorldState, systems: tuple[System[Any], ...] = REGISTRY.systems) -> str:
    return hashlib.sha256(canonical_json(take_snapshot(state, systems)).encode()).hexdigest()
