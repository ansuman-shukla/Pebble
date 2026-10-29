"""The animals of v0 (01-world biomes, 02-simulation ecology): who lives where, in what groups, and how they move.

Kinds are the spectator registry's names (`frontend/src/lib/world/assets.ts` `ANIMALS`). Every group is a herd,
pack, pair or shoal with a home range around one cell; its size is the soft cap the group respawns up to.
"""

import math
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal, get_args

import numpy as np
from numpy.typing import NDArray

from app.core.rng import Rng
from app.sim.state import Animal, AnimalGroup, WorldState
from app.sim.vec import Vec3, step_towards
from app.sim.world import SimWorld
from app.world.biomes import BIOME_IDS
from app.world.spec import BIOME_NAMES

IntArray = NDArray[np.int64]
AnimalKind = Literal[
    "deer", "elk", "antelope", "rabbit", "hare", "boar", "goat", "duck",
    "fox", "wolf", "bear", "lion", "polar_bear", "shark", "fish",
]  # fmt: skip


@dataclass(frozen=True)
class Species:
    kind: str
    one: str  # "a deer"
    many: str  # "deer"
    habitat: frozenset[str]  # biomes its groups live in (and the only ones swimmers may enter)
    group_size: tuple[int, int]  # members of a group (the larger is drawn as the group's cap)
    groups: int  # groups on the planet
    walk_m: float  # metres a minute (= per tick) when walking or swimming
    run_m: float
    flee_m: float  # runs from people this close (0 = doesn't)
    range_m: float  # wanders this far from its home cell
    respawn_days: float  # a dead member is replaced this long after it died
    predator: bool = False
    bite: tuple[float, float] = (0.0, 0.0)  # injury to a person per attack; (0, 0) = never attacks people
    prey: frozenset[str] = frozenset()
    hunt_chance: float = 0.0  # a predator's chance to bring down its prey when it closes in
    meat: int = 0  # pieces a hunter gets
    hide: int = 0
    catch: float = 0.0  # a skilled adult hunter's base chance (03 hunt: skill, tool, strength, group adjust it)
    fights_back: float = 0.0  # chance a failed hunt hurts the hunter
    hurts: tuple[float, float] = (0.0, 0.0)  # injury when it fights back
    swims: bool = False
    near_shore: bool = False  # swimmers that keep to water next to land (shoals the bands can see)

    def count_words(self, count: int) -> str:
        if count <= 1:
            return self.one
        if count == 2:
            return f"two {self.many}"
        if self.predator and self.kind in ("wolf", "lion"):
            return f"a pack of {self.many}" if self.kind == "wolf" else f"a pride of {self.many}"
        if self.kind == "fish":
            return "a shoal of fish"
        if self.kind == "duck":
            return f"a flock of {self.many}"
        if count <= 4 and self.kind in ("rabbit", "hare", "boar"):
            return f"a few {self.many}"
        return f"a herd of {self.many}"


_GRASS = frozenset({"grassland"})
_FOREST = frozenset({"broadleaf_forest"})
_COLD = frozenset({"tundra", "snow", "ice"})

SPECIES: dict[str, Species] = {
    s.kind: s
    for s in (
        # --- herbivores ---
        Species("deer", "a deer", "deer", _GRASS | _FOREST, (3, 6), 9, 40, 250, 40, 450, 2.0,
                meat=8, hide=1, catch=0.45),
        Species("elk", "an elk", "elk", frozenset({"taiga"}), (3, 5), 4, 40, 220, 45, 450, 2.5,
                meat=12, hide=2, catch=0.35, fights_back=0.1, hurts=(10, 25)),
        Species("antelope", "an antelope", "antelope", frozenset({"savanna"}), (4, 6), 5, 45, 300, 50, 500, 2.0,
                meat=6, hide=1, catch=0.35),
        Species("rabbit", "a rabbit", "rabbits", _GRASS | _FOREST | frozenset({"savanna"}), (2, 4), 10, 20, 150,
                15, 250, 1.0, meat=1, hide=1, catch=0.5),
        Species("hare", "a hare", "hares", _COLD | frozenset({"taiga"}), (2, 3), 5, 20, 160, 15, 250, 1.0,
                meat=1, hide=1, catch=0.45),
        Species("boar", "a boar", "boars", _FOREST, (2, 4), 6, 30, 200, 30, 400, 2.0,
                meat=6, hide=1, catch=0.35, fights_back=0.3, hurts=(10, 25)),
        Species("goat", "a goat", "goats", frozenset({"hills", "mountain"}), (3, 5), 5, 30, 180, 40, 400, 2.0,
                meat=5, hide=1, catch=0.3),
        Species("duck", "a duck", "ducks", frozenset({"wetland", "lake"}), (3, 5), 6, 15, 80, 20, 250, 1.0,
                meat=1, catch=0.3, swims=True),
        # --- predators ---
        Species("fox", "a fox", "foxes", _GRASS | _FOREST | frozenset({"taiga"}), (1, 1), 4, 30, 200, 30, 600, 3.0,
                predator=True, prey=frozenset({"rabbit", "hare", "duck"}), hunt_chance=0.4, meat=1, hide=1,
                catch=0.3),
        Species("wolf", "a wolf", "wolves", _GRASS | frozenset({"taiga", "tundra"}), (2, 4), 5, 45, 280, 0, 800,
                4.0, predator=True, bite=(12, 25), prey=frozenset({"deer", "elk", "rabbit", "hare", "goat", "boar"}),
                hunt_chance=0.3, meat=3, hide=1, catch=0.2, fights_back=0.5, hurts=(10, 25)),
        Species("bear", "a bear", "bears", _FOREST | frozenset({"taiga"}), (1, 1), 4, 35, 220, 0, 700, 5.0,
                predator=True, bite=(25, 40), prey=frozenset({"deer", "boar", "elk", "rabbit"}), hunt_chance=0.2,
                meat=10, hide=2, catch=0.1, fights_back=0.7, hurts=(20, 40)),
        Species("lion", "a lion", "lions", frozenset({"savanna"}), (2, 3), 3, 40, 300, 0, 800, 5.0,
                predator=True, bite=(20, 35), prey=frozenset({"antelope", "deer", "boar"}), hunt_chance=0.3,
                meat=6, hide=1, catch=0.1, fights_back=0.6, hurts=(20, 35)),
        Species("polar_bear", "a white bear", "white bears", _COLD, (1, 1), 2, 35, 220, 0, 900, 6.0,
                predator=True, bite=(30, 45), prey=frozenset({"hare"}), hunt_chance=0.25, meat=12, hide=2,
                catch=0.1, fights_back=0.7, hurts=(20, 40)),
        Species("shark", "a shark", "sharks", frozenset({"deep_ocean"}), (1, 1), 4, 40, 200, 0, 900, 5.0,
                predator=True, bite=(30, 50), prey=frozenset({"fish"}), hunt_chance=0.3, swims=True),
        Species("fish", "a fish", "fish", frozenset({"shallow_ocean", "lake"}), (4, 6), 10, 10, 60, 5, 150, 1.0,
                swims=True, near_shore=True),
    )
}  # fmt: skip

HERBIVORES = frozenset(kind for kind, s in SPECIES.items() if not s.predator and kind != "fish")
PREDATORS = frozenset(kind for kind, s in SPECIES.items() if s.predator)
DANGEROUS = frozenset(kind for kind, s in SPECIES.items() if s.bite[1] > 0)
LIVING_SITES = ("town", "band_a_camp", "band_b_camp")  # groups settle near these first, so citizens meet them
NEAR_SITE_M = (200.0, 700.0)  # herbivores' homes this far from a living site (their range reaches it)
PREDATOR_NEAR_SITE_M = (600.0, 1600.0)  # predators keep a little further off (their range still reaches camp)
GROUP_SPACING_M = 500.0  # homes of two groups of one kind elsewhere on the planet
PLACE_TRIES = 30

if set(SPECIES) != set(get_args(AnimalKind)):
    raise ValueError("every species is an AnimalKind and back")
_unknown = {b for s in SPECIES.values() for b in s.habitat} - set(BIOME_NAMES)
if _unknown:
    raise ValueError(f"species habitats name unknown biomes: {sorted(_unknown)}")
_bad_prey = {p for s in SPECIES.values() for p in s.prey} - set(SPECIES)
if _bad_prey:
    raise ValueError(f"species prey on unknown kinds: {sorted(_bad_prey)}")


@dataclass(frozen=True)
class Terrain:
    """Static per-cell facts the animals move by (derived from the world once)."""

    land: NDArray[np.bool_]  # walkable land outside the town (walls keep animals out)
    near_town: NDArray[np.bool_]  # cells close enough to the town chart that positions need the exact check
    shore: NDArray[np.bool_]  # water cells next to land
    surface_m: NDArray[np.float64]  # where an animal stands or swims: ground height, or the water surface


_WORLD_CACHES: dict[int, tuple[SimWorld, dict[object, Any]]] = {}


def world_cache(world: SimWorld) -> dict[object, Any]:
    """Facts derived from a (static) world, kept as long as the process runs; never part of the state."""
    cached = _WORLD_CACHES.get(id(world))
    if cached is None or cached[0] is not world:
        cached = _WORLD_CACHES[id(world)] = (world, {})
    return cached[1]


def terrain(world: SimWorld) -> Terrain:
    """The world's terrain facts."""
    cache = world_cache(world)
    found = cache.get("terrain")
    if isinstance(found, Terrain):
        return found
    water = np.isin(world.biomes, [BIOME_IDS[name] for name in ("deep_ocean", "shallow_ocean", "lake")])
    land = np.isfinite(world.terrain_cost) & ~world.in_town
    town_up = np.asarray(world.town.frame.up, dtype=np.float64)
    near_town = world.grid.positions @ town_up > math.cos(500.0 / world.radius_m)
    shore = np.zeros(world.cell_count, dtype=bool)
    for cell in np.flatnonzero(water).tolist():
        shore[cell] = any(not water[other] for other in world.neighbours[cell])
    lake = world.biomes == BIOME_IDS["lake"]
    surface = np.where(water & ~lake, 0.0, world.heights)
    facts = Terrain(land=land, near_town=near_town, shore=shore, surface_m=surface)
    cache["terrain"] = facts
    return facts


def standable(world: SimWorld, kind: str) -> NDArray[np.bool_]:
    """Cells an animal of the kind may be on: swimmers their waters (shoals only next to land, ducks land too),
    everyone else open land outside the town."""
    cache = world_cache(world)
    mask: NDArray[np.bool_] | None = cache.get(("standable", kind))
    if mask is None:
        species, facts = SPECIES[kind], terrain(world)
        waters = np.isin(world.biomes, _habitat_ids(kind))
        if species.near_shore:
            waters &= facts.shore
        if kind == "duck":
            mask = waters | facts.land
        elif species.swims:
            mask = waters
        else:
            mask = facts.land.copy()
        cache[("standable", kind)] = mask
    return mask


def can_stand(world: SimWorld, species: Species, cell: int) -> bool:
    return bool(standable(world, species.kind)[cell])


def in_town_walls(world: SimWorld, cell: int, unit: Vec3) -> bool:
    """Inside the town chart (walls and fences keep animals out)."""
    return bool(terrain(world).near_town[cell]) and world.town_point(unit) is not None


@cache
def _habitat_ids(kind: str) -> tuple[int, ...]:
    return tuple(BIOME_IDS[name] for name in sorted(SPECIES[kind].habitat))


def habitat_cells(world: SimWorld, kind: str) -> IntArray:
    """Every cell a group of this kind could call home."""
    return np.flatnonzero(np.isin(world.biomes, _habitat_ids(kind)) & standable(world, kind)).astype(np.int64)


def range_cells(world: SimWorld, kind: str, home: int) -> IntArray:
    """The cells of a group's home range it picks wandering goals from (its habitat within its range)."""
    species = SPECIES[kind]
    near = world.grid.positions @ world.grid.positions[home] >= math.cos(species.range_m / world.radius_m)
    cells = np.flatnonzero(near & np.isin(world.biomes, _habitat_ids(kind)) & standable(world, kind))
    return cells.astype(np.int64) if cells.size else np.array([home], dtype=np.int64)


def _cells_between(world: SimWorld, cells: IntArray, centre: Vec3, low_m: float, high_m: float) -> IntArray:
    if cells.size == 0:
        return cells
    distances = np.arccos(np.clip(world.grid.positions[cells] @ np.array(centre), -1, 1)) * world.radius_m
    kept: IntArray = cells[(distances >= low_m) & (distances <= high_m)]
    return kept


def populate(world: SimWorld, state: WorldState) -> None:
    """A new run's animals (see `place_groups`)."""
    groups, animals = place_groups(world, state.rng("fauna.place"))
    state.groups = {group.id: group for group in groups}
    state.animals = {animal.id: animal for animal in animals}
    state.next_animal = len(animals) + 1


def place_groups(world: SimWorld, rng: Rng) -> tuple[list[AnimalGroup], list[Animal]]:
    """The starting population: groups near the living sites first, the rest anywhere in their habitat."""
    groups: list[AnimalGroup] = []
    animals: list[Animal] = []
    for kind in sorted(SPECIES):
        species = SPECIES[kind]
        cells = habitat_cells(world, kind)
        if cells.size == 0:
            continue
        homes: list[int] = []
        low, high = PREDATOR_NEAR_SITE_M if species.predator else NEAR_SITE_M
        for site_id in LIVING_SITES:
            if len(homes) >= species.groups:
                break
            centre = world.places[site_id].centre
            near = _cells_between(world, cells, centre, low, high)
            if near.size:
                homes.append(int(near[rng.randint(0, near.size - 1)]))
        while len(homes) < species.groups:
            for _ in range(PLACE_TRIES):
                cell = int(cells[rng.randint(0, cells.size - 1)])
                unit = world.unit(cell)
                if all(world.distance_m(unit, world.unit(other)) >= GROUP_SPACING_M for other in homes):
                    break
            homes.append(cell)
        for home in homes:
            size = rng.randint(*species.group_size)
            group = AnimalGroup(id=f"{kind}-group:{len(groups) + 1}", kind=kind, home=home, size=size)
            groups.append(group)
            for _ in range(size):
                animal = new_animal(world, group, len(animals) + 1, home, rng)
                group.members.append(animal.id)
                animals.append(animal)
    return groups, animals


def new_animal(world: SimWorld, group: AnimalGroup, number: int, cell: int, rng: Rng) -> Animal:
    """A member of the group a few metres from the cell's centre (jitter within the cell)."""
    species = SPECIES[group.kind]
    position = jitter(world, world.unit(cell), 12.0, rng)
    spot = world.nearest_cell(position, cell)
    if not can_stand(world, species, spot):
        position, spot = world.unit(cell), cell
    return Animal(
        id=f"{group.kind}:{number}",
        kind=group.kind,
        group=group.id,
        position=position,
        cell=spot,
        height_m=float(terrain(world).surface_m[spot]),
        heading_deg=round(rng.random() * 360.0, 2),
        hunger=round(rng.random() * 40.0, 2) if species.predator else 0.0,
    )


def jitter(world: SimWorld, unit: Vec3, radius_m: float, rng: Rng) -> Vec3:
    """A random point within radius_m of the unit vector (uniform on the disc, flat approximation)."""
    return step_towards(unit, rng.random() * 360.0, radius_m * math.sqrt(rng.random()), world.radius_m)
