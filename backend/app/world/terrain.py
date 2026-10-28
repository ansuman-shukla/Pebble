"""Terrain heights: continents and the land-loop band from noise, mountain ranges, then the authored site shapes."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.world.grid import Grid, IntArray
from app.world.noise import fbm, ridged, warp
from app.world.spec import Falls, Hill, LatLon, Plateau, SiteSpec, Volcano, Waypoint, WorldSpec
from app.world.sphere import FloatArray, angle_between, tangent_frame, unit_from_lat_lon

BoolArray = NDArray[np.bool_]

_MIN_LAND_M = 0.5
_LOWEST_LAND_M = 1.0  # base land starts this high above the sea
_SHALLOWEST_SEA_M = -2.0  # and the sea floor this deep
_SHELF_FIELD = 0.6  # continental field depth where the sea floor reaches min_sea_m (a gentle shelf)
_SEA_DEPTH = 0.25  # authored seas are shallower than open ocean
_SEA_SHORE = 0.8  # noise on a sea's reach (in radii) so its shore isn't a circle


def smoothstep(edge0: float, edge1: float, x: FloatArray) -> FloatArray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def polyline_distance(units: FloatArray, points: list[FloatArray], widths: list[float], closed: bool) -> FloatArray:
    """Great-circle distance (radians) from each unit vector to a polyline of arcs, divided by the local width."""
    best = np.full(len(units), np.inf)
    count = len(points) if closed else len(points) - 1
    for index in range(count):
        a, b = points[index], points[(index + 1) % len(points)]
        wa, wb = widths[index], widths[(index + 1) % len(points)]
        normal = np.cross(a, b)
        normal /= np.linalg.norm(normal)
        span = angle_between(b[None], a)[0]
        off_plane = units @ normal
        projected = units - np.outer(off_plane, normal)
        projected /= np.maximum(np.linalg.norm(projected, axis=1, keepdims=True), 1e-12)
        along = np.arctan2(np.cross(a, projected) @ normal, projected @ a)
        inside = (along >= 0) & (along <= span)
        t = np.clip(along / span, 0, 1)
        distance = np.where(
            inside,
            np.abs(np.arcsin(np.clip(off_plane, -1, 1))),
            np.minimum(angle_between(units, a), angle_between(units, b)),
        )
        best = np.minimum(best, distance / (wa + (wb - wa) * t))
    return best


def _waypoint_units(waypoints: list[Waypoint]) -> list[FloatArray]:
    return [unit_from_lat_lon(*waypoint.at) for waypoint in waypoints]


def loop_band(spec: WorldSpec, units: FloatArray, width_scale: float = 1.0) -> FloatArray:
    """Distance to the land-loop spine in units of the waypoints' half-widths (≤ 1 inside the band)."""
    loop = spec.land_loop
    widths = [waypoint.width_m * width_scale / spec.radius_m for waypoint in loop.waypoints]
    return polyline_distance(units, _waypoint_units(loop.waypoints), widths, closed=True)


@dataclass(frozen=True)
class BaseTerrain:
    heights: FloatArray
    continental: FloatArray  # > 0 on land before site shaping


def smooth(heights: FloatArray, neighbours: IntArray, passes: int, strength: float) -> FloatArray:
    """Laplacian smoothing on the grid: each pass moves every cell `strength` of the way to its neighbours' mean."""
    valid = neighbours >= 0
    padded = np.where(valid, neighbours, 0)
    counts = valid.sum(axis=1)
    smoothed = heights.copy()
    for _ in range(passes):
        mean = np.where(valid, smoothed[padded], 0.0).sum(axis=1) / counts
        smoothed += strength * (mean - smoothed)
    return smoothed


def base_terrain(spec: WorldSpec, grid: Grid) -> BaseTerrain:
    terrain, seed = spec.terrain, spec.seed
    units = grid.positions
    warped = warp(units, seed + 1, terrain.warp.frequency, terrain.warp.octaves, terrain.warp.strength)
    warped /= np.linalg.norm(warped, axis=1, keepdims=True)

    field = 1 - loop_band(spec, warped)
    for continent in spec.continents:
        reach = angle_between(warped, unit_from_lat_lon(*continent.at)) / np.radians(continent.radius_deg)
        field = np.maximum(field, 1 - reach)
    shore = _SEA_SHORE * fbm(units, seed + 8, 2 * terrain.coast.frequency, terrain.coast.octaves)
    for sea in spec.seas:
        reach = angle_between(warped, unit_from_lat_lon(*sea.at)) / np.radians(sea.radius_deg) + shore
        field = np.minimum(field, _SEA_DEPTH * (reach - 1))
    field += terrain.coast_amplitude * fbm(units, seed + 2, terrain.coast.frequency, terrain.coast.octaves)
    islands = fbm(units, seed + 3, terrain.islands.frequency, terrain.islands.octaves) - terrain.island_threshold
    field = np.maximum(field, islands * 2)
    field -= terrain.sea_level
    core = loop_band(spec, units, spec.land_loop.core_fraction) <= 1
    field = np.where(core, np.maximum(field, 0.05), field)

    inland = smoothstep(0.0, 0.5, field)
    hills = terrain.hills_m * (0.5 + 0.5 * fbm(units, seed + 4, terrain.hills.frequency, terrain.hills.octaves))
    land = _LOWEST_LAND_M + terrain.lowland_m * inland + hills * smoothstep(0.05, 0.4, field)
    relief = ridged(units, seed + 7, terrain.relief.frequency, terrain.relief.octaves)
    land += terrain.relief_m * smoothstep(terrain.relief_threshold, 1.0, relief) * smoothstep(0.1, 0.45, field)
    land += _mountains(spec, units, seed) * smoothstep(0.0, 0.2, field)
    seabed = _SHALLOWEST_SEA_M + (terrain.min_sea_m - _SHALLOWEST_SEA_M) * smoothstep(0.0, _SHELF_FIELD, -field)
    is_land = field > 0
    heights = np.where(is_land, np.minimum(land, terrain.max_land_m), seabed)
    # smoothing calms crests and coast cliffs; clamping back to each side of sea level keeps the coastline
    heights = smooth(heights, grid.neighbours, terrain.smoothing.passes, terrain.smoothing.strength)
    heights = np.where(is_land, np.maximum(heights, _LOWEST_LAND_M), np.minimum(heights, _SHALLOWEST_SEA_M))
    heights = np.where(core, np.maximum(heights, spec.land_loop.core_height_m), heights)
    return BaseTerrain(heights=heights, continental=field)


def _mountains(spec: WorldSpec, units: FloatArray, seed: int) -> FloatArray:
    crest = ridged(units, seed + 5, spec.terrain.ridges.frequency, spec.terrain.ridges.octaves)
    total = np.zeros(len(units))
    for mountain_range in spec.mountains:
        points = [unit_from_lat_lon(*point) for point in mountain_range.points]
        widths = [mountain_range.width_m / spec.radius_m] * len(points)
        reach = polyline_distance(units, points, widths, closed=False)
        total = np.maximum(total, mountain_range.height_m * smoothstep(1.0, 0.0, reach) * (0.45 + 0.55 * crest))
    return total


# --- authored site shapes ---


@dataclass(frozen=True)
class SiteArea:
    """Cells an authored site pins: their heights must survive hydrology unchanged."""

    site_id: str
    height_m: float  # h0: the plateau height of the site's local frame
    flat: BoolArray  # cells held at h0 (depression filling must not lift them)
    basin: BoolArray  # cells that keep their shaped height through depression filling (the crater)
    bowl: BoolArray  # an authored lake bed (authored rivers start or end there instead of carving it)
    bowl_level: float  # the bowl lake's intended surface (inf without a bowl)
    authored_height: bool  # False: h0 came from the terrain and may follow the plateau when a depression fills


def local_offsets(units: FloatArray, at: LatLon, radius_m: float) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Per cell: great-circle distance (m) to the site and the gnomonic local (x east, z south) offset."""
    frame = tangent_frame(unit_from_lat_lon(*at))
    distance = angle_between(units, frame.up) * radius_m
    facing = np.maximum(units @ frame.up, 1e-6)
    x = radius_m * (units @ frame.east) / facing
    z = radius_m * (units @ frame.south) / facing
    return distance, x, z


def shape_site(spec: WorldSpec, site: SiteSpec, units: FloatArray, heights: FloatArray) -> SiteArea:
    """Reshape `heights` in place for one site and return what it pinned."""
    shape = site.terrain
    distance, x, z = local_offsets(units, site.at, spec.radius_m)
    anchor_height = float(heights[int(np.argmin(distance))])
    if isinstance(shape, Plateau):
        h0 = max(anchor_height, spec.terrain.beach_m) if shape.height_m is None else shape.height_m
        return _flatten(site.id, heights, distance, h0, shape.radius_m, shape.blend_m, shape.height_m is not None)
    if isinstance(shape, Hill):
        h0 = max(anchor_height, spec.terrain.beach_m) + shape.rise_m
        return _flatten(site.id, heights, distance, h0, shape.radius_m, shape.blend_m, False)
    if isinstance(shape, Volcano):
        return _volcano(site.id, heights, distance, shape)
    return _falls(site.id, heights, distance, x, z, shape)


def _flatten(
    site_id: str, heights: FloatArray, distance: FloatArray, h0: float, radius: float, blend: float, authored: bool
) -> SiteArea:
    weight = smoothstep(radius + blend, radius, distance)
    heights[:] = heights + (h0 - heights) * weight
    flat = distance <= max(radius, float(distance.min()))
    heights[flat] = h0
    return SiteArea(
        site_id=site_id,
        height_m=h0,
        flat=flat,
        basin=np.zeros_like(flat),
        bowl=np.zeros_like(flat),
        bowl_level=np.inf,
        authored_height=authored,
    )


def _volcano(site_id: str, heights: FloatArray, distance: FloatArray, shape: Volcano) -> SiteArea:
    rim = shape.peak_m
    cone = (
        rim
        * np.clip(1 - (distance - shape.crater_radius_m) / (shape.base_radius_m - shape.crater_radius_m), 0, 1) ** 1.4
    )
    floor = rim - shape.crater_depth_m
    crater_t = np.clip((distance - shape.floor_radius_m) / (shape.crater_radius_m - shape.floor_radius_m), 0, 1)
    crater = floor + (rim - floor) * crater_t**2
    shaped = np.where(distance <= shape.crater_radius_m, crater, np.maximum(heights, cone))
    heights[:] = np.where(distance <= shape.base_radius_m, shaped, heights)
    flat = distance <= max(shape.floor_radius_m, float(distance.min()))
    heights[flat] = floor
    return SiteArea(
        site_id=site_id,
        height_m=floor,
        flat=flat,
        basin=distance <= shape.crater_radius_m,
        bowl=np.zeros_like(flat),
        bowl_level=np.inf,
        authored_height=True,
    )


def _falls(
    site_id: str, heights: FloatArray, distance: FloatArray, x: FloatArray, z: FloatArray, shape: Falls
) -> SiteArea:
    bearing = np.radians(shape.bearing_deg)
    toward = (np.sin(bearing), -np.cos(bearing))  # local (x east, z south) direction from the lip to the lake
    ahead = x * toward[0] + z * toward[1]
    lake_x, lake_z = toward[0] * shape.lake_distance_m, toward[1] * shape.lake_distance_m
    lake_distance = np.hypot(x - lake_x, z - lake_z)
    surface = shape.lip_m - shape.drop_m

    upland = (distance <= shape.upland_radius_m) & (ahead < shape.lake_distance_m - shape.lake_radius_m)
    heights[upland] = np.maximum(heights[upland], shape.lip_m)
    flat = distance <= max(shape.flat_radius_m, float(distance.min()))
    heights[flat] = shape.lip_m
    rim = (lake_distance <= shape.lake_radius_m * 1.8) & ~upland
    heights[rim] = np.maximum(heights[rim], surface + 4.0)
    bowl = lake_distance <= shape.lake_radius_m
    heights[bowl] = surface - shape.lake_depth_m * (1 - (lake_distance[bowl] / shape.lake_radius_m) ** 2) - 0.5
    return SiteArea(
        site_id=site_id,
        height_m=shape.lip_m,
        flat=flat,
        basin=np.zeros_like(flat),
        bowl=bowl,
        bowl_level=surface,
        authored_height=True,
    )


def ensure_land(heights: FloatArray, cells: BoolArray) -> None:
    heights[cells] = np.maximum(heights[cells], _MIN_LAND_M)
