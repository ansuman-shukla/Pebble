"""Hotspots (10-world-v1 §1.2): named node clusters in rings around each settlement, their fixed features and dens.

Centres are authored (`data/world/hotspots.yaml`) and validated here; features are placed by rule, so they follow the
terrain: fishing spots on the shore, iron sand on its river, obsidian in volcanic ground, dens off the roads.
"""

from collections.abc import Iterable, Sequence

import numpy as np

from app.world.biomes import BIOME_IDS
from app.world.paths import reachable
from app.world.spec import (
    BIOME_NAMES,
    DenSpec,
    FeatureSpec,
    HotspotSpec,
    HotspotsSpec,
    Ring,
    RingSpec,
)
from app.world.sphere import FloatArray, bearing_deg, destination, unit_from_lat_lon
from app.world.surface import Surface
from app.world.terrain import BoolArray, polyline_distance
from app.world.view import Feature, Ground, Hotspot, Road

MAX_MOVE_M = 150.0  # a hotspot may lie this far from its target to keep the rules (10 §1.2)
WATER_MOVE_M = 2000.0  # a hotspot whose features need water follows the nearest water this far instead (D122)
WATER_FEATURES = frozenset({"fishing_spot", "gold_pool", "iron_sand_bar"})
FEATURE_SPACING_M = 20.0  # features of one kind in a hotspot keep this far apart
DEN_BESIDE_M = (40.0, 60.0)  # a den beside a road lies this far off it
DEN_EDGE_M = 35.0  # a den at a hotspot's edge lies this far outside its radius (bushes 30-50 m away)
DEN_MIN_SHARE = 0.5  # a den toward a bearing lies at least this share of its distance from the site
_BEARING_STEP_DEG = 15.0


def ring_of(distance_m: float, rings: RingSpec) -> Ring | None:
    if distance_m <= rings.home_m:
        return "home"
    if distance_m <= rings.middle_m:
        return "middle"
    if distance_m > rings.far_m:
        return "far"
    return None


def place_hotspots(spec: HotspotsSpec, surface: Surface) -> list[Hotspot]:
    """Each hotspot at its target, or at the nearest cell within MAX_MOVE_M (WATER_MOVE_M when its features need
    water) where it keeps every rule: on land of one of its biomes, outside the town chart, reachable on foot from
    the town, in its ring, `min_spacing_m` from the hotspots before it, with room for its fixed features. Raises
    when no such spot exists. A painted hotspot then gives its land its authored biome (in `surface.biomes`, the
    generated world's array)."""
    from_town = reachable(surface.grid, surface.walk, surface.site("town").cell)
    hotspots: list[Hotspot] = []
    for hotspot_spec in spec.hotspots:
        hotspot = _hotspot(hotspot_spec, spec, surface, from_town, hotspots)
        if hotspot_spec.paint is not None:
            inside = surface.distances_m(np.array(hotspot.centre)) <= hotspot.radius_m
            surface.biomes[inside & surface.walk] = BIOME_IDS[hotspot_spec.paint]
        hotspots.append(hotspot)
    return hotspots


def _hotspot(
    spec: HotspotSpec, hotspots: HotspotsSpec, surface: Surface, from_town: BoolArray, placed: list[Hotspot]
) -> Hotspot:
    target = unit_from_lat_lon(*spec.at)
    reach_m = WATER_MOVE_M if any(feature.kind in WATER_FEATURES for feature in spec.features) else MAX_MOVE_M
    at_target = _candidate(spec, surface, target)
    problem = _problem(at_target, spec, hotspots, surface, from_town, placed)
    if problem is None:
        return at_target
    distance = surface.distances_m(target)
    near = np.flatnonzero(distance <= reach_m)
    for cell in near[np.argsort(distance[near], kind="stable")].tolist():
        hotspot = _candidate(spec, surface, surface.cell_unit(cell))
        if _problem(hotspot, spec, hotspots, surface, from_town, placed) is None:
            return hotspot
    raise ValueError(f"hotspot {spec.id} has no spot within {reach_m:.0f} m of {spec.at}: at it, {problem}")


def _candidate(spec: HotspotSpec, surface: Surface, centre: FloatArray) -> Hotspot:
    return Hotspot(
        id=spec.id,
        name=spec.name,
        called=spec.called,
        centre=_vector(centre),
        cell=surface.nearest_cell(centre),
        radius_m=spec.radius_m,
        settlement=spec.of,
        ring=spec.ring,
        distance_m=round(surface.distance_m(surface.site_unit(spec.of), centre), 1),
        claim=spec.claim,
        danger=spec.danger,
        thirst=spec.thirst,
        woodland=spec.woodland,
        flora=dict(spec.flora),
        hunting=list(spec.hunting),
    )


def _problem(
    hotspot: Hotspot,
    spec: HotspotSpec,
    hotspots: HotspotsSpec,
    surface: Surface,
    from_town: BoolArray,
    placed: list[Hotspot],
) -> str | None:
    """Why the hotspot can't be where it is, or None."""
    cell = hotspot.cell
    biome = BIOME_NAMES[surface.biomes[cell]]
    if not surface.walk[cell] or (spec.paint is None and biome not in spec.biomes):
        return f"it lies in {biome}, not in {spec.biomes}"
    if surface.in_town[cell]:
        return "it lies in the town chart"
    if not from_town[cell]:
        return "it can't be reached on foot from the town"
    if ring_of(hotspot.distance_m, hotspots.rings) != spec.ring:
        return f"it lies {hotspot.distance_m:.0f} m from {spec.of}, outside its {spec.ring} ring"
    centre = np.array(hotspot.centre)
    for other in placed:
        gap = surface.distance_m(centre, np.array(other.centre))
        if gap < hotspots.min_spacing_m:
            return f"it lies {gap:.0f} m from {other.id}"
    inside = surface.distances_m(centre) <= hotspot.radius_m
    for feature in spec.features:
        if feature.kind != "waterhole":
            room = len(_spread(_candidates(feature, surface, inside), centre, feature.count, surface))
            if room < feature.count:
                return f"it has room for {room} of {feature.count} {feature.kind}"
    return None


def place_grounds(spec: HotspotsSpec, surface: Surface) -> list[Ground]:
    return [
        Ground(
            id=ground.id,
            name=ground.name,
            site=ground.site,
            centre=_vector(surface.site_unit(ground.site)),
            radius_m=ground.radius_m,
            hunting=list(ground.hunting),
        )
        for ground in spec.grounds
    ]


def place_features(spec: HotspotsSpec, surface: Surface, hotspots: list[Hotspot], roads: list[Road]) -> list[Feature]:
    """Every hotspot's fixed nodes and den, and a claim marker where its owner's road or path enters it."""
    by_id = {hotspot.id: hotspot for hotspot in hotspots}
    features: list[Feature] = []
    for hotspot_spec in spec.hotspots:
        hotspot = by_id[hotspot_spec.id]
        for feature in hotspot_spec.features:
            features.extend(_features(feature, hotspot, surface))
        if hotspot_spec.den is not None:
            features.append(_den(hotspot_spec.den, hotspot, surface, roads))
        if hotspot.claim is not None:
            features.append(_marker(hotspot, surface, roads))
    return features


def _features(spec: FeatureSpec, hotspot: Hotspot, surface: Surface) -> list[Feature]:
    centre = np.array(hotspot.centre)
    inside = surface.distances_m(centre) <= hotspot.radius_m
    if spec.kind == "waterhole":
        return [_waterhole(hotspot, surface, inside)]
    water = "lake" if spec.kind == "gold_pool" else spec.water
    points = _spread(_candidates(spec, surface, inside), centre, spec.count, surface)
    return [
        Feature(
            id=f"{hotspot.id}:{spec.kind}-{index + 1}" if spec.count > 1 else f"{hotspot.id}:{spec.kind}",
            kind=spec.kind,
            hotspot=hotspot.id,
            position=_vector(point),
            cell=surface.nearest_cell(point),
            water=water,
            cap=spec.cap,
        )
        for index, point in enumerate(points)
    ]


def _candidates(spec: FeatureSpec, surface: Surface, inside: BoolArray) -> FloatArray:
    """Where a feature of the kind may lie inside the hotspot."""
    positions = surface.grid.positions
    match spec.kind:
        case "fishing_spot" if spec.water == "sea":
            return _shore_points(surface, inside, surface.ocean, zero_crossing=True)
        case "fishing_spot" if spec.water == "river":
            return positions[inside & surface.river]
        case "fishing_spot" | "gold_pool":
            return _shore_points(surface, inside, surface.lake, zero_crossing=False)
        case "iron_sand_bar":
            on_river = np.zeros(surface.grid.cell_count, dtype=bool)
            on_river[next(river.cells for river in surface.rivers if river.name == spec.river)] = True
            return positions[inside & on_river & surface.walk]
        case "obsidian_field":
            return positions[inside & surface.biome_is("volcanic")]
        case "flint_seam":
            return positions[inside & surface.walk & ~surface.river]
    raise ValueError(f"no placement rule for {spec.kind}")


def _shore_points(surface: Surface, inside: BoolArray, water: BoolArray, zero_crossing: bool) -> FloatArray:
    """Points on the edge between an inside land cell and a neighbouring water cell: where the drawn sea level
    crosses the edge (sea), or halfway (a lake's level surface)."""
    padded_water = np.append(water, False)
    land = np.flatnonzero(inside & surface.walk)
    points: list[FloatArray] = []
    for cell in land.tolist():
        for other in surface.padded_neighbours[cell].tolist():
            if not padded_water[other]:
                continue
            t = 0.5
            if zero_crossing:
                high, low = surface.heights[cell], surface.heights[other]
                t = float(np.clip(high / (high - low), 0.05, 0.95)) if high > low else 0.5
            point = surface.grid.positions[cell] * (1 - t) + surface.grid.positions[other] * t
            points.append(point / np.linalg.norm(point))
    return np.asarray(np.array(points).reshape(-1, 3), dtype=np.float64)


def _spread(candidates: FloatArray, centre: FloatArray, count: int, surface: Surface) -> list[FloatArray]:
    """Up to `count` candidates, nearest the centre first, each FEATURE_SPACING_M from those taken."""
    if len(candidates) == 0:
        return []
    order = np.argsort(surface.distances_m(centre, candidates), kind="stable")
    taken: list[FloatArray] = []
    for index in order.tolist():
        point = candidates[index]
        if all(surface.distance_m(point, other) >= FEATURE_SPACING_M for other in taken):
            taken.append(point)
        if len(taken) == count:
            break
    return taken


def _waterhole(hotspot: Hotspot, surface: Surface, inside: BoolArray) -> Feature:
    """At the fresh water nearest the centre (a river or a lake shore); without any, a drawn pool at the centre."""
    centre = np.array(hotspot.centre)
    river = surface.grid.positions[inside & surface.river]
    shore = _shore_points(surface, inside, surface.lake, zero_crossing=False)
    for water, candidates in (("river", river), ("lake", shore)):
        points = _spread(candidates, centre, 1, surface)
        if points:
            return Feature(
                id=f"{hotspot.id}:waterhole",
                kind="waterhole",
                hotspot=hotspot.id,
                position=_vector(points[0]),
                cell=surface.nearest_cell(points[0]),
                water=water,
            )
    return Feature(
        id=f"{hotspot.id}:waterhole",
        kind="waterhole",
        hotspot=hotspot.id,
        position=hotspot.centre,
        cell=hotspot.cell,
        pool=True,
    )


def route_points(road: Road, surface: Surface) -> list[FloatArray]:
    return [np.array(point) for point in road.lead] + [surface.cell_unit(cell) for cell in road.cells]


def road_distance_m(units: FloatArray, roads: Iterable[Road], surface: Surface) -> FloatArray:
    """Metres from each unit vector to the nearest of the roads' polylines."""
    best = np.full(len(np.atleast_2d(units)), np.inf)
    for road in roads:
        points = route_points(road, surface)
        if len(points) >= 2:
            distance = polyline_distance(np.atleast_2d(units), points, [1.0] * len(points), closed=False)
            best = np.minimum(best, distance * surface.radius_m)
    return best


def _den(spec: DenSpec, hotspot: Hotspot, surface: Surface, roads: list[Road]) -> Feature:
    match spec.place:
        case "beside":
            point = _beside(hotspot, surface, next(road for road in roads if road.id == spec.road), roads)
        case "edge":
            point = _edge(hotspot, surface, roads)
        case "bearing":
            point = _toward(spec, surface)
    if point is None:
        raise ValueError(f"no place for the {spec.animal} den of {hotspot.id}")
    return Feature(
        id=f"{hotspot.id}:den",
        kind="den",
        hotspot=hotspot.id,
        position=_vector(point),
        cell=surface.nearest_cell(point),
        animal=spec.animal,
    )


def _standable(surface: Surface, point: FloatArray) -> bool:
    cell = surface.nearest_cell(point)
    return bool(surface.walk[cell] and not surface.river[cell] and not surface.in_town[cell])


def _beside(hotspot: Hotspot, surface: Surface, road: Road, roads: Sequence[Road]) -> FloatArray | None:
    """DEN_BESIDE_M off the road, beside its cell nearest the hotspot's centre (then the next nearest)."""
    centre = np.array(hotspot.centre)
    points = route_points(road, surface)
    order = np.argsort([surface.distance_m(centre, point) for point in points], kind="stable")
    middle = (DEN_BESIDE_M[0] + DEN_BESIDE_M[1]) / 2
    for index in order.tolist():
        before, after = points[max(index - 1, 0)], points[min(index + 1, len(points) - 1)]
        heading = float(bearing_deg(before, after[None])[0])
        for side in (90.0, -90.0):
            point = destination(points[index], heading + side, middle / surface.radius_m)
            off = float(road_distance_m(point, [road], surface)[0])
            clear = float(road_distance_m(point, roads, surface)[0]) >= DEN_BESIDE_M[0]
            if _standable(surface, point) and clear and DEN_BESIDE_M[0] <= off <= DEN_BESIDE_M[1]:
                return point
    return None


def _edge(hotspot: Hotspot, surface: Surface, roads: Sequence[Road]) -> FloatArray | None:
    """DEN_EDGE_M outside the radius, on the side away from the roads that reach the hotspot."""
    centre = np.array(hotspot.centre)
    near = [
        point
        for road in roads
        if hotspot.id in road.stops
        for point in route_points(road, surface)
        if surface.distance_m(centre, point) <= 2 * hotspot.radius_m
    ]
    away = 0.0
    if near:
        bearings = np.radians(bearing_deg(centre, np.array(near)))
        away = (float(np.degrees(np.arctan2(np.sin(bearings).sum(), np.cos(bearings).sum()))) + 180) % 360
    angle = (hotspot.radius_m + DEN_EDGE_M) / surface.radius_m
    for step in range(int(360 / _BEARING_STEP_DEG)):
        turn = _BEARING_STEP_DEG * ((step + 1) // 2) * (1 if step % 2 else -1)
        point = destination(centre, away + turn, angle)
        if _standable(surface, point) and road_distance_m(point, roads, surface)[0] > DEN_BESIDE_M[0]:
            return point
    return None


def _toward(spec: DenSpec, surface: Surface) -> FloatArray | None:
    """The habitat cell nearest the point `distance_m` from the site along the bearing, at least half that far from
    the site (so it stays out where the bearing puts it, whatever the ground near the point)."""
    assert spec.site is not None and spec.bearing_deg is not None and spec.distance_m is not None
    site = surface.site_unit(spec.site)
    target = destination(site, spec.bearing_deg, spec.distance_m / surface.radius_m)
    habitat = np.isin(surface.biomes, [BIOME_IDS[name] for name in spec.biomes]) & surface.walk & ~surface.river
    distance = surface.distances_m(target)
    habitat &= surface.distances_m(site) >= DEN_MIN_SHARE * spec.distance_m
    if not habitat.any():
        return None
    return surface.cell_unit(int(np.argmin(np.where(habitat, distance, np.inf))))


def _marker(hotspot: Hotspot, surface: Surface, roads: list[Road]) -> Feature:
    """Where the owner's road or path enters the hotspot (its first point inside), else at the centre."""
    centre = np.array(hotspot.centre)
    position = centre
    for road in roads:
        if hotspot.id not in road.stops:
            continue
        inside = [
            point for point in route_points(road, surface) if surface.distance_m(centre, point) <= hotspot.radius_m
        ]
        if inside:
            position = inside[0]
            break
    return Feature(
        id=f"{hotspot.id}:marker",
        kind="marker",
        hotspot=hotspot.id,
        position=_vector(position),
        cell=surface.nearest_cell(position),
        owner=hotspot.claim,
    )


def _vector(values: FloatArray) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))
