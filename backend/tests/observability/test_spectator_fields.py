"""Replay keeps the spectator facts the feed and `/entities` show (10-world-v1 §6.4): goal and driver, standing,
action targets, gait, purse and load, and animals' drawn paths, goals and targets."""

from collections.abc import Callable
from typing import Any

import pytest

from app.observability.replay import ReplayEvent, ReplayState, apply_event, from_snapshot
from app.services.entities import animal_entity, citizen_entity
from app.sim.items import ITEMS, ItemKind
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot
from app.sim.society import SOCIETY
from app.world_api.facade import WorldApi
from tests.observability.payload_samples import ANIMAL_POSE
from tests.sim_helpers import add_animal, make_spec, without_animals


def _world(new_sim: Callable[..., Simulation]) -> tuple[Simulation, ReplayState]:
    sim = without_animals(new_sim(seed=1))
    sim.add_citizen(make_spec("ann", name="Ann", age=25))
    sim.drain()
    return sim, from_snapshot(take_snapshot(sim.state))


def _apply(state: ReplayState, tick: int, kind: str, actor: str | None, payload: dict[str, Any]) -> None:
    apply_event(state, ReplayEvent(tick, kind, actor, payload))


def test_a_goal_and_standing_with_their_own_group_show(new_sim: Callable[..., Simulation]) -> None:
    _, state = _world(new_sim)
    _apply(state, 1, "goal_set", "ann", {"text": "fill the storehouse", "driver": "duty"})
    standing = {"before": 50, "after": 47, "word": "well regarded", "cause": "theft"}
    _apply(state, 1, "standing_changed", "ann", {"group": "town", **standing})
    _apply(state, 1, "standing_changed", "ann", {"group": "band_a", **standing, "after": -40})  # not her group
    entity = citizen_entity(state.citizens["ann"], 1)
    assert (entity.goal, entity.driver, entity.standing) == ("fill the storehouse", "duty", 47)
    _apply(state, 2, "goal_set", "ann", {"text": "eat something", "driver": "hunger"})
    assert citizen_entity(state.citizens["ann"], 2).goal == "eat something"


def test_an_action_s_target_lasts_as_long_as_the_action(new_sim: Callable[..., Simulation]) -> None:
    _, state = _world(new_sim)
    target = {"kind": "place", "id": "well", "name": "the well", "position": [0.6, 0.48, 0.64]}
    started = {"number": 1, "action": "walk_to", "args": {"place": "the well"}, "label": "the well", "target": target}
    _apply(state, 1, "action_started", "ann", started)
    entity = citizen_entity(state.citizens["ann"], 1)
    assert entity.target is not None and (entity.target.kind, entity.target.name) == ("place", "the well")
    _apply(state, 2, "action_finished", "ann", {"number": 1, "action": "walk_to", "outcome": "done", "text": "ok"})
    assert citizen_entity(state.citizens["ann"], 2).target is None


def test_needs_purse_and_carrying_and_the_gait_of_a_move(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ITEMS, "coins", ItemKind("coins", "a coin", 0.004, 0.0))  # an item kind from E1 on
    sim, state = _world(new_sim)
    ann = state.citizens["ann"]
    ann.inventory = {"coins": 12, "wood": 15}
    unit = sim.citizen("ann").position
    moved = {"position": unit, "height_m": 3.0, "cell": 0, "route": [{"unit": unit, "height_m": 3.0, "t_s": 0.0}]}
    summary = {"moved": {"ann": {**moved, "gait": "run"}}, "bodies": {"ann": [61.0, 20.0, 80.0, 95.0]}}
    _apply(state, 1, "tick_summary", None, summary)
    entity = citizen_entity(ann, 1)
    assert (entity.coins, entity.carrying) == (12, {"wood": 15})
    assert entity.needs.model_dump() == {"hunger": 61.0, "thirst": 20.0, "energy": 80.0, "health": 95.0}
    assert (entity.motion, entity.posture) == ("run", "standing")
    _apply(state, 2, "tick_summary", None, {"moved": {}, "bodies": {}})
    assert citizen_entity(ann, 2).motion == "idle"  # stood still: no gait
    assert (entity.rank, entity.titles, entity.slot_heading) == (2, [], None)  # an untitled adult, on no slot


def test_animals_show_their_drawn_path_goal_and_target(new_sim: Callable[..., Simulation]) -> None:
    sim, _ = _world(new_sim)
    deer = add_animal(sim, "deer", sim.citizen("ann").position)
    state = from_snapshot(take_snapshot(sim.state))
    _apply(state, 1, "tick_summary", None, {"moved": {}, "bodies": {}, "animals": {deer.id: ANIMAL_POSE}})
    entity = animal_entity(state.animals[deer.id])
    assert [p.t_s for p in entity.route] == [0.0, 60.0]
    assert (entity.speed_mps, entity.gait, entity.goal) == (5.0, "trot", "fleeing the wolf")
    assert entity.target is not None and entity.target.id == "wolf:2"
    _apply(state, 2, "tick_summary", None, {"moved": {}, "bodies": {}})
    still = animal_entity(state.animals[deer.id])
    assert (still.route, still.speed_mps) == ([], 0.0)  # it didn't move this tick
    assert (still.gait, still.goal) == ("trot", "fleeing the wolf")  # what it is after stays until it changes


def test_a_goal_told_before_the_snapshot_shows_after_it(new_sim: Callable[..., Simulation]) -> None:
    """Regression (#95): a goal set before the latest snapshot vanished from a replay that starts at it, so the
    inspector's "why" was empty for everyone whose aim hadn't changed since."""
    sim = without_animals(new_sim(seed=1))
    WorldApi(sim, sim.add_citizen(make_spec("ann", name="Ann", age=25)).id).set_goal("tend the rice fields", "duty")
    sim.add_citizen(make_spec("bob", name="Bob", age=30))
    sim.drain()
    state = from_snapshot(take_snapshot(sim.state))
    ann, bob = citizen_entity(state.citizens["ann"], 0), citizen_entity(state.citizens["bob"], 0)
    assert (ann.goal, ann.driver) == ("tend the rice fields", "duty")
    assert (bob.goal, bob.driver) == ("", None)  # told nothing yet


def test_standing_rank_and_titles_come_from_the_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim, _ = _world(new_sim)
    society = SOCIETY.of(sim.state)
    society.standing["ann"] |= {"town": 33, "band_a": -12}
    society.members["ann"].titles.append("samurai")
    ann = from_snapshot(take_snapshot(sim.state)).citizens["ann"]
    entity = citizen_entity(ann, 0)
    assert (entity.standing, entity.rank, entity.titles) == (33, 4, ["samurai"])  # the feed: with her own group
    assert (ann.standing["town"], ann.standing["band_a"]) == (33, -12)  # replay keeps every group's


def _crown(state: ReplayState, heir: str, title: str, previous: str | None, cause: str) -> None:
    _apply(state, 3, "leader_changed", heir, {"group": "town", "title": title, "previous": previous, "cause": cause})


def _titles(state: ReplayState, citizen_id: str) -> tuple[int | None, list[str]]:
    entity = citizen_entity(state.citizens[citizen_id], 3)
    return entity.rank, entity.titles


def test_titles_move_as_society_moves_them(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim(seed=1))
    for citizen_id in ("lord", "heir", "chief", "rival"):
        sim.add_citizen(make_spec(citizen_id, name=citizen_id.title(), age=40))
    society = SOCIETY.of(sim.state)
    society.members["lord"].titles.append("lord")
    society.members["heir"].titles.append("samurai")
    society.members["chief"].titles.append("leader")
    sim.drain()
    state = from_snapshot(take_snapshot(sim.state))
    assert [_titles(state, c) for c in ("lord", "heir", "chief")] == [(5, ["lord"]), (4, ["samurai"]), (4, ["leader"])]

    _crown(state, "rival", "leader", "chief", "standing")  # overtaken: the old leader steps down
    assert (_titles(state, "rival"), _titles(state, "chief")) == ((4, ["leader"]), (2, []))

    _apply(state, 3, "died", "lord", {"cause": "starvation"})  # the dead hold no title
    assert _titles(state, "lord") == (2, [])
    _crown(state, "heir", "lord", "lord", "succession")  # the samurai becomes lord
    assert _titles(state, "heir") == (5, ["lord"])

    _apply(state, 3, "died", "rival", {"cause": "starvation"})
    _crown(state, "chief", "leader", "rival", "death")
    assert (_titles(state, "rival"), _titles(state, "chief")) == ((2, []), (4, ["leader"]))
