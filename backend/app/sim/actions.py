"""Actions (03-actions-perception): instant ones change the world at once; durative ones start here, advance each
tick and end on completion or interrupt. Every failure is an in-world sentence; nothing reveals numbers or ids.
"""

import math
import re
from dataclasses import dataclass

from app.observability.events import (
    ItemLocation,
    ResourceChanged,
    RoutePoint,
    Said,
)
from app.sim import fire, wild
from app.sim.acting import begin, capital, item_name, refuse, settled, stack_in_reach
from app.sim.bodies import COLLAPSE_WAKE_ENERGY, Crossing
from app.sim.clock import NIGHT_ALTITUDE_DEG, SECONDS_PER_TICK, sun_altitude_deg, sun_direction
from app.sim.core import HEARING_M, KEPT_HEARD, REACH_M, SimCore
from app.sim.ecology import schedule_regrowth
from app.sim.fauna import DANGEROUS, SPECIES
from app.sim.items import GATHERED, ITEMS, RESOURCE_INDEX, amount_words
from app.sim.navigation import walk_along
from app.sim.perception import (
    HOME_RADIUS_M,
    WATCHING_M,
    compass,
    from_where,
    match_animal,
    match_person,
    match_thing,
    nearest_danger,
    normalize,
    person_label,
    where_words,
)
from app.sim.state import ActionState, Animal, Citizen, Heard
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.world_api.models import (
    Action,
    ActionName,
    ActionResult,
    Attack,
    DirectionTarget,
    Drink,
    Drop,
    Eat,
    FeedFire,
    Fish,
    Flee,
    Gather,
    Give,
    Hunt,
    MakeFire,
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
    Work,
)

WALK_M_PER_TICK = 5000 / 60  # 5 km/h on flat ground
EXHAUSTED_PACE = 0.5
WALK_AHEAD_TICKS = 2  # how much of a walker's path spectators get: enough to draw the walk until the next tick
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
    "work": "working",
    "hunt": "hunting",
    "fish": "fishing",
    "make_fire": "making a fire",
    "feed_fire": "tending the fire",
    "attack": "fighting",
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
STORE_REACH_M = 6.0  # from a storehouse's door
FARM_GROWTH = 12  # measures of rice an hour of tending ripens
FIELD_ID = "rice-fields"  # the town's paddies: a place, and the store their ripe rice waits in
NOT_YET = "You can't do that yet."
FLEE_M = 150.0  # flee() runs this far from the danger
FLEE_PACE = 1.6  # running
FLEE_TURNS = (0.0, 45.0, -45.0, 90.0, -90.0, 135.0, -135.0)
COOKED = 1.5  # raw meat or fish eaten beside a fire is roasted: this much more filling
RAW_SICK_CHANCE = 0.3
RAW_SICKNESS = (6.0, 14.0)


@dataclass(frozen=True)
class WorkTask:
    """A role task for `work(task)` (03): who can do it, where, for how long, and how it reads."""

    name: str
    words: frozenset[str]  # what someone asking for it may say
    minutes: int
    skill: str | None  # None = anyone
    places: tuple[str, ...] = ()  # place ids to stand in (empty: see `at`)
    at: str = "place"  # "place" | "storehouse" | "home"
    nowhere: str = ""  # the failure when not where the task is done
    label: str = ""  # what they are doing, for spectators
    done: str = ""  # the result text when finished


WORK_TASKS: tuple[WorkTask, ...] = (
    WorkTask(
        "farm",
        frozenset({"farm", "farming", "fields", "field", "paddies", "rice", "tend", "harvest"}),
        60,
        "farming",
        places=(FIELD_ID,),
        nowhere="There are no fields here to tend.",
        label="tending the rice paddies",
    ),
    WorkTask(
        "store food",
        frozenset({"store", "storehouse", "stores", "granary"}),
        5,
        None,
        at="storehouse",
        nowhere="There's no storehouse within reach.",
        label="filling the storehouse",
    ),
    WorkTask(
        "guard",
        frozenset({"guard", "patrol", "watch", "sentry"}),
        45,
        "arms",
        places=("main-gate", "west-gate", "castle", "training-ground"),
        nowhere="There is nothing to guard here.",
        label="keeping watch",
        done="You keep watch a while; all is quiet.",
    ),
    WorkTask(
        "trade",
        frozenset({"trade", "sell", "buy", "market", "haggle"}),
        60,
        "trade",
        places=("market",),
        nowhere="There is no market here.",
        label="trading at the market",
        done="You trade with passers-by and haggle over cloth and salt.",
    ),
    WorkTask(
        "weave",
        frozenset({"weave", "weaving", "loom", "cloth"}),
        60,
        "weaving",
        at="home",
        nowhere="Your loom is at home.",
        label="weaving at the loom",
        done="You weave a length of cloth.",
    ),
    WorkTask(
        "govern",
        frozenset({"govern", "rule", "court", "petitions", "council"}),
        60,
        "governing",
        places=("castle",),
        nowhere="You hold court only at the castle.",
        label="holding court",
        done="You hear petitions and settle a quarrel over a boundary stone.",
    ),
)
WORK_BY_NAME = {task.name: task for task in WORK_TASKS}


def work_task(words: str) -> WorkTask | None:
    query = set(normalize(words).split())
    return next((task for task in WORK_TASKS if task.words & query), None)


_NIGHT_STOPS = frozenset({"walk_to", "gather", "wait", "rest", "work", "hunt", "fish"})
_NEED_STOPS = frozenset({"walk_to", "gather", "wait", "rest", "flee", "work", "hunt", "fish"})


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
    stack_id = stack_in_reach(core, citizen, item) if item else None
    store_id = store_in_reach(core, citizen, item) if item and stack_id is None else None
    if item is None or (stack_id is None and store_id is None):
        return refuse(core, citizen, "pick_up", f"There's no {action.item} within reach.")
    room = core.room_for(citizen, item)
    if room == 0:
        return refuse(core, citizen, "pick_up", "You can't carry any more.")
    if stack_id is None:
        return _take_from_store(core, citizen, item, str(store_id), room)
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


def _take_from_store(core: SimCore, citizen: Citizen, item: str, store_id: str, room: int) -> ActionResult:
    """Town folk take what they need from a storehouse within reach (03 pick_up: "within reach")."""
    store = core.state.stores[store_id]
    count = min(room, store[item])
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
    count = min(count, core.room_for(receiver, item))
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


def not_yet(core: SimCore, citizen: Citizen, kind: ActionName) -> ActionResult:
    return refuse(core, citizen, kind, NOT_YET)


# --- starting durative actions ---


def start(core: SimCore, citizen: Citizen, action: Action) -> int:
    """Start a durative action (ending any running one); returns its number. Results arrive via `results`."""
    current = citizen.action
    if current is not None and current.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY:
        return settled(core, citizen, action.action, "failed", "You are too exhausted to move.")
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
        begin(core, citizen, action.action, "", {"minutes": action.minutes}).until_tick = (
            core.state.tick + action.minutes
        )
        return citizen.next_action - 1
    if isinstance(action, Sleep):
        if citizen.body.energy > SLEEPY_ENERGY and not core.is_night_at(citizen.position):
            return settled(core, citizen, "sleep", "failed", "You aren't tired enough to sleep.")
        citizen.body.asleep = True
        begin(core, citizen, "sleep", "", {})
        return citizen.next_action - 1
    if isinstance(action, Flee):
        return _start_flee(core, citizen)
    if isinstance(action, Work):
        return _start_work(core, citizen, action)
    if isinstance(action, Hunt):
        return wild.start_hunt(core, citizen, action)
    if isinstance(action, Attack):
        return wild.start_attack(core, citizen, action)
    if isinstance(action, Fish):
        return wild.start_fish(core, citizen)
    if isinstance(action, MakeFire):
        return wild.start_make_fire(core, citizen)
    if isinstance(action, FeedFire):
        return wild.start_feed_fire(core, citizen)
    return settled(core, citizen, action.action, "failed", NOT_YET)


def _start_walk(core: SimCore, citizen: Citizen, target: Target) -> int:
    resolved = _resolve(core, citizen, target)
    if isinstance(resolved, str):
        return settled(core, citizen, "walk_to", "failed", resolved)
    if resolved.person_id is None and core.distance_m(citizen.position, resolved.goal) < 1.0:
        return settled(core, citizen, "walk_to", "done", "You are already there.")
    if resolved.person_id is not None and core.distance_m(citizen.position, resolved.goal) <= ARRIVE_M:
        return settled(core, citizen, "walk_to", "done", f"You are already beside {resolved.words}.")
    route = core.planner.plan(citizen.position, resolved.goal, citizen.cell)
    if route is None:
        return settled(core, citizen, "walk_to", "failed", "You can't find a way there.")
    walk = begin(
        core,
        citizen,
        "walk_to",
        resolved.shown,
        {"target": target.kind, "arrive": resolved.arrive},
        destination=resolved.words,
    )
    walk.route, walk.goal, walk.target_id = route, resolved.goal, resolved.person_id
    return walk.number


def _start_flee(core: SimCore, citizen: Citizen) -> int:
    """Run away from the nearest danger in view (03 flee), turning aside if water or walls are in the way."""
    danger = nearest_danger(core, citizen)
    if danger is None:
        return settled(core, citizen, "flee", "failed", "You see nothing to run from.")
    animal, _ = danger
    away = bearing_deg(animal.position, citizen.position)
    for turn in FLEE_TURNS:
        goal = step_towards(citizen.position, (away + turn) % 360.0, FLEE_M, core.world.radius_m)
        town = core.world.town_point(goal)
        walkable = (
            core.world.town.walk.is_walkable(*town)
            if town is not None
            else core.planner.outer.allowed[core.world.nearest_cell(goal, citizen.cell)]
        )
        route = core.planner.plan(citizen.position, goal, citizen.cell) if walkable else None
        if route is not None:
            label = f"away from {SPECIES[animal.kind].one}"
            flee = begin(core, citizen, "flee", label, {"arrive": "You run until you feel safer."}, destination=label)
            flee.route, flee.goal = route, goal
            return flee.number
    return settled(core, citizen, "flee", "failed", "There's nowhere to run.")


@dataclass(frozen=True)
class _Destination:
    """Where a walk goes, as the walker names it (`words`, "your home") and as spectators see it (`shown`, "home")."""

    goal: Vec3
    words: str
    person_id: str | None
    arrive: str  # the arrival text, or "rough:<place id>" for a place only guessed at
    shown: str


def _resolve(core: SimCore, citizen: Citizen, target: Target) -> _Destination | str:
    """Where the target is, or the in-world reason it can't be walked to."""
    if isinstance(target, PlaceTarget):
        query = normalize(target.name)
        if query == "home":
            if citizen.home is None:
                return "You have no home to go to."
            door = core.world.structures[citizen.home].door
            return _Destination(door, "your home", None, "You arrive home.", shown="home")
        for place_id in sorted(citizen.places):
            place = core.world.places[place_id]
            if normalize(place.name) == query:
                knowledge = citizen.places[place_id]
                if knowledge.level == "visited":
                    return _Destination(place.stand, place.name, None, f"You arrive at {place.name}.", place.name)
                return _Destination(knowledge.guess, place.name, None, f"rough:{place_id}", place.name)
        return f"You don't know a place called {target.name}."
    if isinstance(target, PersonTarget):
        person = match_person(core, citizen, target.who)
        if person is None:
            return "You don't see anyone like that."
        label = person_label(citizen, person)
        # spectators see who it really is; the walker only knows a stranger by their looks
        return _Destination(person.position, label, person.id, f"You reach {label}.", shown=person.name)
    if isinstance(target, ThingTarget):
        thing = match_thing(core, citizen, target.what)
        if thing is not None:
            return _Destination(thing.goal, thing.label, None, f"You reach {thing.label}.", thing.label)
        animal = match_animal(core, citizen, target.what)
        if animal is not None:
            one = SPECIES[animal.kind].one
            return _Destination(animal.position, one, None, f"You reach where you saw {one}.", one)
        return f"You don't see any {target.what} around here."
    return _resolve_direction(core, citizen, target)


def _resolve_direction(core: SimCore, citizen: Citizen, target: DirectionTarget) -> _Destination | str:
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
    return _Destination(goal, label, None, f"You walk {DISTANCE_PHRASE[target.distance]} {label} and stop.", label)


def _start_gather(core: SimCore, citizen: Citizen, action: Gather) -> int:
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


def _start_eat(core: SimCore, citizen: Citizen, action: Eat) -> int:
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


def _start_work(core: SimCore, citizen: Citizen, action: Work) -> int:
    task = work_task(action.task)
    if task is None or (task.skill is not None and task.skill not in citizen.skills):
        return settled(core, citizen, "work", "failed", "You don't know how to do that.")
    store_id = None
    if task.at == "storehouse":
        store_id = store_in_reach(core, citizen)
        if store_id is None:
            return settled(core, citizen, "work", "failed", task.nowhere)
        if not any(ITEMS[item].food > 0 for item in citizen.inventory):
            return settled(core, citizen, "work", "failed", "You aren't carrying any food to store.")
    elif task.at == "home":
        home = core.world.structures.get(citizen.home) if citizen.home is not None else None
        if home is None or core.distance_m(citizen.position, home.door) > HOME_RADIUS_M:
            return settled(core, citizen, "work", "failed", task.nowhere)
    else:
        places = [core.world.places[place_id] for place_id in task.places]
        if not any(core.distance_m(citizen.position, place.centre) <= place.radius_m for place in places):
            return settled(core, citizen, "work", "failed", task.nowhere)
    work = begin(core, citizen, "work", task.label, {"task": task.name})
    work.item, work.store_id, work.until_tick = task.name, store_id, core.state.tick + task.minutes
    return work.number


def _finish_work(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    task = WORK_BY_NAME[str(action.item)]
    if task.name == "farm":
        core.end_action(citizen, "done", _farm(core, citizen))
    elif task.name == "store food":
        core.end_action(citizen, "done", _store_food(core, citizen, str(action.store_id)))
    else:
        core.end_action(citizen, "done", task.done)


def _farm(core: SimCore, citizen: Citizen) -> str:
    """An hour of tending ripens rice in the field; the farmer harvests what they can carry, the rest waits there."""
    field = core.state.stores.setdefault(FIELD_ID, {})
    field["rice"] = field.get("rice", 0) + FARM_GROWTH
    grown = core.item_moved(
        citizen, "rice", FARM_GROWTH, ItemLocation(kind="world"), ItemLocation(kind="store", id=FIELD_ID)
    )
    taken = min(field["rice"], core.room_for(citizen, "rice"))
    if taken == 0:
        return "You tend the rice paddies, but you can't carry any more rice."
    field["rice"] -= taken
    if field["rice"] == 0:
        del field["rice"]
    citizen.inventory["rice"] = citizen.inventory.get("rice", 0) + taken
    core.item_moved(
        citizen,
        "rice",
        taken,
        ItemLocation(kind="store", id=FIELD_ID),
        ItemLocation(kind="inventory", id=citizen.id),
        cause_seq=grown,
    )
    left = " The rest stays in the field." if field.get("rice", 0) else ""
    return f"You tend the rice paddies and harvest {amount_words(taken, ITEMS['rice'])}.{left}"


def _store_food(core: SimCore, citizen: Citizen, store_id: str) -> str:
    store = core.state.stores.setdefault(store_id, {})
    stored: list[str] = []
    for item in sorted(citizen.inventory):
        if ITEMS[item].food <= 0:
            continue
        count = citizen.inventory.pop(item)
        store[item] = store.get(item, 0) + count
        core.item_moved(
            citizen, item, count, ItemLocation(kind="inventory", id=citizen.id), ItemLocation(kind="store", id=store_id)
        )
        stored.append(amount_words(count, ITEMS[item]))
    if not stored:
        return "You have no food left to store."
    return f"You put {' and '.join(stored)} in the storehouse."


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
        return settled(core, citizen, action.action, "failed", "There's no water within reach.")
    kind, source = water
    if kind == "salt":
        return settled(core, citizen, action.action, "failed", "The water here is salty; you spit it out.")
    drink = begin(core, citizen, "drink", source, {"source": source})
    drink.until_tick = core.state.tick + DRINK_MINUTES
    return drink.number


# --- advancing durative actions (once per tick) ---


def advance(core: SimCore, citizen: Citizen) -> None:
    action = citizen.action
    if action is None:
        return
    if action.kind in ("walk_to", "flee"):
        _advance_walk(core, citizen, action)
    elif action.kind in ("hunt", "attack"):
        wild.advance_stalk(core, citizen, action)
    elif action.kind == "sleep":
        _advance_sleep(core, citizen)
    elif action.until_tick is not None and core.state.tick >= action.until_tick:
        _complete(core, citizen, action)


def _advance_walk(core: SimCore, citizen: Citizen, walk: ActionState) -> None:
    if walk.target_id is not None:
        person = core.state.citizens[walk.target_id]
        distance = core.distance_m(citizen.position, person.position)
        if not person.body.alive or distance > core.sight_range(citizen):
            core.end_action(citizen, "interrupted", f"You stop walking: you lose sight of {walk.destination}.")
            return
        if distance <= ARRIVE_M:
            core.end_action(citizen, "done", f"You reach {walk.destination}.")
            return
        if walk.goal is None or core.distance_m(person.position, walk.goal) > FOLLOW_REPLAN_M:
            route = core.planner.plan(citizen.position, person.position, citizen.cell)
            if route is None:
                core.end_action(
                    citizen, "interrupted", f"You stop walking: you can't find a way to {walk.destination}."
                )
                return
            walk.route, walk.goal, walk.leg, walk.along_m = route, person.position, 0, 0.0
    if walk.route is None:
        raise ValueError(f"walk {walk.number} of {citizen.id} has no route")
    progress = walk_along(walk.route, walk.leg, walk.along_m, WALK_M_PER_TICK * walk_pace(citizen), core.world.radius_m)
    walk.leg, walk.along_m = progress.leg, progress.along_m
    core.place_at(citizen, progress.position)
    if not progress.arrived:
        return
    if walk.target_id is not None:
        if core.distance_m(citizen.position, core.state.citizens[walk.target_id].position) <= ARRIVE_M:
            core.end_action(citizen, "done", f"You reach {walk.destination}.")
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


def walk_pace(citizen: Citizen) -> float:
    """Walking cost budget per tick as a share of WALK_M_PER_TICK (age, halved when exhausted, ×1.6 fleeing)."""
    fleeing = citizen.action is not None and citizen.action.kind == "flee"
    return (
        citizen.traits.speed * (EXHAUSTED_PACE if citizen.body.energy <= 10 else 1.0) * (FLEE_PACE if fleeing else 1.0)
    )


def walk_ahead(core: SimCore, citizen: Citizen) -> tuple[list[RoutePoint], float]:
    """A walker's planned path for the next WALK_AHEAD_TICKS from where they stand (the first point), and their
    ground speed on the current leg in metres per game second; ([], 0) when they aren't walking on.

    The points are the route's own corners plus where the look-ahead ends on a leg, so the path between them is as
    walkable as the route (in town: grid corners, no corner cutting).
    """
    walk = citizen.action
    if walk is None or walk.kind not in ("walk_to", "flee") or walk.route is None or walk.leg >= len(walk.route.costs):
        return [], 0.0
    route, world = walk.route, core.world
    pace = walk_pace(citizen)
    end = walk_along(route, walk.leg, walk.along_m, WALK_AHEAD_TICKS * WALK_M_PER_TICK * pace, world.radius_m)
    points: list[RoutePoint] = []
    cell = citizen.cell
    for unit in (citizen.position, *route.points[walk.leg + 1 : end.leg + 1], end.position):
        if points and unit == points[-1].unit:
            continue
        cell = world.nearest_cell(unit, cell)
        points.append(RoutePoint(unit=unit, height_m=world.ground_height(unit, cell)))
    return points, WALK_M_PER_TICK * pace / route.costs[walk.leg] / SECONDS_PER_TICK


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
    elif action.kind == "work":
        _finish_work(core, citizen, action)
    elif action.kind in ("fish", "make_fire", "feed_fire"):
        wild.complete(core, citizen, action)
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
    if store is not None:
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
    eaten_seq = core.item_moved(citizen, item, eaten, source, ItemLocation(kind="eaten", id=citizen.id))
    full = " You feel full." if citizen.body.hunger < 10 else ""
    words = amount_words(eaten, kind)
    if cooked:
        return f"You roast {words} over the fire and eat it.{full}"
    rng = core.state.rngs["actions"]
    if kind.raw and rng.random() < RAW_SICK_CHANCE:
        low, high = RAW_SICKNESS
        core.injure(
            citizen, low + (high - low) * rng.random(), "bad food", f"the raw {item} turns your stomach", eaten_seq
        )
        return f"You eat {words} raw. Your stomach cramps; it makes you sick.{full}"
    return f"You eat {words}{' raw' if kind.raw else ''}.{full}"


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
    begin(core, citizen, "sleep", "", {"collapsed": True}).collapsed = True


def end_for_death(core: SimCore, citizen: Citizen, died_seq: int) -> None:
    if citizen.action is not None:
        core.end_action(citizen, "interrupted", "Everything goes dark.", cause_seq=died_seq)


# --- interrupts (once per tick, after bodies) ---


@dataclass(frozen=True)
class AnimalNews:
    """What changed about the animals around a citizen this tick (for interrupts)."""

    hurt: tuple[str, int] | None = None  # what hurt them ("a wolf attacks you") and the injured event
    threats: tuple[tuple[Animal, float], ...] = ()  # predators that started coming at them
    groups: tuple[tuple[Animal, float, int], ...] = ()  # groups that came into view: (nearest member, metres, seen)


def interrupt(
    core: SimCore,
    citizen: Citizen,
    worse: list[Crossing],
    strangers_seen: list[str],
    approaching: list[str],
    night_fell: bool,
    news: AnimalNews | None = None,
) -> None:
    """End the running durative action early when something happens (03, "Interrupts").

    Being hurt wakes even sleepers (not the collapsed); a predator coming at you, a stranger or an animal group
    coming into view, or someone known walking up to you interrupt the awake; known people merely walking by don't.
    """
    action = citizen.action
    if action is None:
        return
    news = news or AnimalNews()
    verb = VERB[action.kind]
    stop = "You wake" if action.kind == "sleep" else f"You stop {verb}"
    asleep = action.kind == "sleep"
    if news.hurt is not None and not action.collapsed:
        words, seq = news.hurt
        _interrupt(core, citizen, action, f"{stop}: {words}!", seq)
        return
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
    if asleep:
        return
    for animal, distance in news.threats:
        where = from_where(core, citizen, distance, bearing_deg(citizen.position, animal.position))
        _interrupt(core, citizen, action, f"{stop}: {SPECIES[animal.kind].one} is coming at you {where}.", None)
        return
    for person_id in strangers_seen:
        if person_id == action.target_id:
            continue
        other = core.state.citizens[person_id]
        where = _where(core, citizen, other)
        _interrupt(core, citizen, action, f"{stop}: {person_label(citizen, other)} comes into view {where}.", None)
        return
    hunted = core.state.animals.get(action.target_id or "")
    for animal, distance, count in news.groups:
        if action.kind == "flee" or (hunted is not None and hunted.group == animal.group):
            continue
        species = SPECIES[animal.kind]
        label = species.count_words(count)
        bearing = bearing_deg(citizen.position, animal.position)
        if animal.kind in DANGEROUS and animal.activity != "sleeping" and distance <= WATCHING_M:
            verb_phrase = "is" if count == 1 else "are"
            text = f"{stop}: {label} {verb_phrase} watching you {from_where(core, citizen, distance, bearing)}."
        else:
            text = f"{stop}: {label} {'comes' if count == 1 else 'come'} into view {where_words(distance, bearing)}."
        _interrupt(core, citizen, action, text, None)
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


def body_activity(action: ActionState | None) -> str | None:
    """What the body is doing for need rates: the action, or the work task (farming is hard work)."""
    if action is None:
        return None
    return str(action.item) if action.kind == "work" else action.kind


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
