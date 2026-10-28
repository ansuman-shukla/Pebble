import numpy as np

from app.world.biomes import BIOME_IDS, classify, hop_distance, temperature, walkable
from app.world.grid import build_grid
from app.world.spec import load_world_spec

SPEC = load_world_spec()


def _classify(height: float, temp_c: float, wetness: float, **flags: bool) -> str:
    one = np.ones(1, dtype=bool)
    biome = classify(
        SPEC.biomes,
        np.array([height]),
        np.array([temp_c]),
        np.array([wetness]),
        ocean=one & flags.get("ocean", False),
        lake=one & flags.get("lake", False),
        coast=one & flags.get("coast", False),
        shelf_m=SPEC.terrain.shelf_m,
        beach_m=SPEC.terrain.beach_m,
    )
    return list(BIOME_IDS)[int(biome[0])]


def test_classify_follows_water_cold_height_then_climate() -> None:
    assert _classify(-80, 20, 0.5, ocean=True) == "deep_ocean"
    assert _classify(-10, 20, 0.5, ocean=True) == "shallow_ocean"
    assert _classify(30, 15, 0.5, lake=True) == "lake"
    assert _classify(30, -20, 0.5, lake=True) == "ice"
    assert _classify(5, -20, 0.5) == "ice"
    assert _classify(5, -5, 0.5) == "snow"
    assert _classify(200, 10, 0.5) == "mountain"
    assert _classify(2, 15, 0.5, coast=True) == "beach"
    assert _classify(120, 15, 0.5) == "hills"
    assert _classify(40, 0, 0.5) == "tundra"
    assert _classify(40, 6, 0.5) == "taiga"
    assert _classify(10, 15, 0.9) == "wetland"
    assert _classify(40, 25, 0.2) == "savanna"
    assert _classify(40, 15, 0.7) == "broadleaf_forest"
    assert _classify(40, 15, 0.4) == "grassland"


def test_temperature_cools_toward_the_poles_and_with_height() -> None:
    temp = temperature(SPEC.climate, np.array([0.0, 45.0, 90.0, 0.0]), np.array([0.0, 0.0, 0.0, 250.0]))

    assert temp[0] == SPEC.climate.equator_c
    assert temp[2] == SPEC.climate.pole_c
    assert temp[0] > temp[1] > temp[2]
    assert temp[3] == SPEC.climate.equator_c - 250 * SPEC.climate.lapse_c_per_m


def test_hop_distance_counts_steps_from_sources() -> None:
    grid = build_grid(4)
    sources = np.zeros(grid.cell_count, dtype=bool)
    sources[0] = True

    distance = hop_distance(grid, sources)

    assert distance[0] == 0
    assert (distance[grid.neighbours[0][grid.neighbours[0] >= 0]] == 1).all()
    assert distance.max() > 3 and np.isfinite(distance).all()


def test_only_land_biomes_are_walkable() -> None:
    biomes = np.arange(len(BIOME_IDS), dtype=np.uint8)

    blocked = {name for name, ok in zip(BIOME_IDS, walkable(biomes), strict=True) if not ok}

    assert blocked == {"deep_ocean", "shallow_ocean", "lake"}
