"""The animals (01-world biomes, 02-simulation ecology, 10-world-v1 §4.6): who lives where, in what groups, how fast
they move.

Kinds are the spectator registry's names (`frontend/src/lib/world/assets.ts` `ANIMALS`). Every group is a herd,
pack, pair or shoal with a home range around one cell; its size is the soft cap the group respawns up to. Predator
groups live at the dens of the world view, herds on its hunting grounds (pinned, at their cap, wandering only
PINNED_RANGE_M); herds drink at the nearest waterhole.
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
    """A kind of animal. Speeds are metres a second (10-world-v1 §4.6): it walks (swims), keeps up its sustained
    speed (`trot_mps`) for as long as it must, and runs its burst speed for `burst_s` seconds before it falls back
    to the sustained one."""

    kind: str
    one: str  # "a deer"
    many: str  # "deer"
    habitat: frozenset[str]  # biomes its groups live in (and the only ones swimmers may enter)
    group_size: tuple[int, int]  # members of a group (a pinned group's cap is the larger)
    groups: int  # groups on the planet
    walk_mps: float  # walking, or swimming for swimmers
    trot_mps: float  # its sustained speed
    run_mps: float  # its burst
    burst_s: float
    range_m: float  # wanders this far from its home cell
    respawn_days: float  # a dead member is replaced this long after it died
    flee_people_m: float = 0.0  # runs from people this close (0 = doesn't)
    flee_predators_m: float = 0.0  # runs from an awake predator this close, unless it stalks unseen
    senses_m: float = 0.0  # always notices a stalker this close
    cover_s: float = 0.0  # a flight reaches cover (burrow, cliff, water) this many seconds in (0 = none)
    swim_mps: float = 0.0  # ducks: paddling (they walk on land at `walk_mps`)
    predator: bool = False
    stalk_m: float = 0.0  # a predator starts its stalk this far from its quarry
    pounce_m: float = 0.0  # and pounces from this close if unseen
    strike: float = 0.0  # its chance to kill what it catches
    race_s: float = 60.0  # it gives up a chase after this long
    resists: float = 1.0  # as prey: the predator's strike chance × this (it fights back)
    bite: tuple[float, float] = (0.0, 0.0)  # injury to a person per bite; (0, 0) = never attacks people
    prey: frozenset[str] = frozenset()
    prefers: frozenset[str] = frozenset()  # prey it goes for first when any is about (a bear: boar, not deer)
    lone_people: bool = False  # hunts only a person alone (nobody within GROUP_M): a wolf pack (10 §1.6)
    scavenges: bool = False  # eats from a carcass it finds before it hunts
    meat: int = 0  # pieces a hunter gets (a predator's kill leaves half of them on the ground)
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

# the bible's table (10 §4.6): walk / sustained / run (burst s), flee from people / predators, always senses, cover
SPECIES: dict[str, Species] = {
    s.kind: s
    for s in (
        # --- herbivores ---
        Species("deer", "a deer", "deer", _GRASS | _FOREST, (3, 6), 9, 1.0, 5.0, 11.0, 20.0, 450, 2.0,
                flee_people_m=40, flee_predators_m=80, senses_m=20, meat=8, hide=1, catch=0.45),
        Species("elk", "an elk", "elk", frozenset({"taiga"}), (3, 5), 4, 1.1, 5.0, 10.0, 20.0, 450, 2.5,
                flee_people_m=45, flee_predators_m=80, senses_m=20, resists=0.6,
                meat=12, hide=2, catch=0.35, fights_back=0.1, hurts=(10, 25)),
        Species("antelope", "an antelope", "antelope", frozenset({"savanna"}), (4, 6), 5, 1.1, 6.0, 13.0, 20.0, 500,
                2.0, flee_people_m=50, flee_predators_m=100, senses_m=20, meat=6, hide=1, catch=0.35),
        Species("rabbit", "a rabbit", "rabbits", _GRASS | _FOREST | frozenset({"savanna"}), (2, 4), 10, 0.5, 4.5,
                9.0, 8.0, 250, 1.0, flee_people_m=15, flee_predators_m=30, senses_m=8, cover_s=10,
                meat=1, hide=1, catch=0.5),
        Species("hare", "a hare", "hares", _COLD | frozenset({"taiga"}), (2, 3), 5, 0.5, 4.5, 9.0, 8.0, 250, 1.0,
                flee_people_m=15, flee_predators_m=30, senses_m=8, cover_s=10, meat=1, hide=1, catch=0.45),
        Species("boar", "a boar", "boars", _FOREST, (2, 4), 6, 0.8, 4.5, 8.0, 15.0, 400, 2.0,
                flee_people_m=30, flee_predators_m=60, senses_m=12, resists=0.4,
                meat=6, hide=1, catch=0.35, fights_back=0.3, hurts=(10, 25)),
        Species("goat", "a goat", "goats", frozenset({"hills", "mountain"}), (3, 5), 5, 0.8, 4.5, 7.0, 20.0, 400,
                2.0, flee_people_m=40, flee_predators_m=60, senses_m=15, cover_s=15, meat=5, hide=1, catch=0.3),
        Species("duck", "a duck", "ducks", frozenset({"wetland", "lake"}), (3, 5), 6, 0.4, 0.8, 2.0, 10.0, 250, 1.0,
                flee_people_m=20, flee_predators_m=30, senses_m=6, cover_s=3, swim_mps=0.5,
                meat=1, catch=0.3, swims=True),
        # --- predators ---
        Species("fox", "a fox", "foxes", _GRASS | _FOREST | frozenset({"taiga"}), (1, 1), 4, 0.9, 4.0, 9.0, 10.0,
                600, 3.0, flee_people_m=30, predator=True, stalk_m=30, pounce_m=12, strike=0.7,
                prey=frozenset({"rabbit", "hare", "duck"}), meat=1, hide=1, catch=0.3),
        Species("wolf", "a wolf", "wolves", _GRASS | frozenset({"taiga", "tundra"}), (2, 4), 5, 1.2, 4.5, 10.0, 30.0,
                800, 4.0, predator=True, stalk_m=60, pounce_m=30, strike=0.5, race_s=120, bite=(12, 25),
                lone_people=True, prey=frozenset({"deer", "elk", "rabbit", "hare", "goat", "boar"}),
                meat=3, hide=1, catch=0.2, fights_back=0.5, hurts=(10, 25)),
        Species("bear", "a bear", "bears", _FOREST | frozenset({"taiga"}), (1, 1), 4, 1.0, 4.0, 11.0, 10.0, 700, 5.0,
                predator=True, stalk_m=40, pounce_m=15, strike=0.5, bite=(25, 40),
                prey=frozenset({"deer", "boar", "elk", "rabbit"}), prefers=frozenset({"boar"}), scavenges=True,
                meat=10, hide=2, catch=0.1, fights_back=0.7, hurts=(20, 40)),
        Species("lion", "a lion", "lions", frozenset({"savanna"}), (2, 3), 3, 1.0, 3.0, 12.0, 15.0, 800, 5.0,
                predator=True, stalk_m=60, pounce_m=25, strike=0.6, bite=(20, 35),
                prey=frozenset({"antelope", "deer", "boar"}),
                meat=6, hide=1, catch=0.1, fights_back=0.6, hurts=(20, 35)),
        Species("polar_bear", "a white bear", "white bears", _COLD, (1, 1), 2, 1.0, 4.0, 10.0, 10.0, 900, 6.0,
                predator=True, stalk_m=40, pounce_m=15, strike=0.5, bite=(30, 45), prey=frozenset({"hare"}),
                scavenges=True,
                meat=12, hide=2, catch=0.1, fights_back=0.7, hurts=(20, 40)),
        Species("shark", "a shark", "sharks", frozenset({"deep_ocean"}), (1, 1), 4, 1.0, 5.0, 5.0, 60.0, 900, 5.0,
                predator=True, bite=(30, 50), swims=True),
        Species("fish", "a fish", "fish", frozenset({"shallow_ocean", "lake"}), (4, 6), 10, 0.3, 2.0, 2.0, 60.0,
                150, 1.0, flee_predators_m=5, swims=True, near_shore=True),
    )
}  # fmt: skip

HERBIVORES = frozenset(kind for kind, s in SPECIES.items() if not s.predator and kind != "fish")
PREDATORS = frozenset(kind for kind, s in SPECIES.items() if s.predator)
DANGEROUS = frozenset(kind for kind, s in SPECIES.items() if s.bite[1] > 0)
LIVING_SITES = ("town", "band_a_camp", "band_b_camp")  # groups settle near these first, so citizens meet them
# predators without a den that live by a settlement (10 §4.6: "wolves and a fox near the town"); the others' groups by
# the settlements are the ones at the dens
PREDATORS_NEAR: dict[str, tuple[str, ...]] = {"fox": ("town",)}
NEAR_SITE_M = (200.0, 700.0)  # herbivores' homes this far from a living site (their range reaches it)
PREDATOR_NEAR_SITE_M = (600.0, 1600.0)  # predators keep a little further off (their range still reaches camp)
GROUP_SPACING_M = 500.0  # homes of two groups of one kind elsewhere on the planet
SETTLED_M = 1000.0  # a group whose home lies this close to a living site lives by it
PREDATOR_AWAY_M = 2000.0  # predators placed anywhere keep this far from settlements (10 §4.6 lists those by them)
PINNED_RANGE_M = 250.0  # a pinned herd wanders this far from its hunting ground
WATERHOLE_REACH_M = 1000.0  # a herd walks this far to its waterhole
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


def range_cells(world: SimWorld, group: AnimalGroup) -> IntArray:
    """The cells of a group's home range it picks wandering goals from (its habitat within its range)."""
    cache = world_cache(world)
    found: IntArray | None = cache.get(("range", group.kind, group.home))
    if found is not None:
        return found
    near = world.grid.positions @ world.grid.positions[group.home] >= math.cos(range_m(world, group) / world.radius_m)
    cells = np.flatnonzero(near & np.isin(world.biomes, _habitat_ids(group.kind)) & standable(world, group.kind))
    found = cells.astype(np.int64) if cells.size else np.array([group.home], dtype=np.int64)
    cache[("range", group.kind, group.home)] = found
    return found


def _cells_between(world: SimWorld, cells: IntArray, centre: Vec3, low_m: float, high_m: float) -> IntArray:
    if cells.size == 0:
        return cells
    distances = np.arccos(np.clip(world.grid.positions[cells] @ np.array(centre), -1, 1)) * world.radius_m
    kept: IntArray = cells[(distances >= low_m) & (distances <= high_m)]
    return kept


@dataclass(frozen=True)
class Pin:
    """Where a group is pinned (10-world-v1 §1.2, §4.6): a predator group at its den, a herd on a hunting ground."""

    cell: int  # the group's home
    place: str  # the den feature, hotspot or ground id


def pins(world: SimWorld, kind: str) -> tuple[Pin, ...]:
    """The pinned homes of a kind, in the world view's order: a predator's dens of its kind; a herd's hunting
    grounds (hotspots listing it, at their centre; a settlement's ground, on its habitat between NEAR_SITE_M and the
    ground's edge, the first such cell by distance). A den always pins its kind (wherever it may stand: dens lie at
    a hotspot's edge or off a road, often outside the kind's habitat); a hunting ground off the herd's habitat pins
    nobody."""
    cache = world_cache(world)
    found: tuple[Pin, ...] | None = cache.get(("pins", kind))
    if found is not None:
        return found
    ok = np.isin(world.biomes, _habitat_ids(kind)) & standable(world, kind)
    homes: list[Pin] = []
    if SPECIES[kind].predator:
        homes += [
            Pin(world.nearest_cell(den.position), den.id)
            for den in world.features
            if den.kind == "den" and den.animal == kind and standable(world, kind)[world.nearest_cell(den.position)]
        ]
    else:
        homes += [Pin(spot.cell, spot.id) for spot in world.hotspots if kind in spot.hunting and ok[spot.cell]]
        for ground in world.grounds:
            if kind not in ground.hunting:
                continue
            cells = _cells_between(world, np.flatnonzero(ok).astype(np.int64), ground.centre, NEAR_SITE_M[0],
                                   ground.radius_m)  # fmt: skip
            if cells.size:
                distances = world.grid.positions[cells] @ np.array(ground.centre)
                homes.append(Pin(int(cells[int(np.argmax(distances))]), ground.id))
    found = cache[("pins", kind)] = tuple(homes)
    return found


def pin_of(world: SimWorld, group: AnimalGroup) -> Pin | None:
    return next((pin for pin in pins(world, group.kind) if pin.cell == group.home), None)


def den_of(world: SimWorld, group: AnimalGroup) -> Vec3 | None:
    """A predator group's den, if it is pinned to one."""
    pin = pin_of(world, group)
    den = next((f for f in world.features if pin is not None and f.id == pin.place), None)
    return den.position if den is not None else None


def waterhole_of(world: SimWorld, group: AnimalGroup) -> Vec3 | None:
    """The waterhole a herd drinks at dawn and dusk, and a predator group lies in wait at by dusk (10 §4.6: the
    ambush spot): the nearest within reach of its home (WATERHOLE_REACH_M; a predator's range), else None."""
    cache = world_cache(world)
    key = ("waterhole", group.kind, group.home)
    if key not in cache:
        home = world.unit(group.home)
        reach = SPECIES[group.kind].range_m if SPECIES[group.kind].predator else WATERHOLE_REACH_M
        holes = sorted(
            (world.distance_m(home, feature.position), feature.id, feature.position)
            for feature in world.features
            if feature.kind == "waterhole"
        )
        cache[key] = holes[0][2] if holes and holes[0][0] <= reach else None
    found: Vec3 | None = cache[key]
    return found


def range_m(world: SimWorld, group: AnimalGroup) -> float:
    """How far from home a group wanders: a pinned herd stays on its ground (predators range from their dens)."""
    species = SPECIES[group.kind]
    return PINNED_RANGE_M if not species.predator and pin_of(world, group) is not None else species.range_m


def near_people(world: SimWorld, group: AnimalGroup) -> bool:
    """A group living by a settlement (pinned or settled near one): the herds people and pinned predators press."""
    return _by_people(world, world.unit(group.home), SETTLED_M)


def _by_people(world: SimWorld, unit: Vec3, within_m: float) -> bool:
    return any(world.distance_m(unit, world.places[site].centre) <= within_m for site in LIVING_SITES)


def populate(world: SimWorld, state: WorldState) -> None:
    """A new run's animals (see `place_groups`)."""
    groups, animals = place_groups(world, state.rng("fauna.place"))
    state.groups = {group.id: group for group in groups}
    state.animals = {animal.id: animal for animal in animals}
    state.next_animal = len(animals) + 1


def place_groups(world: SimWorld, rng: Rng) -> tuple[list[AnimalGroup], list[Animal]]:
    """The starting population: each kind's pinned groups first, then a herd near each living site (predators only
    where PREDATORS_NEAR says: the rest live at their dens), all of these at their cap; then the rest anywhere in
    their habitat."""
    groups: list[AnimalGroup] = []
    animals: list[Animal] = []
    for kind in sorted(SPECIES):
        species = SPECIES[kind]
        cells = habitat_cells(world, kind)
        if cells.size == 0:
            continue
        homes = [pin.cell for pin in pins(world, kind)][: species.groups]
        low, high = PREDATOR_NEAR_SITE_M if species.predator else NEAR_SITE_M
        sites = PREDATORS_NEAR.get(kind, ()) if species.predator else LIVING_SITES
        for site_id in sites:
            if len(homes) >= species.groups:
                break
            near = _cells_between(world, cells, world.places[site_id].centre, low, high)
            if near.size:
                homes.append(int(near[rng.randint(0, near.size - 1)]))
        settled = len(homes)
        while len(homes) < species.groups:
            for _ in range(PLACE_TRIES):
                cell = int(cells[rng.randint(0, cells.size - 1)])
                unit = world.unit(cell)
                spaced = all(world.distance_m(unit, world.unit(other)) >= GROUP_SPACING_M for other in homes)
                if spaced and not (species.predator and _by_people(world, unit, PREDATOR_AWAY_M)):
                    break
            homes.append(cell)
        for index, home in enumerate(homes):
            size = species.group_size[1] if index < settled else rng.randint(*species.group_size)
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
    if not can_stand(world, species, spot) or in_town_walls(world, spot, position):
        position, spot = world.unit(cell), cell
    return Animal(
        id=f"{group.kind}:{number}",
        kind=group.kind,
        group=group.id,
        position=position,
        cell=spot,
        height_m=float(terrain(world).surface_m[spot]),
        heading_deg=round(rng.random() * 360.0, 2),
        activity="swimming" if group.kind in ("fish", "shark") else "idle",
        hunger=round(rng.random() * 40.0, 2) if species.predator else 0.0,
    )


def jitter(world: SimWorld, unit: Vec3, radius_m: float, rng: Rng) -> Vec3:
    """A random point within radius_m of the unit vector (uniform on the disc, flat approximation)."""
    return step_towards(unit, rng.random() * 360.0, radius_m * math.sqrt(rng.random()), world.radius_m)
