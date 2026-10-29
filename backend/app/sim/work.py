"""Role work (03 `work(task)`): the task table, starting a task where it is done, and what finishing it does.

`WORK_TASKS` is a seam: a later system adds its task as a row, with its finisher living in that system's module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.observability.events import ItemLocation
from app.sim.acting import begin, settled
from app.sim.core import SimCore
from app.sim.exchange import store_in_reach
from app.sim.items import ITEMS, amount_words
from app.sim.perception import HOME_RADIUS_M, normalize
from app.sim.state import ActionState, Citizen
from app.world_api.models import Work

FARM_GROWTH = 12  # measures of rice an hour of tending ripens
FIELD_ID = "rice-fields"  # the town's paddies: a place, and the store their ripe rice waits in

WorkFinisher = Callable[[SimCore, Citizen, ActionState], str]  # does the task's work; returns the result text


def farm(core: SimCore, citizen: Citizen, _action: ActionState) -> str:
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


def store_food(core: SimCore, citizen: Citizen, action: ActionState) -> str:
    store_id = str(action.store_id)
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
    done: str = ""  # the result text when finished (tasks without a finisher)
    finish: WorkFinisher | None = None  # what finishing the task does to the world, and the result text


WORK_TASKS: tuple[WorkTask, ...] = (
    WorkTask(
        "farm",
        frozenset({"farm", "farming", "fields", "field", "paddies", "rice", "tend", "harvest"}),
        60,
        "farming",
        places=(FIELD_ID,),
        nowhere="There are no fields here to tend.",
        label="tending the rice paddies",
        finish=farm,
    ),
    WorkTask(
        "store food",
        frozenset({"store", "storehouse", "stores", "granary"}),
        5,
        None,
        at="storehouse",
        nowhere="There's no storehouse within reach.",
        label="filling the storehouse",
        finish=store_food,
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
    WorkTask(
        "pray",
        frozenset({"pray", "prayers", "chant", "sutras", "worship"}),
        45,
        None,
        places=("temple",),
        nowhere="There is no temple here.",
        label="praying at the temple",
        done="You chant the sutras and sweep the temple steps.",
    ),
)
WORK_BY_NAME = {task.name: task for task in WORK_TASKS}


def work_task(words: str) -> WorkTask | None:
    query = set(normalize(words).split())
    return next((task for task in WORK_TASKS if task.words & query), None)


def start_work(core: SimCore, citizen: Citizen, action: Work) -> int:
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


def finish_work(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    task = WORK_BY_NAME[str(action.item)]
    core.end_action(citizen, "done", task.done if task.finish is None else task.finish(core, citizen, action))
