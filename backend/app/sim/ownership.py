"""Ownership and theft (10-world-v1 §2.6): every store has an owner, and taking from someone else's is stealing.

- **Owners** are households (the home id their residents share) or a band (its group): a household chest
  (`<home>-chest`) is its home's, the treasury (`castle-keep-chest`) and the granary (every storehouse) are the lord's
  household's, the market stall the merchant's, the field racks each farm household's, a camp's stores its band's.
  A store nobody owns (the paddies' field store) is free to take from.
- **Grants**: a household may take a few measures of rice a day from the granary without owning it (the temple's 15,
  and the wave-2 rations of the households that will buy their food at the stall once they can, D156).
- **Theft**: taking from a store you don't own (or past your grant) by `pick_up` or by eating from it **succeeds** and
  emits one `stole` with the thief as actor and the witnesses who had them in view; it causes the `item_moved`.
- **Noticing**: the owners notice what went missing the next time one of them uses the store ("Some of your rice is
  gone."), without learning who took it.

The system `ownership` keeps what the grants gave today and what is missing from each store since its owners last
used it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Protocol, cast

from pydantic import JsonValue, TypeAdapter

from app.observability.events import ItemLocation, Stole
from app.sim import society
from app.sim.clock import DAY_MINUTES, game_minute
from app.sim.core import SimCore
from app.sim.state import Citizen, Region, System
from app.sim.vec import Vec3
from app.sim.wear import store_spot
from app.sim.world import SimWorld
from app.world.spec import load_world_spec
from app.world.town import load_town

KEEP = "castle-keep"  # the lord's household: the treasury and the granary are theirs
CHEST = "-chest"  # a household chest's id is its home's id and this
REACH_M = 6.0  # a store is within reach this far from its door (a chest: its home's door), or from where it stands
GRANARY_KIND = "storehouse"  # every storehouse is the lord's granary
CAMP_GROUPS: Mapping[str, Region] = {"band_a_camp": "band_a", "band_b_camp": "band_b"}
PLACED_OWNERS: Mapping[str, str] = {  # town stores that are no household's chest: their owning household
    "market-stall": "main-e-2",  # the merchant's
    "field-rack-1": "farmhouse-1",
    "field-rack-2": "farmhouse-2",
    "farm-rack": "farmhouse-2",  # beside the elder farmer's house
}
GRANTS: Mapping[str, int] = {  # household -> measures of rice a day it may take from the granary (D156)
    "temple-hall": 15,  # the temple's grant (§2.6)
    # wave-2 rations until these households buy their food at the stall (BR1 drops them, D156)
    "cross-s-1": 12,  # the night watchman
    "main-e-2": 12,  # the merchant
    "cross-n-8": 12,  # the digger
    "cross-n-9": 12,  # the smith
}
GRANT_ITEM = "rice"
STORE_WORDS: Mapping[str, str] = {
    "storehouse": "the storehouse",
    "chest": "the chest",
    "market_stall": "the stall",
    "drying_rack": "the rack",
}


@dataclass
class Holdings:
    day: int = 0  # the town day `granted` counts
    granted: dict[str, int] = field(default_factory=dict)  # household -> granary rice its grant gave today
    missing: dict[str, dict[str, int]] = field(default_factory=dict)  # store -> item -> taken by others unnoticed


_BLOCK = TypeAdapter(Holdings)


def _dump(holdings: Holdings) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(holdings, mode="json"))


def _load(data: JsonValue) -> Holdings:
    return _BLOCK.validate_python(data)


OWNERSHIP = System[Holdings]("ownership", 1, new=lambda _world: Holdings(), dump=_dump, load=_load)


def is_granary(world: SimWorld, store_id: str) -> bool:
    structure = world.structures.get(store_id)
    return structure is not None and structure.kind == GRANARY_KIND


def owner_of(world: SimWorld, store_id: str) -> str | None:
    """The household (a home id) or band (a group) a store belongs to; None for a store nobody owns."""
    if store_id.endswith(CHEST):
        return store_id.removesuffix(CHEST)
    if is_granary(world, store_id):
        return KEEP
    site, _, _ = store_id.rpartition(":")
    if site:
        return CAMP_GROUPS.get(site)
    return PLACED_OWNERS.get(store_id)


class Household(Protocol):
    """Whoever can own a store: a home's household and a group (a live citizen, or a replayed one)."""

    @property
    def home(self) -> str | None: ...

    @property
    def region(self) -> Region: ...


def owns(world: SimWorld, citizen: Household, store_id: str) -> bool:
    owner = owner_of(world, store_id)
    return owner is not None and owner in (citizen.home, citizen.region)


def fed_by_granary(citizen: Citizen) -> bool:
    """The lord's household eats from the granary; so do the households it grants rice to."""
    return citizen.home == KEEP or citizen.home in GRANTS


def free_to_take(core: SimCore, citizen: Citizen, store_id: str, item: str) -> int | None:
    """How much of `item` the citizen may take from the store without stealing: None = any amount (theirs, or
    nobody's), else what is left of their household's grant today (0 for anyone else's store)."""
    if owner_of(core.world, store_id) is None or owns(core.world, citizen, store_id):
        return None
    home = citizen.home
    if item != GRANT_ITEM or not is_granary(core.world, store_id) or home is None or home not in GRANTS:
        return 0
    return max(0, GRANTS[home] - _granted(core).get(home, 0))


def took(core: SimCore, citizen: Citizen, store_id: str, item: str, count: int) -> int | None:
    """The citizen takes `count` of `item` from a store (the caller moves the goods and emits their `item_moved`,
    caused by the seq returned): what their grant covers is counted, the rest of a store they don't own is stolen,
    one `stole` for it. Returns the `stole` seq, or None if nothing was stolen."""
    free = free_to_take(core, citizen, store_id, item)
    if free is None:
        return None
    granted = min(free, count)
    if granted:
        holdings = _granted(core)
        holdings[str(citizen.home)] = holdings.get(str(citizen.home), 0) + granted
    stolen = count - granted
    if stolen <= 0:
        return None
    owner = str(owner_of(core.world, store_id))
    missing = OWNERSHIP.of(core.state).missing.setdefault(store_id, {})
    missing[item] = missing.get(item, 0) + stolen
    payload = Stole(owner=owner, store=store_id, item=item, count=stolen, witnesses=society.witnesses(core, citizen.id))
    return core.emit("stole", payload, actor=citizen)


def notice(core: SimCore, citizen: Citizen, store_id: str) -> str:
    """An owner using their store notices what others took since they last did (" Some of your rice is gone."), or
    nothing ("")."""
    holdings = OWNERSHIP.of(core.state)
    if not owns(core.world, citizen, store_id) or store_id not in holdings.missing:
        return ""
    items = sorted(holdings.missing.pop(store_id))
    names = " and ".join([", ".join(items[:-1]), items[-1]] if len(items) > 1 else items)
    plural = len(items) > 1 or items[0].endswith("s")  # "coins are", "rice is"
    return f" Some of your {names} {'are' if plural else 'is'} gone."


def _granted(core: SimCore) -> dict[str, int]:
    """Today's grant tally (a new town day starts it afresh)."""
    holdings = OWNERSHIP.of(core.state)
    today = game_minute(core.state.tick) // DAY_MINUTES
    if holdings.day != today:
        holdings.day, holdings.granted = today, {}
    return holdings.granted


def reach_point(core: SimCore, store_id: str) -> Vec3:
    """Where a store is reached from: a storehouse's door, a household chest's home's door (§2.6: within 6 m of
    it), else where the store stands."""
    world = core.world
    structure = world.structures.get(store_id)
    if structure is not None:
        return structure.door
    home = world.structures.get(store_id.removesuffix(CHEST)) if store_id.endswith(CHEST) else None
    return home.door if home is not None else store_spot(world, store_id)


def store_words(store_id: str) -> str:
    """What the citizen calls a store ("the chest", "the storehouse")."""
    return STORE_WORDS.get(_store_kinds().get(store_id, ""), "the store")


@cache
def _store_kinds() -> dict[str, str]:
    """Store id -> its placement kind: town placements by their own id, camp ones as "<camp site>:<placement id>"."""
    kinds = {placement.id: placement.kind for placement in load_town().placements}
    for site in load_world_spec().sites:
        kinds |= {f"{site.id}:{placement.id}": placement.kind for placement in site.placements}
    return kinds


def item_location(store_id: str) -> ItemLocation:
    return ItemLocation(kind="store", id=store_id)
