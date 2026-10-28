import numpy as np
import pytest

from app.world.grid import Grid, build_grid
from app.world.hydrology import carve_channel, priority_flood, settle_water, trace_cells
from app.world.paths import reachable
from app.world.spec import HydrologySpec
from app.world.sphere import angle_between, lat_lon, unit_from_lat_lon

SPEC = HydrologySpec(
    river_min_cells=8,
    river_min_length=3,
    lake_min_depth_m=3.0,
    lake_max_depth_m=8.0,
    lake_min_cells=1,
    channel_depth_m=2.0,
)


@pytest.fixture(scope="module")
def grid() -> Grid:
    return build_grid(12)


def _dome(grid: Grid, peak: float = 100.0) -> np.ndarray:
    """Land rising toward the north pole; ocean south of 10°S."""
    lat, _ = lat_lon(grid.positions)
    return np.where(lat < -10, -50.0, 1 + peak * (lat + 10) / 100)


def _none(grid: Grid) -> np.ndarray:
    return np.zeros(grid.cell_count, dtype=bool)


def _with_pit(grid: Grid, depth: float, cone: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """A pit `depth` metres below the lowest cell around it: flat-bottomed, or a cone deepest at its centre."""
    heights = _dome(grid)
    reach = angle_between(grid.positions, unit_from_lat_lon(40, 0)) / np.radians(9)
    pit = reach < 1
    rim = np.zeros(grid.cell_count, dtype=bool)
    rim[grid.neighbours[pit][grid.neighbours[pit] >= 0]] = True
    rim &= ~pit
    heights[pit] = heights[rim].min() - depth * ((1 - reach[pit]) if cone else 1)
    return heights, pit


def test_flood_drains_every_land_cell_downhill_to_the_ocean(grid: Grid) -> None:
    heights, _ = _with_pit(grid, 30)

    drainage = priority_flood(grid, heights, heights < 0)

    land = np.flatnonzero(heights >= 0)
    assert (drainage.heights >= heights).all()
    for cell in land:
        downstream = drainage.parent[cell]
        assert downstream in grid.neighbours[cell]
        assert drainage.heights[downstream] <= drainage.heights[cell]
    ocean = heights < 0
    assert (drainage.parent[ocean] == -1).all()


def test_shallow_pit_becomes_an_open_lake_at_its_spill_level(grid: Grid) -> None:
    heights, pit = _with_pit(grid, 6)

    water = settle_water(grid, heights, SPEC, [], _none(grid), _none(grid), _none(grid))

    assert water.lake[pit].all()
    surface = water.heights[water.lake]
    assert np.ptp(surface) == 0
    rim = pit.copy()
    rim[grid.neighbours[pit][grid.neighbours[pit] >= 0]] = True
    rim &= ~water.lake
    assert surface[0] == pytest.approx(heights[rim].min(), abs=0.01)
    outflows = [river for river in water.rivers if water.lake[river.cells[0]]]
    assert outflows, "an open lake drains on through a river"


def test_deep_pit_becomes_a_closed_lake_with_dry_slopes(grid: Grid) -> None:
    heights, pit = _with_pit(grid, 40, cone=True)

    water = settle_water(grid, heights, SPEC, [], _none(grid), _none(grid), _none(grid))

    lake = water.lake
    assert lake.any() and not lake[pit].all()
    bottom = heights[pit].min()
    assert water.heights[lake].max() == pytest.approx(bottom + SPEC.lake_max_depth_m)
    dry_slopes = pit & ~lake
    np.testing.assert_allclose(water.heights[dry_slopes], heights[dry_slopes])


def test_pits_shallower_than_the_lake_depth_fill_into_drained_flats(grid: Grid) -> None:
    heights, pit = _with_pit(grid, 2)

    water = settle_water(grid, heights, SPEC, [], _none(grid), _none(grid), _none(grid))

    assert not water.lake.any()
    assert (water.heights[pit] >= heights[pit]).all()


def test_lake_free_cells_and_basins_never_hold_a_lake(grid: Grid) -> None:
    heights, pit = _with_pit(grid, 6)

    kept = settle_water(grid, heights, SPEC, [], pit, _none(grid), _none(grid))
    free = settle_water(grid, heights, SPEC, [], _none(grid), _none(grid), pit)

    assert not kept.lake.any()
    np.testing.assert_array_equal(kept.heights[pit], heights[pit])
    assert not free.lake.any()


def test_rivers_flow_downhill_into_water(grid: Grid) -> None:
    water = settle_water(grid, _dome(grid), SPEC, [], _none(grid), _none(grid), _none(grid))

    assert water.rivers
    sea = water.heights < 0
    river_cells = {cell for river in water.rivers for cell in river.cells}
    for river in water.rivers:
        steps = np.diff(water.heights[river.cells])
        assert (steps <= 0).all()
        last = river.cells[-1]
        assert sea[last] or last in river_cells


def test_trace_cells_follows_neighbours_along_the_arc(grid: Grid) -> None:
    cells = trace_cells(grid, [(30, 0), (30, 40), (0, 40)])

    for a, b in zip(cells, cells[1:], strict=False):
        assert b in grid.neighbours[a]
    lat, lon = lat_lon(grid.positions[[cells[0], cells[-1]]])
    assert abs(lat[0] - 30) < 6 and abs(lon[0]) < 6
    assert abs(lat[1]) < 6 and abs(lon[1] - 40) < 6


def test_carved_channel_runs_downhill_to_the_sea_around_pinned_cells(grid: Grid) -> None:
    heights = _dome(grid)
    lat, _ = lat_lon(grid.positions)
    heights += 15 * np.sin(np.radians(lat) * 12)  # ridges across the path
    cells = trace_cells(grid, [(60, 10), (-30, 10)])
    pinned = np.zeros(grid.cell_count, dtype=bool)
    plateau = cells[len(cells) // 3]
    pinned[plateau] = True
    before = heights.copy()

    path = carve_channel(heights, cells, pinned, np.full(grid.cell_count, np.inf), 2.0, "test")

    assert (np.diff(heights[path]) <= 0).all()
    assert heights[path[-1]] < 0 and (heights[path[:-1]] > 0).all()
    assert heights[plateau] == before[plateau]
    assert path == cells[: len(path)]


def test_carved_channel_leaves_and_enters_lake_bowls_without_cutting_them(grid: Grid) -> None:
    heights = _dome(grid)
    bowl = angle_between(grid.positions, unit_from_lat_lon(30, 10)) < np.radians(6)
    heights[bowl] = 5.0
    before = heights.copy()
    cells = trace_cells(grid, [(30, 10), (-30, 10)])

    path = carve_channel(heights, cells, _none(grid), np.where(bowl, 9.0, np.inf), 2.0, "test")

    assert bowl[path[0]] and not bowl[path[1]]
    np.testing.assert_array_equal(heights[bowl], before[bowl])
    assert heights[path[1]] <= 9.0
    assert (np.diff(heights[path[1:]]) <= 0).all()
    assert heights[path[-1]] < 0


def test_reachable_stays_on_allowed_cells(grid: Grid) -> None:
    lat, _ = lat_lon(grid.positions)
    north = lat > 0

    seen = reachable(grid, north, int(np.argmax(lat)))

    np.testing.assert_array_equal(seen, north)
