"""Animals living, one tick at a time (02-simulation "Ecology").

```
 group goals ─▶ every living animal (by id):
   herbivore: people or a predator close? ─▶ run away │ night ─▶ sleep │ else follow the herd: walk, then graze
   predator:  quarry? ─▶ chase it ─▶ close: bite the person / try to bring the animal down
              dusk or night and hungry ─▶ a lone, exposed person within a short range, else prey within sense
              by day ─▶ sleep (a starving one hunts animals, never people)
 ─▶ move towards goals (never into town, onto the wrong ground, or near a lit fire) ─▶ dead members respawn
```

People are safe from predators near a lit fire, in a group of three or more, inside the town's walls, and by day.
Every death and respawn is an event; positions, facing and activity changes go into the tick's `tick_summary`.
"""

import math

import numpy as np
from numpy.typing import NDArray

from app.observability.events import AnimalSpawned, Died, Injured
from app.sim.clock import NIGHT_ALTITUDE_DEG
from app.sim.core import SimCore
from app.sim.fauna import (
    SPECIES,
    Species,
    can_stand,
    in_town_walls,
    jitter,
    new_animal,
    range_cells,
    terrain,
    world_cache,
)
from app.sim.fire import FEAR_M, SAFE_M, lit_fires, near_lit_fire
from app.sim.state import Animal, AnimalGroup, Citizen
from app.sim.vec import Vec3, bearing_deg, normalize, step_towards

DUSK_ALTITUDE_DEG = 4.0  # predators hunt while the sun is lower than this (dusk, night, dawn)
HUNGRY = 50.0
STARVING = 85.0  # a predator this hungry hunts animals by day too
HUNGER_PER_TICK = 100.0 / (2 * 1440)  # empty to starving in about two days
FED_BY_BITE = 20.0
GRAZE_TICKS = (20, 60)
PROWL_TICKS = (4, 10)  # an awake predator looks for quarry again after this long
SLEEP_TICKS = (45, 90)
WANDER_TICKS = (40, 150)  # a group picks its next goal after this long
SPREAD_M = 15.0  # members gather this close around their group's goal
REJOIN_M = 30.0  # a member further than this from its group's goal walks back
PREDATOR_SENSE_M = 40.0  # herbivores run from an awake predator this close
FLEE_TICKS = 2  # a startled animal runs this many minutes at full speed
HUNT_SENSE_M = 150.0  # predators find animal prey this far off
STALK_M = 40.0  # a hungry predator goes for an exposed person this close (02: "within a short range")
STRIKE_M = 3.0
CHASE_TICKS = 10  # a chase that hasn't closed in by then is given up
GROUP_SAFE = 3  # people together this many (or more) aren't attacked
GROUP_M = 10.0
GIVE_UP_CHANCE = 0.5  # after a bite the predator lets go
MAX_BITES = 3
RETREAT_M = 150.0
REST_AFTER_TICKS = 120  # after a kill, a failed chase or a fight
PACK_FED_M = 100.0  # pack members this close share a kill
DETOUR_M = 40.0  # a blocked animal steps aside this far before heading on

FloatArray = NDArray[np.float64]


def step(core: SimCore) -> None:
    state = core.state
    living = [state.animals[aid] for aid in sorted(state.animals) if state.animals[aid].alive]
    for group_id in sorted(state.groups):
        _group(core, state.groups[group_id])
    if living:
        threatened = _threats(core, living)
        afraid = _near_fires(core, living)
        for animal, threat in zip(living, threatened, strict=True):
            if not animal.alive:  # killed earlier this tick
                continue
            if SPECIES[animal.kind].predator:
                _predator(core, animal)
            else:
                _herbivore(core, animal, threat)
            _move(core, animal, afraid)
    _respawn(core)


# --- groups ---


def _group(core: SimCore, group: AnimalGroup) -> None:
    tick = core.state.tick
    if tick < group.next_move:
        return
    rng = core.state.rng("animals.wander")
    group.next_move = tick + rng.randint(*WANDER_TICKS)
    cells = _range(core, group)
    cell = int(cells[rng.randint(0, cells.size - 1)])
    goal = jitter(core.world, core.world.unit(cell), 10.0, rng)
    if near_lit_fire(core, goal, FEAR_M * 2):
        return  # keep the old goal: animals stay away from fires
    group.goal = goal


def _range(core: SimCore, group: AnimalGroup) -> NDArray[np.int64]:
    cache = world_cache(core.world)
    cells: NDArray[np.int64] | None = cache.get(("range", group.kind, group.home))
    if cells is None:
        cells = cache[("range", group.kind, group.home)] = range_cells(core.world, group.kind, group.home)
    return cells


# --- herbivores ---


def _herbivore(core: SimCore, animal: Animal, threat: Vec3 | None) -> None:
    species = SPECIES[animal.kind]
    tick = core.state.tick
    rng = core.state.rng("animals.graze")
    if threat is not None:
        bearing = (bearing_deg(threat, animal.position) + rng.random() * 40 - 20) % 360
        run_m = species.run_m * FLEE_TICKS
        _go(animal, step_towards(animal.position, bearing, run_m, core.world.radius_m), species.run_m)
        animal.activity, animal.until = "running", tick + 3
        return
    if animal.goal is not None or tick < animal.until:
        return
    if core.altitude(animal.position) < NIGHT_ALTITUDE_DEG and not species.swims:
        animal.activity, animal.until = "sleeping", tick + rng.randint(*SLEEP_TICKS)
        return
    group = core.state.groups[animal.group]
    if group.goal is not None and core.distance_m(animal.position, group.goal) > REJOIN_M:
        _go(animal, jitter(core.world, group.goal, SPREAD_M, rng), species.walk_m)
        return
    animal.activity = "idle" if species.swims else "grazing"
    animal.until = tick + rng.randint(*GRAZE_TICKS)


def _threats(core: SimCore, living: list[Animal]) -> list[Vec3 | None]:
    """For each animal: the nearest thing it runs from (a person not stalking its group, or an awake predator)."""
    found: list[Vec3 | None] = [None] * len(living)
    herbivores = [i for i, animal in enumerate(living) if not SPECIES[animal.kind].predator]
    people = [c for c in core.living() if core.world.town_point(c.position) is None]
    predators = [a for a in living if SPECIES[a.kind].predator and a.activity != "sleeping"]
    if not herbivores or not (people or predators):
        return found
    group_ids = {group_id: number for number, group_id in enumerate(sorted(core.state.groups))}
    where = np.array([p.position for p in people] + [a.position for a in predators])
    stalked = np.array(
        [group_ids.get(_hunted_group(core, p) or "", -1) for p in people] + [-1] * len(predators), dtype=np.int64
    )
    reach = np.array([0.0] * len(people) + [PREDATOR_SENSE_M] * len(predators))
    positions = np.array([living[i].position for i in herbivores])
    flee = np.array([SPECIES[living[i].kind].flee_m for i in herbivores])
    groups = np.array([group_ids[living[i].group] for i in herbivores], dtype=np.int64)
    distances = np.arccos(np.clip(positions @ where.T, -1.0, 1.0)) * core.world.radius_m
    limits = np.where(reach[None, :] > 0, reach[None, :], flee[:, None])
    close = (distances <= limits) & (stalked[None, :] != groups[:, None])
    for row in np.flatnonzero(close.any(axis=1)).tolist():
        column = int(np.argmin(np.where(close[row], distances[row], np.inf)))
        found[herbivores[row]] = tuple(float(v) for v in where[column])  # type: ignore[assignment]
    return found


def _hunted_group(core: SimCore, person: Citizen) -> str | None:
    """The animal group a person is stalking (a hunter creeping up isn't noticed)."""
    action = person.action
    if action is None or action.kind not in ("hunt", "attack") or action.target_id is None:
        return None
    animal = core.state.animals.get(action.target_id)
    return animal.group if animal is not None else None


# --- predators ---


def _predator(core: SimCore, animal: Animal) -> None:
    species = SPECIES[animal.kind]
    tick = core.state.tick
    rng = core.state.rng("animals.prowl")
    animal.hunger = min(100.0, animal.hunger + HUNGER_PER_TICK)
    altitude = core.altitude(animal.position)
    hunting_time = altitude < DUSK_ALTITUDE_DEG or species.swims
    if animal.target is not None:
        _chase(core, animal, hunting_time)
        return
    if tick < animal.until:
        return
    hungry = animal.hunger >= HUNGRY if hunting_time else animal.hunger >= STARVING
    if hungry:
        person = _exposed_person(core, animal) if hunting_time and species.bite[1] > 0 else None
        quarry: Citizen | Animal | None = person or _prey(core, animal)
        if quarry is not None:
            animal.target, animal.bites, animal.until = quarry.id, 0, tick + CHASE_TICKS
            _go(animal, quarry.position, species.run_m)
            animal.activity = "hunting"
            return
    if not hunting_time and not species.swims:
        animal.activity, animal.until = "sleeping", tick + rng.randint(*SLEEP_TICKS)
        return
    group = core.state.groups[animal.group]
    if group.goal is not None and core.distance_m(animal.position, group.goal) > REJOIN_M:
        _go(animal, jitter(core.world, group.goal, SPREAD_M, rng), species.walk_m)
        return
    # awake: prowl about the group's goal and look again in a few minutes
    animal.activity, animal.until = "idle", tick + rng.randint(*PROWL_TICKS)


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


def _exposed_person(core: SimCore, animal: Animal) -> Citizen | None:
    options = [
        (distance, person.id, person)
        for person in core.living()
        if (distance := core.distance_m(animal.position, person.position)) <= STALK_M and exposed(core, person)
    ]
    return min(options)[2] if options else None


def _prey(core: SimCore, animal: Animal) -> Animal | None:
    prey_kinds = SPECIES[animal.kind].prey
    options = [
        (distance, other.id, other)
        for other in core.state.animals.values()
        if other.alive
        and other.kind in prey_kinds
        and (distance := core.distance_m(animal.position, other.position)) <= HUNT_SENSE_M
    ]
    return min(options)[2] if options else None


def _chase(core: SimCore, animal: Animal, hunting_time: bool) -> None:
    species = SPECIES[animal.kind]
    tick = core.state.tick
    target = animal.target
    person = core.state.citizens.get(target) if target is not None else None
    quarry = core.state.animals.get(target) if target is not None and person is None else None
    if person is not None:
        if not (hunting_time and exposed(core, person)):
            _give_up(core, animal, retreat_from=None)
            return
        position = person.position
    elif quarry is not None and quarry.alive:
        position = quarry.position
    else:
        _give_up(core, animal, retreat_from=None)
        return
    distance = core.distance_m(animal.position, position)
    if distance > STRIKE_M + species.run_m:
        if tick >= animal.until:
            _give_up(core, animal, retreat_from=None)
        else:
            _go(animal, position, species.run_m)
            animal.activity = "hunting"
        return
    if distance > STRIKE_M:
        _arrive_beside(core, animal, position)
    if person is not None:
        _bite(core, animal, person)
    elif quarry is not None:
        _bring_down(core, animal, quarry)


def _arrive_beside(core: SimCore, animal: Animal, position: Vec3) -> None:
    """Close the last stretch to its quarry this tick (stopping just short of it)."""
    distance = core.distance_m(animal.position, position)
    share = max(0.0, (distance - STRIKE_M * 0.5) / distance)
    animal.goal = None
    _place(core, animal, _towards(animal.position, position, share))


def _bite(core: SimCore, animal: Animal, person: Citizen) -> None:
    species = SPECIES[animal.kind]
    rng = core.state.rng("animals.bite")
    low, high = species.bite
    amount = low + (high - low) * rng.random()
    animal.heading_deg = _heading(animal.position, person.position, animal.heading_deg)
    core.injure(person, amount, "animal attack", f"{species.one} attacks you")
    animal.bites += 1
    animal.hunger = max(0.0, animal.hunger - FED_BY_BITE)
    if not person.body.alive:
        animal.hunger = 0.0
        animal.target, animal.goal = None, None
        animal.activity, animal.until = "idle", core.state.tick + REST_AFTER_TICKS
        return
    if animal.bites >= MAX_BITES or rng.random() < GIVE_UP_CHANCE:
        _give_up(core, animal, retreat_from=person.position)
    else:
        animal.until = core.state.tick + CHASE_TICKS


def _bring_down(core: SimCore, animal: Animal, quarry: Animal) -> None:
    species = SPECIES[animal.kind]
    rng = core.state.rng("animals.prey")
    if rng.random() < species.hunt_chance:
        kill(core, quarry, f"killed by {species.one}")
        for other in core.state.animals.values():
            if (
                other.alive
                and other.group == animal.group
                and core.distance_m(other.position, animal.position) <= PACK_FED_M
            ):
                other.hunger = 0.0
        animal.target, animal.goal = None, None
        animal.activity, animal.until = "idle", core.state.tick + REST_AFTER_TICKS
    else:
        _give_up(core, animal, retreat_from=None)


def _give_up(core: SimCore, animal: Animal, retreat_from: Vec3 | None) -> None:
    species = SPECIES[animal.kind]
    animal.target, animal.bites, animal.goal = None, 0, None
    animal.activity, animal.until = "idle", core.state.tick + REST_AFTER_TICKS // 2
    if retreat_from is not None:
        away = bearing_deg(retreat_from, animal.position)
        _go(animal, step_towards(animal.position, away, RETREAT_M, core.world.radius_m), species.run_m)
        animal.activity = "running"


def run_from(core: SimCore, animal: Animal, bearing: float) -> None:
    """Bolt off in the compass bearing (a herbivore startled by a hunter)."""
    run_m = SPECIES[animal.kind].run_m
    _go(animal, step_towards(animal.position, bearing, run_m * FLEE_TICKS, core.world.radius_m), run_m)
    animal.until = core.state.tick + 3


def drive_off(core: SimCore, animal: Animal, threat: Vec3) -> None:
    """A predator struck by a person gives up its quarry and retreats."""
    _give_up(core, animal, retreat_from=threat)


def kill(core: SimCore, animal: Animal, cause: str, cause_seq: int | None = None) -> int:
    """An animal dies where it stands (its remains stay until its group replaces it)."""
    animal.alive, animal.health, animal.activity = False, 0.0, "dead"
    animal.goal, animal.target, animal.died_tick = None, None, core.state.tick
    return core.emit("died", Died(cause=cause), actor=animal, cause_seq=cause_seq)


def wound(core: SimCore, animal: Animal, amount: float, cause: str, cause_seq: int | None = None) -> bool:
    """Hurt an animal (an `injured` event); True if it died of it."""
    amount = round(min(amount, animal.health), 2)
    animal.health = max(0.0, animal.health - amount)
    seq = core.emit("injured", Injured(amount=amount, cause=cause), actor=animal, cause_seq=cause_seq)
    if animal.health <= 0:
        kill(core, animal, cause, seq)
        return True
    return False


# --- moving ---


def _go(animal: Animal, goal: Vec3, pace_m: float) -> None:
    animal.goal, animal.pace_m = goal, pace_m
    animal.heading_deg = _heading(animal.position, goal, animal.heading_deg)
    animal.activity = "running" if pace_m > SPECIES[animal.kind].walk_m else "walking"


def _heading(origin: Vec3, target: Vec3, current: float) -> float:
    if origin == target:
        return current
    return round((180.0 - bearing_deg(origin, target)) % 360.0, 2)


def _towards(origin: Vec3, goal: Vec3, share: float) -> Vec3:
    """A fraction of the way along the chord (≈ the arc for the short steps animals take), back on the sphere."""
    return normalize(
        (
            origin[0] + (goal[0] - origin[0]) * share,
            origin[1] + (goal[1] - origin[1]) * share,
            origin[2] + (goal[2] - origin[2]) * share,
        )
    )


def _near_fires(core: SimCore, living: list[Animal]) -> set[str]:
    """Animals close enough to a lit fire that their next step must be checked against it."""
    fires = lit_fires(core.state)
    if not fires:
        return set()
    positions = np.array([animal.position for animal in living])
    where = np.array([fire.position for fire in fires])
    reach = (FEAR_M + 320.0) / core.world.radius_m  # the fastest animal's run
    close = (positions @ where.T >= math.cos(reach)).any(axis=1)
    return {living[i].id for i in np.flatnonzero(close).tolist()}


def _move(core: SimCore, animal: Animal, afraid: set[str]) -> None:
    goal = animal.goal
    if goal is None or not animal.alive:
        return
    distance = core.distance_m(animal.position, goal)
    share = 1.0 if distance <= animal.pace_m else animal.pace_m / distance
    position = goal if share >= 1.0 else _towards(animal.position, goal, share)
    species = SPECIES[animal.kind]
    if not _allowed(core, species, animal, position, afraid):
        animal.goal = None
        animal.activity, animal.until = "idle", core.state.tick + 5
        if animal.target is not None and species.predator:
            _give_up(core, animal, retreat_from=None)
        else:  # water, walls or a fire in the way: step aside somewhere at random and try again from there
            bearing = core.state.rng("animals.detour").random() * 360.0
            _go(animal, step_towards(animal.position, bearing, DETOUR_M, core.world.radius_m), species.walk_m)
        return
    _place(core, animal, position)
    if share >= 1.0:
        animal.goal = None
        if animal.target is None:
            rng = core.state.rng("animals.arrive")
            animal.activity = "grazing" if not species.predator and not species.swims else "idle"
            animal.until = core.state.tick + rng.randint(*GRAZE_TICKS)


def _allowed(core: SimCore, species: Species, animal: Animal, position: Vec3, afraid: set[str]) -> bool:
    cell = core.world.nearest_cell(position, animal.cell)
    if not can_stand(core.world, species, cell) or in_town_walls(core.world, cell, position):
        return False
    if animal.id in afraid and near_lit_fire(core, position, FEAR_M):
        return core.distance_m(animal.position, position) == 0 or _moving_away(core, animal.position, position)
    return True


def _moving_away(core: SimCore, before: Vec3, after: Vec3) -> bool:
    """A step that ends near a lit fire is allowed only away from it (an animal caught near a new fire gets out)."""
    fires = [fire for fire in lit_fires(core.state) if core.distance_m(after, fire.position) <= FEAR_M]
    return all(core.distance_m(after, f.position) > core.distance_m(before, f.position) for f in fires)


def _place(core: SimCore, animal: Animal, position: Vec3) -> None:
    animal.position = position
    animal.cell = core.world.nearest_cell(position, animal.cell)
    animal.height_m = float(terrain(core.world).surface_m[animal.cell])


# --- respawning ---


def _respawn(core: SimCore) -> None:
    state = core.state
    tick = state.tick
    for group_id in sorted(state.groups):
        group = state.groups[group_id]
        days = SPECIES[group.kind].respawn_days
        for slot, member_id in enumerate(group.members):
            dead = state.animals[member_id]
            if dead.alive or dead.died_tick is None or tick < dead.died_tick + round(days * 1440):
                continue
            living = [state.animals[m] for m in group.members if state.animals[m].alive]
            cell = living[0].cell if living else group.home
            animal = new_animal(core.world, group, state.next_animal, cell, state.rng("animals.respawn"))
            state.next_animal += 1
            del state.animals[member_id]
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
