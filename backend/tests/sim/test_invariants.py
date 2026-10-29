"""The invariants of 02-simulation: determinism, ranges, one event per change, resumable snapshots."""

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from app.observability.events import EventDraft, ResourceChanged
from app.observability.replay import ReplayEvent, from_snapshot, replay
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.snapshot import canonical_json, restore, state_hash, take_snapshot
from app.world_api.facade import WorldApi
from tests.sim_helpers import GATE, WELL, make_spec, without_animals

Plan = dict[int, list[tuple[str, Callable[[WorldApi], Any]]]]

PLAN: Plan = {
    0: [
        ("ann", lambda api: api.walk_to_place("the well")),
        ("ben", lambda api: api.walk_towards("west", "a long walk")),
        ("cid", lambda api: api.wait(30)),
    ],
    3: [("cid", lambda api: api.say("Hello! I am Cid. The market is busy today.", "shout"))],
    6: [("ann", lambda api: api.drink()), ("cid", lambda api: api.walk_to_person("a person in a ann cloak"))],
    12: [("ben", lambda api: api.gather("berries"))],
    20: [("cid", lambda api: api.look_around())],
    40: [("ben", lambda api: api.gather("roots")), ("ann", lambda api: api.walk_to_place("home"))],
    65: [("ben", lambda api: api.eat("berries")), ("cid", lambda api: api.walk_to_place("the market"))],
    75: [("ben", lambda api: api.drop("roots"))],
    76: [("ben", lambda api: api.pick_up("roots"))],
    80: [("ben", lambda api: api.drop("berries")), ("ann", lambda api: api.rest(90))],
    95: [("ben", lambda api: api.walk_to_place("the main gate"))],
    130: [("cid", lambda api: api.say("Anyone hungry?"))],
    150: [("ann", lambda api: api.say("I am Ann, coming!")), ("ann", lambda api: api.walk_to_place("the market"))],
}


def _spawn(sim: Simulation) -> None:
    sim.add_citizen(make_spec("ann", name="Ann", at=GATE))
    sim.add_citizen(make_spec("ben", name="Ben", at=WELL, age=15))
    sim.add_citizen(make_spec("cid", name="Cid", at=(20.0, 56.0), age=60, knows_places=["town", "market", "well"]))


def _drive(sim: Simulation, until: int, plan: Plan = PLAN) -> None:
    while sim.tick < until:
        for citizen_id, act in plan.get(sim.tick, []):
            if sim.citizen(citizen_id).body.alive:
                act(WorldApi(sim, citizen_id))
        sim.step()


def _replayable(events: list[EventDraft]) -> list[ReplayEvent]:
    return [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]


def _comparable(events: list[EventDraft]) -> list[tuple[Any, ...]]:
    return [
        (e.seq, e.tick, e.type, e.actor_id, e.cause_seq, e.cell, e.position, e.payload.model_dump(mode="json"))
        for e in events
    ]


def test_same_seed_and_inputs_give_the_same_state(new_sim: Callable[..., Simulation]) -> None:
    runs = []
    for _ in range(2):
        sim = new_sim(seed=11)
        _spawn(sim)
        _drive(sim, 180)
        runs.append((state_hash(sim.state), _comparable(sim.drain())))
    assert runs[0] == runs[1]
    other_seed = new_sim(seed=12)
    _spawn(other_seed)
    _drive(other_seed, 180)
    assert state_hash(other_seed.state) != runs[0][0]


def test_the_hash_sees_every_part_of_the_state(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=11)
    _spawn(sim)
    _drive(sim, 30)
    base = state_hash(sim.state)
    changes: list[Callable[[Simulation], None]] = [
        lambda s: setattr(s.citizen("ann").body, "hunger", s.citizen("ann").body.hunger + 1e-9),
        lambda s: s.citizen("ben").inventory.__setitem__("nuts", 1),
        lambda s: s.citizen("cid").people.add("ben"),
        lambda s: s.state.resources.__setitem__((5, 0), 1),
        lambda s: setattr(s.state.rngs["actions"], "state", 7),
        lambda s: setattr(s.state, "next_seq", s.state.next_seq + 1),
    ]
    for change in changes:
        copy = Simulation(sim.world, restore(take_snapshot(sim.state)), sim.core.planner)
        assert state_hash(copy.state) == base
        change(copy)
        assert state_hash(copy.state) != base


def test_needs_resources_and_items_stay_in_range(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=3)
    _spawn(sim)
    caps = sim.world.resource_caps
    plan: Plan = {t: [("ben", lambda api: api.gather("berries"))] for t in range(100, 2 * 24 * 60, 40)}
    plan |= {t: [("ann", lambda api: api.wait(200))] for t in range(0, 2 * 24 * 60, 210)}
    for tick in range(2 * 24 * 60):
        _drive(sim, tick + 1, {**PLAN, **plan} if tick < 200 else plan)
        for citizen in sim.state.citizens.values():
            body = citizen.body
            assert all(0.0 <= value <= 100.0 for value in (body.hunger, body.thirst, body.energy, body.health))
            assert all(count > 0 for count in citizen.inventory.values())
        assert (sim.state.resources <= caps).all()
    assert all(stack.count > 0 for stack in sim.state.ground.values())
    assert not sim.citizen("ann").body.alive or sim.citizen("ann").body.thirst > 0


def test_every_state_change_is_exactly_one_event(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim(seed=5))  # game coming into view would stop Ben's walk into the wild
    start = take_snapshot(sim.state)  # before anyone exists
    events: list[EventDraft] = []
    _spawn(sim)
    for checkpoint in (1, 7, 30, 77, 120, 181):
        _drive(sim, checkpoint)
        events += sim.drain()
        rebuilt = replay(start, _replayable(events))
        assert rebuilt.same_as(from_snapshot(take_snapshot(sim.state))), f"replay diverged by tick {checkpoint}"
    summaries = [e.tick for e in events if e.type == "tick_summary"]
    assert summaries == list(range(1, 182))
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    types = {e.type for e in events}
    assert {"item_moved", "resource_changed", "action_started", "action_finished", "said"} <= types

    final = from_snapshot(take_snapshot(sim.state))

    def reaches_final(stream: list[EventDraft]) -> bool:
        try:
            return replay(start, _replayable(stream)).same_as(final)
        except (KeyError, ValueError):  # the stream refers to someone or something that never appeared
            return False

    def stock(event: EventDraft) -> tuple[int, str] | None:
        payload = event.payload
        return (payload.cell, payload.resource) if isinstance(payload, ResourceChanged) else None

    def overwritten(index: int) -> bool:  # resource_changed carries the absolute stock: a later change replaces it
        return any(stock(later) == stock(events[index]) for later in events[index + 1 :])

    for index, event in enumerate(events):
        checked = event.type in ("citizen_spawned", "item_moved") or (
            event.type == "resource_changed" and not overwritten(index)
        )
        if checked:
            assert not reaches_final(events[:index] + events[index + 1 :]), f"{event.type} #{event.seq} is redundant"
        if event.type == "item_moved":  # a delta (resource_changed carries absolute values)
            assert not reaches_final(events[: index + 1] + events[index:]), f"{event.type} #{event.seq} counted twice"


def test_a_snapshot_resumes_into_the_same_future(new_sim: Callable[..., Simulation], planner: Planner) -> None:
    straight = new_sim(seed=9)
    _spawn(straight)
    _drive(straight, 60)
    snapshot = take_snapshot(straight.state)
    saved = canonical_json(snapshot)
    straight.drain()
    _drive(straight, 180)
    future = _comparable(straight.drain())

    resumed = Simulation(straight.world, restore(snapshot), planner)
    _drive(resumed, 180)
    assert _comparable(resumed.drain()) == future
    assert state_hash(resumed.state) == state_hash(straight.state)
    assert canonical_json(snapshot) == saved  # resuming didn't touch the snapshot


def test_snapshots_survive_json_round_trips(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=2)
    _spawn(sim)
    _drive(sim, 90)
    snapshot = take_snapshot(sim.state)
    again = type(snapshot).model_validate_json(snapshot.model_dump_json())
    assert canonical_json(again) == canonical_json(snapshot)
    restored = restore(again)
    assert state_hash(restored) == state_hash(sim.state)
    assert np.array_equal(restored.resources, sim.state.resources)
    with pytest.raises(ValueError):
        restore(snapshot.model_copy(update={"version": 99}))
