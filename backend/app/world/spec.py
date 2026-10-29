"""The authored world spec (`data/world/world.yaml`) and its site prop kinds (`data/world/kinds.yaml`)."""

import hashlib
import json
from collections.abc import Mapping
from functools import cache
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.core.config import WORLD_DATA_DIR
from app.world.town import KindSpec, PlacementSpec, load_kinds

WORLD_SPEC_DIR = WORLD_DATA_DIR / "world"

BIOME_NAMES: tuple[str, ...] = (
    "deep_ocean",
    "shallow_ocean",
    "beach",
    "grassland",
    "broadleaf_forest",
    "taiga",
    "wetland",
    "hills",
    "mountain",
    "savanna",
    "tundra",
    "snow",
    "ice",
    "lake",
    "volcanic",
)
BiomeName = Literal[
    "deep_ocean",
    "shallow_ocean",
    "beach",
    "grassland",
    "broadleaf_forest",
    "taiga",
    "wetland",
    "hills",
    "mountain",
    "savanna",
    "tundra",
    "snow",
    "ice",
    "lake",
    "volcanic",
]
SiteKind = Literal["town", "camp", "landmark"]
SITE_IDS: tuple[str, ...] = (
    "town",
    "band_a_camp",
    "band_b_camp",
    "smoking_mountain",
    "great_falls",
    "elder_tree",
    "standing_stones",
    "painted_cave",
    "ice_gate",
    "hot_springs",
)
LatLon = tuple[float, float]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NoiseSpec(_Spec):
    frequency: float
    octaves: int = Field(ge=1)


class WarpSpec(NoiseSpec):
    strength: float


class Continent(_Spec):
    name: str
    at: LatLon
    radius_deg: float = Field(gt=0)


class Sea(_Spec):
    """A round sea cut out of the land (gulfs, inland seas); the land-loop core still wins."""

    name: str
    at: LatLon
    radius_deg: float = Field(gt=0)


class Waypoint(_Spec):
    at: LatLon
    width_m: float = Field(gt=0)  # half-width of the land band around the spine


class LandLoopSpec(_Spec):
    core_fraction: float = Field(gt=0, le=1)  # inner part of the band that is always land
    core_height_m: float = Field(gt=0)  # minimum height in the core
    waypoints: list[Waypoint] = Field(min_length=3)


class MountainRange(_Spec):
    name: str
    height_m: float
    width_m: float = Field(gt=0)
    points: list[LatLon] = Field(min_length=2)


class SmoothingSpec(_Spec):
    """Laplacian passes over the base heights: each moves a cell `strength` of the way to its neighbours' mean."""

    passes: int = Field(ge=0)
    strength: float = Field(gt=0, le=1)


class TerrainSpec(_Spec):
    sea_level: float  # threshold of the continental field: land where the field is above it
    warp: WarpSpec
    coast: NoiseSpec
    coast_amplitude: float
    islands: NoiseSpec
    island_threshold: float
    hills: NoiseSpec
    hills_m: float
    ridges: NoiseSpec  # crest shape of the authored ranges
    relief: NoiseSpec  # ridged noise that raises hills and lesser ranges inland
    relief_m: float
    relief_threshold: float  # ridged values below this add no relief
    lowland_m: float  # height reached a little inland
    smoothing: SmoothingSpec
    max_land_m: float
    min_sea_m: float
    shelf_m: float  # ocean shallower than this is shallow_ocean
    beach_m: float  # coastal land below this is beach


class ClimateSpec(_Spec):
    equator_c: float
    pole_c: float
    exponent: float
    lapse_c_per_m: float
    moisture: NoiseSpec
    moisture_water_m: float  # moisture falls off with this distance from water


class BiomeThresholds(_Spec):
    ice_c: float
    snow_c: float
    tundra_c: float
    taiga_c: float
    savanna_c: float
    mountain_m: float
    hills_m: float
    wetland_moisture: float
    wetland_max_m: float
    forest_moisture: float
    savanna_moisture: float


class HydrologySpec(_Spec):
    river_min_cells: int = Field(ge=1)  # upstream cells needed to form a river
    river_min_length: int = Field(ge=2)
    lake_min_depth_m: float
    lake_max_depth_m: float
    lake_min_cells: int = Field(ge=1)
    channel_depth_m: float  # authored rivers cut this far below the terrain


class AuthoredRiver(_Spec):
    id: str
    name: str | None = None
    points: list[LatLon] = Field(min_length=2)  # spring first; it ends where it first reaches water


class Plateau(_Spec):
    type: Literal["plateau"]
    radius_m: float = Field(gt=0)
    blend_m: float = Field(gt=0)
    height_m: float | None = None  # None: the terrain height at the anchor (at least the beach height)


class Hill(_Spec):
    type: Literal["hill"]
    radius_m: float = Field(gt=0)
    blend_m: float = Field(gt=0)
    rise_m: float = Field(gt=0)


class Volcano(_Spec):
    type: Literal["volcano"]
    peak_m: float
    base_radius_m: float = Field(gt=0)
    crater_radius_m: float = Field(gt=0)
    crater_depth_m: float = Field(gt=0)
    floor_radius_m: float = Field(gt=0)
    volcanic_radius_m: float = Field(gt=0)


class Falls(_Spec):
    """A cliff with a lake at its foot: the anchor is the lip, the lake lies toward `bearing_deg` (0 = north)."""

    type: Literal["falls"]
    lip_m: float
    drop_m: float = Field(gt=0)
    bearing_deg: float
    lake_distance_m: float = Field(gt=0)
    lake_radius_m: float = Field(gt=0)
    lake_depth_m: float = Field(gt=0)
    upland_radius_m: float = Field(gt=0)
    flat_radius_m: float = Field(gt=0)


SiteTerrain = Annotated[Plateau | Hill | Volcano | Falls, Field(discriminator="type")]


class SiteSpec(_Spec):
    id: str
    kind: SiteKind
    name: str
    at: LatLon
    terrain: SiteTerrain
    biome: BiomeName | None = None  # authored biome inside `biome_radius_m`
    biome_radius_m: float = 0.0
    placements: list[PlacementSpec] = []

    @model_validator(mode="after")
    def _check_biome(self) -> "SiteSpec":
        if (self.biome is None) != (self.biome_radius_m == 0):
            raise ValueError(f"{self.id}: give biome and biome_radius_m together")
        return self


Settlement = Literal["town", "band_a_camp", "band_b_camp"]
CAMPS: tuple[Settlement, ...] = ("band_a_camp", "band_b_camp")
Group = Literal["town", "band_a", "band_b"]
Ring = Literal["home", "middle", "far"]
FloraNode = Literal["tree", "nut_tree", "berry_bush", "root_patch", "reed_bed", "deadwood"]
ROADS_STOP = "roads"
TRAIL_STOP = "trail"
FeatureKind = Literal["fishing_spot", "flint_seam", "obsidian_field", "iron_sand_bar", "gold_pool", "waterhole"]
Water = Literal["sea", "river", "lake"]


class FeatureSpec(_Spec):
    """Fixed nodes the generator places inside a hotspot by rule (10 §1.1)."""

    kind: FeatureKind
    count: int = Field(default=1, ge=1)
    water: Water | None = None  # fishing spots: which water they fish
    river: str | None = None  # iron sand: the named river it lies on
    cap: int | None = Field(default=None, gt=0)  # stock cap when it differs from the kind's (flint seams)

    @model_validator(mode="after")
    def _check_fields(self) -> "FeatureSpec":
        if (self.kind == "fishing_spot") != (self.water is not None):
            raise ValueError(f"{self.kind}: give `water` for fishing spots and only for them")
        if (self.kind == "iron_sand_bar") != (self.river is not None):
            raise ValueError(f"{self.kind}: give `river` for iron sand bars and only for them")
        return self


class DenSpec(_Spec):
    """Where a predator's den lies: beside a road through the hotspot, at its edge, or toward a bearing from a site."""

    animal: str
    place: Literal["beside", "edge", "bearing"]
    road: str | None = None  # beside: the route it lies off (40-60 m)
    site: Settlement | None = None  # bearing: measured from this site's anchor
    bearing_deg: float | None = None
    distance_m: float | None = Field(default=None, gt=0)
    biomes: list[BiomeName] = []  # bearing: the den's habitat

    @model_validator(mode="after")
    def _check_fields(self) -> "DenSpec":
        beside, bearing = self.place == "beside", self.place == "bearing"
        if beside != (self.road is not None):
            raise ValueError("a den beside a road names the road, and only then")
        if bearing != (self.site is not None and self.bearing_deg is not None and self.distance_m is not None):
            raise ValueError("a den toward a bearing gives site, bearing_deg and distance_m, and only then")
        if bearing != bool(self.biomes):
            raise ValueError("a den toward a bearing lists its habitat biomes, and only then")
        return self


class HotspotSpec(_Spec):
    """A named cluster of nodes (10 §1.2): a target centre (generation may move it up to 150 m to keep the rules),
    ring and contents."""

    id: str
    name: str
    called: str  # mid-sentence: "the Elder grove"
    at: LatLon
    radius_m: float = Field(gt=0)
    of: Settlement  # the settlement whose rings it lies in
    ring: Ring
    biomes: list[BiomeName] = Field(min_length=1)  # biomes its centre may lie in (all its land when painted)
    paint: BiomeName | None = None  # authored biome over its land within radius_m
    claim: Group | None = None
    danger: str
    thirst: float = Field(default=1.0, gt=0)  # thirst factor while inside (the obsidian field's heat)
    woodland: float = Field(default=1.0, gt=0)  # tree density factor inside (woodlots)
    flora: dict[FloraNode, int] = {}  # exact counts placed inside; natural flora of these kinds stays out
    features: list[FeatureSpec] = []
    den: DenSpec | None = None
    hunting: list[str] = []  # animal kinds whose hunting ground it is


class GroundSpec(_Spec):
    """A hunting ground around a settlement (band B's grass)."""

    id: str
    name: str
    site: Settlement
    radius_m: float = Field(gt=0)
    hunting: list[str] = Field(min_length=1)


class RingSpec(_Spec):
    home_m: float = Field(gt=0)  # home ring: up to this far from the settlement's anchor
    middle_m: float = Field(gt=0)  # middle ring: home_m .. middle_m
    far_m: float = Field(gt=0)  # far ring: beyond this


class HotspotsSpec(_Spec):
    min_spacing_m: float = Field(gt=0)
    rings: RingSpec
    home_ring_flora: dict[FloraNode, int]  # exact counts of these kinds within each camp's home ring
    hotspots: list[HotspotSpec]
    grounds: list[GroundSpec] = []

    @model_validator(mode="after")
    def _check_paint(self) -> "HotspotsSpec":
        for hotspot in self.hotspots:
            if hotspot.paint is not None and hotspot.biomes != [hotspot.paint]:
                raise ValueError(f"{hotspot.id}: a painted hotspot lies in its paint only")
        return self

    @model_validator(mode="after")
    def _check_ids(self) -> "HotspotsSpec":
        ids = [hotspot.id for hotspot in self.hotspots] + [ground.id for ground in self.grounds]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate hotspot or ground ids")
        return self


class GateSpec(_Spec):
    """A town gate roads leave from: its lead runs in town-local metres from the gate to the chart's edge."""

    id: str
    lead: list[tuple[float, float]] = Field(min_length=2)
    bridges: list[tuple[float, float]] = []  # lead points where it crosses town water on a bridge


class RouteSpec(_Spec):
    id: str
    kind: Literal["road", "path"]
    name: str  # as perception says it: "the road from the castle town to the Elder grove"
    # gate, site or hotspot ids; ROADS_STOP = the nearest cell of an earlier road (a spur), TRAIL_STOP = of the trail
    stops: list[str] = Field(min_length=2)


class TrailSpec(_Spec):
    """The land loop drawn and walked as a path."""

    id: str
    name: str


class RoadsSpec(_Spec):
    town_chart_half_m: float = Field(gt=0)  # the town chart's half-width: no road or flora cell inside
    reuse_discount: float = Field(gt=0, le=1)  # cost factor of cells earlier routes took, so later ones merge
    trip_share: float = Field(gt=0, le=1)  # least share of road/path cells on a trip between two places (D121)
    signpost_spacing_m: float = Field(gt=0)  # junctions closer than this to a signpost share it
    gates: list[GateSpec]
    routes: list[RouteSpec]  # most important first: roads, then the trail, then paths
    trail: TrailSpec

    @model_validator(mode="after")
    def _check_order(self) -> "RoadsSpec":
        kinds = [route.kind for route in self.routes]
        if kinds != sorted(kinds, key=lambda kind: kind == "path"):
            raise ValueError("list every road before the first path")
        ids = [route.id for route in self.routes] + [self.trail.id]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate route ids")
        return self


class FloraKindSpec(_Spec):
    id: str  # also the drawn kind
    node: FloraNode
    scale: tuple[float, float]  # drawn scale range


class FloraSpec(_Spec):
    """Usable flora by biome (10 §1.1). Kind order is the u8 code in `/world/flora`: append only."""

    kinds: list[FloraKindSpec] = Field(min_length=1, max_length=256)
    per_cell: dict[BiomeName, dict[str, float]]  # expected count of each kind per cell of the biome
    river_per_cell: dict[str, float]  # extra kinds per river cell in one of river_biomes (reed beds)
    river_biomes: list[BiomeName]

    @model_validator(mode="after")
    def _check_kinds(self) -> "FloraSpec":
        ids = [kind.id for kind in self.kinds]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate flora kinds")
        used = {kind for table in [*self.per_cell.values(), self.river_per_cell] for kind in table}
        if not used <= set(ids):
            raise ValueError(f"unknown flora kinds {sorted(used - set(ids))}")
        return self

    def kind_of(self, node: FloraNode, biome: BiomeName) -> str:
        """The drawn kind of a placed node in a biome: the biome's commonest kind of that node, else the first."""
        table = self.per_cell.get(biome, {})
        nodes = {kind.id: kind.node for kind in self.kinds}
        candidates = sorted((-count, kind) for kind, count in table.items() if nodes[kind] == node)
        if candidates:
            return candidates[0][1]
        return next(kind.id for kind in self.kinds if kind.node == node)


class WorldSpec(_Spec):
    seed: int
    radius_m: float = Field(gt=0)
    frequency: int = Field(ge=1)
    terrain: TerrainSpec
    continents: list[Continent]
    seas: list[Sea] = []
    land_loop: LandLoopSpec
    mountains: list[MountainRange]
    climate: ClimateSpec
    biomes: BiomeThresholds
    hydrology: HydrologySpec
    rivers: list[AuthoredRiver]
    loop_gate: str  # the site id the land loop must pass through
    sites: list[SiteSpec]
    hotspots: HotspotsSpec  # data/world/hotspots.yaml
    roads: RoadsSpec  # data/world/roads.yaml
    flora: FloraSpec  # data/world/flora.yaml

    @model_validator(mode="after")
    def _check_sites(self) -> "WorldSpec":
        ids = [site.id for site in self.sites]
        if sorted(ids) != sorted(SITE_IDS):
            raise ValueError(f"sites must be exactly {sorted(SITE_IDS)}, got {sorted(ids)}")
        if self.loop_gate not in ids:
            raise ValueError(f"unknown loop gate site {self.loop_gate!r}")
        if len({river.id for river in self.rivers}) != len(self.rivers):
            raise ValueError("duplicate river ids")
        return self

    @model_validator(mode="after")
    def _check_places(self) -> "WorldSpec":
        hotspot_ids = {hotspot.id for hotspot in self.hotspots.hotspots}
        stops = hotspot_ids | set(SITE_IDS) | {gate.id for gate in self.roads.gates} | {ROADS_STOP, TRAIL_STOP}
        for route in self.roads.routes:
            unknown = set(route.stops) - stops
            if unknown:
                raise ValueError(f"route {route.id} has unknown stops {sorted(unknown)}")
        routes = {route.id for route in self.roads.routes} | {self.roads.trail.id}
        river_names = {river.name for river in self.rivers}
        for hotspot in self.hotspots.hotspots:
            if hotspot.den is not None and hotspot.den.road is not None and hotspot.den.road not in routes:
                raise ValueError(f"{hotspot.id}: its den lies beside an unknown route {hotspot.den.road!r}")
            for feature in hotspot.features:
                if feature.river is not None and feature.river not in river_names:
                    raise ValueError(f"{hotspot.id}: unknown river {feature.river!r}")
            unknown_nodes = set(hotspot.flora) - {kind.node for kind in self.flora.kinds}
            if unknown_nodes:
                raise ValueError(f"{hotspot.id}: no flora kind grows as {sorted(unknown_nodes)}")
        return self

    def site(self, site_id: str) -> SiteSpec:
        return next(site for site in self.sites if site.id == site_id)


_KINDS_ADAPTER = TypeAdapter(dict[str, KindSpec])


def _read_yaml(name: str) -> object:
    return yaml.safe_load((WORLD_SPEC_DIR / name).read_text())


@cache
def load_world_spec() -> WorldSpec:
    """world.yaml plus the hotspots, roads and flora it is laid out with (one spec, one hash)."""
    raw = _read_yaml("world.yaml")
    if not isinstance(raw, dict):
        raise ValueError("world.yaml must be a mapping")
    layout = {name: _read_yaml(f"{name}.yaml") for name in ("hotspots", "roads", "flora")}
    return WorldSpec.model_validate({**raw, **layout})


@cache
def load_site_kinds() -> Mapping[str, KindSpec]:
    """Kinds sites may place: the town's kinds plus the wild ones from data/world/kinds.yaml."""
    wild = _KINDS_ADAPTER.validate_python(_read_yaml("kinds.yaml"))
    town = load_kinds()
    clashes = sorted(set(wild) & set(town))
    if clashes:
        raise ValueError(f"kinds defined twice (town and world): {clashes}")
    return {**town, **wild}


def spec_hash(spec: WorldSpec, kinds: Mapping[str, KindSpec]) -> str:
    """Stable hash of everything generation reads besides the generator code itself."""
    canonical = {
        "spec": spec.model_dump(mode="json"),
        "kinds": {name: kind.model_dump(mode="json") for name, kind in sorted(kinds.items())},
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
