"""Slots (10-world-v1 §4.3): the one claim registry for the spots bodies take, so no two bodies stand, sit or lie
inside each other and every worker is at the thing they work at.

The layout (`data/slots.yaml`) gives each structure kind, placement and named place its slots: seats, mats, stands,
queues, work slots and each home's `inside`. A citizen holds at most one claim: a slot, or a free spot of the ring
fallback (r 1.0/1.8/2.6/3.4 m x 8 bearings, walkable, at least `PERSONAL_M` from any body or claim). Walks claim
where they go (`reserve_*`), rest a seat, sleep a mat or `inside`, work its task's slot.

At each tick's end `settle` keeps the claims honest and the bodies apart:

    claims ─▶ dead, or walking elsewhere, or a walk cut short               ─▶ freed
           ─▶ awake again inside a house                                  ─▶ freed, out of the door to a free spot
           ─▶ claimed standing still a few steps away (rest, sleep, work)  ─▶ step there (a short drawn walk; a
              sleeper goes in through the door to the house's middle, out of sight)
    bodies ─▶ standing, sitting or lying closer than PERSONAL_M to another ─▶ the one off its slot (the latest to
              arrive) steps aside to a ring spot

so at every tick's end no two living bodies that aren't walking or inside lie within `PERSONAL_M` of each other.
"""

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from app.core.config import WORLD_DATA_DIR
from app.sim.clock import SECONDS_PER_TICK
from app.sim.core import SimCore, Stride, TimedPoint
from app.sim.ground_speed import ground_mps
from app.sim.navigation import walk_along
from app.sim.perception import HOME_RADIUS_M
from app.sim.state import Citizen, System
from app.sim.vec import Vec3, step_towards
from app.sim.world import SimWorld, Structure, site_unit
from app.world.geometry import Rotation, rotate_point
from app.world.town import TownPlacement, TownView, load_town
from app.world.view import Site

SLOTS_FILE = WORLD_DATA_DIR / "slots.yaml"
SlotKind = Literal["seat", "mat", "inside", "stand", "queue", "work"]
SlotPosture = Literal["standing", "sitting", "sitting_ground", "lying", "inside"]

PERSONAL_M = 0.8  # no two bodies end an action closer than this (D117)
OCCUPY_M = 0.05  # a body this close to its claim is on it
APPROACH_M = 8.0  # a mat (sleep) or a stand freed in a queue is taken this close, and walked to at the tick's end
SEAT_M = 4.0  # rest takes a free seat this close
ALREADY_THERE_M = 1.0  # a walk to a spot this close is no walk (movement's "You are already there")
RING_M = (1.0, 1.8, 2.6, 3.4)  # the ring fallback's radii, 8 bearings each
RING_BEARINGS = 8
BESIDE_TURNS = (0.0, 30.0, -30.0, 60.0, -60.0, 90.0, -90.0, 120.0, -120.0, 150.0, -150.0, 180.0)  # free_round
STRAIGHT_M = 1.5  # a step this short goes straight; longer ones follow the planner's route
MIN_STEP_S = 0.5
MOVING = frozenset({"walk_to", "follow", "flee", "hunt", "attack"})  # actions that move the body every tick
_POSTURES: dict[SlotKind, SlotPosture] = {"seat": "sitting", "mat": "lying", "inside": "inside"}
_WORDS: dict[SlotKind, str] = {"seat": "on a seat", "mat": "on a mat", "inside": "inside"}
_SOLID_MARGIN_M = 0.3  # a ring spot keeps a body's half-width off a camp's solid props

ToUnit = Callable[[float, float], Vec3]  # local metres (x, z) -> a direction on the globe


# --- the layout ---


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SlotSpec(_Spec):
    name: str
    kind: Literal["seat", "mat", "stand", "queue", "work"]
    at: tuple[float, float] | None = None
    polar: tuple[float, float] | None = None  # (r, compass bearing) at rotation 0
    heading: float | None = None
    face: tuple[float, float] = (0.0, 0.0)
    task: str | None = None
    skill: str | None = None
    posture: SlotPosture | None = None
    height_m: float = Field(default=0.0, ge=0)
    words: str | None = None

    @model_validator(mode="after")
    def _one_position(self) -> "SlotSpec":
        if (self.at is None) == (self.polar is None):
            raise ValueError(f"slot {self.name}: give exactly one of at and polar")
        if (self.kind == "work") != (self.task is not None) and self.kind != "seat":
            raise ValueError(f"slot {self.name}: work slots, and only they (or confining seats), have a task")
        return self

    def local(self) -> tuple[float, float]:
        if self.at is not None:
            return self.at
        if self.polar is None:
            raise ValueError(f"slot {self.name} has no position")
        r, bearing = self.polar
        return (r * math.sin(math.radians(bearing)), -r * math.cos(math.radians(bearing)))

    def local_heading(self) -> float:
        if self.heading is not None:
            return self.heading
        x, z = self.local()
        return math.degrees(math.atan2(self.face[0] - x, self.face[1] - z)) % 360.0


class PlacementSlotsSpec(_Spec):
    replace: bool = False
    slots: list[SlotSpec] = []


class PlaceSlotsSpec(_Spec):
    owners: list[str] = []
    slots: list[SlotSpec] = []


class SlotsSpec(_Spec):
    kinds: dict[str, list[SlotSpec]]
    placements: dict[str, PlacementSlotsSpec] = {}
    places: dict[str, PlaceSlotsSpec] = {}


@cache
def load_slots_spec() -> SlotsSpec:
    return SlotsSpec.model_validate(yaml.safe_load(SLOTS_FILE.read_text()))


@dataclass(frozen=True)
class Slot:
    """A spot a body takes (§4.3): its owner (a structure, placement or place id), what it is, where, and facing."""

    id: str  # "<owner>#<name>"
    owner: str
    kind: SlotKind
    position: Vec3
    heading_deg: float  # yaw like citizens' (0 = south, 90 = east)
    posture: SlotPosture
    height_m: float = 0.0
    task: str | None = None
    skill: str | None = None
    words: str = ""

    def usable_by(self, citizen: Citizen) -> bool:
        """Anyone may take a slot without a skill; a skilled slot only someone with that skill."""
        return self.skill is None or self.skill in citizen.skills


@dataclass(frozen=True)
class Solid:
    """A camp prop bodies keep clear of (camps have no walk grid)."""

    centre: Vec3
    radius_m: float


@dataclass(frozen=True)
class Layout:
    slots: Mapping[str, Slot]
    owners: Mapping[str, tuple[Slot, ...]]
    places: Mapping[str, tuple[Slot, ...]]  # a named place's slots (its owners' then its own)
    homes: Mapping[str, tuple[Slot, ...]]  # a home's slots, and the skilled work slots within reach of its door
    tasks: frozenset[str]  # work tasks that have slots
    solids: tuple[Solid, ...]


def build_layout(world: SimWorld, town: TownView, spec: SlotsSpec) -> Layout:
    owners: dict[str, list[Slot]] = {}

    def add(owner: str, slot_specs: Iterable[SlotSpec], to_unit: ToUnit, rotation: Rotation = 0) -> None:
        for item in slot_specs:
            x, z = rotate_point(*item.local(), rotation)
            slot = Slot(
                id=f"{owner}#{item.name}",
                owner=owner,
                kind=item.kind,
                position=to_unit(x, z),
                heading_deg=round((item.local_heading() + rotation) % 360.0, 2),
                posture=item.posture or _POSTURES.get(item.kind, "standing"),
                height_m=item.height_m,
                task=item.task,
                skill=item.skill,
                words=item.words if item.words is not None else _WORDS.get(item.kind, ""),
            )
            owners.setdefault(owner, []).append(slot)

    def placed(owner: str, placement: TownPlacement, origin: ToUnit) -> None:
        override = spec.placements.get(placement.id)
        kind_slots = [] if override is not None and override.replace else spec.kinds.get(placement.kind, [])
        extra = override.slots if override is not None else []

        def at(x: float, z: float) -> Vec3:
            return origin(placement.x + x, placement.z + z)

        add(owner, [*kind_slots, *extra], at, placement.rotation_deg)

    for placement in town.placements:
        placed(placement.id, placement, world.town.to_unit)
    solids: list[Solid] = []
    for site in world.sites:
        if site.kind != "camp":
            continue
        in_camp = _site_frame(world, site)
        for placement in site.placements:
            placed(f"{site.id}:{placement.id}", placement, in_camp)
            if placement.walk == "solid":
                half = max(placement.footprint.x, placement.footprint.z) / 2
                solids.append(Solid(in_camp(placement.x, placement.z), half + _SOLID_MARGIN_M))
    for structure in world.structures.values():
        if structure.is_home and structure.kind != "lean_to":
            inside = Slot(f"{structure.id}#inside", structure.id, "inside", structure.centre, 0.0, "inside")
            owners.setdefault(structure.id, []).append(inside)

    places: dict[str, tuple[Slot, ...]] = {}
    for place_id, place_spec in spec.places.items():
        if place_id not in world.places:
            raise ValueError(f"slots.yaml names an unknown place {place_id}")
        unknown = [owner for owner in place_spec.owners if owner not in owners]
        if unknown:
            raise ValueError(f"place {place_id}: no slots for owners {unknown}")
        add(place_id, place_spec.slots, world.town.to_unit)
        own = owners.get(place_id, [])
        places[place_id] = tuple(slot for owner in place_spec.owners for slot in owners[owner]) + tuple(own)

    every = {slot.id: slot for slots in owners.values() for slot in slots}
    if len(every) != sum(len(slots) for slots in owners.values()):
        raise ValueError("two slots share an id")
    homes = {
        structure.id: tuple(owners.get(structure.id, ()))
        + tuple(
            slot
            for slot in every.values()
            if slot.kind == "work"
            and slot.skill is not None
            and slot.owner != structure.id
            and world.distance_m(slot.position, structure.door) <= HOME_RADIUS_M
        )
        for structure in world.structures.values()
        if structure.is_home
    }
    return Layout(
        slots=every,
        owners={owner: tuple(slots) for owner, slots in owners.items()},
        places=places,
        homes=homes,
        tasks=frozenset(slot.task for slot in every.values() if slot.kind == "work" and slot.task is not None),
        solids=tuple(solids),
    )


def _site_frame(world: SimWorld, site: Site) -> ToUnit:
    return lambda x, z: site_unit(world.radius_m, site, x, z)


# --- the claims (a system: snapshotted) ---


@dataclass(frozen=True)
class Claim:
    slot: str | None  # None: a spot of the ring fallback
    position: Vec3  # the slot's (inside: the house's middle)
    approach: bool = False  # taken standing still a few steps off: stepped to at the tick's end
    waits_for: str | None = None  # in a queue (or round about) for this owner's stands: moves up when one frees


@dataclass
class SlotState:
    claims: dict[str, Claim] = field(default_factory=dict)  # by citizen id
    layout: Layout | None = field(default=None, compare=False, repr=False)  # built from the world on first use


class _ClaimSnap(_Spec):
    slot: str | None
    at: tuple[float, float, float]
    approach: bool = False
    waits_for: str | None = None


_CLAIMS = TypeAdapter(dict[str, _ClaimSnap])


def _dump(state: SlotState) -> JsonValue:
    snaps = {
        citizen_id: _ClaimSnap(slot=claim.slot, at=claim.position, approach=claim.approach, waits_for=claim.waits_for)
        for citizen_id, claim in sorted(state.claims.items())
    }
    dumped: JsonValue = _CLAIMS.dump_python(snaps, mode="json")
    return dumped


def _load(data: JsonValue) -> SlotState:
    snaps = _CLAIMS.validate_python(data)
    return SlotState(
        claims={
            citizen_id: Claim(snap.slot, snap.at, snap.approach, snap.waits_for) for citizen_id, snap in snaps.items()
        }
    )


SLOTS = System[SlotState]("slots", 1, new=lambda _world: SlotState(), dump=_dump, load=_load)


def slot_state(core: SimCore) -> SlotState:
    return SLOTS.of(core.state)


def layout(core: SimCore) -> Layout:
    state = slot_state(core)
    if state.layout is None:
        state.layout = build_layout(core.world, load_town(), load_slots_spec())
    return state.layout


def claim_of(core: SimCore, citizen: Citizen) -> Claim | None:
    return slot_state(core).claims.get(citizen.id)


def held_slot(core: SimCore, citizen: Citizen) -> Slot | None:
    claim = claim_of(core, citizen)
    return layout(core).slots[claim.slot] if claim is not None and claim.slot is not None else None


def is_inside(core: SimCore, citizen: Citizen) -> bool:
    slot = held_slot(core, citizen)
    return slot is not None and slot.kind == "inside"


def is_moving(citizen: Citizen) -> bool:
    return citizen.action is not None and citizen.action.kind in MOVING


def claim(
    core: SimCore,
    citizen: Citizen,
    slot: Slot | None,
    position: Vec3,
    approach: bool = False,
    waits_for: str | None = None,
) -> Vec3:
    """Take a slot (or a ring spot when `slot` is None), letting go of any other; returns where it is. `approach`:
    taken standing still, so the citizen steps to it at the tick's end (a walk takes them there otherwise);
    `waits_for`: the owner whose stands they would rather have (they move up when one frees)."""
    slot_state(core).claims[citizen.id] = Claim(slot.id if slot is not None else None, position, approach, waits_for)
    return position


def release(core: SimCore, citizen: Citizen) -> None:
    slot_state(core).claims.pop(citizen.id, None)


# --- what is free ---


def _bodies(core: SimCore, but: str) -> list[Vec3]:
    """Where everyone else stands, sits or lies (walkers pass through; those inside a house are out of the way)."""
    return [
        other.position
        for other in core.living()
        if other.id != but and not is_moving(other) and not is_inside(core, other)
    ]


def _taken(core: SimCore, but: str) -> list[Vec3]:
    """Every spot a body or a claim keeps, except the citizen's own (claims inside a house keep none)."""
    spots = _bodies(core, but)
    lay = layout(core)
    for citizen_id, claimed in slot_state(core).claims.items():
        if citizen_id != but and (claimed.slot is None or lay.slots[claimed.slot].kind != "inside"):
            spots.append(claimed.position)
    return spots


def _clear(core: SimCore, spot: Vec3, spots: Iterable[Vec3]) -> bool:
    return all(core.distance_m(spot, other) >= PERSONAL_M for other in spots)


def walkable(core: SimCore, spot: Vec3) -> bool:
    """On the town's walk grid, or on walkable ground clear of a camp's solid props."""
    town = core.world.town_point(spot)
    if town is not None:
        return core.world.town.walk.is_walkable(*town)
    if not core.planner.outer.allowed[core.world.nearest_cell(spot)]:
        return False
    return all(core.distance_m(spot, solid.centre) >= solid.radius_m for solid in layout(core).solids)


def nearest_free(
    core: SimCore, citizen: Citizen, candidates: Iterable[Slot], within_m: float = math.inf
) -> Slot | None:
    """The nearest free slot among the candidates the citizen may take (ties by id): no one else's body or claim
    within PERSONAL_M of it (their own claim counts as free)."""
    spots = _taken(core, citizen.id)
    free = [
        (distance, slot.id, slot)
        for slot in candidates
        if slot.usable_by(citizen)
        and slot.kind != "inside"
        and (distance := core.distance_m(citizen.position, slot.position)) <= within_m
        and _clear(core, slot.position, spots)
    ]
    return min(free)[2] if free else None


def ring_spot(core: SimCore, citizen: Citizen, centre: Vec3, with_centre: bool) -> Vec3 | None:
    """The first walkable spot round `centre` (the centre itself first if `with_centre`) clear of every body and
    claim but the citizen's own: r 1.0, 1.8, 2.6 and 3.4 m, 8 bearings each from north."""
    spots = _taken(core, citizen.id)
    radii = ((0.0,) if with_centre else ()) + RING_M
    for radius in radii:
        for index in range(1 if radius == 0 else RING_BEARINGS):
            spot = (
                centre
                if radius == 0
                else step_towards(centre, index * 360.0 / RING_BEARINGS, radius, core.world.radius_m)
            )
            if walkable(core, spot) and _clear(core, spot, spots):
                return spot
    return None


def free_round(core: SimCore, citizen: Citizen, centre: Vec3, radius: float, bearing: float) -> Vec3 | None:
    """The walkable spot `radius` m from `centre` nearest the bearing (then 30 degrees either way, alternately, round
    to the far side) clear of every body and claim but the citizen's own; None when the ring is full."""
    spots = _taken(core, citizen.id)
    for turn in BESIDE_TURNS:
        spot = step_towards(centre, (bearing + turn) % 360.0, radius, core.world.radius_m)
        if walkable(core, spot) and _clear(core, spot, spots):
            return spot
    return None


# --- where walks go (destinations) ---


def _arrival(core: SimCore, citizen: Citizen, slots: tuple[Slot, ...], anchor: Vec3, with_centre: bool) -> Vec3:
    """Where someone walking to these slots ends, claimed on the way: the nearest free work slot of theirs (the loom
    for a weaver, the stall for the merchant), else the first owner's free stands, then its queue, then the next
    owner's (the granary before the other storehouses), else a ring spot round the anchor. Seats and mats are taken
    by resting and sleeping, not by walking. Anyone in a queue or round about waits for the first owner's stands."""
    chosen = nearest_free(core, citizen, [slot for slot in slots if slot.kind == "work"])
    for owner in dict.fromkeys(slot.owner for slot in slots):
        for kind in ("stand", "queue"):
            if chosen is None:
                chosen = nearest_free(
                    core, citizen, [slot for slot in slots if slot.owner == owner and slot.kind == kind]
                )
    if chosen is not None and chosen.kind != "queue":
        return _walk_claim(core, citizen, chosen, chosen.position)
    waits_for = next((slot.owner for slot in slots if slot.kind == "stand"), None)
    if chosen is not None:
        return _walk_claim(core, citizen, chosen, chosen.position, waits_for)
    spot = ring_spot(core, citizen, anchor, with_centre)
    if spot is None:
        release(core, citizen)
        return anchor
    return _walk_claim(core, citizen, None, spot, waits_for)


def _walk_claim(core: SimCore, citizen: Citizen, slot: Slot | None, spot: Vec3, waits_for: str | None = None) -> Vec3:
    """A walk's claim; a spot under a metre away is no walk ("You are already there"): they step to it instead."""
    near = core.distance_m(citizen.position, spot) < ALREADY_THERE_M
    return claim(core, citizen, slot, spot, approach=near, waits_for=waits_for)


def reserve_place(core: SimCore, citizen: Citizen, place_id: str) -> Vec3:
    place = core.world.places[place_id]
    return _arrival(core, citizen, layout(core).places.get(place_id, ()), place.stand, with_centre=True)


def reserve_home(core: SimCore, citizen: Citizen, home: Structure) -> Vec3:
    return _arrival(core, citizen, layout(core).homes.get(home.id, ()), home.door, with_centre=True)


def reserve_owner(core: SimCore, citizen: Citizen, owner_id: str, centre: Vec3, goal: Vec3) -> Vec3:
    """Walking up to a structure, hearth or prop: one of its slots, else a ring spot round it."""
    slots = layout(core).owners.get(owner_id, ())
    if not slots:
        return reserve_near(core, citizen, goal, with_centre=True)
    return _arrival(core, citizen, slots, centre, with_centre=False)


def reserve_near(core: SimCore, citizen: Citizen, point: Vec3, with_centre: bool) -> Vec3:
    """Walking to a point (a direction, a patch of plants, an animal) or up to a thing on the ground (beside it)."""
    spot = ring_spot(core, citizen, point, with_centre)
    if spot is None:
        release(core, citizen)
        return point
    return _walk_claim(core, citizen, None, spot)


# --- resting, sleeping and working ---


def take_seat(core: SimCore, citizen: Citizen) -> Slot | None:
    """A free seat within SEAT_M (stepped to at the tick's end), else None: they sit where they are."""
    seats = (slot for slot in layout(core).slots.values() if slot.kind == "seat" and slot.task is None)
    seat = nearest_free(core, citizen, seats, SEAT_M)
    if seat is not None:
        claim(core, citizen, seat, seat.position, approach=True)
    return seat


def take_bed(core: SimCore, citizen: Citizen) -> Slot | None:
    """Sleep at home (§4.3): at your house's door, inside; at camp your lean-to's mats first, then the fire's; else
    None (they lie down where they are)."""
    lay = layout(core)
    home = core.world.structures.get(citizen.home) if citizen.home is not None else None
    if home is None:
        return None
    if home.kind != "lean_to":
        if core.distance_m(citizen.position, home.door) > HOME_RADIUS_M:
            return None
        inside = lay.slots[f"{home.id}#inside"]
        claim(core, citizen, inside, inside.position, approach=True)  # in through the door at the tick's end
        return inside
    fire = f"{home.site}:fire-pit"
    for owner in (home.id, fire):  # the fire's mats on their side of it: still at home
        mats = [
            slot
            for slot in lay.owners.get(owner, ())
            if slot.kind == "mat" and core.distance_m(slot.position, home.door) <= HOME_RADIUS_M
        ]
        mat = nearest_free(core, citizen, mats, APPROACH_M)
        if mat is not None:
            claim(core, citizen, mat, mat.position, approach=True)
            return mat
    return None


WorkSpot = Slot | Literal["no slots", "none here", "all taken"]


def take_work_slot(core: SimCore, citizen: Citizen, task: str, area: tuple[Vec3, float]) -> WorkSpot:
    """The slot to do a task at in the area (a place, or round a home's door): the one they hold, else the nearest
    free one they can walk to within the tick (walked to at its end); or why there is none: the task needs no slot,
    none lies in the area, or all those are taken."""
    if task not in layout(core).tasks:
        return "no slots"
    centre, radius_m = area
    near = [
        slot
        for slot in layout(core).slots.values()
        if slot.kind == "work"
        and slot.task == task
        and slot.usable_by(citizen)
        and core.distance_m(centre, slot.position) <= radius_m
    ]
    if not near:
        return "none here"
    spots = _taken(core, citizen.id)
    options = sorted(
        (core.distance_m(citizen.position, slot.position), slot.id, slot)
        for slot in near
        if _clear(core, slot.position, spots)
    )
    for _, _, slot in options:
        if core.distance_m(citizen.position, slot.position) <= OCCUPY_M or _path(core, citizen, slot.position):
            claim(core, citizen, slot, slot.position, approach=True)
            return slot
    return "all taken"


# --- the tick's end ---


def settle(core: SimCore) -> None:
    """A tick hook (after interrupts): free stale claims, step to claims taken standing still, keep bodies apart."""
    state = slot_state(core)
    lay = layout(core)
    for citizen_id in sorted(state.claims):
        citizen = core.state.citizens[citizen_id]
        claimed = state.claims[citizen_id]
        slot = lay.slots[claimed.slot] if claimed.slot is not None else None
        inside = slot is not None and slot.kind == "inside"
        if not _still_held(core, citizen, claimed, slot):
            del state.claims[citizen_id]
            if inside and citizen.body.alive and slot is not None:
                _come_out(core, citizen, core.world.structures[slot.owner])
            continue
        if is_moving(citizen):
            continue
        if core.distance_m(citizen.position, claimed.position) > OCCUPY_M:
            if not step_to(core, citizen, claimed.position, straight=inside):
                del state.claims[citizen_id]
                continue
        elif claimed.waits_for is not None and citizen.id not in core.strides:
            slot = _move_up(core, citizen, claimed.waits_for) or slot
        if slot is not None and citizen.id in core.strides:  # turned as they arrive (a turn is told with a move)
            citizen.heading_deg = slot.heading_deg
    _keep_apart(core)


def _come_out(core: SimCore, citizen: Citizen, home: Structure) -> None:
    """Awake again: out of the door to a free spot before the house (a stand, the queue, else round the door)."""
    step_to(core, citizen, reserve_home(core, citizen, home), straight=True)


def _move_up(core: SimCore, citizen: Citizen, owner: str) -> Slot | None:
    """Someone standing about in a queue (or round about) steps up to a stand of the owner once one frees."""
    if citizen.action is not None and citizen.action.kind != "wait":
        return None
    stands = [slot for slot in layout(core).owners.get(owner, ()) if slot.kind == "stand"]
    stand = nearest_free(core, citizen, stands, APPROACH_M)
    if stand is None or not step_to(core, citizen, stand.position):
        return None
    claim(core, citizen, stand, stand.position)
    return stand


def _still_held(core: SimCore, citizen: Citizen, claimed: Claim, slot: Slot | None) -> bool:
    if not citizen.body.alive:
        return False
    if slot is not None and slot.kind == "inside":
        return citizen.body.asleep
    action = citizen.action
    if is_moving(citizen):
        return action is not None and action.goal == claimed.position
    distance = core.distance_m(citizen.position, claimed.position)
    if distance <= OCCUPY_M:
        return True
    # a walk that stopped short lets go; a claim taken standing still (a seat, a mat) is stepped to
    return claimed.approach and citizen.id not in core.strides


def _keep_apart(core: SimCore) -> None:
    state = slot_state(core)
    bodies = [c for c in core.living() if not is_moving(c) and not is_inside(core, c)]
    placed: list[Vec3] = []
    loose: list[Citizen] = []
    for citizen in bodies:
        claimed = state.claims.get(citizen.id)
        if claimed is not None and core.distance_m(citizen.position, claimed.position) <= OCCUPY_M:
            placed.append(citizen.position)
        else:
            loose.append(citizen)
    loose.sort(key=lambda c: (c.id in core.strides, c.id))  # who stood there first keeps the spot
    for citizen in loose:
        if _clear(core, citizen.position, placed):
            placed.append(citizen.position)
            continue
        spot = ring_spot(core, citizen, citizen.position, with_centre=False)
        if spot is not None and step_to(core, citizen, spot):
            release(core, citizen)  # a ring spot of their own now: any claim of theirs elsewhere is let go
        placed.append(citizen.position)


def step_to(core: SimCore, citizen: Citizen, spot: Vec3, straight: bool = False) -> bool:
    """Move a body a few steps within this tick, drawn as walking: a walk that ended this tick ends at the spot
    instead (a step aside); anyone else walks there from where they stand, round what's in the way (`straight`:
    in or out through a door). False (and no move) when there's no way there within the tick."""
    stride = core.strides.get(citizen.id)
    if stride is not None and len(stride.walked) >= 2:
        walked: list[TimedPoint] = list(stride.walked[:-1])
        if core.distance_m(walked[-1][0], spot) < 0.001:
            walked.pop()
        walked.append((spot, stride.walked[-1][1]))
        if len(walked) < 2:
            walked.insert(0, stride.walked[0])
        core.strides[citizen.id] = Stride(stride.action, tuple(walked), stride.ahead, stride.gait)
    else:
        path = _path(core, citizen, spot, straight)
        if path is None:
            return False
        number = citizen.action.number if citizen.action is not None else 0
        core.strides[citizen.id] = Stride(number, path)
    core.place_at(citizen, spot)
    return True


def _path(core: SimCore, citizen: Citizen, spot: Vec3, straight: bool = False) -> tuple[TimedPoint, ...] | None:
    """The way from where the citizen stands to the spot, timed by distance at their own walking speed: straight for
    a step or two (or through a door), else the planner's route; None when there is none or it takes longer than the
    tick."""
    mps = ground_mps(core, citizen, "walk")
    distance = core.distance_m(citizen.position, spot)
    if distance <= STRAIGHT_M or straight:
        return ((citizen.position, 0.0), (spot, max(MIN_STEP_S, distance / mps)))
    route = core.planner.plan(citizen.position, spot, citizen.cell)
    if route is None:
        return None
    corners = [unit for unit, _cost in walk_along(route, 0, 0.0, math.inf, core.world.radius_m).corners]
    kept: list[TimedPoint] = [(citizen.position, 0.0)]
    walked_m = 0.0
    for unit in corners:
        step_m = core.distance_m(kept[-1][0], unit)
        if step_m >= 0.001:
            walked_m += step_m
            kept.append((unit, walked_m / mps))
    if kept[-1][1] > SECONDS_PER_TICK:
        return None
    return tuple(kept) if len(kept) >= 2 else ((citizen.position, 0.0), (spot, MIN_STEP_S))


# --- measures (run checks and tests) ---


def crowded(core: SimCore) -> list[tuple[str, str, float]]:
    """Pairs of living bodies standing, sitting or lying closer than PERSONAL_M (walkers and those inside left out):
    (id, id, metres). Empty at every tick's end."""
    bodies = [c for c in core.living() if not is_moving(c) and not is_inside(core, c)]
    return [
        (a.id, b.id, distance)
        for index, a in enumerate(bodies)
        for b in bodies[index + 1 :]
        if (distance := core.distance_m(a.position, b.position)) < PERSONAL_M - 1e-9
    ]


def off_work_slot(core: SimCore) -> list[str]:
    """Workers at a task done at slots (the loom, the stall, the paddies) who aren't standing on one of its slots."""
    lay = layout(core)
    off: list[str] = []
    for citizen in core.living():
        action = citizen.action
        if action is None or action.kind != "work" or str(action.item) not in lay.tasks:
            continue
        slot = held_slot(core, citizen)
        on = slot is not None and slot.task == action.item
        if not on or core.distance_m(citizen.position, slot.position if slot else citizen.position) > OCCUPY_M:
            off.append(citizen.id)
    return off
