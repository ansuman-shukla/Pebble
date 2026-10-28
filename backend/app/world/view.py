"""The world as the API serves it (`GET /api/v1/world`): typed arrays as base64 little-endian bytes."""

import base64
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from app.world.town import TownPlacement

Vector = tuple[float, float, float]


class Anchor(BaseModel):
    position: Vector  # unit vector of the site's local origin
    east: Vector
    north: Vector
    height_m: float  # h0: the plateau height of the site's local frame


class Site(BaseModel):
    id: str
    kind: Literal["town", "camp", "landmark"]
    name: str
    cell: int
    anchor: Anchor
    placements: list[TownPlacement] = []


class River(BaseModel):
    id: str
    name: str | None = None
    cells: list[int]


class WorldView(BaseModel):
    seed: int
    generator_version: str
    radius_m: float
    frequency: int
    cell_count: int
    biome_names: list[str]  # index = biome id
    positions: str  # base64, little-endian float32, cell_count*3 unit vectors (x, y, z)
    heights: str  # base64 float32, cell_count, metres above sea level
    biomes: str  # base64 uint8, cell_count
    triangles: str  # base64 uint32, triangle_count*3 cell indices (counter-clockwise seen from outside)
    rivers: list[River]
    land_loop: list[int]  # closed cycle of neighbouring walkable cells
    sites: list[Site]


def encode_array(values: NDArray[np.generic], dtype: str) -> str:
    """Base64 of the array cast to a little-endian dtype such as '<f4', '<u4' or 'u1'."""
    return base64.b64encode(np.ascontiguousarray(values, dtype=np.dtype(dtype)).tobytes()).decode("ascii")


def decode_array(data: str, dtype: str) -> NDArray[np.generic]:
    return np.frombuffer(base64.b64decode(data), dtype=np.dtype(dtype))
