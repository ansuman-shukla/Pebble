import math

import numpy as np
import pytest
from sqlmodel import Session

from app.sim.items import ITEMS, RESOURCE_INDEX, amount_words
from app.sim.navigation import Planner
from app.sim.vec import angle, bearing_deg, lat_lon_deg, slerp, step_towards
from app.sim.world import TERRAIN_COST, SimWorld, load_sim_world
from app.world.biomes import BIOME_IDS
from app.world.generate import GENERATOR
from app.world.town import load_town


def test_every_town_place_and_structure_door_is_walkable(sim_world: SimWorld) -> None:
    walk = sim_world.town.walk
    for place in sim_world.places.values():
        if place.kind == "town":
            assert walk.is_walkable(*sim_world.town.to_local(place.stand)), place.id
    allowed = Planner(sim_world).outer.allowed
    for structure in sim_world.structures.values():
        if structure.site == "town":
            assert walk.is_walkable(*structure.door_xz), structure.id
        else:  # camps: the door stands on walkable ground outside the town
            assert sim_world.town_point(structure.door) is None, structure.id
            assert allowed[sim_world.nearest_cell(structure.door)], structure.id
        assert math.dist(structure.door_xz, structure.centre_xz) < 8, structure.id


def test_homes_and_storehouses_come_from_the_town_spec_and_the_camps(sim_world: SimWorld) -> None:
    town = load_town()
    houses = {p.id for p in town.placements if p.kind in ("townhouse", "farmhouse", "castle_keep")}
    lean_tos = {f"{camp}:shelter-{side}" for camp in ("band_a_camp", "band_b_camp") for side in "nwe"}
    stores = {p.id for p in town.placements if p.kind == "storehouse"}
    assert {s.id for s in sim_world.structures.values() if s.is_home} == houses | lean_tos
    assert {s.label for s in sim_world.structures.values() if s.kind == "fire_pit"} == {"the fire pit"}
    assert sim_world.structures["castle-keep"].label == "the keep"
    assert {s.id for s in sim_world.structures.values() if s.kind == "storehouse"} == stores
    assert sim_world.structures["well"].label == "the well"
    assert sim_world.structures["main-gate"].label == "the main gate"


def test_town_chart_round_trips_local_metres(sim_world: SimWorld) -> None:
    for x, z in [(0.0, 0.0), (-20.0, 52.5), (150.0, -150.0)]:
        back = sim_world.town.to_local(sim_world.town.to_unit(x, z))
        assert back == pytest.approx((x, z), abs=1e-6)
    assert sim_world.town_point(sim_world.town.to_unit(0, 159)) is not None
    assert sim_world.town_point(sim_world.town.to_unit(0, 161)) is None


def test_cells_inside_the_town_chart_have_no_wild_resources(sim_world: SimWorld) -> None:
    assert 40 < sim_world.in_town.sum() < 200
    assert not sim_world.resource_caps[sim_world.in_town].any()
    forest = sim_world.biomes == BIOME_IDS["broadleaf_forest"]
    assert (sim_world.resource_caps[forest & ~sim_world.in_town, RESOURCE_INDEX["berries"]] == 40).all()
    assert not sim_world.resource_caps[sim_world.biomes == BIOME_IDS["snow"]].any()


def test_terrain_costs_follow_the_world_doc(sim_world: SimWorld) -> None:
    assert (TERRAIN_COST["grassland"], TERRAIN_COST["broadleaf_forest"]) == (1.0, 1.5)
    assert (TERRAIN_COST["hills"], TERRAIN_COST["snow"]) == (2.0, 3.0)
    water = np.isin(sim_world.biomes, [BIOME_IDS[b] for b in ("deep_ocean", "shallow_ocean", "lake")])
    assert np.isinf(sim_world.terrain_cost[water]).all()
    assert np.isfinite(sim_world.terrain_cost[~water]).all()
    assert (sim_world.terrain_cost[sim_world.river] >= 1.5).all()
    assert not (sim_world.river & water).any()


def test_nearest_cell_greedy_walk_matches_a_full_scan(sim_world: SimWorld) -> None:
    rng = np.random.default_rng(3)
    for _ in range(50):
        v = rng.normal(size=3)
        unit = tuple(float(x) for x in v / np.linalg.norm(v))
        hint = int(rng.integers(sim_world.cell_count))
        assert sim_world.nearest_cell(unit, hint) == sim_world.nearest_cell(unit)  # type: ignore[arg-type]


def test_vector_helpers() -> None:
    north_pole, on_equator = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    assert angle(north_pole, on_equator) == pytest.approx(math.pi / 2)
    assert slerp(on_equator, north_pole, 0.5) == pytest.approx((0.0, math.sqrt(0.5), math.sqrt(0.5)))
    assert bearing_deg(on_equator, (0.1, 0.0, 0.995)) == pytest.approx(90, abs=1e-6)
    assert bearing_deg(on_equator, (0.0, 0.1, 0.995)) == pytest.approx(0, abs=1e-6)
    moved = step_towards(on_equator, 90.0, 100.0, 2000.0)
    assert angle(on_equator, moved) * 2000 == pytest.approx(100.0)
    assert lat_lon_deg(moved) == pytest.approx((0.0, math.degrees(0.05)))


def test_amount_words_never_say_numbers() -> None:
    berries = ITEMS["berries"]
    assert [amount_words(n, berries) for n in (1, 3, 12, 40, 41)] == [
        "a berry",
        "a few berries",
        "a handful of berries",
        "plenty of berries",
        "a great many berries",
    ]


def test_the_engine_loads_the_current_world_version_through_the_store(db_session: Session, sim_world: SimWorld) -> None:
    loaded = load_sim_world(db_session)
    assert loaded.generator_version == GENERATOR.version == sim_world.generator_version
    assert np.array_equal(loaded.heights, sim_world.heights)
    assert np.array_equal(loaded.biomes, sim_world.biomes)
    assert loaded.town.height_m == sim_world.town.height_m
