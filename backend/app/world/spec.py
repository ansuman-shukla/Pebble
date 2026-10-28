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

    def site(self, site_id: str) -> SiteSpec:
        return next(site for site in self.sites if site.id == site_id)


_KINDS_ADAPTER = TypeAdapter(dict[str, KindSpec])


def _read_yaml(name: str) -> object:
    return yaml.safe_load((WORLD_SPEC_DIR / name).read_text())


@cache
def load_world_spec() -> WorldSpec:
    return WorldSpec.model_validate(_read_yaml("world.yaml"))


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
