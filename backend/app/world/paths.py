"""Walking over the cell graph: cheapest paths, the land loop and reachability."""

import heapq
from collections import deque

import numpy as np

from app.world.grid import Grid
from app.world.sphere import FloatArray
from app.world.terrain import BoolArray


def cheapest_path(grid: Grid, allowed: BoolArray, cost: FloatArray, start: int, goal: int) -> list[int]:
    """Dijkstra over allowed cells; entering a cell costs `cost[cell]`. Raises when the goal can't be reached."""
    if not (allowed[start] and allowed[goal]):
        raise ValueError(f"path ends must be allowed cells: {start} -> {goal}")
    best = {start: 0.0}
    came_from: dict[int, int] = {}
    heap = [(0.0, start)]
    neighbours = grid.neighbours
    while heap:
        spent, cell = heapq.heappop(heap)
        if cell == goal:
            break
        if spent > best[cell]:
            continue
        for other in neighbours[cell].tolist():
            if other < 0 or not allowed[other]:
                continue
            total = spent + float(cost[other])
            if total < best.get(other, np.inf):
                best[other] = total
                came_from[other] = cell
                heapq.heappush(heap, (total, other))
    if goal not in best:
        raise ValueError(f"no walkable path from cell {start} to cell {goal}")
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    return path[::-1]


def erase_loops(cells: list[int]) -> list[int]:
    """Drop every detour that returns to a cell already on the walk, so each cell appears once."""
    walk: list[int] = []
    index: dict[int, int] = {}
    for cell in cells:
        if cell in index:
            for dropped in walk[index[cell] + 1 :]:
                del index[dropped]
            del walk[index[cell] + 1 :]
            continue
        index[cell] = len(walk)
        walk.append(cell)
    return walk


def closed_loop(grid: Grid, allowed: BoolArray, cost: FloatArray, stops: list[int]) -> list[int]:
    """A simple cycle through the stops in order (the last stop links back to the first)."""
    walk: list[int] = []
    for start, goal in zip(stops, stops[1:] + stops[:1], strict=True):
        walk.extend(cheapest_path(grid, allowed, cost, start, goal)[:-1])
    # start halfway along the first leg: a shortest leg has no detour there for the erasure to cut across the seam
    middle = len(cheapest_path(grid, allowed, cost, stops[0], stops[1])) // 2
    loop = erase_loops(walk[middle:] + walk[:middle])
    if loop[0] not in grid.neighbours[loop[-1]] or len(loop) < 3:
        raise ValueError("the land loop does not close")
    return loop


def reachable(grid: Grid, allowed: BoolArray, start: int) -> BoolArray:
    seen = np.zeros(grid.cell_count, dtype=bool)
    if not allowed[start]:
        return seen
    seen[start] = True
    queue = deque([start])
    neighbours = grid.neighbour_lists()
    while queue:
        for other in neighbours[queue.popleft()]:
            if allowed[other] and not seen[other]:
                seen[other] = True
                queue.append(other)
    return seen
