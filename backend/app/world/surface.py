"""The generated ground as hotspots, roads and flora read it: cells, water, rivers, the town chart and distances."""

from dataclasses import dataclass
from functools import cached_property

import numpy as np

from app.world.biomes import BIOME_IDS, UInt8Array, walkable
from app.world.grid import Grid, IntArray, build_grid
from app.world.hydrology import RiverPath
from app.world.sphere import FloatArray, TangentFrame, angle_between, globe_to_local
from app.world.terrain import BoolArray
from app.world.view import Site, WorldView, decode_array


@dataclass(frozen=True)
class TownChart:
    """The town's square chart (local metres, x east, z south) on its plateau: no road or flora cell inside."""

    frame: TangentFrame
    radius_m: float
    height_m: float
    half_m: float

    def local(self, units: FloatArray) -> FloatArray:
        """(n, 2) local metres of unit vectors (inf on the far side of the planet)."""
        units = np.atleast_2d(units)
        facing = units @ self.frame.up > 0
        local = np.full((len(units), 2), np.inf)
        local[facing] = globe_to_local(self.frame, self.radius_m, self.height_m, units[facing])
        return local

    def contains(self, units: FloatArray) -> BoolArray:
        local = self.local(units)
        return bool_array((np.abs(local[:, 0]) <= self.half_m) & (np.abs(local[:, 1]) <= self.half_m))

    def unit(self, x: float, z: float) -> FloatArray:
        v = self.frame.up * (self.radius_m + self.height_m) + self.frame.east * x + self.frame.south * z
        return np.asarray(v / np.linalg.norm(v), dtype=np.float64)


def bool_array(values: object) -> BoolArray:
    return np.asarray(values, dtype=bool)


def site_frame(site: Site) -> TangentFrame:
    anchor = site.anchor
    return TangentFrame(up=np.array(anchor.position), east=np.array(anchor.east), north=np.array(anchor.north))


@dataclass(frozen=True)
class Surface:
    radius_m: float
    grid: Grid
    heights: FloatArray
    biomes: UInt8Array
    rivers: list[RiverPath]
    river: BoolArray  # land cells a river runs through
    sites: list[Site]
    chart: TownChart

    @cached_property
    def walk(self) -> BoolArray:
        return walkable(self.biomes)

    @cached_property
    def ocean(self) -> BoolArray:
        return self.biome_is("deep_ocean", "shallow_ocean")

    @cached_property
    def lake(self) -> BoolArray:
        return self.biome_is("lake")

    @cached_property
    def in_town(self) -> BoolArray:
        """Cells whose centre lies in the town chart."""
        return self.chart.contains(self.grid.positions)

    @cached_property
    def padded_neighbours(self) -> IntArray:
        """Neighbours with the -1 padding pointing at an extra index (cell_count) for safe fancy indexing."""
        return np.where(self.grid.neighbours < 0, self.grid.cell_count, self.grid.neighbours)

    def biome_is(self, *names: str) -> BoolArray:
        return bool_array(np.isin(self.biomes, [BIOME_IDS[name] for name in names]))

    def site(self, site_id: str) -> Site:
        return next(site for site in self.sites if site.id == site_id)

    def site_unit(self, site_id: str) -> FloatArray:
        return np.array(self.site(site_id).anchor.position)

    def distances_m(self, unit: FloatArray, units: FloatArray | None = None) -> FloatArray:
        """Great-circle metres from a unit vector to every cell (or to the given unit vectors)."""
        targets = self.grid.positions if units is None else np.atleast_2d(units)
        return np.asarray(angle_between(targets, unit) * self.radius_m, dtype=np.float64)

    def distance_m(self, a: FloatArray, b: FloatArray) -> float:
        return float(self.distances_m(a, b)[0])

    def nearest_cell(self, unit: FloatArray, allowed: BoolArray | None = None) -> int:
        scores = self.grid.positions @ unit
        if allowed is not None:
            scores = np.where(allowed, scores, -np.inf)
        return int(np.argmax(scores))

    def cell_unit(self, cell: int) -> FloatArray:
        return np.asarray(self.grid.positions[cell], dtype=np.float64)


def surface_from_view(view: WorldView, chart_half_m: float) -> Surface:
    """The surface of a stored world (what flora generation reads)."""
    grid = build_grid(view.frequency)
    biomes = decode_array(view.biomes, "u1").astype(np.uint8)
    rivers = [RiverPath(id=river.id, name=river.name, cells=river.cells) for river in view.rivers]
    river = np.zeros(grid.cell_count, dtype=bool)
    for path in rivers:
        river[path.cells] = True
    town = next(site for site in view.sites if site.id == "town")
    return Surface(
        radius_m=view.radius_m,
        grid=grid,
        heights=decode_array(view.heights, "<f4").astype(np.float64),
        biomes=biomes,
        rivers=rivers,
        river=river & walkable(biomes),
        sites=view.sites,
        chart=TownChart(
            frame=site_frame(town), radius_m=view.radius_m, height_m=town.anchor.height_m, half_m=chart_half_m
        ),
    )
