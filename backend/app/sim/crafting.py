"""Crafting (10-world-v1 §2.3): `craft(recipe)` makes a tool or good from what the crafter carries, at its station.

A recipe (`data/recipes.yaml`) names its inputs, the wood its station burns besides (2 at the forge for iron), what it
yields, the skill it needs, the kind of station and how long it takes. Starting checks everything (the recipe, the
skill, a station within `STATION_M`, the inputs and fuel carried, room for what it makes) and takes the station's
place to work at (S1: the forge's anvil, the loom's stool, the drying rack; a free log seat round a fire pit); the
work is done when its time is up, all at once: the inputs and fuel are used up and the yield is made in one step,
or, if the crafter no longer carries them, nothing happens. Cut short, nothing is used and nothing made.

    craft ─▶ recipe? skill? station within 4 m? inputs + fuel carried? room? ─▶ a slot at the station ─▶ … minutes
          ─▶ inputs and fuel ─▶ world, yield ─▶ the crafter (one `crafted`, its item moves caused by it)

`work("weave")`, the weaver's hour at her loom, makes cloth as the cloth recipe does when she carries the reeds
(`weave`, D161).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import WORLD_DATA_DIR
from app.observability.events import Crafted, ItemLocation, JsonScalar
from app.sim import slots
from app.sim.acting import begin, item_name, settled
from app.sim.coins import number_words
from app.sim.core import SimCore
from app.sim.items import ITEMS
from app.sim.perception import normalize
from app.sim.state import ActionState, Citizen
from app.sim.vec import Vec3
from app.sim.world import SimWorld, site_unit
from app.world.town import load_town
from app.world_api.models import Craft, RecipeName

RECIPES = WORLD_DATA_DIR / "recipes.yaml"
STATION_M = 4.0  # a station is within reach this close (from its centre)
FUEL = "wood"
CLOTH = "cloth"  # the recipe `work("weave")` makes


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Recipe(_Spec):
    inputs: dict[str, int]
    fuel: int = Field(0, ge=0)
    yields: dict[str, int]
    batch: int = Field(1, ge=1)
    skill: str | None
    station: str
    minutes: int = Field(gt=0)


class StationSpec(_Spec):
    task: str | None  # its work slots' task (data/slots.yaml); None = a free seat round it
    words: str = Field(min_length=1)


class RecipesSpec(_Spec):
    recipes: dict[str, Recipe]
    stations: dict[str, StationSpec]

    @model_validator(mode="after")
    def _check(self) -> "RecipesSpec":
        if set(self.recipes) != set(get_args(RecipeName)):
            raise ValueError(f"the recipes must be the contract's: {sorted(get_args(RecipeName))}")
        for name, recipe in self.recipes.items():
            used = {**recipe.inputs, **recipe.yields}
            if unknown := sorted(set(used) - set(ITEMS)):
                raise ValueError(f"{name} names unknown items {unknown}")
            if not recipe.inputs or len(recipe.yields) != 1 or any(count < 1 for count in used.values()):
                raise ValueError(f"{name} uses up at least one item and yields one kind of item (`crafted` names one)")
            if recipe.station not in self.stations:
                raise ValueError(f"{name}: no station {recipe.station}")
        return self


@cache
def load_recipes(path: Path = RECIPES) -> RecipesSpec:
    return RecipesSpec.model_validate(yaml.safe_load(path.read_text()))


def recipe_named(words: str) -> str | None:
    """The recipe the words name: its name ("iron axe"), or the item it yields ("a length of cloth", "an iron axe")."""
    recipes = load_recipes().recipes
    name = normalize(words)
    if name in recipes:
        return name
    item = item_name(words)
    return next((recipe for recipe, spec in sorted(recipes.items()) if item in spec.yields), None)


# --- stations: the placed things crafts (and the stall) are done at ---


@dataclass(frozen=True)
class Station:
    id: str  # a town placement's id, or "<camp site>:<placement id>"
    kind: str
    centre: Vec3


def stations(world: SimWorld, kind: str) -> list[Station]:
    """Every placement of this kind, in the town and the camps."""
    found = [
        Station(placement.id, kind, world.town.to_unit(placement.x, placement.z))
        for placement in load_town().placements
        if placement.kind == kind
    ]
    found += [
        Station(f"{site.id}:{placement.id}", kind, site_unit(world.radius_m, site, placement.x, placement.z))
        for site in world.sites
        if site.kind == "camp"
        for placement in site.placements
        if placement.kind == kind
    ]
    return found


def station_in_reach(core: SimCore, citizen: Citizen, kind: str, reach_m: float = STATION_M) -> Station | None:
    near = [(core.distance_m(citizen.position, s.centre), s.id, s) for s in stations(core.world, kind)]
    within = [option for option in near if option[0] <= reach_m]
    return min(within)[2] if within else None


# --- crafting ---


def start_craft(core: SimCore, citizen: Citizen, action: Craft) -> int:
    name = recipe_named(action.recipe)
    if name is None:
        return settled(core, citizen, "craft", "failed", "You don't know how to make that.")
    recipe = load_recipes().recipes[name]
    made = _made_words(recipe.yields)
    if recipe.skill is not None and recipe.skill not in citizen.skills:
        return settled(core, citizen, "craft", "failed", f"You don't know how to make {made}.")
    station_spec = load_recipes().stations[recipe.station]
    station = station_in_reach(core, citizen, recipe.station)
    if station is None:
        return settled(core, citizen, "craft", "failed", f"You need {station_spec.words} within reach to make {made}.")
    rounds = _rounds(recipe, citizen.inventory)
    if rounds == 0:
        need = [count_words(item, count) for item, count in sorted(_needs(recipe, 1).items())]
        return settled(core, citizen, "craft", "failed", f"To make {made} you need {_join(need)}.")
    if not _fits(core, citizen, recipe, rounds):
        return settled(core, citizen, "craft", "failed", f"You couldn't carry {made} as well.")
    args: dict[str, JsonScalar] = {"recipe": name, "station": station.id}
    if station_spec.task is None:
        seat = slots.take_seat(core, citizen)
        if seat is not None:
            args |= slots.spot_args(seat)
    else:
        spot = slots.take_work_slot(core, citizen, station_spec.task, (station.centre, STATION_M))
        if spot == "all taken":
            text = f"Someone is working at {station_spec.words}; there's no room for you."
            return settled(core, citizen, "craft", "failed", text)
        if isinstance(spot, slots.Slot):
            args |= slots.spot_args(spot)
    craft = begin(core, citizen, "craft", f"making {_made_words(recipe.yields, rounds)}", args)
    craft.item, craft.amount, craft.until_tick = name, rounds, core.state.tick + recipe.minutes
    return craft.number


def finish_craft(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    """Time is up: use the inputs and fuel and make the yield in one step, as many rounds as were started and are
    still carried (none: nothing happens)."""
    name = str(action.item)
    recipe = load_recipes().recipes[name]
    rounds = min(action.amount, _rounds(recipe, citizen.inventory))
    if rounds == 0:
        core.end_action(citizen, "failed", "You no longer have what it takes.")
        return
    _make(core, citizen, name, rounds, str(action.args.get("station")))
    core.end_action(citizen, "done", f"You make {_made_words(recipe.yields, rounds)}.")


def _make(core: SimCore, citizen: Citizen, name: str, rounds: int, station: str | None) -> None:
    """Use up `rounds` of the recipe's inputs and fuel and make its yield, in one step (one `crafted`)."""
    recipe = load_recipes().recipes[name]
    ((item, each),) = recipe.yields.items()
    seq = core.emit("crafted", Crafted(recipe=name, item=item, count=each * rounds, station=station), actor=citizen)
    hand, world = ItemLocation(kind="inventory", id=citizen.id), ItemLocation(kind="world")
    for used, used_count in sorted(_needs(recipe, rounds).items()):
        citizen.inventory[used] -= used_count
        if citizen.inventory[used] == 0:
            del citizen.inventory[used]
        core.item_moved(citizen, used, used_count, hand, world, cause_seq=seq)
    citizen.inventory[item] = citizen.inventory.get(item, 0) + each * rounds
    core.item_moved(citizen, item, each * rounds, world, hand, cause_seq=seq)


def weave(core: SimCore, citizen: Citizen, action: ActionState) -> str:
    """`work("weave")`'s finisher: an hour at the loom makes a length of cloth from two reeds carried, as the cloth
    recipe does; without them (or room for the cloth) the hour goes on the loom itself (D161)."""
    recipe = load_recipes().recipes[CLOTH]
    if _rounds(recipe, citizen.inventory) == 0:
        return "You mend the loom and set up the warp; there are no reeds to weave."
    if not _fits(core, citizen, recipe, 1):
        return "Your hands are full; you leave the warp on the loom."
    loom = str(action.args.get("slot", "")).partition("#")[0] or None
    _make(core, citizen, CLOTH, 1, loom)
    return f"You weave {_made_words(recipe.yields)}."


def _needs(recipe: Recipe, rounds: int) -> dict[str, int]:
    """What `rounds` of the recipe use up: its inputs and the station's fuel."""
    needs = {item: count * rounds for item, count in recipe.inputs.items()}
    if recipe.fuel:
        needs[FUEL] = needs.get(FUEL, 0) + recipe.fuel * rounds
    return needs


def _rounds(recipe: Recipe, inventory: Mapping[str, int]) -> int:
    """How many rounds (up to the batch) what is carried makes."""
    return min(recipe.batch, *(inventory.get(item, 0) // count for item, count in _needs(recipe, 1).items()))


def _fits(core: SimCore, citizen: Citizen, recipe: Recipe, rounds: int) -> bool:
    used = sum(ITEMS[item].weight_kg * count for item, count in _needs(recipe, rounds).items())
    made = sum(ITEMS[item].weight_kg * count * rounds for item, count in recipe.yields.items())
    return core.carried_kg(citizen) - used + made <= citizen.traits.carry_kg + 1e-9


def count_words(item: str, count: int) -> str:
    """A counted amount, as someone gathering what a recipe takes says it: "a flint nodule", "two hides", "three
    measures of iron sand"."""
    kind = ITEMS[item]
    if count == 1:
        return kind.one
    if kind.mass:
        unit, _, of = kind.one.partition(" ")[2].partition(" of ")
        return f"{number_words(count)} {unit}s of {of}"
    return f"{number_words(count)} {kind.plural or kind.name}"


def _made_words(yields: Mapping[str, int], rounds: int = 1) -> str:
    ((item, each),) = yields.items()
    return count_words(item, each * rounds)


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
