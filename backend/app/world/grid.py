"""The hex-sphere grid: a subdivided icosahedron whose vertices are the world's cells.

Cells are the vertices of the subdivision (their Goldberg dual is hexagons plus 12 pentagons). Order is fixed:
the 12 icosahedron corners, then the interior points of the 30 edges, then the interior points of the 20 faces.
"""

from dataclasses import dataclass
from functools import cache
from itertools import combinations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

_PHI = (1 + 5**0.5) / 2
MAX_NEIGHBOURS = 6


@dataclass(frozen=True)
class Grid:
    frequency: int
    positions: FloatArray  # (cell_count, 3) unit vectors
    triangles: IntArray  # (triangle_count, 3) cell indices, counter-clockwise seen from outside
    neighbours: IntArray  # (cell_count, 6) cell indices sorted ascending, padded with -1 (the 12 pentagons have 5)

    @property
    def cell_count(self) -> int:
        return len(self.positions)

    def neighbour_lists(self) -> list[list[int]]:
        return [[int(n) for n in row if n >= 0] for row in self.neighbours]


def cell_count(frequency: int) -> int:
    return 10 * frequency**2 + 2


@cache
def build_grid(frequency: int) -> Grid:
    if frequency < 1:
        raise ValueError(f"frequency must be >= 1, got {frequency}")
    corners, faces = _icosahedron()
    edges = sorted(
        {
            (min(a, b), max(a, b))
            for face in faces
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[0], face[2]))
        }
    )
    edge_ids = {edge: index for index, edge in enumerate(edges)}

    f = frequency
    # lattice points of one face, as barycentric steps (i toward corner b, j toward corner c)
    i_steps, j_steps = (a.ravel() for a in np.meshgrid(np.arange(f + 1), np.arange(f + 1), indexing="ij"))
    on_face = i_steps + j_steps <= f
    i_steps, j_steps = i_steps[on_face], j_steps[on_face]
    lattice_index = np.full((f + 1, f + 1), -1, dtype=np.int64)
    lattice_index[i_steps, j_steps] = np.arange(len(i_steps))

    edge_base = 12
    face_base = edge_base + len(edges) * (f - 1)
    interior_per_face = (f - 1) * (f - 2) // 2
    interior = (i_steps > 0) & (j_steps > 0) & (i_steps + j_steps < f)

    positions = np.empty((cell_count(f), 3))
    positions[:12] = corners
    for (a, b), edge_id in edge_ids.items():
        t = np.arange(1, f)[:, None] / f
        start = edge_base + edge_id * (f - 1)
        positions[start : start + f - 1] = corners[a] * (1 - t) + corners[b] * t

    face_cells = np.empty((len(faces), len(i_steps)), dtype=np.int64)
    for face_id, (a, b, c) in enumerate(faces):
        cells = np.empty(len(i_steps), dtype=np.int64)
        start = face_base + face_id * interior_per_face
        cells[interior] = start + np.arange(interior_per_face)
        weights_b, weights_c = i_steps[interior, None] / f, j_steps[interior, None] / f
        positions[cells[interior]] = (
            corners[a] * (1 - weights_b - weights_c) + corners[b] * weights_b + corners[c] * weights_c
        )
        for corner, at in ((a, (i_steps == 0) & (j_steps == 0)), (b, i_steps == f), (c, j_steps == f)):
            cells[at] = corner
        _assign_edge(cells, (i_steps > 0) & (i_steps < f) & (j_steps == 0), i_steps, a, b, f, edge_ids, edge_base)
        _assign_edge(cells, (j_steps > 0) & (j_steps < f) & (i_steps == 0), j_steps, a, c, f, edge_ids, edge_base)
        _assign_edge(
            cells, (j_steps > 0) & (j_steps < f) & (i_steps + j_steps == f), j_steps, b, c, f, edge_ids, edge_base
        )
        face_cells[face_id] = cells

    positions /= np.linalg.norm(positions, axis=1, keepdims=True)
    triangles = _face_triangles(lattice_index, f, face_cells)
    return Grid(
        frequency=f, positions=positions, triangles=triangles, neighbours=_neighbours(triangles, len(positions))
    )


def _assign_edge(
    cells: IntArray,
    on_edge: NDArray[np.bool_],
    steps: IntArray,
    start: int,
    end: int,
    f: int,
    edge_ids: dict[tuple[int, int], int],
    edge_base: int,
) -> None:
    """Index the lattice points on the face edge start→end (steps counts from start) by their canonical edge slot."""
    edge = (min(start, end), max(start, end))
    along = steps[on_edge] if start < end else f - steps[on_edge]
    cells[on_edge] = edge_base + edge_ids[edge] * (f - 1) + along - 1


def _face_triangles(lattice_index: IntArray, f: int, face_cells: IntArray) -> IntArray:
    up_i, up_j = np.nonzero(np.add.outer(np.arange(f + 1), np.arange(f + 1)) < f)
    down_i, down_j = np.nonzero(np.add.outer(np.arange(f + 1), np.arange(f + 1)) < f - 1)
    local = np.concatenate(
        [
            np.stack([lattice_index[up_i, up_j], lattice_index[up_i + 1, up_j], lattice_index[up_i, up_j + 1]], axis=1),
            np.stack(
                [
                    lattice_index[down_i + 1, down_j],
                    lattice_index[down_i + 1, down_j + 1],
                    lattice_index[down_i, down_j + 1],
                ],
                axis=1,
            ),
        ]
    )
    return face_cells[:, local].reshape(-1, 3)


def _neighbours(triangles: IntArray, count: int) -> IntArray:
    pairs = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    pairs = np.concatenate([pairs, pairs[:, ::-1]])
    pairs = np.unique(pairs, axis=0)  # sorted by (cell, neighbour)
    starts = np.searchsorted(pairs[:, 0], np.arange(count))
    slot = np.arange(len(pairs)) - starts[pairs[:, 0]]
    neighbours = np.full((count, MAX_NEIGHBOURS), -1, dtype=np.int64)
    neighbours[pairs[:, 0], slot] = pairs[:, 1]
    return neighbours


def _icosahedron() -> tuple[FloatArray, list[tuple[int, int, int]]]:
    corners = np.array(
        [(0, s1, s2 * _PHI) for s1 in (1, -1) for s2 in (1, -1)]
        + [(s1, s2 * _PHI, 0) for s1 in (1, -1) for s2 in (1, -1)]
        + [(s2 * _PHI, 0, s1) for s1 in (1, -1) for s2 in (1, -1)],
        dtype=np.float64,
    )
    corners /= np.linalg.norm(corners, axis=1, keepdims=True)
    edge = min(np.linalg.norm(corners[a] - corners[b]) for a, b in combinations(range(12), 2))
    faces: list[tuple[int, int, int]] = []
    for a, b, c in combinations(range(12), 3):
        sides = (corners[a] - corners[b], corners[b] - corners[c], corners[a] - corners[c])
        if all(abs(np.linalg.norm(side) - edge) < 1e-9 for side in sides):
            outward = np.dot(np.cross(corners[b] - corners[a], corners[c] - corners[a]), corners[a]) > 0
            faces.append((a, b, c) if outward else (a, c, b))
    assert len(faces) == 20
    return corners, faces
