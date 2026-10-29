"""Wear and spoilage (10-world-v1 §2.4): food goes off at each holder's local dawn, tools break with use.

- Spoilage: at a holder's local dawn (a living citizen's inventory, or a store) each spoiling food loses its share
  of the stock, rounded up (`data/economy.yaml`); one `spoiled` per holder per dawn.
- Breakage: a tool breaks per use with its chance (`use_tool`, called by whatever uses it: a hunt strike, a felling,
  a harvest session); a carried pack at each dawn. No per-piece wear state: every use is a fresh roll. A broken item
  is gone (`tool_broke`).

Gone items leave through `item_moved` to the `world`, caused by the `spoiled` or `tool_broke` event, so replay keeps
every inventory and store exact. Wear keeps no state of its own, so it registers hooks but no system.
"""

import math
from collections.abc import Callable, Mapping

from app.observability.events import ItemLocation, Spoiled, ToolBroke
from app.sim.core import SimCore
from app.sim.economy import load_economy
from app.sim.state import Citizen
from app.sim.vec import Vec3
from app.sim.world import SimWorld, site_unit
from app.world.town import load_town

LocalTest = Callable[[Vec3], bool]  # app.sim.systems' (which registers these hooks, so can't be imported here)


def spoilage(stock: Mapping[str, int]) -> dict[str, int]:
    """What a holder's stock loses at a dawn: each spoiling item's share of it, rounded up."""
    shares = load_economy().spoilage
    return {item: math.ceil(shares[item] * count) for item, count in sorted(stock.items()) if item in shares and count}


def store_spot(world: SimWorld, store_id: str) -> Vec3:
    """Where a store stands: a storehouse or camp structure, a place (the paddies' field store), a town placement
    (chests, the market stall, the field racks) or a camp one ("<camp site>:<placement id>")."""
    if store_id in world.structures:
        return world.structures[store_id].centre
    if store_id in world.places:
        return world.places[store_id].centre
    site_id, _, placement_id = store_id.rpartition(":")
    if site_id:
        for site in world.sites:
            for placement in site.placements:
                if (site.id, placement.id) == (site_id, placement_id):
                    return site_unit(world.radius_m, site, placement.x, placement.z)
    else:
        for town_placement in load_town().placements:
            if town_placement.id == store_id:
                return world.town.to_unit(town_placement.x, town_placement.z)
    raise ValueError(f"store {store_id} stands nowhere")


def spoil_at_dawn(core: SimCore, now: LocalTest) -> None:
    """Dawn hook: spoiling food in inventories and stores whose dawn it is goes off."""
    for citizen in core.living():
        lost = spoilage(citizen.inventory)
        if lost and now(citizen.position):
            _spoil(core, citizen.inventory, lost, citizen, ItemLocation(kind="inventory", id=citizen.id))
    for store_id, stock in sorted(core.state.stores.items()):
        lost = spoilage(stock)
        if lost and now(store_spot(core.world, store_id)):
            _spoil(core, stock, lost, None, ItemLocation(kind="store", id=store_id))


def _spoil(
    core: SimCore, stock: dict[str, int], lost: dict[str, int], holder: Citizen | None, where: ItemLocation
) -> None:
    payload = Spoiled(holder=str(where.id), holder_kind="inventory" if holder else "store", items=lost)
    seq = core.emit("spoiled", payload, actor=holder)
    for item, count in lost.items():
        _take(stock, item, count)
        core.item_moved(holder, item, count, where, ItemLocation(kind="world"), cause_seq=seq)


def wear_packs_at_dawn(core: SimCore, now: LocalTest) -> None:
    """Dawn hook: each pack a living citizen carries may break (it wears out on the road, §2.4)."""
    chance = load_economy().breakage["pack"].chance
    for citizen in core.living():
        packs = citizen.inventory.get("pack", 0)
        if not packs or not now(citizen.position):
            continue
        rng = core.state.rng("wear.pack")
        for _ in range(packs):
            if rng.random() < chance:
                _break(core, citizen, "pack", None)


def use_tool(core: SimCore, citizen: Citizen, item: str, cause_seq: int | None = None) -> bool:
    """`citizen` used one `item` (a spear's strike, an axe's felling, a sickle's harvest): it may break, by its chance
    per use. True if it broke (it is gone from their inventory)."""
    if citizen.inventory.get(item, 0) <= 0:
        raise ValueError(f"{citizen.id} has no {item} to use")
    if core.state.rng("wear.breakage").random() >= load_economy().breakage[item].chance:
        return False
    _break(core, citizen, item, cause_seq)
    return True


def _break(core: SimCore, citizen: Citizen, item: str, cause_seq: int | None) -> None:
    use = load_economy().breakage[item].use
    seq = core.emit("tool_broke", ToolBroke(item=item, use=use), actor=citizen, cause_seq=cause_seq)
    _take(citizen.inventory, item, 1)
    where = ItemLocation(kind="inventory", id=citizen.id)
    core.item_moved(citizen, item, 1, where, ItemLocation(kind="world"), cause_seq=seq)


def _take(stock: dict[str, int], item: str, count: int) -> None:
    stock[item] -= count
    if stock[item] == 0:
        del stock[item]
