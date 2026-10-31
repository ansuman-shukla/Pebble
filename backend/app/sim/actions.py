"""Actions (03-actions-perception): instant ones change the world at once; durative ones start here, advance each
tick and end on completion or interrupt. Every failure is an in-world sentence; nothing reveals numbers or ids.

This module dispatches: each action's handlers live in their own module (movement, resting, doing, work, exchange,
expression, market, crafting, wild), one row per action in the tables below. It also decides what interrupts a running
action.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.sim import crafting, doing, exchange, expression, market, movement, resting, wild, work
from app.sim.acting import VERB, refuse, settled
from app.sim.bodies import COLLAPSE_WAKE_ENERGY, Crossing
from app.sim.clock import NIGHT_ALTITUDE_DEG, sun_altitude_deg, sun_direction
from app.sim.core import SimCore
from app.sim.fauna import DANGEROUS, SPECIES
from app.sim.perception import WATCHING_M, from_where, person_label, where_words
from app.sim.state import ActionState, Animal, Citizen
from app.sim.vec import Vec3, bearing_deg
from app.world_api.models import (
    Action,
    ActionName,
    ActionResult,
    Attack,
    Buy,
    Craft,
    Drink,
    Drop,
    Eat,
    FeedFire,
    Fish,
    Flee,
    Follow,
    Gather,
    Gesture,
    Give,
    Hunt,
    MakeFire,
    PickUp,
    Rest,
    Say,
    Sell,
    SetGoal,
    Sleep,
    Stash,
    Volume,
    Wait,
    WalkTo,
    Work,
)

APPROACH_M = 10.0  # a known person walking up to you interrupts once they come this close
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

Starter = Callable[[SimCore, Citizen, Action], int]  # starts a durative action; returns its number
Instant = Callable[[SimCore, Citizen, Action], ActionResult]
Advancer = Callable[[SimCore, Citizen, ActionState], None]  # once per tick while the action runs
Finisher = Callable[[SimCore, Citizen, ActionState], None]  # when a timed action's time is up; must end it


def handles[M: BaseModel, R](
    model: type[M], handler: Callable[[SimCore, Citizen, M], R]
) -> Callable[[SimCore, Citizen, Action], R]:
    """A table row: `handler` takes one action model (checked, so a row under the wrong name fails loudly)."""

    def run(core: SimCore, citizen: Citizen, action: Action) -> R:
        if not isinstance(action, model):
            raise TypeError(f"{action.action} is not handled by {model.__name__}")
        return handler(core, citizen, action)

    return run


INSTANTS: dict[ActionName, Instant] = {
    "say": handles(Say, exchange.say),
    "pick_up": handles(PickUp, exchange.pick_up),
    "drop": handles(Drop, exchange.drop),
    "give": handles(Give, exchange.give),
    "gesture": handles(Gesture, expression.gesture),
    "set_goal": handles(SetGoal, expression.set_goal),
    "stash": handles(Stash, exchange.stash),
    "buy": handles(Buy, market.buy),
    "sell": handles(Sell, market.sell),
}
STARTS: dict[ActionName, Starter] = {
    "walk_to": handles(WalkTo, movement.start_walk),
    "gather": handles(Gather, doing.start_gather),
    "eat": handles(Eat, doing.start_eat),
    "drink": handles(Drink, doing.start_drink),
    "rest": handles(Rest, resting.start_rest),
    "wait": handles(Wait, resting.start_rest),
    "sleep": handles(Sleep, resting.start_sleep),
    "flee": handles(Flee, movement.start_flee),
    "follow": handles(Follow, movement.start_follow),
    "work": handles(Work, work.start_work),
    "hunt": handles(Hunt, wild.start_hunt),
    "attack": handles(Attack, wild.start_attack),
    "fish": handles(Fish, lambda core, citizen, _action: wild.start_fish(core, citizen)),
    "make_fire": handles(MakeFire, lambda core, citizen, _action: wild.start_make_fire(core, citizen)),
    "feed_fire": handles(FeedFire, lambda core, citizen, _action: wild.start_feed_fire(core, citizen)),
    "craft": handles(Craft, crafting.start_craft),
}
ADVANCES: dict[ActionName, Advancer] = {  # actions not listed here wait for their `until_tick`, then finish
    "walk_to": movement.advance_walk,
    "flee": movement.advance_walk,
    "follow": movement.advance_walk,
    "hunt": wild.advance_stalk,
    "attack": wild.advance_stalk,
    "sleep": resting.advance_sleep,
}
FINISHES: dict[ActionName, Finisher] = {
    "gather": doing.finish_gather,
    "eat": doing.finish_eat,
    "drink": doing.finish_drink,
    "rest": resting.finish_rest,
    "wait": resting.finish_wait,
    "work": work.finish_work,
    "fish": wild.complete,
    "make_fire": wild.complete,
    "feed_fire": wild.complete,
    "craft": crafting.finish_craft,
}
_NIGHT_STOPS = frozenset({"walk_to", "follow", "gather", "wait", "rest", "work", "hunt", "fish"})
_NEED_STOPS = frozenset({"walk_to", "follow", "gather", "wait", "rest", "flee", "work", "hunt", "fish", "craft"})


def not_yet(core: SimCore, citizen: Citizen, kind: ActionName) -> ActionResult:
    return refuse(core, citizen, kind, NOT_YET)


def instant(core: SimCore, citizen: Citizen, action: Action) -> ActionResult:
    handler = INSTANTS.get(action.action)
    if handler is None:
        raise ValueError(f"no instant handler for {action.action}")
    return handler(core, citizen, action)


def start(core: SimCore, citizen: Citizen, action: Action) -> int:
    """Start a durative action (ending any running one); returns its number. Results arrive via `results`."""
    current = citizen.action
    if current is not None and current.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY:
        return settled(core, citizen, action.action, "failed", "You are too exhausted to move.")
    starter = STARTS.get(action.action)
    if starter is None:  # in the contract, not in the world yet: what you are doing goes on
        return settled(core, citizen, action.action, "failed", NOT_YET)
    if current is not None:
        text = "You get up." if current.kind == "sleep" else f"You stop {VERB[current.kind]} to do something else."
        _interrupt(core, citizen, current, text, None)
        if not citizen.body.alive:  # what they had eaten so far killed them
            return settled(core, citizen, action.action, "failed", "Everything goes dark.")
    return starter(core, citizen, action)


def advance(core: SimCore, citizen: Citizen) -> None:
    """Once per tick: the running action moves on, or finishes when its time is up."""
    action = citizen.action
    if action is None:
        return
    advancer = ADVANCES.get(action.kind)
    if advancer is not None:
        advancer(core, citizen, action)
    elif action.until_tick is not None and core.state.tick >= action.until_tick:
        finisher = FINISHES.get(action.kind)
        if finisher is None:
            raise ValueError(f"{action.kind} has no timed completion")
        finisher(core, citizen, action)


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


def body_activity(action: ActionState | None) -> str | None:
    """What the body is doing for need rates: the action, or the work task (farming is hard work)."""
    if action is None:
        return None
    return str(action.item) if action.kind == "work" else action.kind


def walking_to(citizen: Citizen) -> str | None:
    """The person a walk heads for (walk_to a person), if any."""
    action = citizen.action
    if action is None or action.kind != "walk_to":
        return None
    return action.target_id


def approaching(
    core: SimCore,
    citizen: Citizen,
    seen: set[str],
    before: dict[str, Vec3],
    walk_targets: dict[str, str | None],
) -> list[str]:
    """Known people in view who came within APPROACH_M this tick while walking to the citizen (someone merely heading
    to the same well, market or field as you doesn't count, even when their walk ends where you stand)."""
    found: list[str] = []
    for person_id in sorted(seen & citizen.people):
        if walk_targets.get(person_id) != citizen.id or person_id not in before:
            continue
        other = core.state.citizens[person_id]
        if core.distance_m(citizen.position, other.position) > APPROACH_M:
            continue
        if core.distance_m(before.get(citizen.id, citizen.position), before[person_id]) <= APPROACH_M:
            continue  # already close
        found.append(person_id)
    return found


def _interrupt(core: SimCore, citizen: Citizen, action: ActionState, text: str, cause_seq: int | None) -> None:
    doing.apply_partial(core, citizen, action)
    if citizen.body.alive:  # raw food eaten so far can kill, and dying has ended the action
        core.end_action(citizen, "interrupted", text, cause_seq)


def _names(words: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name.lower())}\b", words.lower()) is not None


def _where(core: SimCore, citizen: Citizen, other: Citizen) -> str:
    return where_words(core.distance_m(citizen.position, other.position), bearing_deg(citizen.position, other.position))


def night_fell(core: SimCore, citizen: Citizen) -> bool:
    before = sun_altitude_deg(citizen.position, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    return before >= NIGHT_ALTITUDE_DEG > core.altitude(citizen.position)
