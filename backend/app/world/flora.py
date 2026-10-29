"""Usable flora (10-world-v1 §1.1, D78): every tree, nut tree, berry bush, root patch, reed bed and deadwood pile.

Generated from the stored world and its spec (same world + spec = same flora), served packed by
`GET /api/v1/world/flora`, read by the simulation as nodes. A flora's id is its index in the table.

Packed table, little-endian, struct of arrays over n items (9 n bytes, sorted by cell):

```
cell u32 × n | east i8 × n | north i8 × n | kind u8 × n | scale u8 × n | yaw u8 × n
```

- position: the cell's tangent frame (east = Y × up, north = up × east), offset `east, north` × OFFSET_STEP_M
  metres, mapped gnomonically at the planet radius: unit = normalize(up × R + east × e + north × n).
- kind: index into `WorldPlaces.flora_kinds` (`data/world/flora.yaml` order, append only).
- scale: × SCALE_STEP of the drawn size. yaw: × 360/256 degrees, a compass bearing (0 north, 90 east); a felled
  tree falls along it.

Placement:
1. natural flora by biome density (×`woodland` inside woodlot hotspots, ×`lean_belt.share` for its food kinds in the
   belt past each camp's home ring), on every land cell outside the town chart;
2. each hotspot's exact counts inside its radius (natural flora of those node kinds stays out, and natural berry
   bushes stay DEN_NEAREST_BUSH_M off a grove's den);
3. each camp's home ring holds exactly `home_ring_flora` (natural flora of those kinds stays out; counts of a
   home-ring hotspot count toward it; no other hotspot's counted flora falls inside);
4. nothing in water, on cliffs, on rivers, roads, paths, site props, camp grounds or the town chart.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.world.biomes import BIOME_IDS, mean_spacing_m
from app.world.grid import Grid, IntArray
from app.world.spec import BIOME_NAMES, CAMPS, FloraNode, FloraSpec, HotspotsSpec, WorldSpec
from app.world.sphere import FloatArray, angle_between, tangent_frame, tangent_frames
from app.world.surface import Surface, surface_from_view
from app.world.terrain import BoolArray
from app.world.view import Feature, Hotspot, Road, WorldView

OFFSET_STEP_M = 0.2  # i8 offsets reach ±25.4 m, past the farthest point of any cell (D120)
SCALE_STEP = 0.01
YAW_STEP_DEG = 360 / 256
SPREAD = 0.55  # items lie within SPREAD × the mean cell spacing of their cell's centre (the client scatter's reach)
MAX_SLOPE_DEG = 40.0  # nothing grows on steeper ground (cliffs)
SHORE_MIN_HEIGHT_M = 0.3  # above the drawn sea level
RIVER_CLEARANCE_M = 6.0  # from a river's centre line (the drawn rivers are up to 13 m wide)
REED_RIVER_CLEARANCE_M = 3.0  # reeds stand at the water's edge
ROAD_CLEARANCE_M = {"road": 2.5, "path": 1.75}  # half the width + 1 m
CAMP_CLEARING_M = 12.0  # a camp's worn ground
PROP_CLEARANCE_M = 1.0  # beyond a site prop's footprint
FEATURE_CLEARANCE_M = 3.0
COUNTED_SPACING_M = 2.0  # counted items of one hotspot or ring keep this far apart
DEN_FIRST_BUSH_M = 36.0  # from an edge den to its grove's first berry bush
DEN_NEAREST_BUSH_M = 30.0  # no natural berry bush grows nearer a grove's den (10 §1.2: 30-50 m to the nearest)
_ATTEMPTS = 40  # candidates drawn per counted item before giving up
_REDRAWS = 6  # times a natural item off good ground is moved within its cell before it is dropped
_EDGE_MARGIN_M = 0.5  # counted items stay this far inside their annulus (offsets are rounded to OFFSET_STEP_M)
_PACKED_FIELDS: tuple[tuple[str, str], ...] = (
    ("cell", "<u4"),
    ("east", "i1"),
    ("north", "i1"),
    ("kind", "u1"),
    ("scale", "u1"),
    ("yaw", "u1"),
)
BYTES_PER_ITEM = sum(np.dtype(dtype).itemsize for _, dtype in _PACKED_FIELDS)


@dataclass(frozen=True)
class Flora:
    cell: NDArray[np.uint32]
    east: NDArray[np.int8]
    north: NDArray[np.int8]
    kind: NDArray[np.uint8]
    scale: NDArray[np.uint8]
    yaw: NDArray[np.uint8]
    grid: Grid
    radius_m: float

    def __len__(self) -> int:
        return len(self.cell)

    @cached_property
    def units(self) -> FloatArray:
        """(n, 3) unit vectors of every item."""
        return _offset_units(self.grid, self.radius_m, self.cell.astype(np.int64), self.east, self.north)

    def pack(self) -> bytes:
        return b"".join(
            np.ascontiguousarray(getattr(self, name), dtype=dtype).tobytes() for name, dtype in _PACKED_FIELDS
        )

    @classmethod
    def unpack(cls, data: bytes, grid: Grid, radius_m: float) -> "Flora":
        if len(data) % BYTES_PER_ITEM:
            raise ValueError(f"a flora table is a multiple of {BYTES_PER_ITEM} bytes, got {len(data)}")
        count = len(data) // BYTES_PER_ITEM
        columns: list[NDArray[Any]] = []
        offset = 0
        for _, dtype in _PACKED_FIELDS:
            size = np.dtype(dtype).itemsize * count
            columns.append(
                np.frombuffer(data[offset : offset + size], dtype=dtype).astype(np.dtype(dtype).newbyteorder("="))
            )
            offset += size
        cell, east, north, kind, scale, yaw = columns
        return cls(cell=cell, east=east, north=north, kind=kind, scale=scale, yaw=yaw, grid=grid, radius_m=radius_m)


@dataclass(frozen=True)
class _Annulus:
    centre: FloatArray
    inner_m: float
    outer_m: float

    def contains(self, units: FloatArray, radius_m: float) -> BoolArray:
        distance = angle_between(units, self.centre) * radius_m
        return np.asarray((distance >= self.inner_m) & (distance <= self.outer_m), dtype=bool)


@dataclass
class _Items:
    """Flora being placed, as plain arrays (cell, offsets in steps, kind code, scale, yaw)."""

    cell: IntArray
    east: IntArray
    north: IntArray
    kind: IntArray
    scale: IntArray
    yaw: IntArray

    @classmethod
    def empty(cls) -> "_Items":
        return cls(*(np.zeros(0, dtype=np.int64) for _ in range(6)))

    def __len__(self) -> int:
        return len(self.cell)

    def take(self, mask: NDArray[np.bool_] | IntArray) -> "_Items":
        return _Items(
            self.cell[mask], self.east[mask], self.north[mask], self.kind[mask], self.scale[mask], self.yaw[mask]
        )

    def extend(self, other: "_Items") -> "_Items":
        return _Items(*(np.concatenate([getattr(self, f), getattr(other, f)]) for f in _ITEM_FIELDS))


_ITEM_FIELDS = ("cell", "east", "north", "kind", "scale", "yaw")


def generate_flora(view: WorldView, spec: WorldSpec) -> Flora:
    surface = surface_from_view(view, spec.roads.town_chart_half_m)
    return _FloraPlacer(surface, spec, view).place()


class _FloraPlacer:
    def __init__(self, surface: Surface, spec: WorldSpec, view: WorldView) -> None:
        self.surface = surface
        self.flora: FloraSpec = spec.flora
        self.hotspots_spec: HotspotsSpec = spec.hotspots
        self.hotspots: list[Hotspot] = view.places.hotspots
        self.roads: list[Road] = view.places.roads
        self.features: list[Feature] = view.places.features
        self.grid = surface.grid
        digest = hashlib.sha256(f"{spec.seed}:world.flora".encode()).digest()
        self.rng = np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16], "little")))
        self.spacing = mean_spacing_m(self.grid, surface.radius_m)
        self.codes = {kind.id: code for code, kind in enumerate(self.flora.kinds)}
        self.node_of = np.array([kind.node for kind in self.flora.kinds])
        self.scales = np.array([kind.scale for kind in self.flora.kinds])
        self.camps = [surface.site_unit(camp) for camp in CAMPS]
        self.triangles_of = _incident_triangles(self.grid)

    def place(self) -> Flora:
        natural = self._natural()
        bad = np.flatnonzero(~self._ground_ok(natural))
        for _ in range(_REDRAWS):  # an item off good ground moves elsewhere in its cell, so densities hold
            if len(bad) == 0:
                break
            angle, distance = self._spread_offsets(len(bad))
            natural.east[bad] = _steps(np.cos(angle) * distance)
            natural.north[bad] = _steps(np.sin(angle) * distance)
            bad = bad[~self._ground_ok(natural.take(bad))]
        keep = np.ones(len(natural), dtype=bool)
        keep[bad] = False
        natural = natural.take(keep & self._kept_natural(natural))
        counted = self._counted()
        items = natural.extend(counted)
        order = np.lexsort((items.scale, items.yaw, items.north, items.east, items.kind, items.cell))
        items = items.take(order)
        return Flora(
            cell=items.cell.astype(np.uint32),
            east=items.east.astype(np.int8),
            north=items.north.astype(np.int8),
            kind=items.kind.astype(np.uint8),
            scale=items.scale.astype(np.uint8),
            yaw=items.yaw.astype(np.uint8),
            grid=self.grid,
            radius_m=self.surface.radius_m,
        )

    # natural flora ---------------------------------------------------------------------------------------------

    def _natural(self) -> _Items:
        surface = self.surface
        land = surface.walk & ~surface.in_town
        woodland = np.ones(self.grid.cell_count)
        for hotspot in self.hotspots:
            if hotspot.woodland != 1.0:
                woodland[surface.distances_m(np.array(hotspot.centre)) <= hotspot.radius_m] = hotspot.woodland
        belt = self.hotspots_spec.lean_belt
        lean = np.ones(self.grid.cell_count)
        for camp in self.camps:
            distance = surface.distances_m(camp)
            lean[(distance > self.hotspots_spec.rings.home_m) & (distance <= belt.outer_m)] = belt.share
        batches = [_Items.empty()]
        for biome, table in self.flora.per_cell.items():
            cells = np.flatnonzero(land & (surface.biomes == BIOME_IDS[biome]))
            for kind, density in table.items():
                node = self.flora.kinds[self.codes[kind]].node
                factor = woodland[cells] if node == "tree" else lean[cells] if node in belt.nodes else 1.0
                batches.append(self._scatter(cells, density * factor, self.codes[kind]))
        on_rivers = (
            land & surface.river & np.isin(surface.biomes, [BIOME_IDS[name] for name in self.flora.river_biomes])
        )
        for kind, density in self.flora.river_per_cell.items():
            batches.append(
                self._scatter(np.flatnonzero(on_rivers), np.full(int(on_rivers.sum()), density), self.codes[kind])
            )
        items = batches[0]
        for batch in batches[1:]:
            items = items.extend(batch)
        return items

    def _scatter(self, cells: IntArray, expected: FloatArray | float, code: int) -> _Items:
        """floor(expected + u) items in each cell, spread over the cell (stratified: counts stay near expected)."""
        counts = np.floor(np.asarray(expected) + self.rng.random(len(cells))).astype(np.int64)
        owners = np.repeat(cells, counts)
        angle, distance = self._spread_offsets(len(owners))
        return self._items(owners, np.cos(angle) * distance, np.sin(angle) * distance, np.full(len(owners), code))

    def _spread_offsets(self, count: int) -> tuple[FloatArray, FloatArray]:
        """Angles and distances of points uniform over a disc of SPREAD × the cell spacing."""
        angle = self.rng.random(count) * 2 * np.pi
        return angle, np.sqrt(self.rng.random(count)) * self.spacing * SPREAD

    def _items(self, cells: IntArray, east_m: FloatArray, north_m: FloatArray, codes: IntArray) -> _Items:
        low, high = self.scales[codes, 0], self.scales[codes, 1]
        scale = low + (high - low) * self.rng.random(len(cells))
        return _Items(
            cell=cells.astype(np.int64),
            east=_steps(east_m),
            north=_steps(north_m),
            kind=codes.astype(np.int64),
            scale=np.clip(np.round(scale / SCALE_STEP), 1, 255).astype(np.int64),
            yaw=self.rng.integers(0, 256, len(cells)).astype(np.int64),
        )

    def _kept_natural(self, items: _Items) -> BoolArray:
        """Natural items outside every hotspot that counts their node kind and every camp ring that caps it."""
        units = self._units(items)
        nodes = self.node_of[items.kind]
        keep = np.ones(len(items), dtype=bool)
        for hotspot in self.hotspots:
            counted = np.isin(nodes, list(hotspot.flora))
            if counted.any():
                inside = self.surface.distances_m(np.array(hotspot.centre), units) <= hotspot.radius_m
                keep &= ~(counted & inside)
        capped = np.isin(nodes, list(self.hotspots_spec.home_ring_flora))
        for camp in self.camps:
            keep &= ~(capped & (self.surface.distances_m(camp, units) <= self.hotspots_spec.rings.home_m))
        for den in self.grove_dens.values():  # its grove's bushes are the nearest
            keep &= ~((nodes == "berry_bush") & (self.surface.distances_m(den, units) < DEN_NEAREST_BUSH_M))
        return keep

    @cached_property
    def grove_dens(self) -> dict[str, FloatArray]:
        """The dens of hotspots that count berry bushes (a bear's grove), by hotspot id."""
        groves = {hotspot.id for hotspot in self.hotspots if "berry_bush" in hotspot.flora}
        return {
            feature.hotspot: np.array(feature.position)
            for feature in self.features
            if feature.kind == "den" and feature.hotspot in groves
        }

    # counted flora ---------------------------------------------------------------------------------------------

    def _counted(self) -> _Items:
        items = _Items.empty()
        home_m = self.hotspots_spec.rings.home_m
        in_rings: dict[str, dict[str, int]] = {camp: {} for camp in CAMPS}
        for hotspot in self.hotspots:
            centre = np.array(hotspot.centre)
            home_camp = hotspot.settlement if hotspot.ring == "home" and hotspot.settlement in CAMPS else None
            for node, count in hotspot.flora.items():
                region = _Annulus(centre, 0.0, hotspot.radius_m)
                den = self.grove_dens.get(hotspot.id) if node == "berry_bush" else None
                outside_rings = None if home_camp is not None else home_m
                ring = None if home_camp is None else _Annulus(self.surface.site_unit(home_camp), 0.0, home_m)
                items = items.extend(self._place_counted(region, node, count, outside_rings, items, den, within=ring))
                if home_camp is not None:
                    in_rings[home_camp][node] = in_rings[home_camp].get(node, 0) + count
        for camp, unit in zip(CAMPS, self.camps, strict=True):
            for node, cap in self.hotspots_spec.home_ring_flora.items():
                have = in_rings[camp].get(node, 0)
                if have > cap:
                    raise ValueError(f"{camp}'s home-ring hotspots hold {have} {node}, more than its {cap}")
                region = _Annulus(unit, CAMP_CLEARING_M, home_m)
                counted_by = [h for h in self.hotspots if node in h.flora]  # their counts stay exact
                items = items.extend(self._place_counted(region, node, cap - have, None, items, None, counted_by))
        return items

    def _place_counted(
        self,
        region: "_Annulus",
        node: FloraNode,
        count: int,
        outside_rings_m: float | None,
        placed: _Items,
        den: FloatArray | None,
        avoid: Sequence[Hotspot] = (),
        within: "_Annulus | None" = None,
    ) -> _Items:
        """Exactly `count` items of the node kind in the annulus, each on good ground (and in `within`: the home ring
        a home-ring hotspot's counts belong to). The first berry bush of a hotspot with an edge den (DEN_EDGE_M
        outside it, so no bush is nearer) stands DEN_FIRST_BUSH_M from the den, inside its defence ring even in a
        sparse grove (10 §1.6: the Elder grove's bushes lie within its 40 m)."""
        if count == 0:
            return _Items.empty()
        units = self._annulus_points(region, count * _ATTEMPTS)
        if den is not None:
            towards = region.centre - den * float(region.centre @ den)
            first = den * np.cos(DEN_FIRST_BUSH_M / self.surface.radius_m) + towards / np.linalg.norm(towards) * np.sin(
                DEN_FIRST_BUSH_M / self.surface.radius_m
            )
            near_first = self._annulus_points(_Annulus(first, 0.0, 3.0), _ATTEMPTS)
            units = np.concatenate([near_first, units])
        candidates = self._at(units, node, region)
        ok = self._ground_ok(candidates)
        candidate_units = self._units(candidates)
        ok &= region.contains(candidate_units, self.surface.radius_m)
        if outside_rings_m is not None:
            for camp in self.camps:
                ok &= self.surface.distances_m(camp, candidate_units) > outside_rings_m
        if within is not None:
            ok &= within.contains(candidate_units, self.surface.radius_m)
        for hotspot in avoid:
            ok &= self.surface.distances_m(np.array(hotspot.centre), candidate_units) > hotspot.radius_m
        taken: list[int] = []
        others = self._units(placed)
        for index in np.flatnonzero(ok).tolist():
            point = candidate_units[index]
            near = [*candidate_units[taken], *others[self.surface.distances_m(point, others) < COUNTED_SPACING_M]]
            if all(self.surface.distance_m(point, other) >= COUNTED_SPACING_M for other in near):
                taken.append(index)
            if len(taken) == count:
                return candidates.take(np.array(taken, dtype=np.int64))
        raise ValueError(f"room for only {len(taken)} of {count} {node} near {region.centre.round(4).tolist()}")

    def _annulus_points(self, region: "_Annulus", count: int) -> FloatArray:
        frame = tangent_frame(region.centre)
        inner, outer = region.inner_m + _EDGE_MARGIN_M, max(region.outer_m - _EDGE_MARGIN_M, 0.0)
        angle = self.rng.random(count) * 2 * np.pi
        distance = np.sqrt(inner**2 + self.rng.random(count) * (outer**2 - inner**2))
        v = frame.up * self.surface.radius_m + np.outer(np.cos(angle) * distance, frame.east)
        v += np.outer(np.sin(angle) * distance, frame.north)
        return np.asarray(v / np.linalg.norm(v, axis=1, keepdims=True), dtype=np.float64)

    def _at(self, units: FloatArray, node: FloraNode, region: "_Annulus") -> _Items:
        """Items of the node kind at the points, each in its nearest cell (the kind its biome grows)."""
        nearby = np.flatnonzero(self.surface.distances_m(region.centre) <= region.outer_m + 2 * self.spacing)
        cells = nearby[np.argmax(units @ self.grid.positions[nearby].T, axis=1)]
        east_axis, north_axis = tangent_frames(self.grid.positions[cells])
        offsets = units * self.surface.radius_m / np.einsum("ij,ij->i", units, self.grid.positions[cells])[:, None]
        east_m, north_m = np.einsum("ij,ij->i", offsets, east_axis), np.einsum("ij,ij->i", offsets, north_axis)
        biomes = [BIOME_NAMES[biome] for biome in self.surface.biomes[cells]]
        codes = np.array([self.codes[self.flora.kind_of(node, biome)] for biome in biomes])
        return self._items(cells, east_m, north_m, codes)

    # ground rules ----------------------------------------------------------------------------------------------

    def _units(self, items: _Items) -> FloatArray:
        return _offset_units(self.grid, self.surface.radius_m, items.cell, items.east, items.north)

    def _ground_ok(self, items: _Items) -> BoolArray:
        """Land, not too steep, above the sea, clear of rivers, roads, site props, camps, features, the town chart."""
        surface = self.surface
        units = self._units(items)
        owner = _owner_cells(self.grid, surface.padded_neighbours, items.cell, units)
        ok = surface.walk[owner] & ~surface.chart.contains(units)
        corners, weights, tilt_deg = _locate(self.grid, self.triangles_of, owner, units, surface)
        height = (surface.heights[corners] * weights).sum(axis=1)
        by_sea = surface.ocean[corners].any(axis=1)
        ok &= ~(by_sea & (height < SHORE_MIN_HEIGHT_M)) & (tilt_deg <= MAX_SLOPE_DEG)
        reeds = self.node_of[items.kind] == "reed_bed"
        clearance = np.where(reeds, REED_RIVER_CLEARANCE_M, RIVER_CLEARANCE_M)
        index = _CellIndex(owner, surface.padded_neighbours)
        for river in surface.rivers:
            ok &= ~index.near_polyline(units, river.cells, self.grid, surface.radius_m, clearance)
        for road in self.roads:
            ok &= ~index.near_polyline(units, road.cells, self.grid, surface.radius_m, ROAD_CLEARANCE_M[road.kind])
        for point, clear in self.obstacles:
            ok &= ~index.near_point(units, point, self.grid, surface.radius_m, clear)
        return ok

    @cached_property
    def obstacles(self) -> list[tuple[FloatArray, float]]:
        """Points flora keeps clear of, with their clearance: camp grounds, site props, fixed features."""
        obstacles: list[tuple[FloatArray, float]] = []
        for site in self.surface.sites:
            if site.kind == "camp":
                obstacles.append((np.array(site.anchor.position), CAMP_CLEARING_M))
            anchor = site.anchor
            up, east, north = np.array(anchor.position), np.array(anchor.east), np.array(anchor.north)
            for placement in site.placements:
                v = up * (self.surface.radius_m + anchor.height_m) + east * placement.x - north * placement.z
                half = 0.5 * float(np.hypot(placement.footprint.x, placement.footprint.z))
                obstacles.append((v / np.linalg.norm(v), half + PROP_CLEARANCE_M))
        obstacles += [(np.array(feature.position), FEATURE_CLEARANCE_M) for feature in self.features]
        return obstacles


def _steps(metres: FloatArray) -> IntArray:
    return np.asarray(np.clip(np.round(metres / OFFSET_STEP_M), -127, 127), dtype=np.int64)


def _offset_units(
    grid: Grid, radius_m: float, cells: IntArray, east: NDArray[np.integer], north: NDArray[np.integer]
) -> FloatArray:
    ups = grid.positions[cells]
    east_axis, north_axis = tangent_frames(ups)
    v = ups * radius_m + east_axis * (east.astype(np.float64) * OFFSET_STEP_M)[:, None]
    v += north_axis * (north.astype(np.float64) * OFFSET_STEP_M)[:, None]
    return np.asarray(v / np.linalg.norm(v, axis=1, keepdims=True), dtype=np.float64)


def _owner_cells(grid: Grid, padded: IntArray, cells: IntArray, units: FloatArray) -> IntArray:
    """The cell each point lies in: its own cell or the neighbour whose centre is nearest."""
    candidates = np.concatenate([cells[:, None], padded[cells]], axis=1)
    positions = np.concatenate([grid.positions, np.full((1, 3), np.nan)])[candidates]
    scores = np.nan_to_num(np.einsum("ijk,ik->ij", positions, units), nan=-2.0)
    return np.asarray(candidates[np.arange(len(cells)), scores.argmax(axis=1)], dtype=np.int64)


def _incident_triangles(grid: Grid) -> IntArray:
    """(cell_count, 6) triangle indices around each cell, padded with -1."""
    triangles = grid.triangles
    order = np.argsort(triangles.ravel(), kind="stable")
    cells = triangles.ravel()[order]
    triangle_ids = order // 3
    starts = np.searchsorted(cells, np.arange(grid.cell_count))
    rank = np.arange(len(cells)) - starts[cells]
    incident = np.full((grid.cell_count, 6), -1, dtype=np.int64)
    incident[cells, rank] = triangle_ids
    return incident


def _locate(
    grid: Grid, triangles_of: IntArray, owner: IntArray, units: FloatArray, surface: Surface
) -> tuple[IntArray, FloatArray, FloatArray]:
    """The grid triangle under each point (around its owner cell): corners, barycentric weights and the slope of
    the triangle's surface in degrees."""
    count = len(owner)
    corners = np.zeros((count, 3), dtype=np.int64)
    weights = np.zeros((count, 3))
    found = np.zeros(count, dtype=bool)
    for slot in range(triangles_of.shape[1]):
        triangle = triangles_of[owner, slot]
        valid = (triangle >= 0) & ~found
        if not valid.any():
            continue
        tri = grid.triangles[triangle[valid]]
        a, b, c = (grid.positions[tri[:, k]] for k in range(3))
        p = units[valid]
        normal = np.cross(b - a, c - a)
        t = np.einsum("ij,ij->i", a, normal) / np.einsum("ij,ij->i", p, normal)
        hit = p * t[:, None]
        area = np.einsum("ij,ij->i", normal, normal)
        wa = np.einsum("ij,ij->i", np.cross(c - b, hit - b), normal) / area
        wb = np.einsum("ij,ij->i", np.cross(a - c, hit - c), normal) / area
        wc = 1 - wa - wb
        inside = (wa >= -1e-9) & (wb >= -1e-9) & (wc >= -1e-9)
        rows = np.flatnonzero(valid)[inside]
        corners[rows] = tri[inside]
        weights[rows] = np.stack([wa, wb, wc], axis=1)[inside]
        found[rows] = True
    # a point outside its owner's fan (numerically on an edge) takes the owner's height and is flat
    corners[~found] = owner[~found, None]
    weights[~found] = 1 / 3
    lifted = grid.positions[corners] * (surface.radius_m + surface.heights[corners])[..., None]
    normal = np.cross(lifted[:, 1] - lifted[:, 0], lifted[:, 2] - lifted[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    cos_tilt = np.abs(np.einsum("ij,ij->i", normal, units))
    tilt = np.where(found, np.degrees(np.arccos(np.clip(cos_tilt, -1, 1))), 0.0)
    return corners, weights, tilt


class _CellIndex:
    """Items grouped by the cell they lie in, to test only the items near a segment or point."""

    def __init__(self, owner: IntArray, padded: IntArray) -> None:
        self.order = np.argsort(owner, kind="stable")
        self.sorted_cells = owner[self.order]
        self.padded = padded

    def items_near(self, cells: Sequence[int]) -> IntArray:
        around = np.unique(np.concatenate([np.asarray(cells), self.padded[np.asarray(cells)].ravel()]))
        starts = np.searchsorted(self.sorted_cells, around, side="left")
        ends = np.searchsorted(self.sorted_cells, around, side="right")
        if not (ends > starts).any():
            return np.zeros(0, dtype=np.int64)
        return np.asarray(self.order[np.concatenate([np.arange(s, e) for s, e in zip(starts, ends, strict=True)])])

    def near_polyline(
        self, units: FloatArray, cells: list[int], grid: Grid, radius_m: float, clearance: FloatArray | float
    ) -> BoolArray:
        near = np.zeros(len(units), dtype=bool)
        limits = np.broadcast_to(np.asarray(clearance, dtype=np.float64), (len(units),))
        for a_cell, b_cell in zip(cells, cells[1:], strict=False):
            items = self.items_near([a_cell, b_cell])
            if len(items) == 0:
                continue
            a, b = grid.positions[a_cell], grid.positions[b_cell]
            ab = b - a
            p = units[items]
            t = np.clip((p - a) @ ab / max(float(ab @ ab), 1e-18), 0, 1)
            distance = np.linalg.norm(p - (a + t[:, None] * ab), axis=1) * radius_m
            near[items[distance < limits[items]]] = True
        return near

    def near_point(
        self, units: FloatArray, point: FloatArray, grid: Grid, radius_m: float, clearance: float
    ) -> BoolArray:
        near = np.zeros(len(units), dtype=bool)
        items = self.items_near([int(np.argmax(grid.positions @ point))])
        if len(items):
            distance = np.linalg.norm(units[items] - point, axis=1) * radius_m
            near[items[distance < clearance]] = True
        return near
