import numpy as np
import pytest

from app.world.grid import build_grid
from app.world.paths import cheapest_path, closed_loop, erase_loops
from app.world.sphere import lat_lon, unit_from_lat_lon

GRID = build_grid(10)


def _cell(lat: float, lon: float) -> int:
    return int(np.argmax(GRID.positions @ unit_from_lat_lon(lat, lon)))


def test_erase_loops_cuts_detours() -> None:
    assert erase_loops([1, 2, 3, 4, 2, 5, 6, 5, 7]) == [1, 2, 5, 7]
    assert erase_loops([1, 2, 3]) == [1, 2, 3]


def test_cheapest_path_avoids_forbidden_cells_and_prefers_cheap_ones() -> None:
    lat, lon = lat_lon(GRID.positions)
    allowed = ~((np.abs(lon) < 8) & (lat > -40))  # a wall at lon 0 open only in the far south
    start, goal = _cell(0, -30), _cell(0, 30)

    path = cheapest_path(GRID, allowed, np.ones(GRID.cell_count), start, goal)

    assert path[0] == start and path[-1] == goal
    assert all(allowed[cell] for cell in path)
    assert all(b in GRID.neighbours[a] for a, b in zip(path, path[1:], strict=False))
    assert lat[path].min() <= -40


def test_cheapest_path_fails_when_cut_off() -> None:
    allowed = np.abs(GRID.positions[:, 0]) > 0.1  # a great-circle wall through both poles

    with pytest.raises(ValueError, match="no walkable path"):
        cheapest_path(GRID, allowed, np.ones(GRID.cell_count), _cell(0, -30), _cell(0, 30))


def test_closed_loop_is_a_simple_cycle_through_every_stop() -> None:
    stops = [_cell(10, lon) for lon in (0, 90, 180, -90)]
    allowed = np.ones(GRID.cell_count, dtype=bool)

    loop = closed_loop(GRID, allowed, np.ones(GRID.cell_count), stops)

    assert len(set(loop)) == len(loop)
    assert set(stops) <= set(loop)
    for a, b in zip(loop, loop[1:] + loop[:1], strict=True):
        assert b in GRID.neighbours[a]
