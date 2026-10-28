"""World generation: from (seed, spec) to heights, biomes, rivers, the land loop and sites.

Run `python -m app.world.generate` to generate the world, store it and print its stats.
"""

import gzip
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

import numpy as np
from sqlmodel import Session

from app.core.db import engine
from app.world.biomes import (
    BIOME_IDS,
    UInt8Array,
    classify,
    hop_distance,
    mean_spacing_m,
    moisture,
    temperature,
    walkable,
)
from app.world.grid import Grid, build_grid
from app.world.hydrology import RiverPath, carve_channel, settle_water, trace_cells
from app.world.paths import closed_loop
from app.world.spec import BIOME_NAMES, SiteSpec, Volcano, WorldSpec, load_site_kinds, load_world_spec
from app.world.sphere import FloatArray, angle_between, lat_lon, tangent_frame, unit_from_lat_lon
from app.world.store import WorldGenerator, find_payload, save_payload, world_key
from app.world.terrain import BoolArray, SiteArea, base_terrain, ensure_land, loop_band, shape_site
from app.world.town import KindSpec, place_kind
from app.world.view import Anchor, River, Site, WorldView, encode_array

GENERATOR_VERSION = "m3.2"
PLATEAU_TOLERANCE_M = 0.01  # a plateau that moved more sat in a closed depression
_LOOP_CENTRE_PULL = 4.0  # extra path cost per band half-width away from the loop spine


@dataclass(frozen=True)
class GeneratedWorld:
    spec: WorldSpec
    grid: Grid
    heights: FloatArray
    biomes: UInt8Array
    lake: BoolArray  # lake water, frozen or not
    river_cells: BoolArray
    rivers: list[RiverPath]
    land_loop: list[int]
    sites: list[Site]
    timings_s: dict[str, float] = field(default_factory=dict)

    def view(self) -> WorldView:
        return WorldView(
            seed=self.spec.seed,
            generator_version=GENERATOR_VERSION,
            radius_m=self.spec.radius_m,
            frequency=self.spec.frequency,
            cell_count=self.grid.cell_count,
            biome_names=list(BIOME_NAMES),
            positions=encode_array(self.grid.positions, "<f4"),
            heights=encode_array(self.heights, "<f4"),
            biomes=encode_array(self.biomes, "u1"),
            triangles=encode_array(self.grid.triangles, "<u4"),
            rivers=[River(id=river.id, name=river.name, cells=river.cells) for river in self.rivers],
            land_loop=self.land_loop,
            sites=self.sites,
        )


class _Timer:
    def __init__(self) -> None:
        self.timings: dict[str, float] = {}
        self._last = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.timings[name] = round(now - self._last, 4)
        self._last = now


def nearest_cell(grid: Grid, unit: FloatArray) -> int:
    return int(np.argmax(grid.positions @ unit))


def generate_world(spec: WorldSpec, kinds: Mapping[str, KindSpec]) -> GeneratedWorld:
    timer = _Timer()
    grid = build_grid(spec.frequency)
    units = grid.positions
    timer.lap("grid")

    heights = base_terrain(spec, grid).heights
    timer.lap("terrain")

    areas = {site.id: shape_site(spec, site, units, heights) for site in spec.sites}
    flats = np.logical_or.reduce([area.flat for area in areas.values()])
    basins = np.logical_or.reduce([area.basin for area in areas.values()])
    bowl_levels = np.full(grid.cell_count, np.inf)
    for area in areas.values():
        bowl_levels[area.bowl] = area.bowl_level
    ensure_land(heights, flats)
    authored = [
        RiverPath(
            id=river.id,
            name=river.name,
            cells=carve_channel(
                heights, trace_cells(grid, river.points), flats, bowl_levels, spec.hydrology.channel_depth_m, river.id
            ),
        )
        for river in spec.rivers
    ]
    timer.lap("sites")

    loop_core = loop_band(spec, units, spec.land_loop.core_fraction) <= 1
    water = settle_water(grid, heights, spec.hydrology, authored, basins, flats, loop_core)
    heights = water.heights
    areas = {site_id: _settled_area(area, heights) for site_id, area in areas.items()}
    ocean = heights < 0
    wet = ocean | water.lake
    rivers = [_trim_to_water(river, wet) for river in water.rivers]
    river_cells = np.zeros(grid.cell_count, dtype=bool)
    for river in rivers:
        river_cells[river.cells] = True
    river_cells &= ~wet
    timer.lap("water")

    latitude, _ = lat_lon(units)
    temp_c = temperature(spec.climate, latitude, heights)
    water_distance = hop_distance(grid, wet | river_cells) * mean_spacing_m(grid, spec.radius_m)
    wetness = moisture(spec.climate, spec.seed, units, water_distance)
    padded = np.where(grid.neighbours < 0, grid.cell_count, grid.neighbours)
    coast = ~wet & np.append(ocean, False)[padded].any(axis=1)
    biomes = classify(
        spec.biomes, heights, temp_c, wetness, ocean, water.lake, coast, spec.terrain.shelf_m, spec.terrain.beach_m
    )
    for site in spec.sites:
        _paint_site(spec, site, units, biomes, ~wet)
    timer.lap("biomes")

    walk = walkable(biomes)
    land_loop = _land_loop(spec, grid, walk)
    timer.lap("land_loop")

    sites = [_site(site, areas[site.id], grid, walk, kinds) for site in spec.sites]
    timer.lap("sites_view")
    return GeneratedWorld(
        spec=spec,
        grid=grid,
        heights=heights,
        biomes=biomes,
        lake=water.lake,
        river_cells=river_cells,
        rivers=rivers,
        land_loop=land_loop,
        sites=sites,
        timings_s=timer.timings,
    )


def _settled_area(area: SiteArea, heights: FloatArray) -> SiteArea:
    """Check a plateau survived depression filling; a terrain-height plateau may rise with the fill as a whole."""
    plateau = heights[area.flat & ~area.basin]
    if plateau.size == 0:  # the crater floor keeps its shaped height
        return area
    if not area.authored_height and plateau.max() - plateau.min() <= PLATEAU_TOLERANCE_M:
        area = replace(area, height_m=float(plateau.min()))
    drift = float(np.abs(plateau - area.height_m).max())
    if drift > PLATEAU_TOLERANCE_M:
        raise ValueError(f"site {area.site_id} lies in a closed depression: its plateau rose {drift:.2f} m")
    return area


def _trim_to_water(river: RiverPath, wet: BoolArray) -> RiverPath:
    """Start a river in the last water cell it leaves (a lake outflow) and end it in the first water cell it reaches."""
    cells = river.cells
    start = 0
    while start + 1 < len(cells) and wet[cells[start + 1]] and wet[cells[start]]:
        start += 1
    end = next((i for i in range(start + 1, len(cells)) if wet[cells[i]]), len(cells) - 1)
    return RiverPath(id=river.id, name=river.name, cells=cells[start : end + 1])


def _paint_site(spec: WorldSpec, site: SiteSpec, units: FloatArray, biomes: UInt8Array, land: BoolArray) -> None:
    distance = angle_between(units, unit_from_lat_lon(*site.at)) * spec.radius_m
    if isinstance(site.terrain, Volcano):
        biomes[land & (distance <= site.terrain.volcanic_radius_m)] = BIOME_IDS["volcanic"]
    if site.biome is not None:
        biomes[land & (distance <= site.biome_radius_m)] = BIOME_IDS[site.biome]


def _land_loop(spec: WorldSpec, grid: Grid, walk: BoolArray) -> list[int]:
    band = loop_band(spec, grid.positions)
    stops = [nearest_cell(grid, unit_from_lat_lon(*waypoint.at)) for waypoint in spec.land_loop.waypoints]
    loop = closed_loop(grid, walk & (band <= 1), 1 + _LOOP_CENTRE_PULL * band, stops)
    gate = nearest_cell(grid, unit_from_lat_lon(*spec.site(spec.loop_gate).at))
    if gate not in loop:
        raise ValueError(f"the land loop misses the {spec.loop_gate} site; put a waypoint on it")
    return loop


def _site(site: SiteSpec, area: SiteArea, grid: Grid, walk: BoolArray, kinds: Mapping[str, KindSpec]) -> Site:
    frame = tangent_frame(unit_from_lat_lon(*site.at))
    cell = nearest_cell(grid, frame.up)
    if not walk[cell]:
        raise ValueError(f"site {site.id} sits on water (cell {cell})")
    return Site(
        id=site.id,
        kind=site.kind,
        name=site.name,
        cell=cell,
        anchor=Anchor(
            position=_vector(frame.up), east=_vector(frame.east), north=_vector(frame.north), height_m=area.height_m
        ),
        placements=[
            place_kind(placement.id, placement.kind, placement.at, placement.rotation_deg, kinds)
            for placement in site.placements
        ],
    )


def _vector(values: FloatArray) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))


def generate_view(spec: WorldSpec, kinds: Mapping[str, KindSpec]) -> WorldView:
    return generate_world(spec, kinds).view()


GENERATOR = WorldGenerator(version=GENERATOR_VERSION, generate=generate_view)


def world_stats(world: GeneratedWorld, payload: bytes) -> list[str]:
    shares = np.bincount(world.biomes, minlength=len(BIOME_NAMES)) / world.grid.cell_count * 100
    land = float((world.heights >= 0).mean() * 100)
    walk = float(walkable(world.biomes).mean() * 100)
    river_cells = sum(len(river.cells) for river in world.rivers)
    timings = ", ".join(f"{step} {seconds:.3f} s" for step, seconds in world.timings_s.items())
    return [
        f"seed {world.spec.seed}, generator {GENERATOR_VERSION}, {world.grid.cell_count} cells",
        f"land {land:.1f} %, walkable {walk:.1f} %, heights {world.heights.min():.1f} .. {world.heights.max():.1f} m",
        f"rivers {len(world.rivers)} ({river_cells} cells), land loop {len(world.land_loop)} cells",
        "biomes: " + ", ".join(f"{name} {share:.1f} %" for name, share in zip(BIOME_NAMES, shares, strict=True)),
        f"timings: {timings} (total {sum(world.timings_s.values()):.2f} s)",
        f"payload {len(payload) / 1e6:.2f} MB raw, {len(gzip.compress(payload, 6)) / 1e6:.2f} MB gzip",
    ]


def main() -> None:
    spec, kinds = load_world_spec(), load_site_kinds()
    world = generate_world(spec, kinds)
    payload = world.view().model_dump_json().encode()
    key = world_key(spec, kinds, GENERATOR_VERSION)
    with Session(engine) as session:
        existed = find_payload(session, key) is not None
        save_payload(session, key, payload)
    print("\n".join(world_stats(world, payload)))
    print(f"world {'was already stored' if existed else 'stored'} (spec hash {key.spec_hash[:12]})")


if __name__ == "__main__":
    main()
