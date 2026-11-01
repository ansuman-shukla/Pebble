"""Animals living, one tick at a time (02-simulation "Ecology", 10-world-v1 §4.6).

```
 groups: wander their range │ herds: drink at the waterhole at dawn and dusk │ predators: night quarry
 every living animal (by id), moving only along its timed course (`courses.py`):
   herbivore: a person or an open predator within its flee distance ─▶ the herd bolts together (herd alarm)
              within twice that ─▶ alert │ drinking time ─▶ waterhole │ night ─▶ sleep │ else follow the herd, graze
   predator:  feeding ─▶ eat, then leave half the meat │ day ─▶ den: sleep, defend it │
              dusk to dawn, hungry ─▶ a lone exposed person (approach, charge, bite: one animal at a time)
                                      or the herd with most members: prowl ─▶ stalk in 10 s sub-steps (`hunt.py`)
                                      ─▶ pounce, or race ─▶ strike ─▶ feed │ pack mates keep by their leader
 ─▶ catches fall due ─▶ everyone walks its course to the tick's end (the path spectators draw)
 ─▶ kills turn to remains after a day ─▶ dead members respawn
```

People are safe from hunting predators near a lit fire, in a group of three or more, inside the town's walls, and by
day; by day a predator at its den charges whoever comes within DEN_CHARGE_M of it (unless they are safe). Every
death and respawn is an event; positions, facing and activity changes go into the tick's `tick_summary`.
"""

import math
from dataclasses import dataclass, field
from typing import cast

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue

from app.core.rng import Rng
from app.observability.events import AnimalGait, AnimalSpawned, Died, Injured, ItemLocation, Target
from app.sim import hunt
from app.sim.clock import DAY_MINUTES, NIGHT_ALTITUDE_DEG, SECONDS_PER_TICK, sun_altitude_deg, sun_direction
from app.sim.core import SimCore
from app.sim.courses import SAME_S, Course, TimedPoint, ahead, at, redirect, tick_start_s, walked
from app.sim.fauna import (
    SPECIES,
    Species,
    can_stand,
    den_of,
    jitter,
    new_animal,
    range_cells,
    range_m,
    standable,
    terrain,
    waterhole_of,
    world_cache,
)
from app.sim.fire import FEAR_M, SAFE_M, lit_fires, near_lit_fire
from app.sim.state import Animal, AnimalActivity, AnimalGroup, Citizen, Fire, System
from app.sim.vec import Vec3, angle, bearing_deg, step_towards
from app.sim.world import SimWorld
from app.world.view import POOL_RADIUS_M

DUSK_ALTITUDE_DEG = 4.0  # predators hunt while the sun is lower than this (dusk, night, dawn)
HUNGRY = 50.0
STARVING = 85.0  # a predator this hungry hunts animals by day too
HUNGER_PER_TICK = 100.0 / (2 * DAY_MINUTES)  # empty to starving in about two days
FED_BY_BITE = 20.0
GRAZE_TICKS = (20, 60)
SLEEP_TICKS = (45, 90)
ALERT_TICKS = (3, 6)  # it stays alert this long after a scare
FROZEN_TICKS = (4, 10)  # a rabbit keeps still at its cover this long
IDLE_TICKS = (4, 10)  # an awake predator looks about this long before it moves on
WANDER_TICKS = (40, 150)  # a group picks its next goal after this long
AMBUSH_TICKS = (60, 120)  # a predator group waits by the waterhole this long from dusk
DRINK_TICKS = 30  # a herd drinks this long at its waterhole (10 §4.6)
DRINK_EDGE_M = (0.6, 2.0)  # round a drawn pool, members drink standing this far out from the water's edge
SPREAD_M = 15.0  # members gather this close around their group's goal
SPACING_M = 2.0  # and keep this far from each other's spots
REJOIN_M = 30.0  # a member further than this from its group's goal walks back
TROT_M = 120.0  # and trots back from this far
ALARM_M = 60.0  # herd alarm: members this close to one that flees flee too (10 §4.6)
ALARM_TURN_DEG = 15.0  # on its bearing, give or take this much
FLIGHT_S = 30.0  # a startled animal without cover runs this long
FLEE_TURNS = (0.0, 30.0, -30.0, 60.0, -60.0, 90.0, -90.0, 135.0, -135.0)
SAMPLE_M = 2.0  # a straight move is checked for water, walls and fires every this many metres
CELL_REACH_M = 60.0  # the cells a line may pass through lie within its length and this of its start cell's centre
NEAR_CELLS_M = 800.0  # each cell keeps the list of cells this close (most lines are shorter)
DETOUR_M = 40.0  # a blocked animal steps aside this far before heading on
WINDED_TICKS = 5  # a burst comes back this long after it was run
PREY_SCENT_M = 400.0  # a hungry predator finds herds this far off
PERSON_SENSE_M = 120.0  # and people (it comes at a lone, exposed one)
CHARGE_M = 40.0  # D68: it charges a lone, exposed person this close
STRIKE_M = 3.0  # a bite's reach
GROUP_SAFE = 3  # people together this many (or more) aren't attacked
GROUP_M = 10.0
GIVE_UP_CHANCE = 0.5  # after a bite the predator lets go
MAX_BITES = 3
RETREAT_M = 150.0
REST_AFTER_TICKS = 120  # after biting a person
MISS_REST_TICKS = 60  # a missed hunt rests 60 min (10 §4.6)
FEED_TICKS = (60, 120)  # a kill is eaten this long (10 §4.6)
PACK_M = 100.0  # pack mates this close share a kill
CARCASS_THREAT_M = 15.0  # people this close threaten a feeding predator: a pack of two holds, a lone one leaves
LEAVE_M = 100.0
DEN_KEEP_M = 40.0  # within this of its den a predator defends it by day (10 §1.6)
DEN_CHARGE_M = 25.0  # against anyone this close to the den
DEN_CHASE_M = DEN_KEEP_M  # and gives the charge up once they are farther than this from the den (its defence ring)
REMAINS_TICKS = DAY_MINUTES  # a predator's kill turns to bones a game day after it died
REMAINS_SHOWN_TICKS = 120  # and lies as bones at least this long before its group replaces it
ESCORT_M = 5.0  # pack mates keep this far to the side of their leader (and 3 m back) per place in the line
POUNCE_S = 0.5
SWIMMING_KINDS = frozenset({"fish", "shark"})
OPEN_TO = frozenset({"prowling", "stalking", "pouncing", "dead", "remains"})  # predators on the hunt go unseen
SPOT_TRIES = 6


@dataclass
class Catch:
    """A race under way: when it ends, and whether the predator catches its prey then (else it gives up)."""

    at_s: float
    prey: str
    caught: bool


@dataclass(frozen=True)
class Walk:
    """This tick's move, for spectators: timed points (game seconds after the tick began) through its end, then the
    plan ahead, and how it went."""

    points: tuple[TimedPoint, ...]
    walked_to: int  # the points up to this index were walked this tick; the rest is the plan ahead
    gait: AnimalGait
    speed_mps: float


@dataclass
class Wildlife:
    courses: dict[str, Course] = field(default_factory=dict)  # animal -> its timed course (absent: standing)
    catches: dict[str, Catch] = field(default_factory=dict)  # predator -> its race under way
    bursts: dict[str, float] = field(default_factory=dict)  # animal -> the game second its last burst began
    carcasses: dict[str, int] = field(default_factory=dict)  # a predator's kill -> meat still on it
    drinks: dict[str, int] = field(default_factory=dict)  # herd -> the tick its drink at the waterhole ends
    charges: dict[str, str] = field(default_factory=dict)  # predator -> "den" or "hunt" while it goes for a person
    tries: dict[str, int] = field(default_factory=dict)  # predator group -> hunts it tried since dusk
    bodies: set[str] = field(default_factory=set)  # dead animals lying as bodies a day before they turn to bones
    shied: dict[str, str] = field(default_factory=dict)  # animal -> who it flees or watches (citizen or animal)
    walks: dict[str, Walk] = field(default_factory=dict)  # this tick's moves (not saved)
    fires: list[Fire] = field(default_factory=list)  # lit fires this tick (not saved)
    bitten: set[str] = field(default_factory=set)  # people bitten this tick: nobody else bites them now (not saved)


def _dump_point(point: TimedPoint) -> JsonValue:
    return [*point[0], float(point[1])]


def _load_point(data: JsonValue) -> TimedPoint:
    x, y, z, t = (float(cast(float, v)) for v in cast(list[JsonValue], data))
    return ((x, y, z), t)


def _dump(life: Wildlife) -> JsonValue:
    return {
        "courses": {
            aid: {
                "points": [_dump_point(p) for p in c.points],
                "gait": c.gait,
                "moving": c.moving,
                "arrive": c.arrive,
            }
            for aid, c in sorted(life.courses.items())
        },
        "catches": {aid: [float(c.at_s), c.prey, c.caught] for aid, c in sorted(life.catches.items())},
        "bursts": {k: float(v) for k, v in sorted(life.bursts.items())},
        "carcasses": dict[str, JsonValue](sorted(life.carcasses.items())),
        "drinks": dict[str, JsonValue](sorted(life.drinks.items())),
        "charges": dict[str, JsonValue](sorted(life.charges.items())),
        "tries": dict[str, JsonValue](sorted(life.tries.items())),
        "bodies": list[JsonValue](sorted(life.bodies)),
        "shied": dict[str, JsonValue](sorted(life.shied.items())),
    }


def _load(data: JsonValue) -> Wildlife:
    if not isinstance(data, dict):
        raise ValueError("a wildlife block is a map")
    block = cast(dict[str, dict[str, JsonValue]], data)
    courses = {
        aid: Course(
            [_load_point(p) for p in cast(list[JsonValue], c["points"])],
            cast(AnimalGait, c["gait"]),
            cast(AnimalActivity, c["moving"]),
            cast(AnimalActivity | None, c["arrive"]),
        )
        for aid, c in cast(dict[str, dict[str, JsonValue]], block["courses"]).items()
    }
    catches = {
        aid: Catch(float(cast(float, v[0])), str(v[1]), bool(v[2]))
        for aid, v in cast(dict[str, list[JsonValue]], block["catches"]).items()
    }
    return Wildlife(
        courses=courses,
        catches=catches,
        bursts={k: float(cast(float, v)) for k, v in block["bursts"].items()},
        carcasses={k: int(cast(int, v)) for k, v in block["carcasses"].items()},
        drinks={k: int(cast(int, v)) for k, v in block["drinks"].items()},
        charges={k: str(v) for k, v in block["charges"].items()},
        tries={k: int(cast(int, v)) for k, v in block["tries"].items()},
        bodies={str(v) for v in cast(list[JsonValue], block["bodies"])},
        shied={k: str(v) for k, v in block["shied"].items()},
    )


def _new(_world: SimWorld) -> Wildlife:
    return Wildlife()


WILDLIFE = System[Wildlife]("wildlife", 1, new=_new, dump=_dump, load=_load)


@dataclass(frozen=True)
class Threat:
    position: Vec3
    distance_m: float
    flee_m: float
    who: str  # citizen or animal id


def step(core: SimCore) -> None:
    state = core.state
    if not state.animals:
        return
    life = WILDLIFE.of(state)
    life.walks.clear()
    life.bitten.clear()
    life.fires = lit_fires(state)
    start, end = tick_start_s(state.tick), tick_start_s(state.tick) + SECONDS_PER_TICK
    living = [state.animals[aid] for aid in sorted(state.animals) if state.animals[aid].alive]
    for group_id in sorted(state.groups):
        _group(core, state.groups[group_id], life)
    herbivores = [a for a in living if not SPECIES[a.kind].predator]
    for animal, threat in zip(herbivores, _threats(core, herbivores, living), strict=True):
        if animal.alive:
            _herbivore(core, animal, threat, life, start)
    for animal in living:
        if animal.alive and SPECIES[animal.kind].predator:
            _predator(core, animal, life, start)
    for group_id in sorted(state.groups):
        _pack(core, state.groups[group_id], life, start)
    _catches(core, life, end)
    for animal_id in sorted(state.animals):
        _advance(core, state.animals[animal_id], life, start, end)
    _remains(core)
    _respawn(core)


def now_s(core: SimCore) -> float:
    """The game second the tick began (what actions do before the animals' step happens then)."""
    return tick_start_s(core.state.tick)


# --- groups ---


def _group(core: SimCore, group: AnimalGroup, life: Wildlife) -> None:
    tick = core.state.tick
    species = SPECIES[group.kind]
    home = core.world.unit(group.home)  # its dawn and dusk: a moving goal can skip the sun's crossing
    spot = group.goal or home
    if not species.predator and not species.swims and _dawn_or_dusk(core, home) and group.id not in life.drinks:
        hole = waterhole_of(core.world, group) or spot
        travel = math.ceil(core.distance_m(spot, hole) / species.walk_mps / SECONDS_PER_TICK)
        life.drinks[group.id] = tick + travel + DRINK_TICKS
        group.goal, group.next_move = hole, life.drinks[group.id]
        return
    if life.drinks.get(group.id, tick) <= tick:
        life.drinks.pop(group.id, None)
    if species.predator and _dusk(core, home):
        life.tries.pop(group.id, None)  # a new night's hunts
        ambush = waterhole_of(core.world, group)
        if ambush is not None:  # it lies in wait where the herds come to drink
            group.goal, group.next_move = ambush, tick + core.state.rng("animals.ambush").randint(*AMBUSH_TICKS)
            return
    if tick < group.next_move or (species.predator and core.altitude(spot) >= DUSK_ALTITUDE_DEG):
        return  # predators stay put by day: asleep at their den, or where the night left them
    rng = core.state.rng("animals.wander")
    group.next_move = tick + rng.randint(*WANDER_TICKS)
    if species.predator and _hungry_pack(core, group):  # it goes where the game is in its range, not just about
        game = _game(core, species, core.world.unit(group.home), spot, range_m(core.world, group))
        if game is not None:
            group.goal = jitter(core.world, game.position, SPREAD_M, rng)
            return
    cells = range_cells(core.world, group)
    cell = int(cells[rng.randint(0, cells.size - 1)])
    goal = jitter(core.world, core.world.unit(cell), 10.0, rng)
    if near_lit_fire(core, goal, FEAR_M * 2):
        return  # keep the old goal: animals stay away from fires
    group.goal = goal


def _hungry_pack(core: SimCore, group: AnimalGroup) -> bool:
    """Its leader (the first living member) is hungry."""
    leader = next((core.state.animals[m] for m in group.members if core.state.animals[m].alive), None)
    return leader is not None and leader.hunger >= HUNGRY


def _dawn_or_dusk(core: SimCore, unit: Vec3) -> bool:
    """The sun rose there this tick, or sank below the dusk line."""
    before = sun_altitude_deg(unit, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    return before <= 0 < core.altitude(unit) or _dusk(core, unit)


def _dusk(core: SimCore, unit: Vec3) -> bool:
    """The sun sank below the dusk line there this tick."""
    before = sun_altitude_deg(unit, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    return before >= DUSK_ALTITUDE_DEG > core.altitude(unit)


# --- herbivores ---


def _herbivore(core: SimCore, animal: Animal, threat: Threat | None, life: Wildlife, start: float) -> None:
    species = SPECIES[animal.kind]
    tick = core.state.tick
    course = life.courses.get(animal.id)
    if animal.activity == "fleeing" and course is not None and course.end_s > start:
        return  # still running
    if threat is not None and threat.distance_m <= threat.flee_m:
        alarm(core, animal, threat.position, threat.who, start)
        return
    asleep = animal.activity == "sleeping"
    if threat is not None and not asleep:
        _halt(animal, life, start)
        animal.activity, animal.until = "alert", tick + core.state.rng("animals.alert").randint(*ALERT_TICKS)
        animal.heading_deg = _heading(animal.position, threat.position, animal.heading_deg)
        life.shied[animal.id] = threat.who
        return
    if course is not None:
        return  # on its way
    group = core.state.groups[animal.group]
    drinking = group.id in life.drinks and group.goal is not None
    if tick < animal.until and not (drinking and animal.activity == "sleeping"):
        return
    rng = core.state.rng("animals.graze")
    if drinking and group.goal is not None:
        pool = _pool(core.world, group.goal)
        if not _at_drink(core, animal.position, group.goal, pool):
            spot = _drink_spot(core, animal, group.goal, pool, rng)
            _walk(core, animal, spot, species.walk_mps, "walk", "drinking", start)
        else:
            animal.activity, animal.until = "drinking", life.drinks[group.id]
            _face_pool(core, animal)
        return
    night = core.altitude(animal.position) < NIGHT_ALTITUDE_DEG and not species.swims
    if group.goal is not None and core.distance_m(animal.position, group.goal) > REJOIN_M:  # back to the herd
        far = core.distance_m(animal.position, group.goal) > TROT_M
        spot = _spot(core, animal, group.goal, SPREAD_M, rng)
        then: AnimalActivity = "sleeping" if night else _resting(core, animal)
        _walk(core, animal, spot, species.trot_mps if far else _walk_mps(core, animal),
              "trot" if far else _gait(core, animal), then, start)  # fmt: skip
        return
    if night:
        animal.activity, animal.until = "sleeping", tick + rng.randint(*SLEEP_TICKS)
        return
    animal.activity, animal.until = _resting(core, animal), tick + rng.randint(*GRAZE_TICKS)


def _resting(core: SimCore, animal: Animal) -> AnimalActivity:
    """What a herbivore does standing about: grazing on land, floating on water, swimming in it."""
    if animal.kind in SWIMMING_KINDS:
        return "swimming"
    if animal.kind == "duck":
        return "floating" if core.world.is_water(animal.cell) else "idle"
    return "grazing"


def _walk_mps(core: SimCore, animal: Animal) -> float:
    species = SPECIES[animal.kind]
    return species.swim_mps if species.swim_mps and core.world.is_water(animal.cell) else species.walk_mps


def _gait(core: SimCore, animal: Animal) -> AnimalGait:
    return "swim" if SPECIES[animal.kind].swims and core.world.is_water(animal.cell) else "walk"


def _spot(core: SimCore, animal: Animal, centre: Vec3, radius_m: float, rng: Rng) -> Vec3:
    """A spot within radius of the centre at least SPACING_M from where its group mates stand or head."""
    taken = [
        _heading_to(core, core.state.animals[member_id])
        for member_id in core.state.groups[animal.group].members
        if member_id != animal.id
    ]
    spot = jitter(core.world, centre, radius_m, rng)
    for _ in range(SPOT_TRIES):
        if all(core.distance_m(spot, other) >= SPACING_M for other in taken):
            break
        spot = jitter(core.world, centre, radius_m, rng)
    return spot


def _pool(world: SimWorld, hole: Vec3) -> bool:
    """Whether the waterhole at `hole` is a drawn pool (no river or lake at hand)."""
    cache = world_cache(world)
    if "pools" not in cache:
        cache["pools"] = [f.position for f in world.features if f.kind == "waterhole" and f.pool]
    return hole in cache["pools"]


def _at_drink(core: SimCore, at: Vec3, hole: Vec3, pool: bool) -> bool:
    """Close enough to drink: round a pool's water (its edge within reach), else near the waterhole."""
    gap = core.distance_m(at, hole)
    if pool:
        return POOL_RADIUS_M <= gap <= POOL_RADIUS_M + DRINK_EDGE_M[1]
    return gap <= SPREAD_M


def _face_pool(core: SimCore, animal: Animal) -> None:
    """A member drinking at a pool turns its head to the water."""
    hole = core.state.groups[animal.group].goal
    if hole is not None and _pool(core.world, hole):
        animal.heading_deg = _heading(animal.position, hole, animal.heading_deg)


def _drink_spot(core: SimCore, animal: Animal, hole: Vec3, pool: bool, rng: Rng) -> Vec3:
    """Where a member goes to drink: a free spot round a pool's water's edge, else near the waterhole."""
    if not pool:
        return _spot(core, animal, hole, SPREAD_M * 0.5, rng)
    taken = [
        _heading_to(core, core.state.animals[member_id])
        for member_id in core.state.groups[animal.group].members
        if member_id != animal.id
    ]

    def edge() -> Vec3:
        out = POOL_RADIUS_M + DRINK_EDGE_M[0] + rng.random() * (DRINK_EDGE_M[1] - DRINK_EDGE_M[0])
        return step_towards(hole, rng.random() * 360.0, out, core.world.radius_m)

    spot = edge()
    for _ in range(SPOT_TRIES):
        if all(core.distance_m(spot, other) >= SPACING_M for other in taken):
            break
        spot = edge()
    return spot


def _heading_to(core: SimCore, animal: Animal) -> Vec3:
    course = WILDLIFE.of(core.state).courses.get(animal.id)
    return course.points[-1][0] if course is not None else animal.position


def _threats(core: SimCore, herbivores: list[Animal], living: list[Animal]) -> list[Threat | None]:
    """For each herbivore: the nearest thing it shies from within twice its flee distance (a person not stalking
    its group, outside the walls, or an open predator: awake and not on the prowl), by its share of that distance."""
    found: list[Threat | None] = [None] * len(herbivores)
    if not herbivores:
        return found
    people = [c for c in core.living() if core.world.town_point(c.position) is None]
    predators = [a for a in living if SPECIES[a.kind].predator and a.activity not in OPEN_TO | {"sleeping"}]
    positions = np.array([a.position for a in herbivores])
    groups = np.array([a.group for a in herbivores])
    candidates: list[tuple[np.ndarray, np.ndarray, list[str], list[Vec3]]] = []
    if people:
        where = np.array([c.position for c in people])
        stalked = np.array([_hunted_group(core, c) or "" for c in people])
        limits = np.array([SPECIES[a.kind].flee_people_m for a in herbivores])
        mask = (stalked[None, :] != groups[:, None]) & (limits[:, None] > 0)
        candidates.append((where, np.where(mask, limits[:, None], 0.0), [c.id for c in people],
                           [c.position for c in people]))  # fmt: skip
    if predators:
        where = np.array([a.position for a in predators])
        limits = np.array([SPECIES[a.kind].flee_predators_m for a in herbivores])
        candidates.append((where, np.repeat(limits[:, None], len(predators), axis=1), [a.id for a in predators],
                           [a.position for a in predators]))  # fmt: skip
    best = np.full(len(herbivores), np.inf)
    for where, limits, ids, units in candidates:
        distances = np.arccos(np.clip(positions @ where.T, -1.0, 1.0)) * core.world.radius_m
        share = np.where(limits > 0, distances / np.where(limits > 0, limits, 1.0), np.inf)
        columns = np.argmin(share, axis=1)
        for row in np.flatnonzero(share[np.arange(len(herbivores)), columns] < np.minimum(best, 2.0)).tolist():
            column = int(columns[row])
            best[row] = share[row, column]
            found[row] = Threat(units[column], float(distances[row, column]), float(limits[row, column]), ids[column])
    return found


def _hunted_group(core: SimCore, person: Citizen) -> str | None:
    """The animal group a person is stalking (a hunter creeping up isn't noticed)."""
    action = person.action
    if action is None or action.kind not in ("hunt", "attack") or action.target_id is None:
        return None
    animal = core.state.animals.get(action.target_id)
    return animal.group if animal is not None else None


def alarm(core: SimCore, animal: Animal, threat: Vec3, who: str, seconds: float) -> None:
    """The herd alarm (10 §4.6): it bolts away from the threat, and every member of its group within ALARM_M of
    it bolts on the same bearing, give or take ALARM_TURN_DEG."""
    life = WILDLIFE.of(core.state)
    here = at(life.courses[animal.id].points, seconds) if animal.id in life.courses else animal.position
    bearing = bearing_deg(threat, here) if threat != here else animal.heading_deg
    _flee(core, animal, bearing, who, seconds)
    rng = core.state.rng("animals.alarm")
    for member_id in core.state.groups[animal.group].members:
        member = core.state.animals[member_id]
        if member.id == animal.id or not member.alive or member.id in life.catches:
            continue
        there = at(life.courses[member.id].points, seconds) if member.id in life.courses else member.position
        if core.distance_m(here, there) <= ALARM_M and not _fleeing(life, member, seconds):
            _flee(core, member, (bearing + (rng.random() * 2 - 1) * ALARM_TURN_DEG) % 360, who, seconds)


def _fleeing(life: Wildlife, animal: Animal, seconds: float) -> bool:
    course = life.courses.get(animal.id)
    return course is not None and course.moving == "fleeing" and course.end_s > seconds


def _flee(core: SimCore, animal: Animal, bearing: float, who: str, seconds: float, winded: bool = False) -> None:
    """Run off on (about) the bearing from `seconds` on: its burst then its sustained speed for FLIGHT_S, or to its
    cover; then alert (frozen at cover)."""
    species = SPECIES[animal.kind]
    life = WILDLIFE.of(core.state)
    tired = winded or _winded(life, animal.id, seconds)
    run = hunt.dash(species, winded=tired)
    flight_s = species.cover_s or FLIGHT_S
    here = at(life.courses[animal.id].points, seconds) if animal.id in life.courses else animal.position
    bearing, room = _flight_line(core, animal, here, bearing, run.metres(flight_s))
    run = hunt.dash(species, winded=tired, room_m=room)
    points = _dash_points(core, here, bearing, run, seconds, flight_s)
    _set(core, animal, seconds, points, "run", "fleeing", _after_flight(animal))
    if not tired:
        life.bursts[animal.id] = seconds
    life.shied[animal.id] = who
    animal.until = core.state.tick + 1
    group = core.state.groups[animal.group]
    if points:
        group.goal = points[-1][0]  # the herd gathers again where the flight ended
        life.drinks.pop(group.id, None)  # scared off its drink


def _winded(life: Wildlife, animal_id: str, seconds: float) -> bool:
    """It ran its burst within the last WINDED_TICKS (a burst begun this very moment is the one it runs now)."""
    began = life.bursts.get(animal_id)
    return began is not None and SAME_S < seconds - began < WINDED_TICKS * SECONDS_PER_TICK


def _after_flight(animal: Animal) -> AnimalActivity:
    """At the end of a flight: frozen at its cover (a rabbit's burrow, a goat's cliff), else alert."""
    return "frozen" if SPECIES[animal.kind].cover_s and animal.kind != "duck" else "alert"


def _flight_line(core: SimCore, animal: Animal, start: Vec3, bearing: float, length_m: float) -> tuple[float, float]:
    """The bearing (the given one, or the nearest turn of it) with the longest clear run up to `length_m`."""
    best = (-1.0, bearing)
    for turn in FLEE_TURNS:
        heading = (bearing + turn) % 360.0
        room = _clear(core, animal, start, heading, length_m)
        if room >= length_m - 1e-6:
            return heading, room
        if room > best[0]:
            best = (room, heading)
    return best[1], best[0]


def _dash_points(core: SimCore, start: Vec3, bearing: float, run: hunt.Dash, seconds: float, length_s: float
                 ) -> list[TimedPoint]:  # fmt: skip
    """Timed points of a straight dash from `start` at `seconds`: where its speed changes and where it ends."""
    if run.metres(length_s) < 1e-6:
        return []
    moments = sorted({*(t for t in run.breaks() if 0 < t < length_s), length_s})
    radius = core.world.radius_m
    return [(step_towards(start, bearing, run.metres(t), radius), seconds + t) for t in moments]


# --- predators ---


def _predator(core: SimCore, animal: Animal, life: Wildlife, start: float) -> None:
    species = SPECIES[animal.kind]
    tick = core.state.tick
    animal.hunger = min(100.0, animal.hunger + HUNGER_PER_TICK)
    if animal.id in life.catches:
        return
    if animal.activity == "pouncing":  # it pounced last tick: now it feeds, or rests
        animal.activity = "idle"
    target = animal.target
    if target is not None and target in core.state.animals and not core.state.animals[target].alive:
        _feed(core, animal, core.state.animals[target], life, start)
        return
    if target is not None and target in core.state.citizens:
        _press(core, animal, core.state.citizens[target], life, start)
        return
    if not _leads(core, animal):
        return  # pack mates keep by their leader (`_pack`)
    group = core.state.groups[animal.group]
    if species.flee_people_m:
        person = _nearest_person(core, animal.position, species.flee_people_m)
        if person is not None:
            alarm(core, animal, person.position, person.id, start)
            return
    if animal.activity == "fleeing" and animal.id in life.courses:
        return
    hunting_time = core.altitude(animal.position) < DUSK_ALTITUDE_DEG
    den = den_of(core.world, group)
    rested = animal.activity == "sleeping" or tick >= animal.until  # not straight after a charge it gave up
    if not hunting_time and rested and den is not None and core.distance_m(animal.position, den) <= DEN_KEEP_M:
        intruder = _den_intruder(core, animal, den)
        if intruder is not None:
            _go_for(core, animal, intruder, "den", life, start)
            return
    if tick < animal.until:
        return
    if not hunting_time and animal.hunger < STARVING:
        _home(core, animal, den, life, start)
        return
    if animal.hunger >= (HUNGRY if hunting_time else STARVING):
        person = _exposed_person(core, animal) if hunting_time and species.bite[1] > 0 else None
        if person is not None:
            _go_for(core, animal, person, "hunt", life, start)
            return
        carcass = _carcass(core, animal) if species.scavenges else None
        if carcass is not None:  # bears live off carcasses before they hunt (10 §4.6)
            animal.target = carcass.id
            animal.until = tick + core.state.rng("animals.scavenge").randint(*FEED_TICKS)
            _feed(core, animal, carcass, life, start)
            return
        quarry = _quarry(core, animal) if life.tries.get(group.id, 0) < hunt.HUNTS_A_NIGHT else None
        if quarry is not None:
            _stalk(core, animal, quarry, life, start)
            return
    if not hunting_time:  # a starving one found nothing close by day: back to sleep
        _home(core, animal, den, life, start)
        return
    if animal.id in life.courses:
        return
    rng = core.state.rng("animals.prowl")
    hungry = animal.hunger >= HUNGRY
    if group.goal is not None and core.distance_m(animal.position, group.goal) > REJOIN_M:
        spot = jitter(core.world, group.goal, SPREAD_M, rng)
        _walk(core, animal, spot, _walk_mps(core, animal), _gait(core, animal),
              "swimming" if species.swims else "idle", start, moving="prowling" if hungry else None)  # fmt: skip
        return
    animal.activity = "swimming" if species.swims else "idle"
    animal.until = tick + rng.randint(*IDLE_TICKS)


def _leads(core: SimCore, animal: Animal) -> bool:
    """The first living member of its group leads its hunts (pack mates follow it)."""
    group = core.state.groups[animal.group]
    leader = next((m for m in group.members if core.state.animals[m].alive), None)
    return leader == animal.id


def _home(core: SimCore, animal: Animal, den: Vec3 | None, life: Wildlife, start: float) -> None:
    """By day: back to its den (or its group), then asleep."""
    if animal.activity == "sleeping" and core.state.tick < animal.until:
        return
    rest = den or core.state.groups[animal.group].goal or core.world.unit(core.state.groups[animal.group].home)
    if core.distance_m(animal.position, rest) > SPREAD_M:
        if animal.id not in life.courses:
            spot = jitter(core.world, rest, SPREAD_M * 0.5, core.state.rng("animals.den"))
            _walk(core, animal, spot, _walk_mps(core, animal), _gait(core, animal), "sleeping", start)
        return
    if SPECIES[animal.kind].swims:
        animal.activity = "swimming"
        return
    animal.activity, animal.until = "sleeping", core.state.tick + core.state.rng("animals.sleep").randint(*SLEEP_TICKS)


def _den_intruder(core: SimCore, animal: Animal, den: Vec3) -> Citizen | None:
    """Someone within DEN_CHARGE_M of the den it guards, not safe (by a fire, in company, inside the walls), whom no
    other animal is going for."""
    options = [
        (distance, person.id, person)
        for person in core.living()
        if (distance := core.distance_m(person.position, den)) <= DEN_CHARGE_M
        and exposed(core, person)
        and not _taken(core, person, animal)
    ]
    return min(options)[2] if options else None


def exposed(core: SimCore, person: Citizen) -> bool:
    """Whether a predator may attack this person: alive, outside the walls, away from fire and not in a group of 3+."""
    if not person.body.alive or core.world.town_point(person.position) is not None:
        return False
    if near_lit_fire(core, person.position, SAFE_M):
        return False
    together = sum(
        1 for other in core.living() if core.distance_m(other.position, person.position) <= GROUP_M
    )  # themselves included
    return together < GROUP_SAFE


def _taken(core: SimCore, person: Citizen, animal: Animal) -> bool:
    """Another animal is going for the person already, or bit them this tick (one bites at a time, 10 §4.6)."""
    if person.id in WILDLIFE.of(core.state).bitten:
        return True
    return any(other.target == person.id and other.id != animal.id for other in core.state.animals.values())


def _exposed_person(core: SimCore, animal: Animal) -> Citizen | None:
    options = [
        (distance, person.id, person)
        for person in core.living()
        if (distance := core.distance_m(animal.position, person.position)) <= PERSON_SENSE_M
        and exposed(core, person)
        and _huntable(core, animal, person)
        and not _taken(core, person, animal)
    ]
    return min(options)[2] if options else None


def _huntable(core: SimCore, animal: Animal, person: Citizen) -> bool:
    """A wolf pack goes only for a person alone, nobody else within GROUP_M (10 §1.6); the rest for anyone exposed."""
    if not SPECIES[animal.kind].lone_people:
        return True
    return not any(
        other.id != person.id and core.distance_m(other.position, person.position) <= GROUP_M for other in core.living()
    )


def _nearest_person(core: SimCore, position: Vec3, within_m: float) -> Citizen | None:
    options = [
        (distance, person.id, person)
        for person in core.living()
        if (distance := core.distance_m(position, person.position)) <= within_m
    ]
    return min(options)[2] if options else None


def _go_for(core: SimCore, animal: Animal, person: Citizen, why: str, life: Wildlife, start: float) -> None:
    animal.target, animal.bites = person.id, 0
    life.charges[animal.id] = why
    _press(core, animal, person, life, start)


def _press(core: SimCore, animal: Animal, person: Citizen, life: Wildlife, start: float) -> None:
    """Going for a person: approach at a walk ("coming at" them), charge from CHARGE_M, bite once beside them. It
    gives up when they are safe (a fire, company, the walls; for a hunt also daylight) or out of reach."""
    species = SPECIES[animal.kind]
    why = life.charges.get(animal.id, "hunt")
    den = den_of(core.world, core.state.groups[animal.group])
    safe = not exposed(core, person) or (
        core.altitude(animal.position) >= DUSK_ALTITUDE_DEG or not _huntable(core, animal, person)
        if why == "hunt"
        else den is None
    )
    distance = core.distance_m(animal.position, person.position)
    if why == "hunt":
        away = distance > PERSON_SENSE_M * 1.5
    else:  # a den is defended within its ring, never chased beyond it (10 §1.6)
        away = den is None or core.distance_m(person.position, den) > DEN_CHASE_M
    if safe or away:
        _give_up(core, animal, retreat_from=None)
        return
    if distance > CHARGE_M and why == "hunt":
        goal = _short_of(core, animal.position, person.position, CHARGE_M * 0.5)
        _walk(core, animal, goal, species.walk_mps, "walk", "alert", start, moving="prowling")
        return
    run = hunt.dash(species, winded=_winded(life, animal.id, start))
    reach = max(0.0, distance - STRIKE_M * 0.5)
    if _clear(core, animal, animal.position, bearing_deg(animal.position, person.position), reach) < reach - 1e-6:
        _give_up(core, animal, retreat_from=None)  # water or walls between them
        return
    arrive_s = run.seconds_to(reach)
    beside = _short_of(core, animal.position, person.position, STRIKE_M * 0.5)
    if arrive_s > SECONDS_PER_TICK:
        midway = _short_of(core, animal.position, person.position, distance - run.metres(SECONDS_PER_TICK))
        _set(core, animal, start, [(midway, start + SECONDS_PER_TICK)], "run", "chasing", "chasing")
        animal.activity = _shown(animal, "chasing")
        return
    if reach > 1e-6:
        _set(core, animal, start, [(beside, start + arrive_s)], "run", "chasing", "attacking")
        if run.burst_mps > species.trot_mps:
            life.bursts[animal.id] = start
    _bite(core, animal, person, why)


def _short_of(core: SimCore, origin: Vec3, target: Vec3, short_m: float) -> Vec3:
    """The point `short_m` before the target on the way to it from origin (origin itself if it's that close)."""
    distance = core.distance_m(origin, target)
    if distance <= short_m:
        return origin
    return step_towards(origin, bearing_deg(origin, target), distance - short_m, core.world.radius_m)


def _bite(core: SimCore, animal: Animal, person: Citizen, why: str) -> None:
    species = SPECIES[animal.kind]
    rng = core.state.rng("animals.bite")
    low, high = species.bite
    amount = low + (high - low) * rng.random()
    animal.heading_deg = _heading(animal.position, person.position, animal.heading_deg)
    animal.activity = "attacking"
    words = f"{species.one} charges you" if why == "den" else f"{species.one} attacks you"
    core.injure(person, amount, "animal attack", words, attacker=animal.id)
    WILDLIFE.of(core.state).bitten.add(person.id)
    animal.bites += 1
    animal.hunger = max(0.0, animal.hunger - FED_BY_BITE)
    if not person.body.alive:
        animal.hunger = 0.0
        animal.target = None
        WILDLIFE.of(core.state).charges.pop(animal.id, None)
        animal.until = core.state.tick + REST_AFTER_TICKS
        return
    if animal.bites >= MAX_BITES or rng.random() < GIVE_UP_CHANCE:
        _give_up(core, animal, retreat_from=person.position)


def _quarry(core: SimCore, animal: Animal) -> Animal | None:
    """The nearest member of the herd it goes for: among herds of its prey with a member within PREY_SCENT_M, the one
    with the most members, the nearest of those (so kills spread over the herds, 10 §4.6)."""
    return _game(core, SPECIES[animal.kind], animal.position, animal.position, PREY_SCENT_M)


def _game(core: SimCore, species: Species, around: Vec3, origin: Vec3, within_m: float) -> Animal | None:
    """The herd a predator goes for among its prey's herds with a member within `within_m` of `around` (the kind it
    prefers first): the one with the most members, the nearest to `origin` of those; its member nearest `origin`."""
    herds: dict[str, list[tuple[float, str, Animal]]] = {}
    for other in core.state.animals.values():
        if other.alive and other.kind in species.prey and can_stand(core.world, species, other.cell):
            if core.distance_m(around, other.position) <= within_m:
                herds.setdefault(other.group, []).append((core.distance_m(origin, other.position), other.id, other))
    if not herds:
        return None
    preferred = {group: members for group, members in herds.items() if members[0][2].kind in species.prefers}
    herds = preferred or herds
    sizes = {group: sum(core.state.animals[m].alive for m in core.state.groups[group].members) for group in herds}
    chosen = min(herds, key=lambda group: (-sizes[group], min(herds[group])[0], group))
    return min(herds[chosen])[2]


def _carcass(core: SimCore, animal: Animal) -> Animal | None:
    """The nearest kill still lying fresh (not yet bones) within PREY_SCENT_M that no other group feeds on."""
    eaten = {a.target for a in core.state.animals.values() if a.alive and a.target and a.group != animal.group}
    options = [
        (distance, body.id, body)
        for body in core.state.animals.values()
        if body.activity == "dead"
        and body.id not in eaten
        and can_stand(core.world, SPECIES[animal.kind], body.cell)
        and (distance := core.distance_m(animal.position, body.position)) <= PREY_SCENT_M
    ]
    return min(options)[2] if options else None


def _stalk(core: SimCore, animal: Animal, quarry: Animal, life: Wildlife, start: float) -> None:
    """Prowl up to its stalk distance, then stalk in 10 s sub-steps: each, the quarry may notice it; unseen inside its
    pounce range it pounces; noticed, it races (10 §4.6). The rolls are on `animals.hunt`."""
    species, prey = SPECIES[animal.kind], SPECIES[quarry.kind]
    animal.target = quarry.id
    gap = core.distance_m(animal.position, quarry.position)
    if gap > species.stalk_m:
        goal = _short_of(core, animal.position, quarry.position, species.stalk_m * 0.9)
        _walk(core, animal, goal, species.walk_mps, "walk", "stalking", start, moving="prowling")
        if animal.id not in life.courses:  # nowhere to go: give it up for now
            animal.target, animal.until = None, core.state.tick + IDLE_TICKS[1]
        return
    rng = _hunt_rng(core)
    step_m = hunt.stalk_step_m(species)
    points: list[TimedPoint] = []
    here = animal.position
    for k in range(round(SECONDS_PER_TICK / hunt.SUB_STEP_S)):
        moment = start + k * hunt.SUB_STEP_S
        there = _where(life, quarry, moment)
        gap = core.distance_m(here, there)
        if gap > species.stalk_m * 1.5 or not quarry.alive:
            break  # it wandered off: prowl after it next tick
        sensed = hunt.sense(gap, species, prey, rng)
        if sensed != "unseen":
            life.tries[animal.group] = life.tries.get(animal.group, 0) + 1
            if points:
                _set(core, animal, start, points, "stalk", "stalking", None)
            if sensed == "pounce":
                _set(core, animal, moment, [(there, moment + POUNCE_S)], "run", "pouncing", "pouncing")
                _strike(core, animal, quarry, moment + POUNCE_S)
            else:
                _race(core, animal, quarry, moment, here, there)
            return
        move = min(step_m, max(0.0, gap - species.pounce_m * 0.5))
        bearing = bearing_deg(here, there)
        if _clear(core, animal, here, bearing, move) < move - 1e-6:
            animal.target, animal.until = None, core.state.tick + IDLE_TICKS[1]
            break
        here = step_towards(here, bearing, move, core.world.radius_m)
        points.append((here, moment + hunt.SUB_STEP_S))
    if points:
        _set(core, animal, start, points, "stalk", "stalking", "stalking")
    animal.activity = "stalking" if animal.target is not None else "idle"


def _hunt_rng(core: SimCore) -> Rng:
    """The hunt's rolls: sensing and the strike (10 §4.6: one stream, `animals.hunt`)."""
    return core.state.rng("animals.hunt")


def _where(life: Wildlife, animal: Animal, seconds: float) -> Vec3:
    course = life.courses.get(animal.id)
    return at(course.points, seconds) if course is not None else animal.position


def _race(core: SimCore, animal: Animal, quarry: Animal, seconds: float, here: Vec3, there: Vec3) -> None:
    """The quarry noticed it at `seconds`: both run (the 1-D race of `hunt.py`), the quarry's herd bolts with it.
    The predator runs to where the quarry was, then along its line; it catches it where its run reaches the gap plus
    the quarry's run, or gives up when the race ends."""
    life = WILDLIFE.of(core.state)
    species, prey = SPECIES[animal.kind], SPECIES[quarry.kind]
    tick = core.state.tick
    gap = core.distance_m(here, there)
    length_s = hunt.race_seconds(species, prey)
    flight = hunt.dash(prey, winded=_winded(life, quarry.id, seconds))
    bearing, room = _flight_line(core, quarry, there, bearing_deg(here, there), flight.metres(length_s))
    flight = hunt.dash(prey, winded=_winded(life, quarry.id, seconds), room_m=room)
    run = hunt.dash(species, winded=_winded(life, animal.id, seconds))
    to_quarry = _clear(core, animal, here, bearing_deg(here, there), gap)  # it stops where it can't follow
    follow = _clear(core, animal, there, bearing, run.metres(length_s)) if to_quarry >= gap - 1e-6 else 0.0
    run = hunt.dash(species, winded=_winded(life, animal.id, seconds), room_m=to_quarry + follow)
    caught_s = hunt.catch_time(run, flight, gap, length_s)
    end_s = caught_s if caught_s is not None else length_s
    radius = core.world.radius_m
    _set(core, quarry, seconds, _dash_points(core, there, bearing, flight, seconds, end_s), "run", "fleeing",
         None if caught_s is not None else _after_flight(quarry))  # fmt: skip
    quarry.until, life.shied[quarry.id] = tick + 1, animal.id
    for runner in (quarry.id, animal.id):
        if not _winded(life, runner, seconds):
            life.bursts[runner] = seconds

    def place(metres: float) -> Vec3:
        if metres <= gap:
            return step_towards(here, bearing_deg(here, there), metres, radius) if gap > 0 else here
        return step_towards(there, bearing, metres - gap, radius)

    moments = sorted({*(t for t in (*run.breaks(), run.seconds_to(gap)) if 0 < t < end_s), end_s})
    _set(core, animal, seconds, [(place(run.metres(t)), seconds + t) for t in moments if run.metres(t) > 0],
         "run", "chasing", None)  # fmt: skip
    animal.activity = "chasing"
    life.catches[animal.id] = Catch(seconds + end_s, quarry.id, caught_s is not None)
    for member_id in core.state.groups[quarry.group].members:  # the herd bolts with it
        member = core.state.animals[member_id]
        mate_at = _where(life, member, seconds)
        if member.id != quarry.id and member.alive and core.distance_m(mate_at, there) <= ALARM_M:
            if not _fleeing(life, member, seconds):
                turn = (core.state.rng("animals.bolt").random() * 2 - 1) * ALARM_TURN_DEG
                _flee(core, member, (bearing + turn) % 360, animal.id, seconds)


def _catches(core: SimCore, life: Wildlife, end: float) -> None:
    """Races that end by the tick's end, in time order: a catch is struck at, a miss rests."""
    due = sorted((catch.at_s, aid) for aid, catch in life.catches.items() if catch.at_s <= end + 1e-6)
    for _, predator_id in due:
        catch = life.catches.pop(predator_id)
        predator = core.state.animals.get(predator_id)
        prey = core.state.animals.get(catch.prey)
        if predator is None or not predator.alive:
            continue
        if catch.caught and prey is not None and prey.alive:
            _strike(core, predator, prey, catch.at_s)
        else:
            _rest(core, predator)


def _strike(core: SimCore, animal: Animal, prey: Animal, seconds: float) -> None:
    """It has caught its prey at `seconds`: a kill by its strike chance (× the prey's fight-back), else the prey
    breaks free and runs, and it rests."""
    life = WILDLIFE.of(core.state)
    species = SPECIES[animal.kind]
    animal.activity = "pouncing"
    animal.heading_deg = _heading(animal.position, prey.position, animal.heading_deg)
    if _hunt_rng(core).random() < hunt.strike_chance(species, SPECIES[prey.kind]):
        kill(core, prey, f"killed by {species.one}", attacker=animal.id, seconds=seconds)
        life.carcasses[prey.id] = SPECIES[prey.kind].meat // 2
        until = core.state.tick + core.state.rng("animals.feed").randint(*FEED_TICKS)
        carcass = _where(life, prey, seconds)
        for member_id in core.state.groups[animal.group].members:
            mate = core.state.animals[member_id]
            if mate.alive and (mate.id == animal.id or core.distance_m(_where(life, mate, seconds), carcass) <= PACK_M):
                mate.target, mate.until, mate.hunger = prey.id, until, 0.0
                life.catches.pop(mate.id, None)
        return
    _rest(core, animal)
    _flee(core, prey, (bearing_deg(animal.position, prey.position)) % 360, animal.id, seconds, winded=True)


def _rest(core: SimCore, animal: Animal) -> None:
    """A missed hunt: it rests a while before it hunts again."""
    animal.target = None
    animal.until = core.state.tick + MISS_REST_TICKS
    if animal.activity not in ("pouncing",):
        animal.activity = _shown(animal, "idle")


def _feed(core: SimCore, animal: Animal, carcass: Animal, life: Wildlife, start: float) -> None:
    """At its kill until it has eaten (then the meat left drops beside the carcass); people close by drive a lone
    feeder off (a pack of two or more holds)."""
    tick = core.state.tick
    if carcass.id not in core.state.animals or tick >= animal.until:
        _leave_carcass(core, animal, carcass)
        animal.activity, animal.until = _shown(animal, "idle"), tick + IDLE_TICKS[0]
        return
    person = _nearest_person(core, carcass.position, CARCASS_THREAT_M)
    feeders = [
        m
        for m in core.state.groups[animal.group].members
        if core.state.animals[m].alive and core.state.animals[m].target == carcass.id
    ]
    if person is not None and len(feeders) < 2:
        _leave_carcass(core, animal, carcass)
        away = step_towards(animal.position, bearing_deg(person.position, animal.position), LEAVE_M,
                            core.world.radius_m)  # fmt: skip
        _walk(core, animal, away, SPECIES[animal.kind].trot_mps, "trot", "idle", start)
        animal.until = tick + MISS_REST_TICKS
        return
    if core.distance_m(animal.position, carcass.position) > STRIKE_M * 2:
        if animal.id not in life.courses:
            beside = _short_of(core, animal.position, carcass.position, STRIKE_M * 0.6)
            _walk(core, animal, beside, SPECIES[animal.kind].trot_mps, "trot", "feeding", start)
        return
    if person is not None:
        animal.activity = "alert"
        animal.heading_deg = _heading(animal.position, person.position, animal.heading_deg)
        return
    animal.activity, animal.hunger = "feeding", 0.0  # it eats
    animal.heading_deg = _heading(animal.position, carcass.position, animal.heading_deg)


def _leave_carcass(core: SimCore, animal: Animal, carcass: Animal) -> None:
    """It stops feeding; the last to leave lets the meat left drop as ground `meat` (scavengers may take it)."""
    animal.target = None
    life = WILDLIFE.of(core.state)
    still = [a for a in core.state.animals.values() if a.alive and a.target == carcass.id]
    meat = life.carcasses.get(carcass.id, 0)
    if still or carcass.id not in life.carcasses:
        return
    del life.carcasses[carcass.id]
    if meat <= 0 or carcass.id not in core.state.animals:
        return
    stack = core.new_stack("meat", meat, carcass.position, carcass.cell)
    core.item_moved(
        None,
        "meat",
        meat,
        ItemLocation(kind="animal", id=carcass.id, cell=carcass.cell),
        ItemLocation(kind="ground", id=stack.id, cell=stack.cell, position=stack.position),
    )


def _give_up(core: SimCore, animal: Animal, retreat_from: Vec3 | None) -> None:
    species = SPECIES[animal.kind]
    life = WILDLIFE.of(core.state)
    carcass = core.state.animals.get(animal.target or "")
    if carcass is not None and not carcass.alive:
        _leave_carcass(core, animal, carcass)
    animal.target, animal.bites = None, 0
    why = life.charges.pop(animal.id, "hunt")
    animal.until = core.state.tick + REST_AFTER_TICKS // 2
    start = now_s(core)
    if animal.activity != "attacking":
        animal.activity = _shown(animal, "idle")
    life.catches.pop(animal.id, None)
    if retreat_from is not None:
        den = den_of(core.world, core.state.groups[animal.group])
        away = (
            den
            if why == "den" and den is not None
            else step_towards(
                animal.position, bearing_deg(retreat_from, animal.position), RETREAT_M, core.world.radius_m
            )
        )
        _walk(core, animal, away, species.trot_mps, "trot", "idle", start, keep_walked=True)
    elif animal.id in life.courses:
        _halt(animal, life, start)


def scatter(core: SimCore, animal: Animal, threat: Vec3, who: str) -> None:
    """A missed animal bolts away from the hunter with its herd (10 §4.6: the scatter after a missed hunt)."""
    if SPECIES[animal.kind].predator:
        drive_off(core, animal, threat)
    else:
        alarm(core, animal, threat, who, now_s(core))


def drive_off(core: SimCore, animal: Animal, threat: Vec3) -> None:
    """A predator struck by a person gives up its quarry and retreats, its pack with it (D75)."""
    for member_id in core.state.groups[animal.group].members:
        member = core.state.animals[member_id]
        if member.alive:
            _give_up(core, member, retreat_from=threat)


def kill(
    core: SimCore,
    animal: Animal,
    cause: str,
    cause_seq: int | None = None,
    attacker: str | None = None,
    seconds: float | None = None,
    remains: bool = False,
) -> int:
    """An animal dies where it is at `seconds` (the tick's start by default): a predator's kill lies `dead` a day,
    then turns to `remains`; a hunter's (`remains`) at once. The remains stay until its group replaces it."""
    life = WILDLIFE.of(core.state)
    moment = now_s(core) if seconds is None else seconds
    course = life.courses.get(animal.id)
    if course is not None:
        life.courses[animal.id] = redirect(course, animal.position, moment, [], course.gait, course.moving, None)
    for other in (life.catches, life.bursts, life.shied):
        other.pop(animal.id, None)
    animal.alive, animal.health, animal.activity = False, 0.0, "remains" if remains else "dead"
    if not remains:
        life.bodies.add(animal.id)
    animal.goal, animal.target, animal.died_tick = None, None, core.state.tick
    return core.emit("died", Died(cause=cause, attacker=attacker), actor=animal, cause_seq=cause_seq)


def wound(
    core: SimCore, animal: Animal, amount: float, cause: str, cause_seq: int | None = None, attacker: str | None = None
) -> bool:
    """Hurt an animal (an `injured` event); True if it died of it."""
    amount = round(min(amount, animal.health), 2)
    animal.health = max(0.0, animal.health - amount)
    seq = core.emit("injured", Injured(amount=amount, cause=cause, attacker=attacker), actor=animal,
                    cause_seq=cause_seq)  # fmt: skip
    if animal.health <= 0:
        kill(core, animal, cause, seq, attacker=attacker)
        return True
    return False


# --- pack mates ---


def _pack(core: SimCore, group: AnimalGroup, life: Wildlife, start: float) -> None:
    """Pack mates keep by their leader: in line beside it (ESCORT_M to a side, 3 m back per place, by the way it
    faces as the tick begins) along its course, doing what it does, never faster than it went on each leg (a mate
    that falls behind keeps its lag); asleep or still beside it."""
    species = SPECIES[group.kind]
    members = [core.state.animals[m] for m in group.members if core.state.animals[m].alive]
    if not species.predator or len(members) < 2:
        return
    leader = members[0]
    lead = life.courses.get(leader.id)
    for place, mate in enumerate(members[1:], start=1):
        if mate.id in life.catches or mate.target is not None or _fleeing(life, mate, start):
            continue
        side = ESCORT_M * math.ceil(place / 2) * (1 if place % 2 else -1)
        back = 3.0 * math.ceil(place / 2)
        if lead is None or lead.end_s <= start:
            slot = _beside(core, leader.position, leader.heading_deg, side, back)
            if core.distance_m(mate.position, slot) > SPREAD_M:
                if mate.id not in life.courses:
                    _walk(core, mate, slot, species.trot_mps, "trot", leader.activity, start)
            else:
                life.courses.pop(mate.id, None)
                mate.activity, mate.until = leader.activity, leader.until
                mate.heading_deg = leader.heading_deg
            continue
        points: list[TimedPoint] = []
        last, last_s, lag = _where(life, mate, start), start, 0.0
        leg_from, leg_s = lead.points[0]
        for unit, seconds in lead.points:
            if seconds <= start + 1e-6:
                leg_from, leg_s = unit, seconds
                continue
            # one offset for the whole course (its legs as long as the leader's), the leader's own spot if blocked
            spots = (_beside(core, unit, leader.heading_deg, side, back), unit)
            follow = next((spot for spot in spots if _open(core, mate, last, spot)), None)
            if follow is None:
                break  # it can't follow that way
            # as long as the leader took on the leg, any way further at its sustained speed: it never runs its burst
            # longer, nor anything faster, than its leader did
            extra_m = max(0.0, core.distance_m(last, follow) - core.distance_m(leg_from, unit))
            there_s = max(seconds + lag, last_s + max(seconds - leg_s, 0.0)) + extra_m / species.trot_mps
            lag = there_s - seconds
            points.append((follow, there_s))
            last, last_s, leg_from, leg_s = follow, there_s, unit, seconds
        _set(core, mate, start, points, lead.gait, lead.moving, lead.arrive or leader.activity)
        mate.activity = leader.activity


def _open(core: SimCore, animal: Animal, origin: Vec3, goal: Vec3) -> bool:
    """The straight way from origin to goal is clear for it."""
    distance = core.distance_m(origin, goal)
    return distance < 1e-6 or _clear(core, animal, origin, bearing_deg(origin, goal), distance) >= distance - 1e-6


def _beside(core: SimCore, unit: Vec3, heading_deg: float, side_m: float, back_m: float) -> Vec3:
    """The spot `side_m` to the right (negative: left) and `back_m` behind a body facing `heading_deg` there."""
    facing = (180.0 - heading_deg) % 360  # the compass bearing it faces
    radius = core.world.radius_m
    behind = step_towards(unit, (facing + 180.0) % 360, back_m, radius)
    return step_towards(behind, (facing + 90.0) % 360, side_m, radius) if side_m else behind


# --- moving ---


def _walk(
    core: SimCore,
    animal: Animal,
    goal: Vec3,
    mps: float,
    gait: AnimalGait,
    arrive: AnimalActivity,
    start: float,
    moving: AnimalActivity | None = None,
    keep_walked: bool = False,
) -> None:
    """Walk (trot, swim) straight towards the goal from the tick's start, as far as the way is clear; blocked at
    once, step aside somewhere at random instead. `keep_walked`: from where the course this tick has got it to."""
    life = WILDLIFE.of(core.state)
    seconds = start
    origin = animal.position
    if keep_walked and animal.id in life.courses:
        seconds = max(start, min(life.courses[animal.id].end_s, start + SECONDS_PER_TICK))
        origin = at(life.courses[animal.id].points, seconds)
    distance = core.distance_m(origin, goal)
    if distance < 0.01:
        return
    bearing = bearing_deg(origin, goal)
    room = _clear(core, animal, origin, bearing, distance)
    if room < 1.0:
        bearing = core.state.rng("animals.detour").random() * 360.0
        room = _clear(core, animal, origin, bearing, DETOUR_M)
        if room < 1.0:
            return
        goal = step_towards(origin, bearing, room, core.world.radius_m)
    elif room < distance - 1e-6:
        goal = step_towards(origin, bearing, room, core.world.radius_m)
    walking: AnimalActivity = moving or _moving_word(gait)
    _set(core, animal, seconds, [(goal, seconds + min(room, distance) / mps)], gait, walking, arrive)


def _moving_word(gait: AnimalGait) -> AnimalActivity:
    if gait == "swim":
        return "swimming"
    return "trotting" if gait in ("trot", "run") else "walking"


def _set(
    core: SimCore,
    animal: Animal,
    seconds: float,
    points: list[TimedPoint],
    gait: AnimalGait,
    moving: AnimalActivity,
    arrive: AnimalActivity | None,
) -> None:
    """Its course from `seconds` on (it moves only along courses)."""
    life = WILDLIFE.of(core.state)
    if not points:
        return
    moving, arrive = _shown(animal, moving), _shown(animal, arrive) if arrive is not None else None
    course = redirect(life.courses.get(animal.id), animal.position, seconds, points, gait, moving, arrive)
    life.courses[animal.id] = course
    animal.goal, animal.activity = course.points[-1][0], moving
    span = course.end_s - seconds
    animal.pace_m = core.distance_m(at(course.points, seconds), course.points[-1][0]) / span * 60 if span > 0 else 0.0
    animal.heading_deg = _heading(at(course.points, seconds), points[0][0], animal.heading_deg)


def _halt(animal: Animal, life: Wildlife, seconds: float) -> None:
    """Stop where its course has it at `seconds`."""
    course = life.courses.get(animal.id)
    if course is not None and course.end_s > seconds:
        life.courses[animal.id] = redirect(course, animal.position, seconds, [], course.gait, course.moving, None)
        animal.goal = None


def _shown(animal: Animal, activity: AnimalActivity) -> AnimalActivity:
    """What it is drawn doing: fish and sharks only swim (fast at gait run) or, sharks, attack (10 §4.6)."""
    if animal.kind in SWIMMING_KINDS and activity not in ("swimming", "attacking", "dead", "remains"):
        return "swimming"
    return activity


def _heading(origin: Vec3, target: Vec3, current: float) -> float:
    if origin == target:
        return current
    return round((180.0 - bearing_deg(origin, target)) % 360.0, 2)


def _clear(core: SimCore, animal: Animal, start: Vec3, bearing: float, length_m: float) -> float:
    """How far it can go straight on the bearing (up to `length_m`): ground it may stand on, outside the walls and
    not nearer a lit fire than FEAR_M (unless that takes it away from the fire); checked every SAMPLE_M."""
    if length_m <= 0:
        return 0.0
    world = core.world
    radius = world.radius_m
    steps = max(1, math.ceil(length_m / SAMPLE_M))
    metres = np.arange(1, steps + 1) * (length_m / steps)
    origin = np.array(start)
    east = np.cross((0.0, 1.0, 0.0), origin)  # the frame of `vec.step_towards`
    if np.linalg.norm(east) < 1e-9:
        east = np.cross((0.0, 0.0, 1.0), origin)
    east = east / np.linalg.norm(east)
    turn = math.radians(bearing)
    heading = np.cross(origin, east) * math.cos(turn) + east * math.sin(turn)
    angles = metres / radius
    points = origin[None, :] * np.cos(angles)[:, None] + heading[None, :] * np.sin(angles)[:, None]
    near = _cells_near(world, world.nearest_cell(start, animal.cell), length_m + CELL_REACH_M)
    cells = near[np.argmax(points @ world.grid.positions[near].T, axis=1)]
    ok = standable(world, animal.kind)[cells].copy()
    towny = terrain(world).near_town[cells]
    if towny.any():
        ok[towny] &= ~world.town.holds(points[towny])
    for fire in WILDLIFE.of(core.state).fires:
        where = np.array(fire.position)
        near_m = np.arccos(np.clip(points @ where, -1.0, 1.0)) * radius
        ok &= ~((near_m <= FEAR_M) & (near_m <= core.distance_m(start, fire.position)))
    blocked = np.flatnonzero(~ok)
    if not blocked.size:
        return length_m
    return float(metres[blocked[0] - 1]) if blocked[0] > 0 else 0.0


def _cells_near(world: SimWorld, cell: int, reach_m: float) -> NDArray[np.int64]:
    """The cells within `reach_m` of a cell's centre (from a list kept per cell up to NEAR_CELLS_M, nearest first)."""
    if reach_m > NEAR_CELLS_M:
        positions = world.grid.positions
        found: NDArray[np.int64] = np.flatnonzero(positions @ positions[cell] >= math.cos(reach_m / world.radius_m))
        return found
    cache = world_cache(world)
    key = ("near cells", cell)
    if key not in cache:
        positions = world.grid.positions
        angles = np.arccos(np.clip(positions @ positions[cell], -1.0, 1.0))
        inside = np.flatnonzero(angles <= NEAR_CELLS_M / world.radius_m)
        order = np.argsort(angles[inside], kind="stable")
        cache[key] = (inside[order], angles[inside][order] * world.radius_m)
    cells, metres = cache[key]
    return cast(NDArray[np.int64], cells[: int(np.searchsorted(metres, reach_m, side="right"))])


def _advance(core: SimCore, animal: Animal, life: Wildlife, start: float, end: float) -> None:
    """It walks its course to the tick's end: where it stands then, the path drawn, and what it does on arrival."""
    course = life.courses.get(animal.id)
    if course is None:
        return
    done = walked(course.points, start, end)
    plan = ahead(course.points, end, end + SECONDS_PER_TICK)
    metres = sum(angle(a, b) for (a, _), (b, _) in zip(done, done[1:], strict=False)) * core.world.radius_m
    if metres >= 0.001:
        first_move = min(t0 for (a, t0), (b, _) in zip(done, done[1:], strict=False) if angle(a, b) > 0)
        last_move = max(t1 for (a, _), (b, t1) in zip(done, done[1:], strict=False) if angle(a, b) > 0)
        span = max(1e-6, last_move - first_move)
        life.walks[animal.id] = Walk(
            tuple((unit, seconds - start) for unit, seconds in (*done, *plan)),
            len(done) - 1,
            course.gait,
            round(metres / span, 2),
        )
        legs = [(a, b) for (a, _), (b, _) in zip(done, done[1:], strict=False) if angle(a, b) > 0]
        animal.heading_deg = _heading(legs[-1][0], legs[-1][1], animal.heading_deg)
        _place(core, animal, done[-1][0])
    if course.end_s <= end + 1e-6:
        del life.courses[animal.id]
        animal.goal = None
        if animal.alive and course.arrive is not None:
            _arrive(core, animal, course.arrive)
    else:
        later = [point for point in course.points if point[1] > end + 1e-6]
        life.courses[animal.id] = Course([(done[-1][0], end), *later], course.gait, course.moving, course.arrive)
        if animal.alive:
            animal.activity = course.moving


ARRIVE_TICKS: dict[str, tuple[int, int]] = {
    "grazing": GRAZE_TICKS,
    "floating": GRAZE_TICKS,
    "swimming": GRAZE_TICKS,
    "idle": IDLE_TICKS,
    "alert": ALERT_TICKS,
    "frozen": FROZEN_TICKS,
    "sleeping": SLEEP_TICKS,
}


def _arrive(core: SimCore, animal: Animal, activity: AnimalActivity) -> None:
    tick = core.state.tick
    if activity == "drinking":
        animal.activity = "drinking"
        animal.until = WILDLIFE.of(core.state).drinks.get(animal.group, tick + DRINK_TICKS)
        _face_pool(core, animal)
        return
    if activity in ("grazing", "floating") and not SPECIES[animal.kind].predator:
        activity = _resting(core, animal)
    animal.activity = _shown(animal, activity)
    if activity in ARRIVE_TICKS:  # never cutting short a rest it is due (after a charge, a missed hunt)
        animal.until = max(animal.until, tick + core.state.rng("animals.arrive").randint(*ARRIVE_TICKS[activity]))


def _place(core: SimCore, animal: Animal, position: Vec3) -> None:
    animal.position = position
    animal.cell = core.world.nearest_cell(position, animal.cell)
    animal.height_m = float(terrain(core.world).surface_m[animal.cell])


# --- remains and respawning ---


def _remains(core: SimCore) -> None:
    """A predator's kill turns to bones a game day after it died."""
    tick = core.state.tick
    for animal_id in sorted(core.state.animals):
        animal = core.state.animals[animal_id]
        if animal.activity == "dead" and animal.died_tick is not None and tick >= animal.died_tick + REMAINS_TICKS:
            animal.activity = "remains"


def _respawn(core: SimCore) -> None:
    state = core.state
    life = WILDLIFE.of(state)
    tick = state.tick
    for group_id in sorted(state.groups):
        group = state.groups[group_id]
        days = SPECIES[group.kind].respawn_days
        for slot, member_id in enumerate(group.members):
            dead = state.animals[member_id]
            due = round(days * DAY_MINUTES)
            if member_id in life.bodies:  # a body lies a day: its bones show a while before it is replaced
                due = max(due, REMAINS_TICKS + REMAINS_SHOWN_TICKS)
            if dead.alive or dead.died_tick is None or tick < dead.died_tick + due:
                continue
            living = [state.animals[m] for m in group.members if state.animals[m].alive]
            cell = living[0].cell if living else group.home
            animal = new_animal(core.world, group, state.next_animal, cell, state.rng("animals.respawn"))
            state.next_animal += 1
            del state.animals[member_id]
            life.courses.pop(member_id, None)
            life.carcasses.pop(member_id, None)
            life.bodies.discard(member_id)
            state.animals[animal.id] = animal
            group.members[slot] = animal.id
            core.emit(
                "animal_spawned",
                AnimalSpawned(
                    id=animal.id,
                    kind=animal.kind,
                    group=group.id,
                    position=animal.position,
                    height_m=animal.height_m,
                    cell=animal.cell,
                    heading_deg=animal.heading_deg,
                    replaces=member_id,
                ),
                actor=animal,
            )


# --- what it is after, in words (the spectators' feed) ---


def aim(core: SimCore, animal: Animal) -> tuple[str, Target | None]:
    """What the animal is after ("stalking a deer", "fleeing Kenji", "drinking at the waterhole") and at whom."""
    life = WILDLIFE.of(core.state)
    target = _target(core, animal.target) if animal.target else None
    shied = _target(core, life.shied[animal.id]) if animal.id in life.shied else None
    activity = animal.activity
    group = core.state.groups.get(animal.group)
    if activity in ("fleeing", "alert", "frozen") and shied is not None:
        shy = {"fleeing": "fleeing", "alert": "watching", "frozen": "hiding from"}[activity]
        return f"{shy} {shied.name}", shied
    if target is not None:
        quarry = core.state.animals.get(animal.target or "")
        if quarry is not None and not quarry.alive:
            return f"feeding on {target.name}", target
        verb = {"stalking": "stalking", "chasing": "chasing", "pouncing": "pouncing on", "attacking": "attacking"}
        if target.kind == "animal":  # a quarry is stalked, prowled up to or chased; only people are "come at"
            verb |= {"prowling": "stalking", "swimming": "stalking"}
        return f"{verb.get(activity, 'coming at')} {target.name}", target
    if group is not None and group.id in life.drinks and group.goal is not None:
        place = Target(kind="place", name="the waterhole", position=group.goal)
        return ("drinking at the waterhole" if activity == "drinking" else "heading to the waterhole"), place
    words = {"grazing": "grazing", "sleeping": "asleep", "prowling": "on the prowl", "walking": "with its group",
             "trotting": "catching up with its group", "feeding": "feeding", "dead": "", "remains": ""}  # fmt: skip
    return words.get(activity, ""), None


def _target(core: SimCore, ref: str) -> Target | None:
    if ref in core.state.citizens:
        person = core.state.citizens[ref]
        return Target(kind="person", id=person.id, name=person.name, position=person.position)
    if ref in core.state.animals:
        other = core.state.animals[ref]
        return Target(kind="animal", id=other.id, name=SPECIES[other.kind].one, position=other.position)
    return None
