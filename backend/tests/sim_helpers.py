from functools import cache
from typing import Any, get_args

import numpy as np

from app.observability.events import RoutePoint
from app.sim.citizens import CitizenSpec
from app.sim.clock import local_minute, sun_altitude_deg, sun_direction
from app.sim.fauna import terrain
from app.sim.simulation import Simulation
from app.sim.state import Animal, AnimalGroup, Citizen
from app.sim.vec import Vec3, bearing_deg, lat_lon_deg
from app.sim.world import SimWorld, sim_world_from_view
from app.world.biomes import BIOME_IDS
from app.world.generate import GENERATOR
from app.world.spec import load_site_kinds, load_world_spec
from app.world_api.models import Compass

GATE = (0.0, 104.0)  # just outside the main gate
WELL = (-20.0, 52.5)
HOME = "main-w-3"


@cache
def real_world() -> SimWorld:
    return sim_world_from_view(GENERATOR.generate(load_world_spec(), load_site_kinds()))


def drawn_on(route: list[RoutePoint], seconds: float) -> Vec3:
    """Where a spectator draws a mover `seconds` (game) after the tick began: along the streamed route by its times,
    straight between its points (as the globe does), standing at its end once there."""
    times = [point.t_s for point in route]
    if any(t is None for t in times):
        raise ValueError("an untimed route")
    for a, b in zip(route, route[1:], strict=False):
        if a.t_s is not None and b.t_s is not None and seconds <= b.t_s:
            share = max(0.0, (seconds - a.t_s) / (b.t_s - a.t_s))
            mixed = np.array(a.unit) + (np.array(b.unit) - np.array(a.unit)) * share
            x, y, z = (mixed / np.linalg.norm(mixed)).tolist()
            return (x, y, z)
    return route[-1].unit


def make_spec(citizen_id: str = "tester", **overrides: Any) -> CitizenSpec:
    fields: dict[str, Any] = {
        "id": citizen_id,
        "name": citizen_id.capitalize(),
        "look": "town-farmer",
        "appearance": f"a person in a {citizen_id} cloak",
        "age": 25,
        "at": GATE,
        "home": HOME,
        "knows_places": ["town", "well", "main-gate"],
    }
    fields.update(overrides)
    return CitizenSpec(**fields)


def without_animals(sim: Simulation) -> Simulation:
    """A world with no animals, for tests about something else that put citizens out in the wild."""
    sim.state.animals.clear()
    sim.state.groups.clear()
    return sim


def add_animal(sim: Simulation, kind: str, position: Vec3, **fields: Any) -> Animal:
    """One animal of the kind (in a group of its own) at the position, with any fields overridden."""
    world, state = sim.world, sim.state
    cell = world.nearest_cell(position)
    group = AnimalGroup(id=f"test-group:{len(state.groups) + 1}", kind=kind, home=cell, size=1)
    animal = Animal(
        id=f"{kind}:{state.next_animal}",
        kind=kind,
        group=group.id,
        position=position,
        cell=cell,
        height_m=float(terrain(world).surface_m[cell]),
        **fields,
    )
    state.next_animal += 1
    group.members.append(animal.id)
    state.groups[group.id] = group
    state.animals[animal.id] = animal
    return animal


def move_animal(sim: Simulation, animal: Animal, position: Vec3) -> None:
    animal.position = position
    animal.cell = sim.world.nearest_cell(position)
    animal.height_m = float(terrain(sim.world).surface_m[animal.cell])


def wild_cell(sim: Simulation, biome: str = "grassland", clear_m: float = 1000.0, flat_m: float | None = None) -> int:
    """A walkable cell of the biome at least `clear_m` from every site (nobody lives there); with `flat_m`, one whose
    neighbours and theirs lie within that many metres of its height (walks from it don't climb)."""
    world = sim.world
    for cell in range(world.cell_count):
        if world.biome(cell) != biome or not sim.core.planner.outer.allowed[cell] or world.river[cell]:
            continue
        around = {far for near in world.neighbours[cell] for far in world.neighbours[near]}
        if flat_m is not None and any(abs(world.heights[other] - world.heights[cell]) > flat_m for other in around):
            continue
        if all(world.distance_m(world.unit(cell), place.centre) >= clear_m for place in world.places.values()):
            if all(sim.core.planner.outer.allowed[other] for other in world.neighbours[cell]):
                return cell
    raise LookupError(f"no clear {biome} cell")


def put_in_the_wild(sim: Simulation, citizen_id: str, cell: int) -> Citizen:
    citizen = sim.citizen(citizen_id)
    sim.core.place_at(citizen, sim.world.unit(cell))
    return citizen


def skip_to(sim: Simulation, position: Vec3, night: bool) -> None:
    """Jump the clock (between ticks) to the next deep night (sun below -12°) or full day (above 20°) there."""
    tick = sim.tick
    while True:
        altitude = sun_altitude_deg(position, sun_direction(tick + 1, sim.world.town_lon_deg))
        if (night and altitude < -12) or (not night and altitude > 20):
            sim.state.tick = tick
            return
        tick += 1


def nearest_cell_of(world: SimWorld, biomes: tuple[str, ...], origin: Vec3) -> int:
    ids = [BIOME_IDS[name] for name in biomes]
    candidates = np.flatnonzero(np.isin(world.biomes, ids))
    angles = world.grid.positions[candidates] @ np.array(origin)
    return int(candidates[np.argmax(angles)])


def compass_towards(origin: Vec3, target: Vec3) -> Compass:
    names: tuple[Compass, ...] = get_args(Compass)
    return names[int((bearing_deg(origin, target) + 22.5) // 45) % 8]


def local_hour(sim: Simulation, citizen_id: str) -> float:
    _, lon = lat_lon_deg(sim.citizen(citizen_id).position)
    return local_minute(sim.tick, sim.world.town_lon_deg, lon) / 60
