"""The static world the simulation runs on: the stored planet, the town chart, named places and structures.

Built once per engine start from the stored `WorldView` (read by the current generator version) and the town spec.
Nothing here changes while the simulation runs.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Literal

import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.sim.items import RESOURCE_CAPS, RESOURCE_INDEX, RESOURCES, RIVER_FISH, RIVER_REEDS
from app.sim.vec import Vec3, angle, as_vec, dot, normalize
from app.world.biomes import BIOME_IDS
from app.world.generate import GENERATOR
from app.world.geometry import Point
from app.world.grid import Grid, build_grid
from app.world.spec import BIOME_NAMES, load_site_kinds, load_world_spec
from app.world.sphere import TangentFrame, lat_lon
from app.world.store import WorldGenerator, load_or_generate
from app.world.town import TOWN_DATA_DIR, Extent, KindSpec, TownView, load_kinds, load_town
from app.world.view import Site, WorldView, decode_array
from app.world.walkability import WalkGrid, town_walk_grid

BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]
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
WATER_BIOMES = ("deep_ocean", "shallow_ocean", "lake")
RIVER_FORD_COST = 1.5  # rivers are fordable: at least this slow
SITE_RADIUS_M: dict[str, float] = {"town": 230.0, "camp": 60.0, "landmark": 80.0}
HOME_KINDS = frozenset({"townhouse", "farmhouse", "castle_keep", "lean_to"})
STRUCTURE_LABELS: dict[str, str] = {  # town placements
    "well": "the well",
    "storehouse": "a storehouse",
    "townhouse": "a house",
    "farmhouse": "a farmhouse",
    "castle_gatehouse": "a gatehouse",
    "castle_keep": "the keep",
}
CAMP_STRUCTURE_LABELS: dict[str, str] = {"lean_to": "a lean-to", "fire_pit": "the fire pit"}  # camp placements
STRUCTURE_NAMES: dict[str, str] = {  # structures with a name of their own (by placement id)
    "main-gate": "the main gate",
    "west-gate": "the west gate",
    "castle-gate": "the castle gate",
}
_DOOR_SEARCH_CELLS = 12

if set(TERRAIN_COST) | set(WATER_BIOMES) != set(BIOME_NAMES):
    raise ValueError("every biome needs a walking cost or must be water")


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TownPlaceSpec(_Spec):
    id: str
    name: str
    at: Point
    radius_m: float = Field(gt=0)


class TownPlacesSpec(_Spec):
    places: list[TownPlaceSpec]


@cache
def load_town_places() -> TownPlacesSpec:
    return TownPlacesSpec.model_validate(yaml.safe_load((TOWN_DATA_DIR / "places.yaml").read_text()))


@dataclass(frozen=True)
class TownChart:
    """The town's local metres (x east, z south) on its plateau, mapped to the globe with the gnomonic mapping."""

    frame: TangentFrame
    radius_m: float
    height_m: float
    extent: Extent
    walk: WalkGrid

    def to_local(self, unit: Vec3) -> tuple[float, float]:
        up, east, south = (as_vec(self.frame.up), as_vec(self.frame.east), as_vec(self.frame.south))
        along_up = dot(unit, up)
        if along_up <= 0:
            return (math.inf, math.inf)
        t = (self.radius_m + self.height_m) / along_up
        return (t * dot(unit, east), t * dot(unit, south))

    def to_unit(self, x: float, z: float) -> Vec3:
        r = self.radius_m + self.height_m
        up, east, south = self.frame.up, self.frame.east, self.frame.south
        return normalize(as_vec(up * r + east * x + south * z))

    def contains(self, x: float, z: float) -> bool:
        e = self.extent
        return e.min_x <= x < e.max_x and e.min_z <= z < e.max_z


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    kind: Literal["site", "town"]
    centre: Vec3
    stand: Vec3  # where someone walking there goes
    radius_m: float


@dataclass(frozen=True)
class Structure:
    """A town placement (id = placement id) or a camp's (id = "<camp site>:<placement id>")."""

    id: str
    kind: str
    label: str
    centre_xz: tuple[float, float]  # local metres of its chart: the town's, or around its camp's anchor
    door_xz: tuple[float, float]  # a walkable spot in front of it
    centre: Vec3
    door: Vec3
    site: str = "town"

    @property
    def is_home(self) -> bool:
        return self.kind in HOME_KINDS


@dataclass(frozen=True)
class Hearth:
    """A place built to hold a fire: a camp's fire pit or a town fire basket (id = its structure/placement id)."""

    id: str
    kind: Literal["pit", "basket"]
    centre: Vec3
    stand: Vec3  # a walkable spot beside it to tend it from


@dataclass(frozen=True)
class SimWorld:
    seed: int
    generator_version: str
    radius_m: float
    grid: Grid
    neighbours: list[list[int]]
    heights: FloatArray
    biomes: UInt8Array
    river: BoolArray  # land cells a river runs through
    in_town: BoolArray  # cells whose centre lies in the town chart (handled by the town walk grid)
    terrain_cost: FloatArray  # per metre; inf on water
    town: TownChart
    town_lon_deg: float
    sites: tuple[Site, ...]
    places: Mapping[str, Place]
    structures: Mapping[str, Structure]
    resource_caps: UInt8Array  # (cells, len(RESOURCES))
    hearths: Mapping[str, Hearth]

    @property
    def cell_count(self) -> int:
        return self.grid.cell_count

    def biome(self, cell: int) -> str:
        return BIOME_NAMES[int(self.biomes[cell])]

    def is_water(self, cell: int) -> bool:
        return self.biome(cell) in WATER_BIOMES

    def unit(self, cell: int) -> Vec3:
        return as_vec(self.grid.positions[cell])

    def distance_m(self, a: Vec3, b: Vec3) -> float:
        return angle(a, b) * self.radius_m

    def nearest_cell(self, unit: Vec3, hint: int | None = None) -> int:
        """The cell whose centre is closest to the direction (greedy walk from the hint, else a full scan)."""
        if hint is None:
            return int(np.argmax(self.grid.positions @ np.array(unit)))
        positions = self.grid.positions
        cell = hint
        best = float(positions[cell] @ unit)
        while True:
            improved = False
            for other in self.neighbours[cell]:
                value = float(positions[other] @ unit)
                if value > best:
                    best, cell, improved = value, other, True
            if not improved:
                return cell

    def town_point(self, unit: Vec3) -> tuple[float, float] | None:
        """Town local (x, z) when the direction lies inside the town chart, else None."""
        x, z = self.town.to_local(unit)
        return (x, z) if self.town.contains(x, z) else None

    def ground_height(self, unit: Vec3, cell: int) -> float:
        return self.town.height_m if self.town_point(unit) is not None else float(self.heights[cell])


def town_site(view: WorldView) -> Site:
    return next(site for site in view.sites if site.kind == "town")


def _frame(site: Site) -> TangentFrame:
    anchor = site.anchor
    up = np.array(anchor.position)
    north = np.array(anchor.north)
    return TangentFrame(up=up, east=np.array(anchor.east), north=north)


def site_unit(radius_m: float, site: Site, x: float, z: float) -> Vec3:
    """A site's local metres (x east, z south around its anchor, on its plateau) as a direction on the globe."""
    anchor = site.anchor
    r = radius_m + anchor.height_m
    up, east, north = np.array(anchor.position), np.array(anchor.east), np.array(anchor.north)
    return normalize(as_vec(up * r + east * x - north * z))


def _nearest_walkable(walk: WalkGrid, x: float, z: float) -> tuple[float, float]:
    """The centre of the walkable cell nearest to the point (searching outward in rings)."""
    size = walk.cell_size
    column = math.floor((x - walk.extent.min_x) / size)
    row = math.floor((z - walk.extent.min_z) / size)
    best: tuple[float, float, float] | None = None
    for ring in range(_DOOR_SEARCH_CELLS + 1):
        for dr in range(-ring, ring + 1):
            for dc in range(-ring, ring + 1):
                if max(abs(dr), abs(dc)) != ring:
                    continue
                r, c = row + dr, column + dc
                if not (0 <= r < walk.rows and 0 <= c < walk.columns) or walk.blocked[r * walk.columns + c]:
                    continue
                cx = walk.extent.min_x + (c + 0.5) * size
                cz = walk.extent.min_z + (r + 0.5) * size
                distance = math.hypot(cx - x, cz - z)
                if best is None or distance < best[0]:
                    best = (distance, cx, cz)
        if best is not None:
            return (best[1], best[2])
    raise ValueError(f"no walkable town cell near ({x}, {z})")


def build_sim_world(
    view: WorldView,
    town_view: TownView,
    kinds: Mapping[str, KindSpec],
    town_places: TownPlacesSpec,
) -> SimWorld:
    grid = build_grid(view.frequency)
    if grid.cell_count != view.cell_count:
        raise ValueError(f"world has {view.cell_count} cells, frequency {view.frequency} gives {grid.cell_count}")
    heights = decode_array(view.heights, "<f4").astype(np.float64)
    biomes = decode_array(view.biomes, "u1").astype(np.uint8)
    water = np.isin(biomes, [BIOME_IDS[name] for name in WATER_BIOMES])
    river = np.zeros(grid.cell_count, dtype=bool)
    for path in view.rivers:
        river[path.cells] = True
    river &= ~water

    site = town_site(view)
    walk = town_walk_grid(town_view, kinds)
    chart = TownChart(
        frame=_frame(site), radius_m=view.radius_m, height_m=site.anchor.height_m, extent=town_view.extent, walk=walk
    )
    in_town = np.zeros(grid.cell_count, dtype=bool)
    near = np.flatnonzero(grid.positions @ chart.frame.up > math.cos(400.0 / view.radius_m))
    for cell in near.tolist():
        x, z = chart.to_local(as_vec(grid.positions[cell]))
        in_town[cell] = chart.contains(x, z)

    cost_by_biome = np.array([TERRAIN_COST.get(name, math.inf) for name in BIOME_NAMES])
    terrain_cost = cost_by_biome[biomes]
    terrain_cost = np.where(river, np.maximum(terrain_cost, RIVER_FORD_COST), terrain_cost)

    caps = np.zeros((grid.cell_count, len(RESOURCES)), dtype=np.uint8)
    for biome_name, biome_caps in RESOURCE_CAPS.items():
        rows = biomes == BIOME_IDS[biome_name]
        for column, resource in enumerate(RESOURCES):
            caps[rows, column] = biome_caps.get(resource, 0)
    reeds = caps[:, RESOURCE_INDEX["reeds"]]
    banks = river & np.isin(biomes, [BIOME_IDS[name] for name in RESOURCE_CAPS])  # rivers through living ground
    reeds[banks] = np.maximum(reeds[banks], RIVER_REEDS)
    fish = caps[:, RESOURCE_INDEX["fish"]]
    fish[banks] = np.maximum(fish[banks], RIVER_FISH)
    caps[in_town] = 0

    places: dict[str, Place] = {}
    for other in view.sites:
        centre = as_vec(other.anchor.position)
        stand = chart.to_unit(0.0, 120.0) if other.kind == "town" else centre
        places[other.id] = Place(
            id=other.id,
            name=other.name,
            kind="site",
            centre=centre,
            stand=stand,
            radius_m=SITE_RADIUS_M[other.kind],
        )
    for spec in town_places.places:
        if spec.id in places:
            raise ValueError(f"town place {spec.id} clashes with a site id")
        if not walk.is_walkable(*spec.at):
            raise ValueError(f"town place {spec.id} stands on a blocked spot {spec.at}")
        unit = chart.to_unit(*spec.at)
        places[spec.id] = Place(
            id=spec.id, name=spec.name, kind="town", centre=unit, stand=unit, radius_m=spec.radius_m
        )

    structures: dict[str, Structure] = {}
    for placement in town_view.placements:
        if placement.kind not in STRUCTURE_LABELS:
            continue
        door = _nearest_walkable(walk, *placement.front(0.75))
        structures[placement.id] = Structure(
            id=placement.id,
            kind=placement.kind,
            label=STRUCTURE_NAMES.get(placement.id, STRUCTURE_LABELS[placement.kind]),
            centre_xz=(placement.x, placement.z),
            door_xz=door,
            centre=chart.to_unit(placement.x, placement.z),
            door=chart.to_unit(*door),
        )

    for camp in view.sites:
        if camp.kind != "camp":
            continue
        for placement in camp.placements:
            if placement.kind not in CAMP_STRUCTURE_LABELS:
                continue
            door = placement.front(0.75)
            structure_id = f"{camp.id}:{placement.id}"
            structures[structure_id] = Structure(
                id=structure_id,
                kind=placement.kind,
                label=CAMP_STRUCTURE_LABELS[placement.kind],
                centre_xz=(placement.x, placement.z),
                door_xz=door,
                centre=site_unit(view.radius_m, camp, placement.x, placement.z),
                door=site_unit(view.radius_m, camp, *door),
                site=camp.id,
            )

    hearths = {
        structure.id: Hearth(id=structure.id, kind="pit", centre=structure.centre, stand=structure.door)
        for structure in structures.values()
        if structure.kind == "fire_pit"
    }
    for placement in town_view.placements:
        if placement.kind == "fire_basket":
            stand = chart.to_unit(*_nearest_walkable(walk, placement.x, placement.z))
            centre = chart.to_unit(placement.x, placement.z)
            hearths[placement.id] = Hearth(id=placement.id, kind="basket", centre=centre, stand=stand)

    _, town_lon = lat_lon(chart.frame.up)
    return SimWorld(
        seed=view.seed,
        generator_version=view.generator_version,
        radius_m=view.radius_m,
        grid=grid,
        neighbours=grid.neighbour_lists(),
        heights=heights,
        biomes=biomes,
        river=river,
        in_town=in_town,
        terrain_cost=terrain_cost,
        town=chart,
        town_lon_deg=float(town_lon),
        sites=tuple(view.sites),
        places=places,
        structures=structures,
        resource_caps=caps,
        hearths=dict(sorted(hearths.items())),
    )


def sim_world_from_view(view: WorldView) -> SimWorld:
    return build_sim_world(view, load_town(), load_kinds(), load_town_places())


def load_sim_world(session: Session, generator: WorldGenerator = GENERATOR) -> SimWorld:
    """The simulation world over the stored planet of the current generator version (generated first if needed)."""
    payload = load_or_generate(session, load_world_spec(), load_site_kinds(), generator)
    return sim_world_from_view(WorldView.model_validate_json(payload))
