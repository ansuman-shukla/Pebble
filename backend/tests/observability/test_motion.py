"""Citizens' motion and posture (10-world-v1 §4.5): one table from what the sim knows, and replay tells the same
motion at every tick as the sim had."""

from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from app.engine import citizen_brains
from app.observability.events import JsonScalar, TickSummary
from app.observability.replay import ReplayEvent, apply_event, from_snapshot
from app.services.entities import TALKING_TICKS, citizen_entity
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.locomotion import Gait
from app.sim.motion import BodyMotion, body_motion, load_share
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot


def _motion(
    action: str | None = None,
    args: Mapping[str, JsonScalar] | None = None,
    *,
    alive: bool = True,
    asleep: bool = False,
    gait: Gait | None = None,
    load: float = 0.0,
    talking: bool = False,
) -> tuple[str, str]:
    body = body_motion(
        alive=alive, asleep=asleep, action=action, args=args or {}, gait=gait, load=load, talking=talking
    )
    return body.motion, body.posture


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"alive": False, "action": "gather", "args": {"resource": "berries"}}, ("lie", "lying")),
        ({"asleep": True, "action": "sleep"}, ("lie", "lying")),
        ({"asleep": True, "action": "sleep", "args": {"collapsed": True}}, ("lie", "lying")),
        ({"action": "walk_to", "gait": "walk"}, ("walk", "standing")),
        ({"action": "walk_to", "gait": "walk", "load": 0.5}, ("carry_walk", "standing")),
        ({"action": "walk_to", "gait": "walk", "load": 0.49}, ("walk", "standing")),
        ({"action": "flee", "gait": "run", "load": 0.9}, ("run", "standing")),
        ({"action": "follow", "gait": "jog"}, ("jog", "standing")),
        ({"action": "hunt", "gait": "stalk"}, ("stalk", "standing")),
        ({"action": "hunt"}, ("stalk", "standing")),
        ({"action": "hunt", "gait": "run"}, ("run", "standing")),  # the chase
        ({"action": "walk_to"}, ("idle", "standing")),  # arrived, or blocked: standing
        ({"action": "gather", "args": {"resource": "berries"}}, ("gather_high", "standing")),
        ({"action": "gather", "args": {"resource": "nuts"}}, ("gather_high", "standing")),
        ({"action": "gather", "args": {"resource": "roots"}}, ("gather_low", "crouching")),
        ({"action": "gather", "args": {"resource": "wood"}}, ("gather_low", "crouching")),
        ({"action": "gather", "args": {"resource": "iron sand"}}, ("mine", "standing")),
        ({"action": "gather", "args": {"resource": "gold"}}, ("pan", "crouching")),
        ({"action": "work", "args": {"task": "farm"}}, ("farm", "standing")),
        ({"action": "work", "args": {"task": "weave"}}, ("craft", "crouching")),
        ({"action": "work", "args": {"task": "trade"}}, ("trade", "standing")),
        ({"action": "work", "args": {"task": "store food"}}, ("pick_up", "standing")),
        ({"action": "work", "args": {"task": "govern"}}, ("talk", "standing")),
        ({"action": "work", "args": {"task": "pray"}}, ("pray", "sitting_ground")),
        ({"action": "work", "args": {"task": "guard"}}, ("idle", "standing")),
        ({"action": "work", "args": {"task": "juggle"}}, ("idle", "standing")),
        ({"action": "rest", "args": {"minutes": 30}}, ("sit_ground", "sitting_ground")),
        ({"action": "fish"}, ("fish", "standing")),
        ({"action": "attack"}, ("attack", "standing")),
        ({"action": "eat"}, ("eat", "standing")),
        ({"action": "drink"}, ("drink", "standing")),
        ({"action": "make_fire"}, ("tend", "crouching")),
        ({"action": "feed_fire"}, ("pick_up", "standing")),
        ({}, ("idle", "standing")),
        ({"talking": True}, ("talk", "standing")),
        ({"action": "wait", "talking": True}, ("talk", "standing")),
        ({"action": "walk_to", "talking": True}, ("talk", "standing")),  # arrived and speaking
        ({"action": "gather", "args": {"resource": "roots"}, "talking": True}, ("gather_low", "crouching")),
    ],
)
def test_the_motion_table(kwargs: dict[str, Any], expected: tuple[str, str]) -> None:
    assert _motion(**kwargs) == expected


BENCH = {"slot": "b#seat-1", "where": "on the bench", "posture": "sitting", "facing": 90.0, "seat_m": 0.45}
LOOM = {"slot": "l#seat", "where": "at the loom", "posture": "sitting", "facing": 180.0, "seat_m": 0.3, "task": "weave"}
MAT = {"slot": "c#mat-1", "where": "on a mat", "posture": "lying", "facing": 45.0, "seat_m": 0.0}
INSIDE = {"slot": "h#inside", "where": "inside", "posture": "inside", "facing": 0.0, "seat_m": 0.0}
STALL = {"slot": "m#stall", "where": "at the stall", "posture": "standing", "facing": 270.0, "seat_m": 0.0}
PRAY = {"slot": "t#pray-1", "where": "before the hall", "posture": "sitting_ground", "facing": 180.0, "seat_m": 0.0}


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"action": "rest", "args": BENCH}, BodyMotion("sit", "sitting", 90.0, 0.45)),
        ({"action": "rest", "args": BENCH, "gait": "walk"}, BodyMotion("walk", "standing")),  # stepping onto it
        (
            {"action": "rest", "args": {"slot": None, "where": "on the ground"}},
            BodyMotion("sit_ground", "sitting_ground"),
        ),
        ({"action": "work", "args": LOOM}, BodyMotion("craft", "sitting", 180.0, 0.3)),
        ({"action": "work", "args": {**STALL, "task": "trade"}}, BodyMotion("trade", "standing", 270.0)),
        ({"action": "work", "args": {**STALL, "task": "weave"}}, BodyMotion("craft", "crouching", 270.0)),  # its own
        ({"action": "work", "args": {**PRAY, "task": "pray"}}, BodyMotion("pray", "sitting_ground", 180.0)),
        ({"action": "sleep", "args": MAT, "asleep": True}, BodyMotion("lie", "lying", 45.0)),
        ({"action": "sleep", "args": INSIDE, "asleep": True}, BodyMotion("inside", "inside")),
        ({"action": "sleep", "args": INSIDE, "asleep": True, "gait": "walk"}, BodyMotion("inside", "inside")),
        ({"action": "sleep", "args": INSIDE, "alive": False}, BodyMotion("lie", "lying")),  # died in their sleep
    ],
)
def test_a_body_on_its_slot_rests_the_slot_s_way(kwargs: dict[str, Any], expected: BodyMotion) -> None:
    """S1's slots (D119): the action's args say how the body rests on the slot it took, and which way it faces."""
    args = kwargs.pop("args")
    defaults: dict[str, Any] = {"alive": True, "asleep": False, "gait": None, "load": 0.0, "talking": False}
    assert body_motion(**(defaults | kwargs), args=args) == expected


def test_load_is_the_share_of_what_their_age_can_carry() -> None:
    assert load_share({}, "young_adult") == 0.0
    assert load_share({"wood": 5, "rice": 25}, "young_adult") == pytest.approx(10 / 25)
    assert load_share({"wood": 5}, "elder") == pytest.approx(5 / 10)


def test_replay_tells_the_motion_the_sim_had_at_every_tick(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=7)
    cast = load_citizens(CITIZENS)
    for store_id, items in cast.stores.items():
        for item, count in items.items():
            sim.stock_store(store_id, item, count)
    for spec in cast.citizens:
        sim.add_citizen(spec)
    sim.drain()
    replayed = from_snapshot(take_snapshot(sim.state))
    brains = citizen_brains(sim, 7)
    spoke: dict[str, int] = {}
    seen: Counter[str] = Counter()
    for _ in range(900):
        brains(sim)
        sim.step()
        events = sim.drain()
        moved: dict[str, Gait] = {}
        for event in events:
            apply_event(replayed, ReplayEvent(event.tick, event.type, event.actor_id, event.payload.model_dump()))
            if event.type == "said" and event.actor_id is not None:
                spoke[event.actor_id] = event.tick
            if isinstance(event.payload, TickSummary):
                moved = {cid: m.gait for cid, m in event.payload.moved.items() if m.route}
        for citizen in sim.state.citizens.values():
            action = citizen.action
            truth = body_motion(
                alive=citizen.body.alive,
                asleep=citizen.body.asleep,
                action=action.kind if action is not None else None,
                args=action.args if action is not None else {},
                gait=moved.get(citizen.id),
                load=sim.core.carried_kg(citizen) / citizen.traits.carry_kg,
                talking=sim.tick - spoke.get(citizen.id, -TALKING_TICKS) < TALKING_TICKS,
            )
            entity = citizen_entity(replayed.citizens[citizen.id], sim.tick)
            shown = BodyMotion(entity.motion, entity.posture, entity.slot_heading, entity.slot_height_m)
            assert shown == truth, (sim.tick, citizen.id)
            seen[truth.motion] += 1
    exercised = {
        "walk",
        "carry_walk",
        "idle",
        "talk",
        "lie",
        "sit_ground",
        "gather_low",
        "gather_high",
        "farm",
        "craft",
        "inside",
        "sit",
    }
    assert exercised | {"trade", "eat", "drink", "tend", "pick_up"} <= set(seen), seen  # the run really used the table
