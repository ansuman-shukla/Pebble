"""The contract's rules: act only on what you perceive or reach, fail in-world, never leak numbers or ids;
interrupts end durative actions with a reason; bodies kill when needs go unmet."""

import re
from collections.abc import Callable

import pytest

from app.observability.events import EventDraft
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi, run_until_done
from app.world_api.models import ActionResult, Perception
from tests.sim_helpers import GATE, WELL, make_spec

FAR_IN_TOWN = (70.0, 85.0)  # the storehouses, ~95 m from the well
LEAK = re.compile(r"\d|dev-|stack-|tester|cell|\bid\b")


def _assert_in_world(*texts: str) -> None:
    for text in texts:
        assert not LEAK.search(text), f"leaks numbers or ids: {text!r}"


def _types(events: list[EventDraft]) -> list[str]:
    return [event.type for event in events]


def test_unknown_or_unseen_targets_fail_in_world(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    results = [
        run_until_done(sim, me.walk_to_place("the temple"), 1),  # never been there, never told
        run_until_done(sim, me.walk_to_person("a woman in red"), 1),
        run_until_done(sim, me.walk_to_thing("boat"), 1),
    ]
    assert results[0] == ActionResult(
        action="walk_to", outcome="failed", text="You don't know a place called the temple."
    )
    assert results[1].text == "You don't see anyone like that."
    assert results[2].text == "You don't see any boat around here."
    assert sim.citizen(me.citizen_id).action is None
    _assert_in_world(*(r.text for r in results))


def test_people_out_of_sight_cannot_be_walked_to_or_given_to(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    far = sim.add_citizen(make_spec("far", at=(-20.0, -140.0), appearance="a man in a fur cloak"))  # ~190 m north
    sim.citizen(me.citizen_id).inventory["berries"] = 3
    assert sim.world.distance_m(sim.citizen(me.citizen_id).position, far.position) > 150
    assert run_until_done(sim, me.walk_to_person("a man in a fur cloak"), 1).text == "You don't see anyone like that."
    assert me.give("berries", "a man in a fur cloak").text == "You don't see anyone like that."
    assert sim.citizen(me.citizen_id).inventory == {"berries": 3}
    assert far.inventory == {}


def test_nothing_within_reach_fails_without_changing_the_world(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(at=FAR_IN_TOWN))
    api = WorldApi(sim, citizen.id)
    resources_before = sim.state.resources.copy()
    sim.drain()
    results = [
        run_until_done(sim, api.drink(), 1),
        run_until_done(sim, api.gather("berries"), 1),
        run_until_done(sim, api.gather("wood"), 1),
        run_until_done(sim, api.eat("berries"), 1),
        api.pick_up("berries"),
        api.drop("nuts"),
        run_until_done(sim, api.flee(), 1),
    ]
    assert [r.text for r in results] == [
        "There's no water within reach.",
        "There are no berries within reach.",
        "You can't gather wood here.",
        "You have no berries, and there are none within reach.",
        "There's no berries within reach.",
        "You aren't carrying any nuts.",
        "You see nothing to run from.",
    ]
    assert all(r.outcome == "failed" for r in results)
    assert (sim.state.resources == resources_before).all()
    assert citizen.inventory == {} and sim.state.ground == {}
    assert "item_moved" not in _types(sim.drain())
    _assert_in_world(*(r.text for r in results))


def test_stacks_must_be_within_reach_to_pick_up(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    dropper = sim.add_citizen(make_spec("dropper", at=WELL))
    sim.add_citizen(make_spec("picker", at=(-20.0, 62.0)))
    dropper.inventory["nuts"] = 5
    assert WorldApi(sim, "dropper").drop("nuts").text == "You put down a handful of nuts."
    picker = WorldApi(sim, "picker")
    assert picker.pick_up("nuts").outcome == "failed"  # ~10 m away
    assert any(thing.label == "a handful of nuts on the ground" for thing in picker.look_around().things)
    assert run_until_done(sim, picker.walk_to_thing("nuts"), 5).outcome == "done"
    assert picker.pick_up("nuts").text == "You pick up a handful of nuts."
    assert sim.citizen("picker").inventory == {"nuts": 5}
    assert sim.state.ground == {}


def test_salt_water_is_not_drinkable(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    world = sim.world
    shore = next(
        cell
        for cell in range(world.cell_count)
        if sim.core.planner.outer.allowed[cell]
        and not world.river[cell]
        and any(world.biome(o) == "shallow_ocean" for o in world.neighbours[cell])
        and not any(world.biome(o) == "lake" for o in world.neighbours[cell])
    )
    citizen = sim.add_citizen(make_spec(at=GATE))
    sim.core.place_at(citizen, world.unit(shore))
    citizen.body.thirst = 50.0
    result = run_until_done(sim, WorldApi(sim, citizen.id).drink(), 1)
    assert result.text == "The water here is salty; you spit it out."
    assert citizen.body.thirst == 50.0


def test_speech_interrupts_a_walk_with_what_was_said(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("caller", name="Caller", at=(0.0, 96.0)))  # just inside the main gate
    walker = sim.add_citizen(make_spec("walker", age=70, at=(0.0, 150.0), knows_people=["caller"]))  # 3 minutes out
    walk = WorldApi(sim, "walker").walk_to_place("the well")
    sim.step()
    said = WorldApi(sim, "caller").say("Wait for me!")
    assert said.text == 'You say: "Wait for me!"'
    result = run_until_done(sim, walk, 5)
    assert result.outcome == "interrupted"
    assert result.text == 'You stop walking: Caller says, "Wait for me!"'
    assert walker.action is None
    heard = WorldApi(sim, "walker").look_around().heard
    assert [(h.who, h.words, h.volume) for h in heard] == [("Caller", "Wait for me!", "normal")]
    assert WorldApi(sim, "walker").look_around().heard == []  # reported once


def test_whispers_only_carry_a_few_steps(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("speaker", at=WELL))
    sim.add_citizen(make_spec("near", at=(-20.0, 54.5)))
    sim.add_citizen(make_spec("far", at=(-20.0, 62.0)))
    WorldApi(sim, "speaker").say("a secret", "whisper")
    WorldApi(sim, "speaker").say("HELLO", "shout")
    assert [h.words for h in sim.citizen("near").heard] == ["a secret", "HELLO"]
    assert [h.words for h in sim.citizen("far").heard] == ["HELLO"]


def test_a_new_person_coming_into_view_interrupts_waiting(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("watcher", at=(0.0, 150.0)))
    sim.add_citizen(make_spec("visitor", at=(-90.0, -90.0), appearance="a woman in a red shawl"))
    wait = WorldApi(sim, "watcher").wait(120)
    WorldApi(sim, "visitor").walk_to_place("the main gate")
    result = run_until_done(sim, wait, 120)
    assert result.outcome == "interrupted"
    assert result.text.startswith("You stop waiting: a woman in a red shawl comes into view")


def test_night_falling_interrupts_waiting_outdoors(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec(at=GATE))
    api = WorldApi(sim, "tester")
    sim.run(10 * 60)  # 18:00 town time
    sim.citizen("tester").body.hunger = sim.citizen("tester").body.thirst = 0.0
    result = run_until_done(sim, api.wait(120), 130)
    assert result.text == "You stop waiting: night is falling."
    assert "night" in api.look_around().time or "dusk" in api.look_around().time


def test_crossing_a_need_threshold_interrupts_with_the_need(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(at=GATE))
    citizen.body.thirst = 59.0
    result = run_until_done(sim, WorldApi(sim, citizen.id).wait(60), 61)
    assert result.text == "You stop waiting: you are getting thirsty."
    assert "thirsty" in WorldApi(sim, citizen.id).check_self().feeling


def test_starting_a_new_action_ends_the_running_one(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = WorldApi(sim, sim.add_citizen(make_spec(at=GATE)).id)
    first = api.wait(60)
    second = api.walk_to_place("the well")
    assert first.result == ActionResult(
        action="wait", outcome="interrupted", text="You stop waiting to do something else."
    )
    assert run_until_done(sim, second, 5).outcome == "done"


def test_starvation_kills_a_citizen_with_water_but_nothing_to_eat(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(at=WELL))
    api = WorldApi(sim, citizen.id)
    for _ in range(6 * 24):  # up to six game days, an hour at a time
        if not citizen.body.alive:
            break
        if citizen.body.thirst > 40:
            run_until_done(sim, api.drink(), 5)
        if citizen.body.alive and citizen.action is None:
            api.wait(60)
        sim.run(60) if citizen.body.alive else None
    assert not citizen.body.alive
    assert citizen.body.cause_of_death == "starvation"
    assert 2.5 * 24 * 60 < sim.tick < 4.5 * 24 * 60
    where = citizen.position
    events = sim.drain()
    deaths = [e for e in events if e.type == "died"]
    assert len(deaths) == 1 and deaths[0].actor_id == citizen.id
    sim.run(30)
    assert citizen.position == where  # the body stays where it fell
    assert citizen.id in sim.state.citizens
    with pytest.raises(ValueError):
        api.look_around()
    others = WorldApi(sim, sim.add_citizen(make_spec("finder", at=(-20.0, 56.0))).id).look_around()
    assert "the still body of a person in a tester cloak" in [p.label for p in others.people]


def test_not_yet_actions_answer_in_world(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = WorldApi(sim, sim.add_citizen(make_spec(at=GATE)).id)
    handles = [api.follow("someone"), api.fish(), api.hunt("deer"), api.make_fire(), api.feed_fire()]
    handles += [api.work("farm"), api.attack("someone")]
    results = [handle.result for handle in handles] + [api.recall("yesterday")]
    assert [(r.outcome, r.text) for r in results if r is not None] == [("failed", "You can't do that yet.")] * 8


def test_giving_needs_reach_and_a_waking_receiver(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    giver = sim.add_citizen(make_spec("giver", at=WELL, knows_people=["taker"]))
    taker = sim.add_citizen(make_spec("taker", name="Taker", at=(-20.0, 54.0)))
    giver.inventory["roots"] = 4
    api = WorldApi(sim, "giver")
    taker.body.asleep = True
    assert api.give("roots", "Taker").text == "Taker is asleep."
    taker.body.asleep = False
    assert api.give("roots", "Taker").text == "Taker takes a handful of roots."
    assert (giver.inventory, taker.inventory) == ({}, {"roots": 4})


def test_names_and_places_are_learned_by_listening(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("local", name="Aiko", at=WELL, knows_places=["town", "well", "market"]))
    newcomer = sim.add_citizen(make_spec("newcomer", at=(-20.0, 56.0), knows_places=["town"]))
    listener = WorldApi(sim, "newcomer")
    before: Perception = listener.look_around()
    assert "a person in a local cloak" in [p.label for p in before.people]
    WorldApi(sim, "local").say("I am Aiko. Fresh fish at the market today!")
    assert "Aiko" in [p.label for p in listener.look_around().people]
    assert newcomer.places["market"].level == "rough"
    result = run_until_done(sim, listener.walk_to_place("the market"), 20)
    assert result.outcome == "done"
    assert "the market" in result.text
    sim.step()
    assert {newcomer.places["market"].level} == {"visited"}  # a set keeps mypy from narrowing the attribute
