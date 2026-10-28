"""Actions (03-actions-perception): instant ones change the world at once; durative ones start here, advance each
tick and end on completion or interrupt. Every failure is an in-world sentence; nothing reveals numbers or ids.
"""

import math
import re

from app.observability.events import (
    ActionEnded,
    ActionStarted,
    ItemLocation,
    JsonScalar,
    ResourceChanged,
    Said,
)
from app.sim.bodies import COLLAPSE_WAKE_ENERGY, Crossing
from app.sim.clock import NIGHT_ALTITUDE_DEG, sun_altitude_deg, sun_direction
from app.sim.core import HEARING_M, KEPT_HEARD, REACH_M, SimCore
from app.sim.items import ITEMS, RESOURCE_INDEX, amount_words
from app.sim.navigation import walk_along
from app.sim.perception import (
    compass,
    match_person,
    match_thing,
    normalize,
    person_label,
    where_words,
)
from app.sim.state import ActionState, Citizen, Heard
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.world_api.models import (
    Action,
    ActionName,
    ActionResult,
    DirectionTarget,
    Drink,
    Drop,
    Eat,
    Flee,
    Gather,
    Give,
    PersonTarget,
    PickUp,
    PlaceTarget,
    Rest,
    Say,
    Sleep,
    Target,
    ThingTarget,
    Volume,
    Wait,
    WalkTo,
)

WALK_M_PER_TICK = 5000 / 60  # 5 km/h on flat ground
EXHAUSTED_PACE = 0.5
ARRIVE_M = 2.0  # close enough to a person
FOLLOW_REPLAN_M = 3.0
GATHER_MINUTES = 20
GATHER_YIELD = (3, 6)
DRINK_MINUTES = 3
SLEEPY_ENERGY = 80.0  # above this nobody falls asleep by day
APPROACH_M = 10.0  # a known person walking up to you interrupts once they come this close
BESIDE_M = 3.0  # "walking up to you": to you, or to a spot this close to you
ROUGH_DISTANCE_M: dict[str, float] = {
    "a few steps": 15.0,
    "a short walk": 100.0,
    "a long walk": 500.0,
    "very far": 1500.0,
}
DISTANCE_PHRASE: dict[str, str] = {
    "a few steps": "a few steps",
    "a short walk": "a short way",
    "a long walk": "a long way",
    "very far": "very far",
}
COMPASS_BEARING = {name: index * 45.0 for index, name in enumerate(compass(b * 45.0) for b in range(8))}
VERB: dict[str, str] = {
    "walk_to": "walking",
    "gather": "gathering",
    "eat": "eating",
    "drink": "drinking",
    "rest": "resting",
    "sleep": "sleeping",
    "wait": "waiting",
    "flee": "running",
}
SAY_VERB: dict[Volume, str] = {"whisper": "whisper", "normal": "say", "shout": "shout"}
SAYS_VERB: dict[Volume, str] = {"whisper": "whispers", "normal": "says", "shout": "shouts"}
NEED_WORDS: dict[str, str] = {
    "hungry": "getting hungry",
    "starving": "starving",
    "thirsty": "getting thirsty",
    "parched": "parched with thirst",
    "tired": "getting tired",
    "exhausted": "exhausted",
    "hurt": "hurting",
    "near death": "close to death",
}
NOT_YET = "You can't do that yet."
_NIGHT_STOPS = frozenset({"walk_to", "gather", "wait", "rest"})
_NEED_STOPS = frozenset({"walk_to", "gather", "wait", "rest", "flee"})
_SINGULAR = {"berry": "berries", "root": "roots", "nut": "nuts"}


# --- bookkeeping ---


def _begin(core: SimCore, citizen: Citizen, kind: ActionName, label: str, args: dict[str, JsonScalar]) -> ActionState:
    number = citizen.next_action
    citizen.next_action += 1
    seq = core.emit("action_started", ActionStarted(number=number, action=kind, args=args, label=label), actor=citizen)
    action = ActionState(
        number=number, kind=kind, started_tick=core.state.tick, started_seq=seq, args=args, label=label
    )
    citizen.action = action
    return action


def _settled(core: SimCore, citizen: Citizen, kind: ActionName, outcome: str, text: str) -> int:
    """A durative action that ends the moment it is asked for (failed, or already done)."""
    number = citizen.next_action
    citizen.next_action += 1
    result = ActionResult(action=kind, outcome="done" if outcome == "done" else "failed", text=text)
    core.emit(
        "action_finished",
        ActionEnded(number=number, action=kind, outcome=result.outcome, text=text),
        actor=citizen,
    )
    core.record_result(citizen, number, result)
    return number


def refuse(core: SimCore, citizen: Citizen, kind: ActionName, text: str) -> ActionResult:
    result = ActionResult(action=kind, outcome="failed", text=text)
    core.emit(
        "action_finished",
        ActionEnded(number=0, action=kind, outcome="failed", text=text),
        actor=citizen,
        visibility="private",
    )
    return result


def item_name(words: str) -> str | None:
    query = normalize(words)
    for word in reversed(query.split()):
        name = _SINGULAR.get(word, word)
        if name in ITEMS:
            return name
    return None


def _stack_in_reach(core: SimCore, citizen: Citizen, item: str) -> str | None:
    options = [
        (core.distance_m(citizen.position, stack.position), stack.id)
        for stack in core.state.ground.values()
        if stack.item == item and stack.count > 0
    ]
    near = [option for option in options if option[0] <= REACH_M]
    return min(near)[1] if near else None


# --- instant actions ---


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
    stack_id = _stack_in_reach(core, citizen, item) if item else None
    if item is None or stack_id is None:
        return refuse(core, citizen, "pick_up", f"There's no {action.item} within reach.")
    room = core.room_for(citizen, item)
    if room == 0:
        return refuse(core, citizen, "pick_up", "You can't carry any more.")
    stack = core.state.ground[stack_id]
    count = min(room, stack.count)
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


def drop(core: SimCore, citizen: Citizen, action: Drop) -> ActionResult:
    item = item_name(action.item)
    count = citizen.inventory.get(item, 0) if item else 0
    if item is None or count == 0:
        return refuse(core, citizen, "drop", f"You aren't carrying any {action.item}.")
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
        return refuse(core, citizen, "give", f"{_capital(label)} is too far away to hand anything to.")
    item = item_name(action.item)
    count = citizen.inventory.get(item, 0) if item else 0
    if item is None or count == 0:
        return refuse(core, citizen, "give", f"You aren't carrying any {action.item}.")
    if receiver.body.asleep:
        return refuse(core, citizen, "give", f"{_capital(label)} is asleep.")
    count = min(count, core.room_for(receiver, item))
    if count == 0:
        return refuse(core, citizen, "give", f"{_capital(label)} can't carry any more.")
    if not core.accepts_gift(citizen, receiver, item, count):
        return refuse(core, citizen, "give", f"{_capital(label)} doesn't take it.")
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
        action="give", outcome="done", text=f"{_capital(label)} takes {amount_words(count, ITEMS[item])}."
    )


def not_yet(core: SimCore, citizen: Citizen, kind: ActionName) -> ActionResult:
    return refuse(core, citizen, kind, NOT_YET)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


# --- starting durative actions ---


def start(core: SimCore, citizen: Citizen, action: Action) -> int:
    """Start a durative action (ending any running one); returns its number. Results arrive via `results`."""
    current = citizen.action
    if current is not None and current.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY:
        return _settled(core, citizen, action.action, "failed", "You are too exhausted to move.")
    if current is not None:
        _apply_partial(core, citizen, current)
        text = "You get up." if current.kind == "sleep" else f"You stop {VERB[current.kind]} to do something else."
        core.end_action(citizen, "interrupted", text)
    if isinstance(action, WalkTo):
        return _start_walk(core, citizen, action.target)
    if isinstance(action, Gather):
        return _start_gather(core, citizen, action)
    if isinstance(action, Eat):
        return _start_eat(core, citizen, action)
    if isinstance(action, Drink):
        return _start_drink(core, citizen, action)
    if isinstance(action, Rest | Wait):
        _begin(core, citizen, action.action, "", {"minutes": action.minutes}).until_tick = (
            core.state.tick + action.minutes
        )
        return citizen.next_action - 1
    if isinstance(action, Sleep):
        if citizen.body.energy > SLEEPY_ENERGY and not core.is_night_at(citizen.position):
            return _settled(core, citizen, "sleep", "failed", "You aren't tired enough to sleep.")
        citizen.body.asleep = True
        _begin(core, citizen, "sleep", "", {})
        return citizen.next_action - 1
    if isinstance(action, Flee):
        return _settled(core, citizen, "flee", "failed", "You see nothing to run from.")
    return _settled(core, citizen, action.action, "failed", NOT_YET)


def _start_walk(core: SimCore, citizen: Citizen, target: Target) -> int:
    resolved = _resolve(core, citizen, target)
    if isinstance(resolved, str):
        return _settled(core, citizen, "walk_to", "failed", resolved)
    goal, label, person_id, arrive = resolved
    if person_id is None and core.distance_m(citizen.position, goal) < 1.0:
        return _settled(core, citizen, "walk_to", "done", "You are already there.")
    if person_id is not None and core.distance_m(citizen.position, goal) <= ARRIVE_M:
        return _settled(core, citizen, "walk_to", "done", f"You are already beside {label}.")
    route = core.planner.plan(citizen.position, goal, citizen.cell)
    if route is None:
        return _settled(core, citizen, "walk_to", "failed", "You can't find a way there.")
    walk = _begin(core, citizen, "walk_to", label, {"target": target.kind, "arrive": arrive})
    walk.route, walk.goal, walk.target_id = route, goal, person_id
    return walk.number


def _resolve(
    core: SimCore, citizen: Citizen, target: Target
) -> tuple[tuple[float, float, float], str, str | None, str] | str:
    """(goal, label, person id, arrival text) or the in-world reason it can't be walked to."""
    if isinstance(target, PlaceTarget):
        query = normalize(target.name)
        if query == "home":
            if citizen.home is None:
                return "You have no home to go to."
            return core.world.structures[citizen.home].door, "your home", None, "You arrive home."
        for place_id in sorted(citizen.places):
            place = core.world.places[place_id]
            if normalize(place.name) == query:
                knowledge = citizen.places[place_id]
                if knowledge.level == "visited":
                    return place.stand, place.name, None, f"You arrive at {place.name}."
                return knowledge.guess, place.name, None, f"rough:{place_id}"
        return f"You don't know a place called {target.name}."
    if isinstance(target, PersonTarget):
        person = match_person(core, citizen, target.who)
        if person is None:
            return "You don't see anyone like that."
        label = person_label(citizen, person)
        return person.position, label, person.id, f"You reach {label}."
    if isinstance(target, ThingTarget):
        thing = match_thing(core, citizen, target.what)
        if thing is None:
            return f"You don't see any {target.what} around here."
        return thing.goal, thing.label, None, f"You reach {thing.label}."
    return _resolve_direction(core, citizen, target)


def _resolve_direction(
    core: SimCore, citizen: Citizen, target: DirectionTarget
) -> tuple[tuple[float, float, float], str, None, str] | str:
    full = ROUGH_DISTANCE_M[target.distance]
    for share in (1.0, 0.75, 0.5, 0.25):
        goal = step_towards(citizen.position, COMPASS_BEARING[target.direction], full * share, core.world.radius_m)
        town = core.world.town_point(goal)
        if town is not None:
            if core.world.town.walk.is_walkable(*town):
                break
        elif core.planner.outer.allowed[core.world.nearest_cell(goal, citizen.cell)]:
            break
    else:
        return f"You can't go {target.distance} to the {target.direction} from here."
    label = f"to the {target.direction}"
    return goal, label, None, f"You walk {DISTANCE_PHRASE[target.distance]} {label} and stop."


def _start_gather(core: SimCore, citizen: Citizen, action: Gather) -> int:
    resource = item_name(action.resource)
    if resource is None or resource not in RESOURCE_INDEX:
        return _settled(core, citizen, "gather", "failed", f"You can't gather {action.resource} here.")
    if core.state.resources[citizen.cell, RESOURCE_INDEX[resource]] == 0:
        return _settled(core, citizen, "gather", "failed", f"There are no {resource} within reach.")
    if core.room_for(citizen, resource) == 0:
        return _settled(core, citizen, "gather", "failed", "You can't carry any more.")
    gather = _begin(core, citizen, "gather", resource, {"resource": resource})
    gather.item, gather.until_tick = resource, core.state.tick + GATHER_MINUTES
    return gather.number


def _start_eat(core: SimCore, citizen: Citizen, action: Eat) -> int:
    item = item_name(action.item)
    if item is None or ITEMS[item].food <= 0:
        return _settled(core, citizen, "eat", "failed", "You can't eat that.")
    stack_id = None
    available = citizen.inventory.get(item, 0)
    if available == 0:
        stack_id = _stack_in_reach(core, citizen, item)
        if stack_id is None:
            return _settled(core, citizen, "eat", "failed", f"You have no {item}, and there are none within reach.")
        available = core.state.ground[stack_id].count
    pieces = max(1, min(available, math.ceil(citizen.body.hunger / ITEMS[item].food)))
    eat = _begin(core, citizen, "eat", item, {"item": item})
    eat.item, eat.amount, eat.target_id, eat.until_tick = item, pieces, stack_id, core.state.tick + pieces
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


def _start_drink(core: SimCore, citizen: Citizen, action: Drink) -> int:
    water = water_within_reach(core, citizen)
    if water is None:
        return _settled(core, citizen, action.action, "failed", "There's no water within reach.")
    kind, source = water
    if kind == "salt":
        return _settled(core, citizen, action.action, "failed", "The water here is salty; you spit it out.")
    drink = _begin(core, citizen, "drink", source, {"source": source})
    drink.until_tick = core.state.tick + DRINK_MINUTES
    return drink.number


# --- advancing durative actions (once per tick) ---


def advance(core: SimCore, citizen: Citizen) -> None:
    action = citizen.action
    if action is None:
        return
    if action.kind == "walk_to":
        _advance_walk(core, citizen, action)
    elif action.kind == "sleep":
        _advance_sleep(core, citizen)
    elif action.until_tick is not None and core.state.tick >= action.until_tick:
        _complete(core, citizen, action)


def _advance_walk(core: SimCore, citizen: Citizen, walk: ActionState) -> None:
    if walk.target_id is not None:
        person = core.state.citizens[walk.target_id]
        distance = core.distance_m(citizen.position, person.position)
        if not person.body.alive or distance > core.sight_range(citizen):
            core.end_action(citizen, "interrupted", f"You stop walking: you lose sight of {walk.label}.")
            return
        if distance <= ARRIVE_M:
            core.end_action(citizen, "done", f"You reach {walk.label}.")
            return
        if walk.goal is None or core.distance_m(person.position, walk.goal) > FOLLOW_REPLAN_M:
            route = core.planner.plan(citizen.position, person.position, citizen.cell)
            if route is None:
                core.end_action(citizen, "interrupted", f"You stop walking: you can't find a way to {walk.label}.")
                return
            walk.route, walk.goal, walk.leg, walk.along_m = route, person.position, 0, 0.0
    if walk.route is None:
        raise ValueError(f"walk {walk.number} of {citizen.id} has no route")
    pace = citizen.traits.speed * (EXHAUSTED_PACE if citizen.body.energy <= 10 else 1.0)
    progress = walk_along(walk.route, walk.leg, walk.along_m, WALK_M_PER_TICK * pace, core.world.radius_m)
    walk.leg, walk.along_m = progress.leg, progress.along_m
    core.place_at(citizen, progress.position)
    if not progress.arrived:
        return
    if walk.target_id is not None:
        if core.distance_m(citizen.position, core.state.citizens[walk.target_id].position) <= ARRIVE_M:
            core.end_action(citizen, "done", f"You reach {walk.label}.")
        else:
            walk.goal = None  # they moved on: plan again next tick
        return
    arrive = str(walk.args["arrive"])
    if arrive.startswith("rough:"):
        place = core.world.places[arrive.removeprefix("rough:")]
        if core.distance_m(citizen.position, place.centre) <= place.radius_m:
            arrive = f"You arrive at {place.name}."
        else:
            arrive = f"You reach about where {place.name} should be, but you don't find it."
    core.end_action(citizen, "done", arrive)


def _advance_sleep(core: SimCore, citizen: Citizen) -> None:
    action = citizen.action
    if action is None or (action.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY):
        return
    now = core.altitude(citizen.position)
    before = sun_altitude_deg(citizen.position, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    if before <= 0 < now:
        core.end_action(citizen, "done", "You wake up; it is morning.")
    elif now > 0 and citizen.body.energy >= 100:
        core.end_action(citizen, "done", "You wake up rested.")


def _complete(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    if action.kind == "gather":
        _finish_gather(core, citizen, action)
    elif action.kind == "eat":
        text = _eat(core, citizen, action, action.amount)
        core.end_action(citizen, "done" if text else "failed", text or "There's nothing left to eat.")
    elif action.kind == "drink":
        _drink(citizen, 1.0)
        core.end_action(citizen, "done", f"You drink from {action.label} until you are no longer thirsty.")
    elif action.kind == "rest":
        core.end_action(citizen, "done", "You rest a while.")
    elif action.kind == "wait":
        core.end_action(citizen, "done", "You wait a while.")
    else:
        raise ValueError(f"{action.kind} has no timed completion")


def _finish_gather(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    resource = action.item
    if resource is None:
        raise ValueError("a gather action needs a resource")
    column = RESOURCE_INDEX[resource]
    cell = citizen.cell
    before = int(core.state.resources[cell, column])
    room = core.room_for(citizen, resource)
    count = min(core.state.rngs["actions"].randint(*GATHER_YIELD), before, room)
    if count == 0:
        core.end_action(
            citizen, "failed", "You can't carry any more." if before else "You find nothing left to gather."
        )
        return
    core.state.resources[cell, column] = before - count
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


def _eat(core: SimCore, citizen: Citizen, action: ActionState, pieces: int) -> str | None:
    """Eat up to `pieces` of the action's item; the result text, or None if there was nothing left."""
    item = action.item
    if item is None:
        raise ValueError("an eat action needs an item")
    stack = core.state.ground.get(action.target_id) if action.target_id is not None else None
    available = stack.count if stack is not None else citizen.inventory.get(item, 0)
    eaten = min(pieces, available)
    if eaten <= 0:
        return None
    if stack is not None:
        stack.count -= eaten
        if stack.count == 0:
            del core.state.ground[stack.id]
        source = ItemLocation(kind="ground", id=stack.id, cell=stack.cell, position=stack.position)
    else:
        citizen.inventory[item] -= eaten
        if citizen.inventory[item] == 0:
            del citizen.inventory[item]
        source = ItemLocation(kind="inventory", id=citizen.id)
    citizen.body.hunger = max(0.0, citizen.body.hunger - eaten * ITEMS[item].food)
    core.item_moved(citizen, item, eaten, source, ItemLocation(kind="eaten", id=citizen.id))
    full = " You feel full." if citizen.body.hunger < 10 else ""
    return f"You eat {amount_words(eaten, ITEMS[item])}.{full}"


def _drink(citizen: Citizen, share: float) -> None:
    citizen.body.thirst = max(0.0, citizen.body.thirst - 100.0 * share)


def _apply_partial(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    """What an eat or drink cut short achieved."""
    elapsed = core.state.tick - action.started_tick
    if action.kind == "eat" and elapsed > 0:
        _eat(core, citizen, action, min(elapsed, action.amount))
    elif action.kind == "drink" and elapsed > 0:
        _drink(citizen, min(1.0, elapsed / DRINK_MINUTES))


# --- body events that end actions ---


def collapse(core: SimCore, citizen: Citizen) -> None:
    if citizen.action is not None:
        _apply_partial(core, citizen, citizen.action)
        core.end_action(citizen, "interrupted", "Your legs give way; you collapse, exhausted.")
    citizen.body.asleep = True
    _begin(core, citizen, "sleep", "", {"collapsed": True}).collapsed = True


def end_for_death(core: SimCore, citizen: Citizen, died_seq: int) -> None:
    if citizen.action is not None:
        core.end_action(citizen, "interrupted", "Everything goes dark.", cause_seq=died_seq)


# --- interrupts (once per tick, after bodies) ---


def interrupt(
    core: SimCore,
    citizen: Citizen,
    worse: list[Crossing],
    strangers_seen: list[str],
    approaching: list[str],
    night_fell: bool,
) -> None:
    """End the running durative action early when something happens (03, "Interrupts").

    People interrupt when a stranger comes into view or someone known comes up to you; known people merely walking
    by don't (animals join with M6).
    """
    action = citizen.action
    if action is None:
        return
    verb = VERB[action.kind]
    stop = "You wake" if action.kind == "sleep" else f"You stop {verb}"
    asleep = action.kind == "sleep"
    for heard in citizen.heard:
        if heard.tick != core.state.tick - 1 or heard.speaker_id == citizen.id:
            continue
        if asleep and (action.collapsed or not (heard.volume == "shout" or _names(heard.words, citizen.name))):
            continue
        text = f'{stop}: {heard.who} {SAYS_VERB[heard.volume]}, "{heard.words}"'
        _interrupt(core, citizen, action, text, heard.seq)
        return
    for crossing in worse:
        if action.kind in _NEED_STOPS or (crossing.need == "health" and action.kind != "eat"):
            _interrupt(core, citizen, action, f"{stop}: you are {NEED_WORDS[crossing.words]}.", None)
            return
    if not asleep:
        for person_id in strangers_seen:
            if person_id == action.target_id:
                continue
            other = core.state.citizens[person_id]
            where = _where(core, citizen, other)
            _interrupt(core, citizen, action, f"{stop}: {person_label(citizen, other)} comes into view {where}.", None)
            return
        for person_id in approaching:
            if person_id == action.target_id:
                continue
            label = person_label(citizen, core.state.citizens[person_id])
            _interrupt(core, citizen, action, f"{stop}: {label} is coming toward you.", None)
            return
    if night_fell and action.kind in _NIGHT_STOPS:
        _interrupt(core, citizen, action, f"{stop}: night is falling.", None)


WalkHeading = tuple[str | None, Vec3 | None]  # (person walked to, where the walk goes)


def walk_heading(citizen: Citizen) -> WalkHeading | None:
    action = citizen.action
    if action is None or action.kind != "walk_to":
        return None
    return action.target_id, action.goal


def approaching(
    core: SimCore,
    citizen: Citizen,
    seen: set[str],
    before: dict[str, Vec3],
    headings: dict[str, WalkHeading | None],
) -> list[str]:
    """Known people in view who came within APPROACH_M this tick while walking to the citizen or to a spot beside
    them (someone merely heading to the same well or market as you doesn't count)."""
    found: list[str] = []
    for person_id in sorted(seen & citizen.people):
        heading = headings.get(person_id)
        if heading is None or person_id not in before:
            continue
        other = core.state.citizens[person_id]
        if core.distance_m(citizen.position, other.position) > APPROACH_M:
            continue
        if core.distance_m(before.get(citizen.id, citizen.position), before[person_id]) <= APPROACH_M:
            continue  # already close
        target_id, goal = heading
        if target_id == citizen.id or (goal is not None and core.distance_m(goal, citizen.position) <= BESIDE_M):
            found.append(person_id)
    return found


def _interrupt(core: SimCore, citizen: Citizen, action: ActionState, text: str, cause_seq: int | None) -> None:
    _apply_partial(core, citizen, action)
    core.end_action(citizen, "interrupted", text, cause_seq)


def _names(words: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name.lower())}\b", words.lower()) is not None


def _where(core: SimCore, citizen: Citizen, other: Citizen) -> str:
    return where_words(core.distance_m(citizen.position, other.position), bearing_deg(citizen.position, other.position))


def night_fell(core: SimCore, citizen: Citizen) -> bool:
    before = sun_altitude_deg(citizen.position, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    return before >= NIGHT_ALTITUDE_DEG > core.altitude(citizen.position)
