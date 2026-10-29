"""Climate (temperature, moisture) and the biome of every cell."""

import numpy as np
from numpy.typing import NDArray

from app.world.grid import Grid
from app.world.noise import fbm
from app.world.spec import BIOME_NAMES, BiomeThresholds, ClimateSpec
from app.world.sphere import FloatArray
from app.world.terrain import BoolArray

BIOME_IDS = {name: index for index, name in enumerate(BIOME_NAMES)}
WATER_BIOMES = frozenset({BIOME_IDS["deep_ocean"], BIOME_IDS["shallow_ocean"], BIOME_IDS["lake"]})
UInt8Array = NDArray[np.uint8]

# Walking cost per metre by biome (01-world: forest ×1.5, hills ×2, snow ×3, water impassable).
TERRAIN_COST: dict[str, float] = {
    "beach": 1.0,
    "grassland": 1.0,
    "savanna": 1.0,
    "tundra": 1.2,
    "broadleaf_forest": 1.5,
    "taiga": 1.5,
    "wetland": 1.5,
    "hills": 2.0,
    "volcanic": 2.0,
    "mountain": 2.5,
    "snow": 3.0,
    "ice": 3.0,
}
RIVER_FORD_COST = 1.5  # rivers are fordable: at least this slow

if set(TERRAIN_COST) | {BIOME_NAMES[biome] for biome in WATER_BIOMES} != set(BIOME_NAMES):
    raise ValueError("every biome needs a walking cost or must be water")


def walk_costs(biomes: UInt8Array, river: BoolArray) -> FloatArray:
    """Walking cost per metre of every cell: its biome's, at least the ford cost on a river, inf on water."""
    cost_by_biome = np.array([TERRAIN_COST.get(name, np.inf) for name in BIOME_NAMES])
    costs = cost_by_biome[biomes]
    return np.asarray(np.where(river, np.maximum(costs, RIVER_FORD_COST), costs), dtype=np.float64)


def hop_distance(grid: Grid, sources: BoolArray) -> FloatArray:
    """Steps over the neighbour graph from each cell to the nearest source cell (inf when unreachable)."""
    padded = np.where(grid.neighbours < 0, grid.cell_count, grid.neighbours)
    distance = np.where(sources, 0.0, np.inf)
    while True:
        extended = np.append(distance, np.inf)
        relaxed = np.minimum(distance, extended[padded].min(axis=1) + 1)
        if np.array_equal(relaxed, distance):
            return distance
        distance = relaxed


def mean_spacing_m(grid: Grid, radius_m: float) -> float:
    a, b = grid.triangles[:, 0], grid.triangles[:, 1]
    return float(np.linalg.norm(grid.positions[a] - grid.positions[b], axis=1).mean() * radius_m)


def temperature(spec: ClimateSpec, latitude_deg: FloatArray, heights: FloatArray) -> FloatArray:
    cooling = (np.abs(latitude_deg) / 90) ** spec.exponent
    return spec.equator_c - (spec.equator_c - spec.pole_c) * cooling - spec.lapse_c_per_m * np.maximum(heights, 0)


def moisture(spec: ClimateSpec, seed: int, units: FloatArray, water_distance_m: FloatArray) -> FloatArray:
    noise = fbm(units, seed + 6, spec.moisture.frequency, spec.moisture.octaves)
    wet = np.exp(-water_distance_m / spec.moisture_water_m)
    return np.clip(0.45 + 0.45 * noise + 0.35 * wet - 0.15, 0, 1)


def classify(
    thresholds: BiomeThresholds,
    heights: FloatArray,
    temp_c: FloatArray,
    wetness: FloatArray,
    ocean: BoolArray,
    lake: BoolArray,
    coast: BoolArray,
    shelf_m: float,
    beach_m: float,
) -> UInt8Array:
    """Biome ids from water, height, temperature and moisture (site overrides come later)."""
    t = thresholds
    conditions = [
        ocean & (heights < shelf_m),
        ocean,
        lake & (temp_c >= t.ice_c),
        temp_c < t.ice_c,  # frozen lakes included
        temp_c < t.snow_c,
        heights >= t.mountain_m,
        coast & (heights < beach_m),
        heights >= t.hills_m,
        temp_c < t.tundra_c,
        temp_c < t.taiga_c,
        (wetness >= t.wetland_moisture) & (heights < t.wetland_max_m),
        (temp_c >= t.savanna_c) & (wetness < t.savanna_moisture),
        wetness >= t.forest_moisture,
    ]
    choices = [
        "deep_ocean",
        "shallow_ocean",
        "lake",
        "ice",
        "snow",
        "mountain",
        "beach",
        "hills",
        "tundra",
        "taiga",
        "wetland",
        "savanna",
        "broadleaf_forest",
    ]
    return np.select(conditions, [BIOME_IDS[name] for name in choices], BIOME_IDS["grassland"]).astype(np.uint8)


def walkable(biomes: UInt8Array) -> BoolArray:
    return ~np.isin(biomes, sorted(WATER_BIOMES))
