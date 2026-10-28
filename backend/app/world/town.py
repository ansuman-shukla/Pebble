"""The authored town: spec models, loading and expansion into the view the API serves.

The spec is world data (`data/town/*.yaml`). It only names prop kinds; how a kind looks is the frontend's business.
"""

from collections import Counter
from collections.abc import Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.core.config import WORLD_DATA_DIR
from app.world.geometry import Point, Polygon, Rect, Rotation, facing

TOWN_DATA_DIR = WORLD_DATA_DIR / "town"
_LENGTH_TOLERANCE = 1e-6

WalkKind = Literal["solid", "surface", "none"]
AreaKind = Literal["street", "road", "plaza", "courtyard", "field"]
WaterKind = Literal["moat", "stream"]
RectSpec = tuple[float, float, float, float]


# --- view (served at /api/v1/town) ---


class Extent(BaseModel):
    min_x: float
    max_x: float
    min_z: float
    max_z: float

    def rect(self) -> Rect:
        return Rect(self.min_x, self.min_z, self.max_x, self.max_z)


class Spawn(BaseModel):
    x: float
    z: float
    heading_deg: float


class Footprint(BaseModel):
    """Axis-aligned size after rotation."""

    x: float
    z: float


class TownArea(BaseModel):
    id: str
    kind: AreaKind
    polygon: list[tuple[float, float]]


class TownWater(BaseModel):
    id: str
    kind: WaterKind
    polygon: list[tuple[float, float]]
    holes: list[list[tuple[float, float]]] = []


class TownPlacement(BaseModel):
    id: str
    kind: str
    x: float
    z: float
    rotation_deg: Rotation
    footprint: Footprint
    walk: WalkKind

    def rect(self) -> Rect:
        return Rect.centred(self.x, self.z, self.footprint.x, self.footprint.z)

    def front(self, distance: float = 1.0) -> Point:
        """The point `distance` metres in front of the footprint, in the direction the placement faces."""
        dx, dz = facing(self.rotation_deg)
        reach = abs(dx) * self.footprint.x / 2 + abs(dz) * self.footprint.z / 2 + distance
        return (self.x + dx * reach, self.z + dz * reach)


class TownCitizen(BaseModel):
    look: str
    x: float
    z: float
    heading_deg: float
    route: list[tuple[float, float]] = []  # empty = stands still; otherwise loops through the points


class TownView(BaseModel):
    name: str
    extent: Extent
    spawn: Spawn
    areas: list[TownArea]
    water: list[TownWater]
    placements: list[TownPlacement]
    citizens: list[TownCitizen]


# --- spec (data/town/*.yaml) ---


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KindSpec(_Spec):
    footprint: tuple[float, float]
    walk: WalkKind
    blockers: list[RectSpec] | None = None  # local rects at rotation 0; default = the whole footprint

    @model_validator(mode="after")
    def _check_blockers(self) -> "KindSpec":
        if self.blockers is None:
            return self
        if self.walk != "solid":
            raise ValueError("only solid kinds have blockers")
        bounds = Rect.centred(0, 0, *self.footprint)
        if not all(Rect(*blocker).inside(bounds) for blocker in self.blockers):
            raise ValueError("blockers must lie inside the footprint")
        return self

    def local_blockers(self) -> list[Rect]:
        if self.walk != "solid":
            return []
        if self.blockers is None:
            return [Rect.centred(0, 0, *self.footprint)]
        return [Rect(*blocker) for blocker in self.blockers]


class _ShapeSpec(_Spec):
    """A ground shape given either as a polygon or as a rect shorthand."""

    polygon: list[Point] | None = None
    rect: RectSpec | None = None

    @model_validator(mode="after")
    def _check_one_shape(self) -> "_ShapeSpec":
        if (self.polygon is None) == (self.rect is None):
            raise ValueError("give exactly one of polygon or rect")
        if self.polygon is not None and len(self.polygon) < 3:
            raise ValueError("a polygon needs at least 3 points")
        return self

    def outline(self) -> Polygon:
        if self.rect is not None:
            return Rect(*self.rect).polygon()
        assert self.polygon is not None  # guaranteed by _check_one_shape
        return list(self.polygon)


class AreaSpec(_ShapeSpec):
    id: str
    kind: AreaKind


class WaterSpec(_ShapeSpec):
    id: str
    kind: WaterKind
    holes: list[list[Point]] = []


class PlacementSpec(_Spec):
    id: str
    kind: str
    at: Point
    rotation_deg: Rotation = 0


class RunSpec(_Spec):
    """A straight row of segments (walls, fences) from one end point to the other."""

    id: str
    kind: str
    start: Point = Field(alias="from")
    end: Point = Field(alias="to")


class TilesSpec(_Spec):
    """A rectangle filled with tiles of the kind's footprint."""

    id: str
    kind: str
    rect: RectSpec


class SpawnSpec(_Spec):
    at: Point
    heading_deg: float


class CitizenSpec(_Spec):
    look: str
    at: Point
    heading_deg: float
    route: list[Point] = []


class TownSpec(_Spec):
    name: str
    extent: Extent
    spawn: SpawnSpec
    areas: list[AreaSpec] = []
    water: list[WaterSpec] = []
    placements: list[PlacementSpec] = []
    runs: list[RunSpec] = []
    tiles: list[TilesSpec] = []
    citizens: list[CitizenSpec] = []


_KINDS_ADAPTER = TypeAdapter(dict[str, KindSpec])


# --- loading and expansion ---


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@cache
def load_kinds() -> Mapping[str, KindSpec]:
    return _KINDS_ADAPTER.validate_python(_read_yaml(TOWN_DATA_DIR / "kinds.yaml"))


@cache
def load_town_spec() -> TownSpec:
    return TownSpec.model_validate(_read_yaml(TOWN_DATA_DIR / "town.yaml"))


@cache
def load_town() -> TownView:
    return expand_town(load_town_spec(), load_kinds())


def expand_town(spec: TownSpec, kinds: Mapping[str, KindSpec]) -> TownView:
    """Turn the authored spec into concrete placements; fails on unknown kinds, duplicate ids or uneven runs/tiles."""
    placements = list(_expand_placements(spec, kinds))
    duplicates = sorted(placement_id for placement_id, count in Counter(p.id for p in placements).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate placement ids: {duplicates}")
    return TownView(
        name=spec.name,
        extent=spec.extent,
        spawn=Spawn(x=spec.spawn.at[0], z=spec.spawn.at[1], heading_deg=spec.spawn.heading_deg),
        areas=[TownArea(id=area.id, kind=area.kind, polygon=area.outline()) for area in spec.areas],
        water=[
            TownWater(id=water.id, kind=water.kind, polygon=water.outline(), holes=water.holes) for water in spec.water
        ],
        placements=placements,
        citizens=[
            TownCitizen(
                look=citizen.look,
                x=citizen.at[0],
                z=citizen.at[1],
                heading_deg=citizen.heading_deg,
                route=citizen.route,
            )
            for citizen in spec.citizens
        ],
    )


def placement_blockers(placement: TownPlacement, kind: KindSpec) -> list[Rect]:
    """The world rectangles where this placement blocks walking (empty unless the kind is solid)."""
    return [
        blocker.rotated(placement.rotation_deg).translated(placement.x, placement.z)
        for blocker in kind.local_blockers()
    ]


def _expand_placements(spec: TownSpec, kinds: Mapping[str, KindSpec]) -> Iterator[TownPlacement]:
    for single in spec.placements:
        yield place_kind(single.id, single.kind, single.at, single.rotation_deg, kinds)
    for run in spec.runs:
        for index, (at, rotation) in enumerate(_run_segments(run, _kind(run.kind, kinds))):
            yield place_kind(f"{run.id}-{index}", run.kind, at, rotation, kinds)
    for tiles in spec.tiles:
        for index, at in enumerate(_tile_centres(tiles, _kind(tiles.kind, kinds))):
            yield place_kind(f"{tiles.id}-{index}", tiles.kind, at, 0, kinds)


def _kind(name: str, kinds: Mapping[str, KindSpec]) -> KindSpec:
    if name not in kinds:
        raise ValueError(f"unknown prop kind {name!r}; add it to kinds.yaml")
    return kinds[name]


def place_kind(
    placement_id: str, kind_name: str, at: Point, rotation: Rotation, kinds: Mapping[str, KindSpec]
) -> TownPlacement:
    kind = _kind(kind_name, kinds)
    size_x, size_z = kind.footprint
    if rotation in (90, 270):
        size_x, size_z = size_z, size_x
    return TownPlacement(
        id=placement_id,
        kind=kind_name,
        x=at[0],
        z=at[1],
        rotation_deg=rotation,
        footprint=Footprint(x=size_x, z=size_z),
        walk=kind.walk,
    )


def _even_count(length: float, step: float, what: str) -> int:
    count = round(length / step)
    if count < 1 or abs(count * step - length) > _LENGTH_TOLERANCE:
        raise ValueError(f"{what}: length {length} m is not a whole number of {step} m pieces")
    return count


def _run_segments(run: RunSpec, kind: KindSpec) -> Iterator[tuple[Point, Rotation]]:
    (x0, z0), (x1, z1) = run.start, run.end
    along_x = z0 == z1 and x0 != x1
    along_z = x0 == x1 and z0 != z1
    if not (along_x or along_z):
        raise ValueError(f"run {run.id}: only axis-aligned runs are supported")
    step = kind.footprint[0]
    length = abs(x1 - x0) + abs(z1 - z0)
    count = _even_count(length, step, f"run {run.id}")
    dx, dz = (x1 - x0) / length, (z1 - z0) / length
    rotation: Rotation = 0 if along_x else 90
    for index in range(count):
        offset = (index + 0.5) * step
        yield (x0 + dx * offset, z0 + dz * offset), rotation


def _tile_centres(tiles: TilesSpec, kind: KindSpec) -> Iterator[Point]:
    rect = Rect(*tiles.rect)
    size_x, size_z = kind.footprint
    columns = _even_count(rect.x1 - rect.x0, size_x, f"tiles {tiles.id} (x)")
    rows = _even_count(rect.z1 - rect.z0, size_z, f"tiles {tiles.id} (z)")
    for row in range(rows):
        for column in range(columns):
            yield (rect.x0 + (column + 0.5) * size_x, rect.z0 + (row + 0.5) * size_z)
