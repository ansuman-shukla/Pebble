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


class Hotspot(BaseModel):
    """A named cluster of nodes (10-world-v1 §1.2)."""

    id: str
    name: str
    called: str  # mid-sentence: "the Elder grove"
    centre: Vector  # unit vector
    cell: int
    radius_m: float
    settlement: str  # site id of the settlement whose rings it lies in
    ring: Literal["home", "middle", "far"]
    distance_m: float  # from that settlement's anchor
    claim: Literal["town", "band_a", "band_b"] | None = None
    danger: str
    thirst: float = 1.0  # thirst factor while inside
    woodland: float = 1.0  # tree density factor inside
    flora: dict[str, int] = {}  # node kind -> exact count inside
    hunting: list[str] = []  # animal kinds whose hunting ground it is


class Ground(BaseModel):
    """A hunting ground around a settlement."""

    id: str
    name: str
    site: str
    centre: Vector
    radius_m: float
    hunting: list[str]


FeatureKind = Literal[
    "fishing_spot",
    "flint_seam",
    "obsidian_field",
    "iron_sand_bar",
    "gold_pool",
    "waterhole",
    "den",
    "signpost",
    "marker",
]


class Feature(BaseModel):
    """A fixed thing in the wild: a node (seam, fishing spot, waterhole...), a den, a signpost or a claim marker."""

    id: str
    kind: FeatureKind
    hotspot: str | None = None
    position: Vector  # unit vector
    cell: int
    water: Literal["sea", "river", "lake"] | None = None  # fishing spots and waterholes
    pool: bool = False  # waterholes: a drawn pool, no river or lake at hand
    cap: int | None = None  # stock cap when it differs from the kind's
    animal: str | None = None  # dens
    names: list[str] = []  # signposts: the two places it points to
    owner: Literal["town", "band_a", "band_b"] | None = None  # markers


class Road(BaseModel):
    """A road (3 m) or path (1.5 m): an optional lead inside the town chart, then a cell route outside it."""

    id: str
    kind: Literal["road", "path"]
    name: str
    stops: list[str]
    lead: list[Vector] = []  # unit vectors from a town gate to the chart's edge, walked before `cells`
    cells: list[int]


class Bridge(BaseModel):
    id: str
    road: str
    cell: int | None  # None: on the town chart (the west lead over the stream)
    position: Vector
    heading_deg: float  # compass bearing along the road


class WorldPlaces(BaseModel):
    """Hotspots, grounds, fixed features, roads and bridges (`GET /api/v1/world/places`)."""

    hotspots: list[Hotspot]
    grounds: list[Ground]
    features: list[Feature]
    roads: list[Road]
    bridges: list[Bridge]
    flora_kinds: list[str]  # index = the kind code in `GET /api/v1/world/flora`
    flora_nodes: list[str]  # node kind of each flora kind


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
