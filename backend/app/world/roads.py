"""Roads, paths, bridges and signposts (10-world-v1 §1.3, D80).

Routes run on the cell graph over walking cost, most important first; every cell a route takes costs
`reuse_discount` × for the routes after it, so later routes merge into trunks:

```
  west gate ──lead──▶ ◆ chart edge ─▶ cells ... Lord's woods ... ─▶ Band B camp      (road 1)
  west gate ──lead──▶ ◆ ──── shared trunk ────┬─▶ ... Standing stones                 (road 6)
                                              └ signpost: "Band B camp" / "Standing stones"
```

A road or path over a river is a bridge; a signpost stands at each junction of a road with another route. The sim
walks roads through `walk_costs_with_roads`: road cells cost max(0.8, base × 0.5), path cells max(0.9, base × 0.7),
bridges 0.8 instead of the 1.5 ford, so A* prefers them with no new movement code.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.world.biomes import UInt8Array, walk_costs
from app.world.paths import cheapest_path_to_any, closed_loop
from app.world.spec import CAMPS, ROADS_STOP, TRAIL_STOP, GateSpec, RouteSpec, WorldSpec
from app.world.sphere import FloatArray, bearing_deg, destination
from app.world.surface import Surface
from app.world.terrain import BoolArray
from app.world.view import Bridge, Feature, Hotspot, Road

NONE, PATH, ROAD = 0, 1, 2  # cell kinds, most important last
ROAD_COST = (0.8, 0.5)  # a road cell costs max(floor, base × factor)
PATH_COST = (0.9, 0.7)
BRIDGE_COST = 0.8
SIGNPOST_OFFSET_M = 4.0  # beside the road, not on it
TRIP_MIN_M = 400.0  # trips between places this far apart or less need no path of their own
_DESIRE_PASSES = 4


@dataclass(frozen=True)
class Network:
    roads: list[Road]
    bridges: list[Bridge]
    signposts: list[Feature]


def cell_kinds(roads: list[Road], cell_count: int) -> UInt8Array:
    """NONE, PATH or ROAD per cell (a road wins over a path)."""
    kinds = np.zeros(cell_count, dtype=np.uint8)
    for road in roads:
        kind = ROAD if road.kind == "road" else PATH
        kinds[road.cells] = np.maximum(kinds[road.cells], kind)
    return kinds


def walk_costs_with_roads(base: FloatArray, kinds: UInt8Array, river: BoolArray) -> FloatArray:
    """Walking cost per cell with roads, paths and bridges (D80) over the base cost of `walk_costs`."""
    road = np.maximum(ROAD_COST[0], base * ROAD_COST[1])
    path = np.maximum(PATH_COST[0], base * PATH_COST[1])
    costs = np.where(kinds == ROAD, road, np.where(kinds == PATH, path, base))
    return np.asarray(np.where((kinds != NONE) & river, BRIDGE_COST, costs), dtype=np.float64)


def route_network(
    spec: WorldSpec, surface: Surface, hotspots: list[Hotspot], trail_band: BoolArray, trail_stops: list[int]
) -> Network:
    """Every listed route in order (roads, the trail through the land loop's waypoints inside its band, paths),
    then the desire paths."""
    builder = _NetworkBuilder(spec, surface, hotspots)
    roads_spec = spec.roads
    for route in [route for route in roads_spec.routes if route.kind == "road"]:
        builder.add(route, builder.route_cells(route))
    trail = RouteSpec(id=roads_spec.trail.id, kind="path", name=roads_spec.trail.name, stops=[TRAIL_STOP, TRAIL_STOP])
    loop = closed_loop(surface.grid, builder.allowed & trail_band, builder.cost, trail_stops)
    builder.trail_cells = set(loop)
    builder.add(trail, [*loop, loop[0]])
    for route in [route for route in roads_spec.routes if route.kind == "path"]:
        builder.add(route, builder.route_cells(route))
    builder.add_desire_paths()
    return Network(
        roads=builder.roads, bridges=_bridges(builder.roads, builder.gates, surface), signposts=builder.signposts
    )


class _NetworkBuilder:
    def __init__(self, spec: WorldSpec, surface: Surface, hotspots: list[Hotspot]) -> None:
        self.spec = spec
        self.surface = surface
        self.hotspots = hotspots
        self.allowed = surface.walk & ~surface.in_town
        self.base = walk_costs(surface.biomes, surface.river)
        self.cost = self.base.copy()  # routing cost: cells earlier routes took are discounted
        self.kinds = np.zeros(surface.grid.cell_count, dtype=np.uint8)
        self.owner = np.full(surface.grid.cell_count, -1, dtype=np.int64)  # the first route on each cell
        self.names = _place_names(spec, hotspots)
        self.cells_of = {hotspot.id: hotspot.cell for hotspot in hotspots} | {s.id: s.cell for s in surface.sites}
        self.gates = {gate.id: gate for gate in spec.roads.gates}
        self.trail_cells: set[int] = set()
        self.ordered: list[RouteSpec] = []
        self.roads: list[Road] = []
        self.signposts: list[Feature] = []

    def route_cells(self, route: RouteSpec) -> list[int]:
        first = route.stops[0]
        if first in self.gates:
            lead_end = self.surface.chart.unit(*self.gates[first].lead[-1])
            # off the river: a lead that crossed it on its own bridge doesn't step back into it
            cells = [self.surface.nearest_cell(lead_end, self.allowed & ~self.surface.river)]
        else:
            cells = [self.cells_of[first]]
        for stop in route.stops[1:]:
            goals = _goals(stop, route, self.roads, self.cells_of, self.gates, self.trail_cells)
            cells += cheapest_path_to_any(self.surface.grid, self.allowed, self.cost, cells[-1], goals)[1:]
        return cells

    def add(self, route: RouteSpec, cells: list[int]) -> None:
        gate = self.gates.get(route.stops[0])
        lead = [self.surface.chart.unit(x, z) for x, z in gate.lead] if gate is not None else []
        road = Road(
            id=route.id,
            kind=route.kind,
            name=route.name,
            stops=[] if route.id == self.spec.roads.trail.id else list(route.stops),
            lead=[_vector(point) for point in lead],
            cells=cells,
        )
        self.ordered.append(route)
        index = len(self.ordered) - 1
        self.signposts += _signposts(
            road,
            self.ordered,
            index,
            self.owner,
            self.names,
            self.surface,
            self.signposts,
            self.spec.roads.signpost_spacing_m,
        )
        self.owner[[cell for cell in cells if self.owner[cell] < 0]] = index
        self.cost[cells] = self.base[cells] * self.spec.roads.reuse_discount
        self.kinds[cells] = np.maximum(self.kinds[cells], ROAD if route.kind == "road" else PATH)
        self.roads.append(road)

    def add_desire_paths(self) -> None:
        """A trip between two places over TRIP_MIN_M apart that keeps less than `trip_share` of its cells on the
        network becomes a path along that trip, shortest trips first (people tread paths where they walk)."""
        places = {hotspot.id: (np.array(hotspot.centre), hotspot.cell) for hotspot in self.hotspots}
        places |= {camp: (self.surface.site_unit(camp), self.surface.site(camp).cell) for camp in CAMPS}
        ids = sorted(places)
        trips = sorted(
            (self.surface.distance_m(places[a][0], places[b][0]), a, b) for i, a in enumerate(ids) for b in ids[i + 1 :]
        )
        called = {hotspot.id: hotspot.called for hotspot in self.hotspots}
        called |= {camp: self.surface.site(camp).name for camp in CAMPS}
        trips = [(gap, a, b) for gap, a, b in trips if gap > TRIP_MIN_M]
        for _ in range(_DESIRE_PASSES):  # a later path can turn an earlier trip off the network: go round again
            added = False
            for _gap, a, b in trips:
                path = self.trip(places[a][1], places[b][1])
                if trip_share(path, self.kinds) >= self.spec.roads.trip_share:
                    continue
                route_id = f"desire:{a}:{b}"
                taken = sum(1 for road in self.roads if road.id.startswith(route_id))
                name = f"the path from {called[a]} to {called[b]}"
                self.add(
                    RouteSpec(id=route_id + (f":{taken + 1}" if taken else ""), kind="path", name=name, stops=[a, b]),
                    path,
                )
                added = True
            if not added:
                return
        raise ValueError(f"trips still leave the roads after {_DESIRE_PASSES} rounds of desire paths")

    def trip(self, start: int, goal: int) -> list[int]:
        """The cheapest walk between two cells as the sim walks it (roads, paths and bridges at their D80 cost)."""
        costs = walk_costs_with_roads(self.base, self.kinds, self.surface.river)
        return cheapest_path_to_any(self.surface.grid, self.allowed, costs, start, {goal})


def trip_share(cells: list[int], kinds: UInt8Array) -> float:
    return float((kinds[cells] != NONE).mean())


def _goals(
    stop: str,
    route: RouteSpec,
    roads: list[Road],
    cells_of: dict[str, int],
    gates: dict[str, GateSpec],
    trail_cells: set[int],
) -> set[int]:
    if stop in gates:
        raise ValueError(f"route {route.id}: a gate can only be a route's first stop")
    if stop == ROADS_STOP:
        return {cell for road in roads if road.kind == "road" for cell in road.cells}
    if stop == TRAIL_STOP:
        return trail_cells
    return {cells_of[stop]}


def _place_names(spec: WorldSpec, hotspots: list[Hotspot]) -> dict[str, str]:
    """What a signpost calls each route's far end."""
    names = {hotspot.id: hotspot.name for hotspot in hotspots} | {site.id: site.name for site in spec.sites}
    return names | {spec.roads.trail.id: spec.roads.trail.name.capitalize()}


def _ends(route: RouteSpec, names: dict[str, str]) -> list[str]:
    """The names of the places a route links, its far end first."""
    if route.stops[0] == TRAIL_STOP:
        return [names[route.id]]
    return [names[stop] for stop in reversed(route.stops) if stop in names]


def _signposts(
    road: Road,
    ordered: list[RouteSpec],
    index: int,
    owner: NDArray[np.int64],
    names: dict[str, str],
    surface: Surface,
    placed: list[Feature],
    spacing_m: float,
) -> list[Feature]:
    """Signposts where this route joins or leaves an earlier one, when either of the two is a road."""
    cells = road.cells
    on = [bool(owner[cell] >= 0) for cell in cells]
    found: list[Feature] = []
    for i, cell in enumerate(cells):
        if not on[i]:
            continue
        leaves = i + 1 < len(cells) and not on[i + 1]
        joins = i > 0 and not on[i - 1]
        if not (leaves or joins):
            continue
        other = ordered[int(owner[cell])]
        if road.kind != "road" and other.kind != "road":
            continue
        here = surface.cell_unit(cell)
        if any(surface.distance_m(here, np.array(post.position)) < spacing_m for post in [*placed, *found]):
            continue
        ahead = surface.cell_unit(cells[min(i + 1, len(cells) - 1)])
        behind = surface.cell_unit(cells[max(i - 1, 0)])
        heading = float(bearing_deg(behind, ahead[None])[0])
        position = destination(here, heading + 90, SIGNPOST_OFFSET_M / surface.radius_m)
        owner_end = _ends(other, names)[0]
        pair = [owner_end, next((end for end in _ends(ordered[index], names) if end != owner_end), owner_end)]
        found.append(
            Feature(
                id=f"signpost-{len(placed) + len(found) + 1}",
                kind="signpost",
                position=_vector(position),
                cell=cell,
                names=list(dict.fromkeys(pair)),
            )
        )
    return found


def _bridges(roads: list[Road], gates: dict[str, GateSpec], surface: Surface) -> list[Bridge]:
    """A bridge at each river cell a road or path crosses (once per cell), and at each gate lead's authored one."""
    bridges: list[Bridge] = []
    bridged: set[int] = set()
    bridged_leads: set[tuple[str, float, float]] = set()
    for road in roads:
        count = 0
        gate = gates.get(road.stops[0]) if road.stops else None
        if gate is not None:
            for x, z in gate.bridges:
                if (gate.id, x, z) in bridged_leads:
                    continue
                bridged_leads.add((gate.id, x, z))
                count += 1
                position = surface.chart.unit(x, z)
                lead = [np.array(point) for point in road.lead]
                nearest = int(np.argmin([surface.distance_m(position, point) for point in lead]))
                heading = float(bearing_deg(lead[max(nearest - 1, 0)], lead[min(nearest + 1, len(lead) - 1)][None])[0])
                bridges.append(
                    Bridge(
                        id=f"{road.id}:bridge-{count}",
                        road=road.id,
                        cell=None,
                        position=_vector(position),
                        heading_deg=round(heading, 1),
                    )
                )
        for i, cell in enumerate(road.cells):
            if not surface.river[cell] or cell in bridged:
                continue
            bridged.add(cell)
            count += 1
            behind = surface.cell_unit(road.cells[max(i - 1, 0)])
            ahead = surface.cell_unit(road.cells[min(i + 1, len(road.cells) - 1)])
            bridges.append(
                Bridge(
                    id=f"{road.id}:bridge-{count}",
                    road=road.id,
                    cell=cell,
                    position=_vector(surface.cell_unit(cell)),
                    heading_deg=round(float(bearing_deg(behind, ahead[None])[0]), 1),
                )
            )
    return bridges


def _vector(values: FloatArray) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))
