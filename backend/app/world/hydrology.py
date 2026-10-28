"""Water: authored river channels, depression filling (priority flood), lakes, flow accumulation and rivers."""

import heapq
from collections import deque
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.world.grid import Grid
from app.world.spec import HydrologySpec
from app.world.sphere import FloatArray, unit_from_lat_lon
from app.world.terrain import BoolArray

IntArray = NDArray[np.int64]

_SAMPLE_STEP_RAD = 2e-3  # ~4 m on a 2 km planet: fine enough that consecutive nearest cells are neighbours
_CHANNEL_MIN_M = 0.3
_MAX_LAKE_PASSES = 8


@dataclass(frozen=True)
class RiverPath:
    id: str
    name: str | None
    cells: list[int]


def trace_cells(grid: Grid, points: list[tuple[float, float]]) -> list[int]:
    """Neighbouring cells along the great-circle arcs through lat/lon points."""
    cells: list[int] = []
    for start, end in zip(points, points[1:], strict=False):
        a, b = unit_from_lat_lon(*start), unit_from_lat_lon(*end)
        span = float(np.arccos(np.clip(a @ b, -1, 1)))
        steps = max(2, int(np.ceil(span / _SAMPLE_STEP_RAD)) + 1)
        t = np.linspace(0, 1, steps)[:, None]
        omega = span
        samples = (np.sin((1 - t) * omega) * a + np.sin(t * omega) * b) / np.sin(omega)
        nearest = np.argmax(samples @ grid.positions.T, axis=1)
        for cell in nearest.tolist():
            if cells and cells[-1] == cell:
                continue
            if cells and cell not in grid.neighbours[cells[-1]]:
                cells.append(_bridge(grid, cells[-1], cell))
            cells.append(cell)
    return cells


def _bridge(grid: Grid, a: int, b: int) -> int:
    shared = sorted(set(grid.neighbours[a].tolist()) & set(grid.neighbours[b].tolist()) - {-1})
    if not shared:
        raise ValueError(f"cells {a} and {b} are not two steps apart; sample the river path more finely")
    return int(shared[0])


def carve_channel(
    heights: FloatArray, cells: list[int], pinned: BoolArray, bowl_levels: FloatArray, depth_m: float, river_id: str
) -> list[int]:
    """Cut a non-increasing channel along `cells`; pinned cells (site plateaus) keep their height.

    Water here is the ocean or an authored lake bowl (`bowl_levels` holds its intended surface, inf elsewhere).
    A river that starts in water leaves from the last water cell it crosses, its channel no higher than the bowl's
    surface (so the lake spills into it); it ends at the first water cell it then reaches (or at the path's end).
    Water cells aren't carved. Returns the river's cells.
    """

    def wet(cell: int) -> bool:
        return bool(heights[cell] < 0 or np.isfinite(bowl_levels[cell]))

    start = 0
    while start + 1 < len(cells) and wet(cells[start]) and wet(cells[start + 1]):
        start += 1
    end = next((i for i in range(start + 1, len(cells)) if wet(cells[i])), len(cells) - 1)
    path = cells[start : end + 1]
    channel = path[int(wet(path[0])) : len(path) - int(wet(path[-1]) and len(path) > 1)]
    if not channel:
        return path
    profile = np.array([heights[c] if pinned[c] else heights[c] - depth_m for c in channel])
    if wet(path[0]) and not pinned[channel[0]]:
        profile[0] = min(profile[0], bowl_levels[path[0]])
    is_pinned = np.array([pinned[c] for c in channel])
    for i in range(1, len(channel)):
        if not is_pinned[i]:
            profile[i] = min(profile[i], profile[i - 1])
    for i in range(len(channel) - 2, -1, -1):
        if is_pinned[i] and profile[i] < profile[i + 1] - 1e-9:
            raise ValueError(f"river {river_id}: a pinned cell lies below a later one; reorder the river points")
        profile[i] = max(profile[i], profile[i + 1])
    profile = np.maximum(profile, _CHANNEL_MIN_M)
    for cell, value in zip(channel, profile, strict=True):
        if not pinned[cell]:
            heights[cell] = value
    return path


@dataclass(frozen=True)
class Drainage:
    heights: FloatArray  # filled heights: every land cell drains to the ocean through `parent`
    parent: IntArray  # downstream cell, -1 for ocean
    order: IntArray  # cells in flooding order (downstream before upstream)


def priority_flood(grid: Grid, heights: FloatArray, sinks: BoolArray) -> Drainage:
    """Flood inward from the sinks (ocean, closed lakes), lifting every depression to its spill level.

    Filled depressions become exactly level; `parent` still says which way their water drains.
    """
    filled = heights.copy()
    parent = np.full(grid.cell_count, -1, dtype=np.int64)
    visited = sinks.copy()
    heap = [(float(heights[c]), int(c)) for c in np.flatnonzero(visited)]
    heapq.heapify(heap)
    order: list[int] = []
    neighbours = grid.neighbour_lists()
    while heap:
        level, cell = heapq.heappop(heap)
        order.append(cell)
        for other in neighbours[cell]:
            if visited[other]:
                continue
            visited[other] = True
            parent[other] = cell
            filled[other] = max(heights[other], level)
            heapq.heappush(heap, (float(filled[other]), other))
    if not visited.all():
        raise ValueError("some land has no sink to drain into")
    return Drainage(heights=filled, parent=parent, order=np.array(order, dtype=np.int64))


def components(grid: Grid, mask: BoolArray) -> list[list[int]]:
    """Connected groups of cells in `mask`, each sorted, in order of their smallest cell."""
    seen = np.zeros(grid.cell_count, dtype=bool)
    neighbours = grid.neighbour_lists()
    groups: list[list[int]] = []
    for start in np.flatnonzero(mask).tolist():
        if seen[start]:
            continue
        seen[start] = True
        queue, group = deque([start]), [start]
        while queue:
            for other in neighbours[queue.popleft()]:
                if mask[other] and not seen[other]:
                    seen[other] = True
                    queue.append(other)
                    group.append(other)
        groups.append(sorted(group))
    return groups


@dataclass(frozen=True)
class Water:
    heights: FloatArray
    lake: BoolArray
    rivers: list[RiverPath]
    accumulation: IntArray


def settle_water(
    grid: Grid,
    shaped: FloatArray,
    spec: HydrologySpec,
    authored: list[RiverPath],
    basins: BoolArray,
    flats: BoolArray,
    lake_free: BoolArray,
) -> Water:
    """Turn depressions into lakes or drained flats, then trace rivers down the drainage tree.

    A depression at least `lake_min_depth_m` deep holds a lake. If the lake fits within `lake_max_depth_m` it fills
    to the spill level and drains on through its outlet (open); otherwise its surface stops `lake_max_depth_m`
    above the bottom and it becomes a sink with dry slopes around it (closed). Shallower depressions are filled
    into flats that drain. `basins` keep their shaped height (the crater); `flats` (site plateaus) never hold a lake
    or a spring; `lake_free` cells (the land-loop core) never hold a lake.
    """
    heights = shaped.copy()
    lake = np.zeros(grid.cell_count, dtype=bool)
    closed = np.zeros(grid.cell_count, dtype=bool)
    ocean = shaped < 0
    for _ in range(_MAX_LAKE_PASSES):
        filled = priority_flood(grid, heights, ocean | closed).heights
        raised = (filled > heights + 1e-6) & ~basins & ~flats & ~lake_free & ~lake
        formed = False
        for group in components(grid, raised):
            cells = np.array(group)
            spill, bottom = float(filled[cells].min()), float(heights[cells].min())
            if spill - bottom < spec.lake_min_depth_m:
                continue
            surface = min(spill, bottom + spec.lake_max_depth_m)
            pocket = cells[heights[cells] < surface]
            if len(pocket) < spec.lake_min_cells:
                continue
            lake[pocket] = True
            closed[pocket] = surface < spill
            heights[pocket] = surface
            formed = True
        if not formed:
            break

    drainage = priority_flood(grid, heights, ocean | closed)
    surfaces = heights[lake]
    heights = drainage.heights
    heights[lake] = surfaces
    heights[basins] = shaped[basins]

    accumulation = _accumulate(drainage, grid.cell_count)
    rivers = _trace_rivers(grid, heights, drainage, accumulation, lake, basins | flats, spec, authored)
    return Water(heights=heights, lake=lake, rivers=rivers, accumulation=accumulation)


def _accumulate(drainage: Drainage, count: int) -> IntArray:
    accumulation = np.ones(count, dtype=np.int64)
    for cell in drainage.order[::-1].tolist():
        downstream = drainage.parent[cell]
        if downstream >= 0:
            accumulation[downstream] += accumulation[cell]
    return accumulation


def _trace_rivers(
    grid: Grid,
    heights: FloatArray,
    drainage: Drainage,
    accumulation: IntArray,
    lake: BoolArray,
    no_springs: BoolArray,
    spec: HydrologySpec,
    authored: list[RiverPath],
) -> list[RiverPath]:
    water = (heights < 0) | lake
    river = (accumulation >= spec.river_min_cells) & ~water & ~no_springs
    parent = drainage.parent
    fed = np.zeros(grid.cell_count, dtype=bool)
    fed[parent[river & (parent >= 0)]] = True
    depth = np.zeros(grid.cell_count, dtype=np.int64)
    for cell in drainage.order.tolist():
        if parent[cell] >= 0:
            depth[cell] = depth[parent[cell]] + 1
    springs = sorted(np.flatnonzero(river & ~fed).tolist(), key=lambda c: (-depth[c], c))

    claimed = np.zeros(grid.cell_count, dtype=bool)
    for path in authored:
        claimed[path.cells] = True
    rivers = list(authored)
    for spring in springs:
        cells = _from_lake(grid, spring, parent, lake, accumulation)
        cell = spring
        while True:
            cells.append(cell)
            if water[cell] or claimed[cell] or parent[cell] < 0:
                break
            claimed[cell] = True
            cell = int(parent[cell])
        if len(cells) >= spec.river_min_length:
            rivers.append(RiverPath(id=f"river-{len(rivers) - len(authored) + 1}", name=None, cells=cells))
        else:
            claimed[cells[:-1]] = False
    return rivers


def _from_lake(grid: Grid, spring: int, parent: IntArray, lake: BoolArray, accumulation: IntArray) -> list[int]:
    """A lake outflow starts in the lake: the biggest lake cell draining into the spring."""
    feeders = [n for n in grid.neighbours[spring].tolist() if n >= 0 and lake[n] and parent[n] == spring]
    return [max(feeders, key=lambda n: (accumulation[n], -n))] if feeders else []
