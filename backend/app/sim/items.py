"""Item kinds and the wild plant resources counted per cell."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.sim.coins import coin_words
from app.world.spec import BIOME_NAMES

Tool = Literal["spear", "axe", "sickle"]


@dataclass(frozen=True)
class ItemKind:
    name: str  # the item's name: plural as citizens say it ("berries"), the mass noun ("rice") or a tool ("iron axe")
    one: str  # one of them ("a berry", "a measure of rice")
    weight_kg: float
    food: float  # hunger removed per piece eaten; 0 = not food
    mass: bool = False  # counted in measures ("some rice"), not pieces ("a handful of berries")
    raw: bool = False  # better cooked: eaten by a fire it is roasted (more filling), raw it can make you sick
    plural: str = ""  # several pieces, when the name isn't already plural ("hides"); defaults to the name
    tool: Tool | None = None  # what it is used as; one item kind per material keeps stacks fungible (§2.3)


ITEMS: dict[str, ItemKind] = {
    "berries": ItemKind("berries", "a berry", 0.05, 2.0),
    "roots": ItemKind("roots", "a root", 0.2, 6.0),
    "nuts": ItemKind("nuts", "a nut", 0.03, 3.0),
    "reeds": ItemKind("reeds", "a reed", 0.1, 0.0),
    "wood": ItemKind("wood", "a piece of wood", 1.0, 0.0, mass=True),
    "rice": ItemKind("rice", "a measure of rice", 0.2, 10.0, mass=True),
    "dried meat": ItemKind("dried meat", "a strip of dried meat", 0.1, 8.0, mass=True),
    "meat": ItemKind("meat", "a piece of meat", 0.5, 10.0, mass=True, raw=True),
    "fish": ItemKind("fish", "a fish", 0.4, 6.0, raw=True),
    "hide": ItemKind("hide", "a hide", 2.0, 0.0, plural="hides"),
    # World v1 goods (10-world-v1 §2.1-2.2): money, minerals, woven goods and tools by material
    "coins": ItemKind("coins", "a coin", 0.004, 0.0),
    "flint": ItemKind("flint", "a flint nodule", 0.5, 0.0, plural="flint nodules"),
    "obsidian": ItemKind("obsidian", "an obsidian shard", 0.3, 0.0, plural="obsidian shards"),
    "iron sand": ItemKind("iron sand", "a measure of iron sand", 1.0, 0.0, mass=True),
    "gold": ItemKind("gold", "a grain of gold", 0.01, 0.0, mass=True),
    "cloth": ItemKind("cloth", "a length of cloth", 1.0, 0.0, mass=True),
    "pack": ItemKind("pack", "a pack", 1.5, 0.0, plural="packs"),
    "flint spear": ItemKind("flint spear", "a flint spear", 1.5, 0.0, plural="flint spears", tool="spear"),
    "obsidian spear": ItemKind("obsidian spear", "an obsidian spear", 1.5, 0.0, plural="obsidian spears", tool="spear"),
    "iron spear": ItemKind("iron spear", "an iron spear", 1.5, 0.0, plural="iron spears", tool="spear"),
    "stone axe": ItemKind("stone axe", "a stone axe", 1.2, 0.0, plural="stone axes", tool="axe"),
    "iron axe": ItemKind("iron axe", "an iron axe", 1.2, 0.0, plural="iron axes", tool="axe"),
    "sickle": ItemKind("sickle", "a sickle", 0.6, 0.0, plural="sickles", tool="sickle"),
}
# what an item is called in a phrase of one or two words: its name, its plural and one of it without the article
# ("berry", "coin", "hides", "iron spears", "flint nodule"); longer phrases ("a piece of wood") go by the name
ITEM_WORDS: dict[str, str] = {
    phrase: kind.name
    for kind in ITEMS.values()
    for phrase in (kind.name, kind.plural, kind.one.partition(" ")[2])
    if phrase and len(phrase.split()) <= 2
}
# the better tool first: someone carrying several uses the best (spears: hunt × 1.4 stone, × 1.6 obsidian and iron)
TOOL_ORDER: dict[Tool, tuple[str, ...]] = {
    "spear": ("iron spear", "obsidian spear", "flint spear"),
    "axe": ("iron axe", "stone axe"),
    "sickle": ("sickle",),
}
if {item for items in TOOL_ORDER.values() for item in items} != {k.name for k in ITEMS.values() if k.tool}:
    raise ValueError("every tool needs its place in TOOL_ORDER")
TOOL_WORDS: dict[str, Tool] = {word: tool for tool in TOOL_ORDER for word in (tool, f"{tool}s")}  # "spear", "axes"


def tool_in(inventory: Mapping[str, int], tool: Tool) -> str | None:
    """The best item of this tool someone carries ("iron spear"), or None."""
    return next((item for item in TOOL_ORDER[tool] if inventory.get(item, 0) > 0), None)


RESOURCES: tuple[str, ...] = ("berries", "roots", "nuts", "reeds", "wood", "fish")  # column order of the counters
GATHERED = frozenset({"berries", "roots", "nuts", "reeds", "wood"})  # picked by hand; fish are caught (`fish()`)
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
    "shallow_ocean": {"fish": 30},
    "lake": {"fish": 20},
}
RIVER_REEDS = 12
RIVER_FISH = 8

# Game days a cell takes to grow back from bare to full (02-simulation: berries ~3, roots ~5, nuts ~7).
REGROW_DAYS: dict[str, float] = {"berries": 3.0, "roots": 5.0, "nuts": 7.0, "reeds": 4.0, "wood": 6.0, "fish": 4.0}

_UNKNOWN = set(RESOURCE_CAPS) - set(BIOME_NAMES)
if _UNKNOWN:
    raise ValueError(f"resource caps name unknown biomes: {sorted(_UNKNOWN)}")
_BAD_ITEMS = {item for caps in RESOURCE_CAPS.values() for item in caps} - set(RESOURCES)
if _BAD_ITEMS:
    raise ValueError(f"resource caps name unknown resources: {sorted(_BAD_ITEMS)}")
if set(REGROW_DAYS) != set(RESOURCES):
    raise ValueError("every resource needs a regrowth time")


def amount_words(count: int, kind: ItemKind) -> str:
    """How much of an item someone holding it would say they have (coins are counted: §2.1)."""
    if kind.name == "coins":
        return coin_words(count)
    many = kind.plural or kind.name
    if count <= 0:
        return f"no {many}"
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
        return f"a few {many}"
    if count <= 12:
        return f"a handful of {many}"
    if count <= 40:
        return f"plenty of {many}"
    return f"a great many {many}"
