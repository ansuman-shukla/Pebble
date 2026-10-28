import numpy as np
import pytest

from app.world.grid import Grid, build_grid, cell_count


@pytest.fixture(scope="module", params=[1, 2, 5, 8])
def grid(request: pytest.FixtureRequest) -> Grid:
    return build_grid(request.param)


def test_full_grid_has_the_contract_counts() -> None:
    grid = build_grid(60)

    assert grid.cell_count == 36_002
    assert len(grid.triangles) == 72_000


def test_counts_follow_the_frequency(grid: Grid) -> None:
    f = grid.frequency

    assert grid.cell_count == cell_count(f) == 10 * f**2 + 2
    assert len(grid.triangles) == 20 * f**2
    assert set(np.unique(grid.triangles)) == set(range(grid.cell_count))


def test_positions_are_distinct_unit_vectors(grid: Grid) -> None:
    np.testing.assert_allclose(np.linalg.norm(grid.positions, axis=1), 1.0, atol=1e-12)
    closest = min(
        np.linalg.norm(grid.positions[a] - grid.positions[b])
        for a, row in enumerate(grid.neighbour_lists())
        for b in row
    )
    assert closest > 0.5 / grid.frequency


def test_every_cell_has_five_or_six_neighbours_and_twelve_are_pentagons(grid: Grid) -> None:
    counts = np.array([len(row) for row in grid.neighbour_lists()])

    assert set(counts) <= {5, 6}
    assert (counts == 5).sum() == 12


def test_neighbours_are_symmetric_and_sorted(grid: Grid) -> None:
    lists = grid.neighbour_lists()

    for cell, row in enumerate(lists):
        assert row == sorted(row)
        assert cell not in row
        for other in row:
            assert cell in lists[other]


def test_neighbours_are_the_closest_cells(grid: Grid) -> None:
    positions = grid.positions
    for cell, row in enumerate(grid.neighbour_lists()):
        distances = np.linalg.norm(positions - positions[cell], axis=1)
        nearest = set(np.argsort(distances)[1 : len(row) + 1].tolist())
        assert nearest == set(row)


def test_triangles_are_counter_clockwise_from_outside(grid: Grid) -> None:
    a, b, c = (grid.positions[grid.triangles[:, k]] for k in range(3))

    outward = np.einsum("ij,ij->i", np.cross(b - a, c - a), a + b + c)

    assert (outward > 0).all()


def test_triangle_edges_are_neighbour_pairs(grid: Grid) -> None:
    lists = grid.neighbour_lists()
    for a, b, c in grid.triangles.tolist():
        assert b in lists[a] and c in lists[b] and a in lists[c]


def test_grid_is_deterministic() -> None:
    first, second = build_grid.__wrapped__(6), build_grid.__wrapped__(6)

    np.testing.assert_array_equal(first.positions, second.positions)
    np.testing.assert_array_equal(first.triangles, second.triangles)
