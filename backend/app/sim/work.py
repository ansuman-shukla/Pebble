"""Role work (03 `work(task)`): the task table, starting a task where it is done, and what finishing it does.

`WORK_TASKS` is a seam: a later system adds its task as a row, with its finisher living in that system's module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.observability.events import JsonScalar
from app.sim import crafting, market, paddies, reach, slots, society, tax
from app.sim.acting import begin, settled
from app.sim.core import SimCore
from app.sim.exchange import storehouse_in_reach
from app.sim.items import ITEMS
from app.sim.perception import HOME_RADIUS_M, normalize
from app.sim.state import ActionState, Citizen
from app.sim.vec import Vec3
from app.world_api.models import Work

FIELD_ID = "rice-fields"  # the town's paddies: a place

WorkFinisher = Callable[[SimCore, Citizen, ActionState], str]  # does the task's work; returns the result text
WorkTiming = Callable[[SimCore, Citizen], int | str]  # minutes the task takes now, or why it can't be done now
WorkSpotFinder = Callable[[SimCore, Citizen], slots.Slot | str]  # a node's spot it is done at (claimed), or why none


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
    timing: WorkTiming | None = None  # a task whose length or chance hangs on the world (else `minutes`, any time)
    spot: WorkSpotFinder | None = None  # a task done at a node's spot (the paddies) rather than at a layout slot


WORK_TASKS: tuple[WorkTask, ...] = (
    WorkTask(
        "farm",
        frozenset({"farm", "farming", "fields", "field", "paddies", "rice", "tend", "harvest"}),
        60,
        "farming",
        places=(FIELD_ID,),
        nowhere="There are no fields here to tend.",
        label="tending the rice paddies",
        finish=paddies.farm,
        timing=paddies.minutes,
        spot=paddies.take_spot,
    ),
    WorkTask(
        "store food",
        frozenset({"store", "storehouse", "stores", "granary"}),
        5,
        None,
        at="storehouse",
        nowhere="There's no storehouse within reach.",
        label="filling the storehouse",
        finish=tax.store_food,
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
        finish=market.trade,
    ),
    WorkTask(
        "weave",
        frozenset({"weave", "weaving", "loom", "cloth"}),
        60,
        "weaving",
        at="home",
        nowhere="Your loom is at home.",
        label="weaving at the loom",
        finish=crafting.weave,
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
    WorkTask(
        "ring bell",
        frozenset({"bell", "bells", "ring"}),
        5,
        None,
        places=(society.BELL_TOWER,),
        nowhere="There is no bell here.",
        label="waiting to ring the temple bell",  # keeping the hour; it rings as the work ends
        finish=society.ring_bell,
        timing=society.ring_timing,
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
    area: tuple[Vec3, float] = (citizen.position, 0.0)  # where its slots may be: the place, or round the home's door
    if task.at == "storehouse":
        store_id = storehouse_in_reach(core, citizen)
        if store_id is None:
            return settled(core, citizen, "work", "failed", task.nowhere)
        if not any(ITEMS[item].food > 0 for item in citizen.inventory):
            return settled(core, citizen, "work", "failed", "You aren't carrying any food to store.")
    elif task.at == "home":
        home = core.world.structures.get(citizen.home) if citizen.home is not None else None
        if home is None or core.distance_m(citizen.position, home.door) > HOME_RADIUS_M:
            return settled(core, citizen, "work", "failed", task.nowhere)
        area = (home.door, HOME_RADIUS_M)
    else:
        places = [core.world.places[place_id] for place_id in task.places]
        here = [place for place in places if core.distance_m(citizen.position, place.centre) <= place.radius_m]
        if not here:
            return settled(core, citizen, "work", "failed", task.nowhere)
        area = (here[0].centre, here[0].radius_m)
    if task.spot is None:
        minutes = task.minutes if task.timing is None else task.timing(core, citizen)
        if isinstance(minutes, str):  # before a slot is claimed, so a refusal holds none
            return settled(core, citizen, "work", "failed", minutes)
        slot = slots.take_work_slot(core, citizen, task.name, area)  # a task with slots is done at one (loom, stall)
    else:  # done at a node's spot (the paddies): the spot taken decides how long (harvest or tend)
        found = task.spot(core, citizen)
        if isinstance(found, str):
            return settled(core, citizen, "work", "failed", found)
        slot = found
        minutes = task.minutes if task.timing is None else task.timing(core, citizen)
        if isinstance(minutes, str):
            slots.release(core, citizen)
            return settled(core, citizen, "work", "failed", minutes)
    if slot == "none here":
        return settled(core, citizen, "work", "failed", task.nowhere)
    if slot == "all taken":
        return settled(core, citizen, "work", "failed", "Others are working there; there's no room for you.")
    args: dict[str, JsonScalar] = {"task": task.name}
    if isinstance(slot, slots.Slot):
        args |= slots.spot_args(slot)
    node = core.world.nodes.index.get(slot.owner) if isinstance(slot, slots.Slot) else None
    target = reach.node_target(core, node) if node is not None else None  # a paddy farmed: the renderer marks it
    work = begin(core, citizen, "work", task.label, args, target=target)
    work.item, work.store_id, work.until_tick = task.name, store_id, core.state.tick + minutes
    return work.number


def finish_work(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    task = WORK_BY_NAME[str(action.item)]
    core.end_action(citizen, "done", task.done if task.finish is None else task.finish(core, citizen, action))
