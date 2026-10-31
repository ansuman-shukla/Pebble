"""Gathering, eating and drinking (03): durative actions that take a while in one spot and change the body or the
inventory when done; an eat or drink cut short keeps what it achieved so far.
"""

import math

from app.observability.events import ItemLocation, ResourceChanged
from app.sim import fire, ownership
from app.sim.acting import begin, item_name, settled, stack_in_reach
from app.sim.core import REACH_M, SimCore
from app.sim.ecology import schedule_regrowth
from app.sim.exchange import store_in_reach
from app.sim.items import GATHERED, ITEMS, RESOURCE_INDEX, amount_words
from app.sim.state import ActionState, Citizen
from app.world_api.models import Drink, Eat, Gather

GATHER_MINUTES = 20
GATHER_YIELD = (3, 6)
DRINK_MINUTES = 3
COOKED = 1.5  # raw meat or fish eaten beside a fire is roasted: this much more filling
RAW_SICK_CHANCE = 0.3
RAW_SICKNESS = (6.0, 14.0)


def start_gather(core: SimCore, citizen: Citizen, action: Gather) -> int:
    resource = item_name(action.resource)
    if resource == "fish":
        return settled(core, citizen, "gather", "failed", "Fish have to be caught; try fishing.")
    if resource is None or resource not in GATHERED:
        return settled(core, citizen, "gather", "failed", f"You can't gather {action.resource} here.")
    if core.state.resources[citizen.cell, RESOURCE_INDEX[resource]] == 0:
        return settled(core, citizen, "gather", "failed", f"There are no {resource} within reach.")
    if core.room_for(citizen, resource) == 0:
        return settled(core, citizen, "gather", "failed", "You can't carry any more.")
    gather = begin(core, citizen, "gather", resource, {"resource": resource})
    gather.item, gather.until_tick = resource, core.state.tick + GATHER_MINUTES
    return gather.number


def start_eat(core: SimCore, citizen: Citizen, action: Eat) -> int:
    item = item_name(action.item)
    if item is None or ITEMS[item].food <= 0:
        return settled(core, citizen, "eat", "failed", "You can't eat that.")
    stack_id = store_id = None
    available = citizen.inventory.get(item, 0)
    if available == 0:
        stack_id = stack_in_reach(core, citizen, item)
        store_id = None if stack_id is not None else store_in_reach(core, citizen, item)
        if stack_id is not None:
            available = core.state.ground[stack_id].count
        elif store_id is not None:
            available = core.state.stores[store_id][item]
        else:
            return settled(core, citizen, "eat", "failed", f"You have no {item}, and there are none within reach.")
    pieces = max(1, min(available, math.ceil(citizen.body.hunger / ITEMS[item].food)))
    eat = begin(core, citizen, "eat", item, {"item": item})
    eat.item, eat.amount, eat.target_id, eat.until_tick = item, pieces, stack_id, core.state.tick + pieces
    eat.store_id = store_id
    return eat.number


def water_within_reach(core: SimCore, citizen: Citizen) -> tuple[str, str] | None:
    """("fresh" | "salt", what you drink from) for the water within reach, if any."""
    world = core.world
    for structure in world.structures.values():
        if structure.kind == "well" and core.distance_m(citizen.position, structure.centre) <= REACH_M + 1.5:
            return "fresh", "the well"
    if world.town_point(citizen.position) is not None:
        return None
    if world.river[citizen.cell]:
        return "fresh", "the river"
    around = [world.biome(other) for other in world.neighbours[citizen.cell]]
    if "lake" in around:
        return "fresh", "the lake"
    if "shallow_ocean" in around or "deep_ocean" in around:
        return "salt", "the sea"
    return None


def start_drink(core: SimCore, citizen: Citizen, action: Drink) -> int:
    water = water_within_reach(core, citizen)
    if water is None:
        return settled(core, citizen, action.action, "failed", "There's no water within reach.")
    kind, source = water
    if kind == "salt":
        return settled(core, citizen, action.action, "failed", "The water here is salty; you spit it out.")
    drink = begin(core, citizen, "drink", source, {"source": source})
    drink.until_tick = core.state.tick + DRINK_MINUTES
    return drink.number


def finish_gather(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    resource = action.item
    if resource is None:
        raise ValueError("a gather action needs a resource")
    column = RESOURCE_INDEX[resource]
    cell = citizen.cell
    before = int(core.state.resources[cell, column])
    room = core.room_for(citizen, resource)
    count = min(core.state.rng("doing.gather").randint(*GATHER_YIELD), before, room)
    if count == 0:
        core.end_action(
            citizen, "failed", "You can't carry any more." if before else "You find nothing left to gather."
        )
        return
    core.state.resources[cell, column] = before - count
    schedule_regrowth(core, cell, resource)
    seq = core.emit(
        "resource_changed",
        ResourceChanged(cell=cell, resource=resource, before=before, after=before - count),
        actor=citizen,
    )
    citizen.inventory[resource] = citizen.inventory.get(resource, 0) + count
    core.item_moved(
        citizen,
        resource,
        count,
        ItemLocation(kind="resource", cell=cell),
        ItemLocation(kind="inventory", id=citizen.id),
        cause_seq=seq,
    )
    core.end_action(citizen, "done", f"You gather {amount_words(count, ITEMS[resource])}.")


def finish_eat(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    text = _eat(core, citizen, action, action.amount)
    if citizen.body.alive:  # raw food can kill, and dying has ended the action
        core.end_action(citizen, "done" if text else "failed", text or "There's nothing left to eat.")


def finish_drink(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    _drink(citizen, 1.0)
    core.end_action(citizen, "done", f"You drink from {action.label} until you are no longer thirsty.")


def _eat(core: SimCore, citizen: Citizen, action: ActionState, pieces: int) -> str | None:
    """Eat up to `pieces` of the action's item; the result text, or None if there was nothing left."""
    item = action.item
    if item is None:
        raise ValueError("an eat action needs an item")
    stack = core.state.ground.get(action.target_id) if action.target_id is not None else None
    store = core.state.stores.get(action.store_id, {}) if action.store_id is not None else None
    if stack is not None:
        available = stack.count
    elif store is not None:
        available = store.get(item, 0)
    else:
        available = citizen.inventory.get(item, 0)
    eaten = min(pieces, available)
    if eaten <= 0:
        return None
    stole = None
    if store is not None:
        stole = ownership.took(core, citizen, str(action.store_id), item, eaten)  # someone else's: stolen (§2.6)
        store[item] -= eaten
        if store[item] == 0:
            del store[item]
        source = ItemLocation(kind="store", id=action.store_id)
    elif stack is not None:
        stack.count -= eaten
        if stack.count == 0:
            del core.state.ground[stack.id]
        source = ItemLocation(kind="ground", id=stack.id, cell=stack.cell, position=stack.position)
    else:
        citizen.inventory[item] -= eaten
        if citizen.inventory[item] == 0:
            del citizen.inventory[item]
        source = ItemLocation(kind="inventory", id=citizen.id)
    kind = ITEMS[item]
    cooked = kind.raw and fire.near_lit_fire(core, citizen.position, fire.REACH_M)
    citizen.body.hunger = max(0.0, citizen.body.hunger - eaten * kind.food * (COOKED if cooked else 1.0))
    eaten_seq = core.item_moved(citizen, item, eaten, source, ItemLocation(kind="eaten", id=citizen.id), stole)
    full = " You feel full." if citizen.body.hunger < 10 else ""
    words = amount_words(eaten, kind)
    if cooked:
        return f"You roast {words} over the fire and eat it.{full}"
    rng = core.state.rng("doing.raw_food")
    if kind.raw and rng.random() < RAW_SICK_CHANCE:
        low, high = RAW_SICKNESS
        core.injure(
            citizen, low + (high - low) * rng.random(), "bad food", f"the raw {item} turns your stomach", eaten_seq
        )
        return f"You eat {words} raw. Your stomach cramps; it makes you sick.{full}"
    return f"You eat {words}{' raw' if kind.raw else ''}.{full}"


def _drink(citizen: Citizen, share: float) -> None:
    citizen.body.thirst = max(0.0, citizen.body.thirst - 100.0 * share)


def apply_partial(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    """What an eat or drink cut short achieved."""
    elapsed = core.state.tick - action.started_tick
    if action.kind == "eat" and elapsed > 0:
        _eat(core, citizen, action, min(elapsed, action.amount))
    elif action.kind == "drink" and elapsed > 0:
        _drink(citizen, min(1.0, elapsed / DRINK_MINUTES))
