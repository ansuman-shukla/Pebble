"""Instant actions between people and things (03): say, pick up, drop and give; and the storehouses within reach."""

import re

from app.observability.events import ItemLocation, Said
from app.sim.acting import capital, item_amount, item_name, refuse, stack_in_reach
from app.sim.core import HEARING_M, KEPT_HEARD, REACH_M, SimCore
from app.sim.items import ITEMS, amount_words
from app.sim.perception import match_person, normalize, person_label
from app.sim.state import Citizen, Heard
from app.world_api.models import ActionResult, Drop, Give, PickUp, Say, Volume

SAY_VERB: dict[Volume, str] = {"whisper": "whisper", "normal": "say", "shout": "shout"}
STORE_REACH_M = 6.0  # from a storehouse's door


def say(core: SimCore, citizen: Citizen, action: Say) -> ActionResult:
    hearers = [
        other
        for other in core.living()
        if other.id != citizen.id and core.distance_m(citizen.position, other.position) <= HEARING_M[action.volume]
    ]
    seq = core.emit(
        "said", Said(words=action.words, volume=action.volume, heard_by=[h.id for h in hearers]), actor=citizen
    )
    spoken = normalize(action.words)
    named = re.search(rf"\b{re.escape(citizen.name.lower())}\b", action.words.lower()) is not None
    for hearer in hearers:
        sees = not hearer.body.asleep and core.distance_m(hearer.position, citizen.position) <= core.sight_range(hearer)
        who = person_label(hearer, citizen) if sees else "someone"
        hearer.heard.append(Heard(core.state.tick, seq, citizen.id, who, action.words, action.volume, citizen.position))
        del hearer.heard[:-KEPT_HEARD]
        if hearer.body.asleep:
            continue
        if named and sees:
            core.learn_person(hearer, citizen.id, seq)
        for place_id in sorted(citizen.places):
            name = normalize(core.world.places[place_id].name)
            if name and re.search(rf"\b{re.escape(name)}\b", spoken):
                core.learn_place(hearer, place_id, "rough", seq)
    return ActionResult(action="say", outcome="done", text=f'You {SAY_VERB[action.volume]}: "{action.words}"')


def pick_up(core: SimCore, citizen: Citizen, action: PickUp) -> ActionResult:
    item = item_name(action.item)
    stack_id = stack_in_reach(core, citizen, item) if item else None
    store_id = store_in_reach(core, citizen, item) if item and stack_id is None else None
    if item is None or (stack_id is None and store_id is None):
        return refuse(core, citizen, "pick_up", f"There's no {action.item} within reach.")
    room = core.room_for(citizen, item)
    if room == 0:
        return refuse(core, citizen, "pick_up", "You can't carry any more.")
    if stack_id is None:
        return _take_from_store(core, citizen, item, str(store_id), item_amount(action.item, room))
    stack = core.state.ground[stack_id]
    count = item_amount(action.item, min(room, stack.count))
    stack.count -= count
    if stack.count == 0:
        del core.state.ground[stack_id]
    citizen.inventory[item] = citizen.inventory.get(item, 0) + count
    core.item_moved(
        citizen,
        item,
        count,
        ItemLocation(kind="ground", id=stack_id, cell=stack.cell, position=stack.position),
        ItemLocation(kind="inventory", id=citizen.id),
    )
    return ActionResult(action="pick_up", outcome="done", text=f"You pick up {amount_words(count, ITEMS[item])}.")


def _take_from_store(core: SimCore, citizen: Citizen, item: str, store_id: str, wanted: int) -> ActionResult:
    """Town folk take what they need from a storehouse within reach (03 pick_up: "within reach")."""
    store = core.state.stores[store_id]
    count = min(wanted, store[item])
    store[item] -= count
    if store[item] == 0:
        del store[item]
    citizen.inventory[item] = citizen.inventory.get(item, 0) + count
    core.item_moved(
        citizen, item, count, ItemLocation(kind="store", id=store_id), ItemLocation(kind="inventory", id=citizen.id)
    )
    words = amount_words(count, ITEMS[item])
    return ActionResult(action="pick_up", outcome="done", text=f"You take {words} from the storehouse.")


def drop(core: SimCore, citizen: Citizen, action: Drop) -> ActionResult:
    item = item_name(action.item)
    count = citizen.inventory.get(item, 0) if item else 0
    if item is None or count == 0:
        return refuse(core, citizen, "drop", f"You aren't carrying any {action.item}.")
    count = item_amount(action.item, count)
    citizen.inventory[item] -= count
    if citizen.inventory[item] == 0:
        del citizen.inventory[item]
    stack = core.new_stack(item, count, citizen.position, citizen.cell)
    core.item_moved(
        citizen,
        item,
        count,
        ItemLocation(kind="inventory", id=citizen.id),
        ItemLocation(kind="ground", id=stack.id, cell=stack.cell, position=stack.position),
    )
    return ActionResult(action="drop", outcome="done", text=f"You put down {amount_words(count, ITEMS[item])}.")


def give(core: SimCore, citizen: Citizen, action: Give) -> ActionResult:
    receiver = match_person(core, citizen, action.person)
    if receiver is None:
        return refuse(core, citizen, "give", "You don't see anyone like that.")
    label = person_label(citizen, receiver)
    if core.distance_m(citizen.position, receiver.position) > REACH_M:
        return refuse(core, citizen, "give", f"{capital(label)} is too far away to hand anything to.")
    item = item_name(action.item)
    count = citizen.inventory.get(item, 0) if item else 0
    if item is None or count == 0:
        return refuse(core, citizen, "give", f"You aren't carrying any {action.item}.")
    if receiver.body.asleep:
        return refuse(core, citizen, "give", f"{capital(label)} is asleep.")
    count = min(item_amount(action.item, count), core.room_for(receiver, item))
    if count == 0:
        return refuse(core, citizen, "give", f"{capital(label)} can't carry any more.")
    if not core.accepts_gift(citizen, receiver, item, count):
        return refuse(core, citizen, "give", f"{capital(label)} doesn't take it.")
    citizen.inventory[item] -= count
    if citizen.inventory[item] == 0:
        del citizen.inventory[item]
    receiver.inventory[item] = receiver.inventory.get(item, 0) + count
    core.item_moved(
        citizen,
        item,
        count,
        ItemLocation(kind="inventory", id=citizen.id),
        ItemLocation(kind="inventory", id=receiver.id),
    )
    return ActionResult(
        action="give", outcome="done", text=f"{capital(label)} takes {amount_words(count, ITEMS[item])}."
    )


def store_in_reach(core: SimCore, citizen: Citizen, item: str | None = None) -> str | None:
    """The nearest storehouse within reach that the citizen may use (town folk only), holding `item` if given."""
    if citizen.region != "town":
        return None
    options = [
        (core.distance_m(citizen.position, structure.door), structure.id)
        for structure in core.world.structures.values()
        if structure.kind == "storehouse" and (item is None or core.state.stores.get(structure.id, {}).get(item, 0) > 0)
    ]
    near = [option for option in options if option[0] <= STORE_REACH_M]
    return min(near)[1] if near else None
