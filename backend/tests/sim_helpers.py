from functools import cache
from typing import Any, get_args

import numpy as np

from app.sim.citizens import CitizenSpec
from app.sim.clock import local_minute
from app.sim.simulation import Simulation
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
