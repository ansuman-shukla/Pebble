"""Finding a way: A* on the town's 0.5 m walk grid inside the town chart, A* on the cell graph outside, and a
combined planner that hands over between them at portals on the town chart's edge.

```
  town walk grid (local metres)        portal         cell graph (sphere)
  start ─▶ streets ─▶ gate ─▶ ... ─▶ ◆ edge cell ─▶ nearest outer cell ─▶ ... ─▶ goal
```

Inside the chart walkers move 8-connected without cutting corners, so a straight leg between two grid cells never
touches a blocked cell; the gnomonic mapping sends local straight lines to great circles, so walking the great
circle between two mapped points walks the straight local line. Outside, edges cost metres × the mean terrain cost
of their ends; water cells and the cells inside the town chart are not in the graph.
"""

import heapq
import math
from collections.abc import Mapping
from dataclasses import dataclass

from app.sim.vec import Vec3, angle, as_vec, slerp
from app.sim.world import SimWorld
from app.world.walkability import WalkGrid

_SQRT2 = math.sqrt(2.0)
_PORTAL_SPACING_CELLS = 20  # one portal every 10 m of walkable chart edge
_PORTAL_REACH_M = 90.0  # an outer cell this close to a portal links to it
_SNAP_CELLS = 8  # a start or goal in a blocked town cell snaps to a walkable cell this close


@dataclass(frozen=True)
class Route:
    points: tuple[Vec3, ...]  # unit vectors; the first is where the walk starts
    costs: tuple[float, ...]  # walking cost per metre of each leg (len(points) - 1)

    def __post_init__(self) -> None:
        if len(self.points) < 1 or len(self.costs) != len(self.points) - 1:
            raise ValueError("a route needs one cost per leg")


@dataclass(frozen=True)
class WalkProgress:
    leg: int
    along_m: float
    position: Vec3
    arrived: bool
    cost_spent: float


def walk_along(route: Route, leg: int, along_m: float, budget: float, radius_m: float) -> WalkProgress:
    """Advance along the route by a cost budget (metres × terrain cost)."""
    points, costs = route.points, route.costs
    spent = 0.0
    while leg < len(costs):
        length = angle(points[leg], points[leg + 1]) * radius_m
        need = (length - along_m) * costs[leg]
        if need <= budget - spent:
            spent += need
            leg, along_m = leg + 1, 0.0
            continue
        along_m += (budget - spent) / costs[leg]
        position = slerp(points[leg], points[leg + 1], along_m / length) if length > 0 else points[leg + 1]
        return WalkProgress(leg=leg, along_m=along_m, position=position, arrived=False, cost_spent=budget)
    return WalkProgress(leg=leg, along_m=0.0, position=points[-1], arrived=True, cost_spent=spent)


class TownPlanner:
    """A* over the town walk grid (8-connected, no corner cutting)."""

    def __init__(self, walk: WalkGrid) -> None:
        self.walk = walk
        self.columns = walk.columns
        self.rows = walk.rows
        self.size = walk.cell_size

    def centre(self, cell: int) -> tuple[float, float]:
        e = self.walk.extent
        return (e.min_x + (cell % self.columns + 0.5) * self.size, e.min_z + (cell // self.columns + 0.5) * self.size)

    def snap(self, x: float, z: float) -> int | None:
        """The walkable cell under the point, else the nearest walkable cell within a few cells, else None."""
        e = self.walk.extent
        column = math.floor((x - e.min_x) / self.size)
        row = math.floor((z - e.min_z) / self.size)
        best: tuple[float, int] | None = None
        for ring in range(_SNAP_CELLS + 1):
            for dr in range(-ring, ring + 1):
                for dc in range(-ring, ring + 1):
                    if max(abs(dr), abs(dc)) != ring:
                        continue
                    r, c = row + dr, column + dc
                    if not (0 <= r < self.rows and 0 <= c < self.columns):
                        continue
                    cell = r * self.columns + c
                    if self.walk.blocked[cell]:
                        continue
                    cx, cz = self.centre(cell)
                    distance = math.hypot(cx - x, cz - z)
                    if best is None or (distance, cell) < best:
                        best = (distance, cell)
            if best is not None:
                return best[1]
        return None

    def search(self, starts: Mapping[int, float], goal: int) -> list[int] | None:
        """Cheapest cell path from any start (with its starting cost) to the goal, in metres; None if unreachable."""
        columns, rows, blocked, size = self.columns, self.rows, self.walk.blocked, self.size
        goal_column, goal_row = goal % columns, goal // columns
        diagonal = size * _SQRT2

        def heuristic(cell: int) -> float:
            dx = abs(cell % columns - goal_column)
            dz = abs(cell // columns - goal_row)
            return size * (max(dx, dz) + (_SQRT2 - 1) * min(dx, dz))

        best: dict[int, float] = {}
        came_from: dict[int, int] = {}
        heap: list[tuple[float, float, int]] = []
        for cell, cost in sorted(starts.items()):
            if blocked[cell] or cost >= best.get(cell, math.inf):
                continue
            best[cell] = cost
            came_from.pop(cell, None)
            heapq.heappush(heap, (cost + heuristic(cell), cost, cell))
        if blocked[goal]:
            return None
        while heap:
            _, spent, cell = heapq.heappop(heap)
            if cell == goal:
                path = [goal]
                while path[-1] in came_from:
                    path.append(came_from[path[-1]])
                return path[::-1]
            if spent > best[cell]:
                continue
            column, row = cell % columns, cell // columns
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                c, r = column + dc, row + dr
                if not (0 <= c < columns and 0 <= r < rows):
                    continue
                other = r * columns + c
                if blocked[other]:
                    continue
                if dc and dr:
                    if blocked[row * columns + c] or blocked[r * columns + column]:
                        continue
                    total = spent + diagonal
                else:
                    total = spent + size
                if total < best.get(other, math.inf):
                    best[other] = total
                    came_from[other] = cell
                    heapq.heappush(heap, (total + heuristic(other), total, other))
        return None

    def corners(self, path: list[int]) -> list[int]:
        """The path's cells where its direction changes (plus both ends)."""
        if len(path) <= 2:
            return list(path)
        kept = [path[0]]
        columns = self.columns
        for previous, cell, following in zip(path, path[1:], path[2:], strict=False):
            step_in = (cell % columns - previous % columns, cell // columns - previous // columns)
            step_out = (following % columns - cell % columns, following // columns - cell // columns)
            if step_in != step_out:
                kept.append(cell)
        kept.append(path[-1])
        return kept


class OuterGraph:
    """The walkable cells outside the town chart; edge cost = metres × mean terrain cost of both ends."""

    def __init__(self, world: SimWorld) -> None:
        self.radius_m = world.radius_m
        self.units: list[Vec3] = [as_vec(row) for row in world.grid.positions]
        cost = world.terrain_cost
        self.cost: list[float] = [float(value) for value in cost]
        self.allowed: list[bool] = [
            math.isfinite(self.cost[cell]) and not bool(world.in_town[cell]) for cell in range(world.cell_count)
        ]
        self.edges: list[list[tuple[int, float]]] = []
        for cell, others in enumerate(world.neighbours):
            row: list[tuple[int, float]] = []
            if self.allowed[cell]:
                for other in others:
                    if self.allowed[other]:
                        length = angle(self.units[cell], self.units[other]) * self.radius_m
                        row.append((other, length * (self.cost[cell] + self.cost[other]) / 2))
            self.edges.append(row)

    def _chord_m(self, a: int, b: int) -> float:
        ua, ub = self.units[a], self.units[b]
        dx, dy, dz = ua[0] - ub[0], ua[1] - ub[1], ua[2] - ub[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz) * self.radius_m

    def astar(self, start: int, goal: int) -> list[int] | None:
        if not (self.allowed[start] and self.allowed[goal]):
            return None
        best = {start: 0.0}
        came_from: dict[int, int] = {}
        heap = [(self._chord_m(start, goal), 0.0, start)]
        while heap:
            _, spent, cell = heapq.heappop(heap)
            if cell == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(came_from[path[-1]])
                return path[::-1]
            if spent > best[cell]:
                continue
            for other, edge in self.edges[cell]:
                total = spent + edge
                if total < best.get(other, math.inf):
                    best[other] = total
                    came_from[other] = cell
                    heapq.heappush(heap, (total + self._chord_m(other, goal), total, other))
        return None

    def costs_to(self, source: int, targets: set[int]) -> dict[int, float]:
        """Cheapest cost from the source to each reachable target (Dijkstra, stops once all targets are settled)."""
        found: dict[int, float] = {}
        if not self.allowed[source]:
            return found
        best = {source: 0.0}
        heap = [(0.0, source)]
        remaining = set(targets)
        while heap and remaining:
            spent, cell = heapq.heappop(heap)
            if spent > best[cell]:
                continue
            if cell in remaining:
                remaining.discard(cell)
                found[cell] = spent
            for other, edge in self.edges[cell]:
                total = spent + edge
                if total < best.get(other, math.inf):
                    best[other] = total
                    heapq.heappush(heap, (total, other))
        return found


@dataclass(frozen=True)
class Portal:
    town_cell: int
    unit: Vec3
    outer_cell: int
    link_cost: float  # cost of the leg between the portal and its outer cell


class Planner:
    def __init__(self, world: SimWorld) -> None:
        self.world = world
        self.town = TownPlanner(world.town.walk)
        self.outer = OuterGraph(world)
        self.portals = self._portals()
        self.portal_by_cell = {portal.town_cell: portal for portal in self.portals}

    def _portals(self) -> list[Portal]:
        walk, town = self.world.town.walk, self.town
        ring: list[int] = []
        ring += list(range(walk.columns))
        ring += [r * walk.columns + walk.columns - 1 for r in range(1, walk.rows)]
        ring += [(walk.rows - 1) * walk.columns + c for c in range(walk.columns - 2, -1, -1)]
        ring += [r * walk.columns for r in range(walk.rows - 2, 0, -1)]
        portals: list[Portal] = []
        candidates = [cell for cell in range(self.world.cell_count) if self.outer.allowed[cell]]
        near_town = [
            cell for cell in candidates if self.world.distance_m(self.outer.units[cell], self._town_up()) < 400
        ]
        for index, cell in enumerate(ring):
            if index % _PORTAL_SPACING_CELLS or walk.blocked[cell]:
                continue
            unit = self.world.town.to_unit(*town.centre(cell))
            distance, outer_cell = min((self.world.distance_m(unit, self.outer.units[c]), c) for c in near_town)
            if distance <= _PORTAL_REACH_M:
                portals.append(Portal(cell, unit, outer_cell, distance * self.outer.cost[outer_cell]))
        if not portals:
            raise ValueError("the town chart has no way out")
        return portals

    def _town_up(self) -> Vec3:
        return as_vec(self.world.town.frame.up)

    def outer_cell_for(self, unit: Vec3, hint: int | None = None) -> int | None:
        """The graph cell a point outside the town belongs to (the nearest allowed one around it)."""
        cell = self.world.nearest_cell(unit, hint)
        if self.outer.allowed[cell]:
            return cell
        options = [(self.world.distance_m(unit, self.outer.units[o]), o) for o in self.world.neighbours[cell]]
        allowed = [option for option in options if self.outer.allowed[option[1]]]
        return min(allowed)[1] if allowed else None

    def plan(self, start: Vec3, goal: Vec3, start_hint: int | None = None) -> Route | None:
        """A route from start to goal, or None when there is no way."""
        world = self.world
        start_local, goal_local = world.town_point(start), world.town_point(goal)
        if start_local is not None and goal_local is not None:
            return self._town_to_town(start, goal, start_local, goal_local)
        if start_local is not None:
            goal_cell = self.outer_cell_for(goal)
            return None if goal_cell is None else self._town_to_outer(start, goal, start_local, goal_cell)
        start_cell = self.outer_cell_for(start, start_hint)
        if start_cell is None:
            return None
        if goal_local is not None:
            return self._outer_to_town(start, goal, start_cell, goal_local)
        goal_cell = self.outer_cell_for(goal)
        if goal_cell is None:
            return None
        cells = self.outer.astar(start_cell, goal_cell)
        if cells is None:
            return None
        builder = _RouteBuilder(start)
        builder.outer(self, cells, entry_cost=self.outer.cost[start_cell])
        builder.add(goal, self.outer.cost[goal_cell])
        return builder.route()

    def _town_to_town(
        self, start: Vec3, goal: Vec3, start_local: tuple[float, float], goal_local: tuple[float, float]
    ) -> Route | None:
        start_cell, goal_cell = self.town.snap(*start_local), self.town.snap(*goal_local)
        if start_cell is None or goal_cell is None:
            return None
        cells = self.town.search({start_cell: 0.0}, goal_cell)
        if cells is None:
            return None
        builder = _RouteBuilder(start)
        builder.town(self, cells)
        builder.add(goal if goal_cell == self._cell_under(goal_local) else builder.last, 1.0)
        return builder.route()

    def _cell_under(self, local: tuple[float, float]) -> int | None:
        cell = self.world.town.walk.cell_of(*local)
        return None if cell is None or self.world.town.walk.blocked[cell] else cell

    def _town_to_outer(self, start: Vec3, goal: Vec3, start_local: tuple[float, float], goal_cell: int) -> Route | None:
        start_cell = self.town.snap(*start_local)
        if start_cell is None:
            return None
        costs = self.outer.costs_to(goal_cell, {portal.outer_cell for portal in self.portals})
        starts = {p.town_cell: costs[p.outer_cell] + p.link_cost for p in self.portals if p.outer_cell in costs}
        if not starts:
            return None
        town_cells = self.town.search(starts, start_cell)
        if town_cells is None:
            return None
        town_cells.reverse()
        portal = self.portal_by_cell[town_cells[-1]]
        outer_cells = self.outer.astar(portal.outer_cell, goal_cell)
        if outer_cells is None:
            return None
        builder = _RouteBuilder(start)
        builder.town(self, town_cells)
        builder.outer(self, outer_cells, entry_cost=self.outer.cost[portal.outer_cell])
        builder.add(goal, self.outer.cost[goal_cell])
        return builder.route()

    def _outer_to_town(self, start: Vec3, goal: Vec3, start_cell: int, goal_local: tuple[float, float]) -> Route | None:
        goal_cell = self.town.snap(*goal_local)
        if goal_cell is None:
            return None
        costs = self.outer.costs_to(start_cell, {portal.outer_cell for portal in self.portals})
        starts = {p.town_cell: costs[p.outer_cell] + p.link_cost for p in self.portals if p.outer_cell in costs}
        if not starts:
            return None
        town_cells = self.town.search(starts, goal_cell)
        if town_cells is None:
            return None
        portal = self.portal_by_cell[town_cells[0]]
        outer_cells = self.outer.astar(start_cell, portal.outer_cell)
        if outer_cells is None:
            return None
        builder = _RouteBuilder(start)
        builder.outer(self, outer_cells, entry_cost=self.outer.cost[start_cell])
        builder.add(portal.unit, self.outer.cost[portal.outer_cell])
        builder.town(self, town_cells)
        builder.add(goal if goal_cell == self._cell_under(goal_local) else builder.last, 1.0)
        return builder.route()


class _RouteBuilder:
    def __init__(self, start: Vec3) -> None:
        self.points: list[Vec3] = [start]
        self.costs: list[float] = []

    @property
    def last(self) -> Vec3:
        return self.points[-1]

    def add(self, point: Vec3, cost: float) -> None:
        if point == self.points[-1]:
            return
        self.points.append(point)
        self.costs.append(cost)

    def town(self, planner: Planner, cells: list[int]) -> None:
        chart = planner.world.town
        for cell in planner.town.corners(cells):
            self.add(chart.to_unit(*planner.town.centre(cell)), 1.0)

    def outer(self, planner: Planner, cells: list[int], entry_cost: float) -> None:
        graph = planner.outer
        self.add(graph.units[cells[0]], entry_cost)
        for previous, cell in zip(cells, cells[1:], strict=False):
            self.add(graph.units[cell], (graph.cost[previous] + graph.cost[cell]) / 2)

    def route(self) -> Route:
        return Route(points=tuple(self.points), costs=tuple(self.costs))
