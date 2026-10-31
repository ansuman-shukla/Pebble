"""The node table (10-world-v1 §1.1): every usable wild thing in the world, where it is and what it can hold.

Static, built once with the simulation's world from three sources, one table:

- flora (`app.world.flora`): every tree, nut tree, berry bush, root patch, reed bed and deadwood pile, id
  `flora:<index>` (its index in `GET /world/flora`, as the client draws it);
- fixed features (`WorldPlaces.features`): fishing spots, flint seams, the obsidian field, the iron-sand bar and the
  gold pool, id = the feature's id;
- the town's six rice paddies (the drawn rects), id = the paddy's tile id (`paddy-1` ... `paddy-6`).

The kinds' numbers, spots, stages and words live in `data/world/node_stages.yaml`. A node's work spots are worked
out here from its kind and yaw; `app.sim.slots` claims them like any other slot and `app.sim.nodes` keeps the stock.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Literal, Self

import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import WORLD_DATA_DIR
from app.sim.vec import Vec3, as_vec, bearing_deg, step_towards
from app.world.flora import YAW_STEP_DEG, Flora
from app.world.geometry import Rect
from app.world.grid import Grid
from app.world.town import TownSpec
from app.world.view import Feature, Hotspot

NODE_STAGES_FILE = WORLD_DATA_DIR / "world" / "node_stages.yaml"
NODE_FEATURES = ("fishing_spot", "flint_seam", "obsidian_field", "iron_sand_bar", "gold_pool")
SHORE_KINDS = frozenset({"fishing_spot", "gold_pool"})  # spots along the shore, a metre inland
PADDY_KIND = "rice_paddy"
INLAND_M = 1.0
_CELL_MARGIN_M = 30.0  # flora lies this far at most from its cell's centre (offsets reach ±25.4 m)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PiecesSpec(_Spec):
    pieces: str
    of: int = Field(gt=0)
    round: Literal["nearest", "up"]


class LevelsSpec(_Spec):
    levels: list[tuple[float, str]] = Field(min_length=1)
    by: Literal["share", "stock"] = "share"

    @model_validator(mode="after")
    def _ends_at_zero(self) -> Self:
        least = [level for level, _ in self.levels]
        if least[-1] != 0 or least != sorted(least, reverse=True):
            raise ValueError("levels go from the highest down to 0")
        return self


class NodeKindSpec(_Spec):
    item: str
    cap: int = Field(gt=0)
    sea_cap: int | None = None
    take: tuple[int, int]
    chance: float = Field(default=1.0, gt=0, le=1)
    minutes: int = Field(gt=0)
    axe_minutes: dict[str, int] = {}
    regrow_hours: float | None = None
    full_days: float | None = None
    full_days_by_cap: dict[int, float] = {}
    stump_days: float | None = None
    sapling_days: float | None = None
    spots: int = Field(ge=1, le=4)
    spot_m: float | None = None
    spot_gap_m: float | None = None
    paddy_spot_m: tuple[float, float] | None = None
    start_growth: list[int] = []  # paddies: each paddy's growth at a run's start, in paddy order
    one: str
    many: str
    stage: PiecesSpec | LevelsSpec | None = None  # None: trees and paddies (stages from their own state)
    words: dict[str | int, str]

    @model_validator(mode="after")
    def _check(self) -> Self:
        low, high = self.take
        if not 1 <= low <= high:
            raise ValueError(f"take {self.take} must be 1 <= low <= high")
        if self.regrow_hours is not None and self.full_days is not None:
            raise ValueError("regrow by `regrow_hours` or by `full_days`, not both")
        if self.spot_m is None and self.spot_gap_m is None and self.paddy_spot_m is None:
            raise ValueError("a node kind needs `spot_m`, `spot_gap_m` or `paddy_spot_m`")
        return self

    def regrow_minutes(self, cap: int) -> int | None:
        """Ticks between two pieces growing back on a node holding at most `cap`; None: it never grows back."""
        if self.regrow_hours is not None:
            return max(1, round(self.regrow_hours * 60))
        if self.full_days is not None:
            return max(1, round(self.full_days_by_cap.get(cap, self.full_days) * 24 * 60 / cap))
        return None


class NodeStagesSpec(_Spec):
    kinds: dict[str, NodeKindSpec]


@cache
def load_node_kinds() -> Mapping[str, NodeKindSpec]:
    return NodeStagesSpec.model_validate(yaml.safe_load(NODE_STAGES_FILE.read_text())).kinds


GATHERED: frozenset[str] = frozenset(kind.item for kind in load_node_kinds().values()) - {"fish"}  # gather()'s


def stage_of(kind: NodeKindSpec, stock: int, cap: int) -> str:
    """The drawn stage of a node whose stage follows its stock (not trees or paddies)."""
    if isinstance(kind.stage, PiecesSpec):
        share = kind.stage.of * stock / cap
        count = math.ceil(share - 1e-9) if kind.stage.round == "up" else math.floor(share + 0.5)
        return f"{kind.stage.pieces}-{count}"
    if isinstance(kind.stage, LevelsSpec):
        value = stock if kind.stage.by == "stock" else stock / cap
        return next(name for least, name in kind.stage.levels if value >= least)
    raise ValueError("trees and paddies take their stage from their own state")


def stage_words(kind: NodeKindSpec, stage: str, count: int = 1) -> str:
    """What a person sees at this stage ("a berry bush heavy with fruit", "three berry bushes heavy with fruit")."""
    if isinstance(kind.stage, PiecesSpec):
        pieces = int(stage.rsplit("-", 1)[1])
        template = kind.words[max(int(key) for key in kind.words if int(key) <= pieces)]
    else:
        template = kind.words[stage]
    noun = kind.one if count == 1 else f"{COUNT_WORDS.get(count, 'several' if count < 10 else 'many')} {kind.many}"
    return template.format(noun=noun)


COUNT_WORDS = {2: "two", 3: "three", 4: "four", 5: "five"}


@dataclass(frozen=True)
class Spot:
    """Where someone stands to work a node, facing it (heading: yaw, 0 = south, like citizens')."""

    position: Vec3
    heading_deg: float


@dataclass(frozen=True)
class NodeTable:
    ids: tuple[str, ...]
    kinds: tuple[str, ...]  # node kind of each node
    units: FloatArray  # (n, 3)
    cells: IntArray  # the cell each node belongs to (a flora's own cell, a feature's nearest)
    caps: IntArray
    yaw_deg: FloatArray  # compass bearing (0 north): the way a felled tree falls; turns a node's spots
    hotspots: tuple[str | None, ...]
    shore: FloatArray  # compass bearing from a shore node to the land (nan elsewhere)
    paddy_spots: Mapping[str, tuple[Vec3, ...]]  # each paddy's four spots, inside its rect
    paddy_rects: Mapping[str, Rect]  # each paddy's rect in the town's metres
    radius_m: float
    index: Mapping[str, int]
    by_cell: Mapping[int, IntArray]
    _spots: dict[int, tuple[Spot, ...]] = field(default_factory=dict, compare=False, repr=False)

    def __len__(self) -> int:
        return len(self.ids)

    def full_stock(self) -> dict[str, int]:
        """What all the nodes of each item hold when full, by item."""
        totals: dict[str, int] = {}
        for kind_name, cap in zip(self.kinds, self.caps.tolist(), strict=True):
            item = load_node_kinds()[kind_name].item
            totals[item] = totals.get(item, 0) + int(cap)
        return dict(sorted(totals.items()))

    def food_by_bearing(
        self,
        grid: Grid,
        centre: Vec3,
        inner_m: float,
        outer_m: float,
        items: frozenset[str],
        sectors: int = 8,
        avoid: Sequence[Vec3] = (),
        clear_m: float = 0.0,
    ) -> list[int]:
        """What the nodes of these items hold when full, between `inner_m` and `outer_m` of a point, in `sectors`
        compass sectors (the first centred on north, then clockwise), leaving out nodes within `clear_m` of a point
        to `avoid`."""
        totals = [0] * sectors
        width = 360.0 / sectors
        avoided = np.array(avoid, dtype=np.float64).reshape(-1, 3)
        for metres, node in self.near(grid, centre, outer_m):
            if metres < inner_m or self.kind(node).item not in items:
                continue
            gaps = np.arccos(np.clip(avoided @ self.units[node], -1.0, 1.0)) * self.radius_m
            if (gaps >= clear_m).all():
                sector = int(((bearing_deg(centre, self.unit(node)) + width / 2) % 360.0) // width)
                totals[sector] += int(self.caps[node])
        return totals

    def kind(self, node: int) -> NodeKindSpec:
        return load_node_kinds()[self.kinds[node]]

    def unit(self, node: int) -> Vec3:
        return as_vec(self.units[node])

    def near(self, grid: Grid, unit: Vec3, radius_m: float) -> list[tuple[float, int]]:
        """Nodes within `radius_m` of the point, nearest first: (metres, node)."""
        centre = np.array(unit)
        cos_cells = math.cos(min(math.pi, (radius_m + _CELL_MARGIN_M) / self.radius_m))
        cells = np.flatnonzero(grid.positions @ centre >= cos_cells).tolist()
        found = [self.by_cell[cell] for cell in cells if cell in self.by_cell]
        if not found:
            return []
        nodes = np.concatenate(found)
        metres = np.arccos(np.clip(self.units[nodes] @ centre, -1.0, 1.0)) * self.radius_m
        keep = metres <= radius_m
        return sorted(zip(metres[keep].tolist(), nodes[keep].tolist(), strict=True))

    def spots(self, node: int) -> tuple[Spot, ...]:
        """The node's work spots, facing it (worked out once, then kept)."""
        known = self._spots.get(node)
        if known is not None:
            return known
        kind = self.kind(node)
        centre = self.unit(node)
        kind_name = self.kinds[node]
        if kind_name == PADDY_KIND:
            points = list(self.paddy_spots[self.ids[node]])
            spots = tuple(Spot(point, 0.0) for point in points)
        else:
            if kind_name in SHORE_KINDS and not math.isnan(float(self.shore[node])):
                inland = float(self.shore[node])
                base = step_towards(centre, inland, INLAND_M, self.radius_m)
                gap = kind.spot_gap_m or 0.0
                offsets = [(index + 1) // 2 * gap * (1 if index % 2 else -1) for index in range(kind.spots)]
                points = [step_towards(base, (inland + 90.0) % 360.0, offset, self.radius_m) for offset in offsets]
            else:
                reach = kind.spot_m if kind.spot_m is not None else kind.spot_gap_m or 1.0
                yaw = float(self.yaw_deg[node])
                start = yaw + 180.0 if kind.spots == 1 else yaw + 90.0  # a feller stands away from the fall
                points = [
                    step_towards(centre, (start + k * 360.0 / kind.spots) % 360.0, reach, self.radius_m)
                    for k in range(kind.spots)
                ]
            spots = tuple(Spot(point, round((180.0 - bearing_deg(point, centre)) % 360.0, 2)) for point in points)
        self._spots[node] = spots
        return spots


def build_node_table(
    grid: Grid,
    radius_m: float,
    flora: Flora,
    flora_nodes: Sequence[str],
    features: Sequence[Feature],
    hotspots: Sequence[Hotspot],
    water: NDArray[np.bool_],
    paddies: Mapping[str, tuple[Vec3, tuple[Vec3, ...]]],
    paddy_rects: Mapping[str, Rect],
) -> NodeTable:
    """The table from the flora, the node features and the paddies (centre and spots on the globe, rects in the
    town's metres); `water` marks water cells (a shore node's spots lie a metre inland of it)."""
    kinds = load_node_kinds()
    node_kinds = np.array(flora_nodes)[flora.kind.astype(np.int64)].tolist() if len(flora) else []
    ids = [f"flora:{index}" for index in range(len(flora))]
    units = [flora.units] if len(flora) else []
    cells = flora.cell.astype(np.int64).tolist()
    caps = [kinds[name].cap for name in node_kinds]
    yaws = (flora.yaw.astype(np.float64) * YAW_STEP_DEG).tolist()
    shore: list[float] = [math.nan] * len(flora)
    for feature in features:
        if feature.kind not in NODE_FEATURES:
            continue
        spec = kinds[feature.kind]
        ids.append(feature.id)
        node_kinds.append(feature.kind)
        units.append(np.array([feature.position]))
        cells.append(feature.cell)
        cap = feature.cap or (spec.sea_cap if feature.water == "sea" and spec.sea_cap else spec.cap)
        caps.append(cap)
        yaws.append(0.0)
        shore.append(_inland(grid, feature, water) if feature.kind in SHORE_KINDS else math.nan)
    for paddy_id, (centre, _spots) in sorted(paddies.items()):
        ids.append(paddy_id)
        node_kinds.append(PADDY_KIND)
        units.append(np.array([centre]))
        cells.append(int(np.argmax(grid.positions @ np.array(centre))))
        caps.append(kinds[PADDY_KIND].cap)
        yaws.append(0.0)
        shore.append(math.nan)
    unknown = set(node_kinds) - set(kinds)
    if unknown:
        raise ValueError(f"node kinds without a row in node_stages.yaml: {sorted(unknown)}")
    all_units = np.concatenate(units) if units else np.zeros((0, 3))
    cell_array = np.array(cells, dtype=np.int64)
    order = np.argsort(cell_array, kind="stable")
    bounds = np.flatnonzero(np.diff(cell_array[order])) + 1
    by_cell = {int(cell_array[group[0]]): group for group in np.split(order, bounds) if len(group)}
    return NodeTable(
        ids=tuple(ids),
        kinds=tuple(node_kinds),
        units=all_units,
        cells=cell_array,
        caps=np.array(caps, dtype=np.int64),
        yaw_deg=np.array(yaws, dtype=np.float64),
        hotspots=_hotspots_of(all_units, ids, features, hotspots, radius_m),
        shore=np.array(shore, dtype=np.float64),
        paddy_spots={paddy_id: spots for paddy_id, (_centre, spots) in paddies.items()},
        paddy_rects=dict(paddy_rects),
        radius_m=radius_m,
        index={node_id: index for index, node_id in enumerate(ids)},
        by_cell=by_cell,
    )


def paddy_rects(town: TownSpec) -> dict[str, Rect]:
    """The town's paddies (tiles of kind rice_paddy) by id."""
    return {tiles.id: Rect(*tiles.rect) for tiles in town.tiles if tiles.kind == PADDY_KIND}


def paddy_points(rect: Rect) -> tuple[tuple[float, float], tuple[tuple[float, float], ...]]:
    """A paddy's centre and its four spots in the town's metres (x east, z south), inside the rect."""
    dx, dz = load_node_kinds()[PADDY_KIND].paddy_spot_m or (0.0, 0.0)
    cx, cz = (rect.x0 + rect.x1) / 2, (rect.z0 + rect.z1) / 2
    return (cx, cz), tuple((cx + sx * dx, cz + sz * dz) for sz in (-1, 1) for sx in (-1, 1))


def _inland(grid: Grid, feature: Feature, water: NDArray[np.bool_]) -> float:
    """Compass bearing from a shore feature towards the nearest land cell's centre."""
    point = np.array(feature.position)
    cell = int(np.argmax(grid.positions @ point))
    around = [cell, *[int(c) for c in grid.neighbours[cell] if c >= 0]]
    land = [c for c in around if not water[c]]
    if not land:
        return 0.0
    nearest = max(land, key=lambda c: float(grid.positions[c] @ point))
    return bearing_deg(as_vec(point), as_vec(grid.positions[nearest]))


def _hotspots_of(
    units: FloatArray, ids: Sequence[str], features: Sequence[Feature], hotspots: Sequence[Hotspot], radius_m: float
) -> tuple[str | None, ...]:
    """The hotspot each node lies in (a feature: its own; flora: the nearest hotspot whose radius holds it)."""
    owner: list[str | None] = [None] * len(ids)
    best = np.full(len(ids), np.inf)
    for hotspot in hotspots:
        metres = np.arccos(np.clip(units @ np.array(hotspot.centre), -1.0, 1.0)) * radius_m
        inside = (metres <= hotspot.radius_m) & (metres < best)
        for index in np.flatnonzero(inside).tolist():
            owner[index] = hotspot.id
        best = np.where(inside, metres, best)
    feature_hotspot = {feature.id: feature.hotspot for feature in features}
    return tuple(feature_hotspot.get(node_id, found) for node_id, found in zip(ids, owner, strict=True))
