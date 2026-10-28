"""Item kinds and the wild plant resources counted per cell."""

from dataclasses import dataclass

from app.world.spec import BIOME_NAMES


@dataclass(frozen=True)
class ItemKind:
    name: str  # plural as citizens say it ("berries")
    one: str  # one of them ("a berry")
    weight_kg: float
    food: float  # hunger removed per piece eaten; 0 = not food


ITEMS: dict[str, ItemKind] = {
    "berries": ItemKind("berries", "a berry", 0.05, 2.0),
    "roots": ItemKind("roots", "a root", 0.2, 6.0),
    "nuts": ItemKind("nuts", "a nut", 0.03, 3.0),
}

RESOURCES: tuple[str, ...] = ("berries", "roots", "nuts")  # column order of the per-cell counters
RESOURCE_INDEX = {name: index for index, name in enumerate(RESOURCES)}

# Most of each wild resource a cell holds, by biome (cells are ~40 m across). Regrowth arrives with M6.
RESOURCE_CAPS: dict[str, dict[str, int]] = {
    "grassland": {"berries": 10, "roots": 20},
    "broadleaf_forest": {"berries": 40, "roots": 10, "nuts": 25},
    "taiga": {"berries": 12, "nuts": 20},
    "wetland": {"roots": 15},
    "savanna": {"roots": 15},
    "tundra": {"berries": 6},
    "hills": {"roots": 6},
}

_UNKNOWN = set(RESOURCE_CAPS) - set(BIOME_NAMES)
if _UNKNOWN:
    raise ValueError(f"resource caps name unknown biomes: {sorted(_UNKNOWN)}")
_BAD_ITEMS = {item for caps in RESOURCE_CAPS.values() for item in caps} - set(RESOURCES)
if _BAD_ITEMS:
    raise ValueError(f"resource caps name unknown resources: {sorted(_BAD_ITEMS)}")


def amount_words(count: int, kind: ItemKind) -> str:
    """How much of an item someone holding it would say they have."""
    if count <= 0:
        return f"no {kind.name}"
    if count == 1:
        return kind.one
    if count <= 3:
        return f"a few {kind.name}"
    if count <= 12:
        return f"a handful of {kind.name}"
    if count <= 40:
        return f"plenty of {kind.name}"
    return f"a great many {kind.name}"
