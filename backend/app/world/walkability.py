"""Grid walkability over flat ground: which cells a walker can stand on and reach.

A cell is blocked when a solid blocker overlaps it, or when its centre is in water that no walkable surface covers.
Movement is 4-connected, so a wall one cell thick is enough to stop a walker.
"""

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.world.geometry import Rect, point_in_polygon, polygon_bounds
from app.world.town import Extent, KindSpec, TownView, TownWater, placement_blockers

CELL_SIZE = 0.5
# Keeps rectangles that only touch a cell edge from claiming that cell.
_EDGE_EPS = 1e-9


@dataclass(frozen=True)
class Obstacles:
    solids: tuple[Rect, ...]
    surfaces: tuple[Rect, ...]
    water: tuple[TownWater, ...]


def town_obstacles(view: TownView, kinds: Mapping[str, KindSpec]) -> Obstacles:
    solids: list[Rect] = []
    surfaces: list[Rect] = []
    for placement in view.placements:
        if placement.walk == "solid":
            solids.extend(placement_blockers(placement, kinds[placement.kind]))
        elif placement.walk == "surface":
            surfaces.append(placement.rect())
    return Obstacles(solids=tuple(solids), surfaces=tuple(surfaces), water=tuple(view.water))


class WalkGrid:
    """Square cells of `cell_size` metres over the extent; nothing outside the extent is walkable."""

    def __init__(self, extent: Extent, cell_size: float = CELL_SIZE) -> None:
        self.extent = extent
        self.cell_size = cell_size
        self.columns = round((extent.max_x - extent.min_x) / cell_size)
        self.rows = round((extent.max_z - extent.min_z) / cell_size)
        self.blocked = bytearray(self.columns * self.rows)

    def cell_of(self, x: float, z: float) -> int | None:
        """Index of the cell containing the point, or None outside the extent."""
        column = math.floor((x - self.extent.min_x) / self.cell_size)
        row = math.floor((z - self.extent.min_z) / self.cell_size)
        if not (0 <= column < self.columns and 0 <= row < self.rows):
            return None
        return row * self.columns + column

    def is_walkable(self, x: float, z: float) -> bool:
        cell = self.cell_of(x, z)
        return cell is not None and not self.blocked[cell]

    def block_overlapping(self, rect: Rect) -> None:
        """Block every cell the rectangle overlaps by more than an edge."""
        for row in self._overlapping(rect.z0, rect.z1, self.extent.min_z, self.rows):
            for column in self._overlapping(rect.x0, rect.x1, self.extent.min_x, self.columns):
                self.blocked[row * self.columns + column] = 1

    def centres_inside(self, rect: Rect) -> Iterable[tuple[int, float, float]]:
        """(cell, centre x, centre z) for every cell whose centre lies in the rectangle (edges included)."""
        for row in self._centred(rect.z0, rect.z1, self.extent.min_z, self.rows):
            z = self.extent.min_z + (row + 0.5) * self.cell_size
            for column in self._centred(rect.x0, rect.x1, self.extent.min_x, self.columns):
                yield row * self.columns + column, self.extent.min_x + (column + 0.5) * self.cell_size, z

    def reachable_from(self, x: float, z: float) -> "Reach":
        """Every cell a walker starting at the point can get to (4-connected flood fill)."""
        start = self.cell_of(x, z)
        if start is None or self.blocked[start]:
            raise ValueError(f"start ({x}, {z}) is not walkable")
        visited = bytearray(len(self.blocked))
        visited[start] = 1
        frontier = deque([start])
        columns, blocked = self.columns, self.blocked
        while frontier:
            cell = frontier.popleft()
            column = cell % columns
            neighbours = [cell - columns, cell + columns]
            if column > 0:
                neighbours.append(cell - 1)
            if column < columns - 1:
                neighbours.append(cell + 1)
            for neighbour in neighbours:
                if 0 <= neighbour < len(blocked) and not blocked[neighbour] and not visited[neighbour]:
                    visited[neighbour] = 1
                    frontier.append(neighbour)
        return Reach(self, visited)

    def _overlapping(self, lo: float, hi: float, origin: float, count: int) -> range:
        first = math.floor((lo - origin) / self.cell_size + _EDGE_EPS)
        last = math.ceil((hi - origin) / self.cell_size - _EDGE_EPS)
        return range(max(first, 0), min(last, count))

    def _centred(self, lo: float, hi: float, origin: float, count: int) -> range:
        first = math.ceil((lo - origin) / self.cell_size - 0.5)
        last = math.floor((hi - origin) / self.cell_size - 0.5)
        return range(max(first, 0), min(last + 1, count))


@dataclass(frozen=True)
class Reach:
    grid: WalkGrid
    visited: bytearray

    def contains(self, x: float, z: float) -> bool:
        cell = self.grid.cell_of(x, z)
        return cell is not None and bool(self.visited[cell])


def build_walk_grid(extent: Extent, obstacles: Obstacles, cell_size: float = CELL_SIZE) -> WalkGrid:
    grid = WalkGrid(extent, cell_size)
    covered = bytearray(len(grid.blocked))
    for surface in obstacles.surfaces:
        for cell, _, _ in grid.centres_inside(surface):
            covered[cell] = 1
    for water in obstacles.water:
        for cell, x, z in grid.centres_inside(polygon_bounds(water.polygon)):
            if covered[cell] or not point_in_polygon(x, z, water.polygon):
                continue
            if not any(point_in_polygon(x, z, hole) for hole in water.holes):
                grid.blocked[cell] = 1
    for solid in obstacles.solids:
        grid.block_overlapping(solid)
    return grid


def town_walk_grid(view: TownView, kinds: Mapping[str, KindSpec]) -> WalkGrid:
    return build_walk_grid(view.extent, town_obstacles(view, kinds))
