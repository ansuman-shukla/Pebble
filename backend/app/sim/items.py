"""Item kinds and the wild plant resources counted per cell."""

from dataclasses import dataclass

from app.world.spec import BIOME_NAMES


@dataclass(frozen=True)
class ItemKind:
    name: str  # plural as citizens say it ("berries"), or the mass noun ("rice")
    one: str  # one of them ("a berry", "a measure of rice")
    weight_kg: float
    food: float  # hunger removed per piece eaten; 0 = not food
    mass: bool = False  # counted in measures ("some rice"), not pieces ("a handful of berries")


ITEMS: dict[str, ItemKind] = {
    "berries": ItemKind("berries", "a berry", 0.05, 2.0),
    "roots": ItemKind("roots", "a root", 0.2, 6.0),
    "nuts": ItemKind("nuts", "a nut", 0.03, 3.0),
    "reeds": ItemKind("reeds", "a reed", 0.1, 0.0),
    "wood": ItemKind("wood", "a piece of wood", 1.0, 0.0, mass=True),
    "rice": ItemKind("rice", "a measure of rice", 0.2, 10.0, mass=True),
    "dried meat": ItemKind("dried meat", "a strip of dried meat", 0.1, 8.0, mass=True),
}

RESOURCES: tuple[str, ...] = ("berries", "roots", "nuts", "reeds", "wood")  # column order of the per-cell counters
RESOURCE_INDEX = {name: index for index, name in enumerate(RESOURCES)}

# Most of each wild resource a cell holds, by biome (cells are ~40 m across). Rivers through these biomes also grow
# RIVER_REEDS reeds on their cells.
RESOURCE_CAPS: dict[str, dict[str, int]] = {
    "grassland": {"berries": 10, "roots": 20, "wood": 6},
    "broadleaf_forest": {"berries": 40, "roots": 10, "nuts": 25, "wood": 40},
    "taiga": {"berries": 12, "nuts": 20, "wood": 40},
    "wetland": {"roots": 15, "reeds": 40},
    "savanna": {"roots": 15, "wood": 4},
    "tundra": {"berries": 6},
    "hills": {"roots": 6, "wood": 4},
}
RIVER_REEDS = 12

# Game days a cell takes to grow back from bare to full (02-simulation: berries ~3, roots ~5, nuts ~7).
REGROW_DAYS: dict[str, float] = {"berries": 3.0, "roots": 5.0, "nuts": 7.0, "reeds": 4.0, "wood": 6.0}

_UNKNOWN = set(RESOURCE_CAPS) - set(BIOME_NAMES)
if _UNKNOWN:
    raise ValueError(f"resource caps name unknown biomes: {sorted(_UNKNOWN)}")
_BAD_ITEMS = {item for caps in RESOURCE_CAPS.values() for item in caps} - set(RESOURCES)
if _BAD_ITEMS:
    raise ValueError(f"resource caps name unknown resources: {sorted(_BAD_ITEMS)}")
if set(REGROW_DAYS) != set(RESOURCES):
    raise ValueError("every resource needs a regrowth time")


def amount_words(count: int, kind: ItemKind) -> str:
    """How much of an item someone holding it would say they have."""
    if count <= 0:
        return f"no {kind.name}"
    if count == 1:
        return kind.one
    if kind.mass:
        if count <= 3:
            return f"a little {kind.name}"
        if count <= 12:
            return f"some {kind.name}"
        if count <= 40:
            return f"plenty of {kind.name}"
        return f"a great deal of {kind.name}"
    if count <= 3:
        return f"a few {kind.name}"
    if count <= 12:
        return f"a handful of {kind.name}"
    if count <= 40:
        return f"plenty of {kind.name}"
    return f"a great many {kind.name}"
