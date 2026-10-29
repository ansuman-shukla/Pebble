"""The contract's rules: act only on what you perceive or reach, fail in-world, never leak numbers or ids;
interrupts end durative actions with a reason; bodies kill when needs go unmet."""

import re
from collections.abc import Callable

import pytest

from app.observability.events import EventDraft
from app.sim.simulation import Simulation
from app.sim.vec import step_towards
from app.world_api.facade import WorldApi, run_until_done
from app.world_api.models import ActionResult, Perception
from tests.sim_helpers import GATE, WELL, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

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
    ground_before = {stack_id: stack.count for stack_id, stack in sim.state.ground.items()}  # the camps' woodpiles
    sim.drain()
    results = [
        run_until_done(sim, api.drink(), 1),
        run_until_done(sim, api.gather("berries"), 1),
        run_until_done(sim, api.gather("flint"), 1),
        run_until_done(sim, api.eat("berries"), 1),
        api.pick_up("berries"),
        api.drop("nuts"),
        run_until_done(sim, api.flee(), 1),
    ]
    assert [r.text for r in results] == [
        "There's no water within reach.",
        "There are no berries within reach.",
        "You can't gather flint here.",
        "You have no berries, and there are none within reach.",
        "There's no berries within reach.",
        "You aren't carrying any nuts.",
        "You see nothing to run from.",
    ]
    assert all(r.outcome == "failed" for r in results)
    assert (sim.state.resources == resources_before).all()
    assert citizen.inventory == {}
    assert {stack_id: stack.count for stack_id, stack in sim.state.ground.items()} == ground_before
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
    assert not [stack for stack in sim.state.ground.values() if stack.item == "nuts"]


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
    deaths = [e for e in events if e.type == "died" and e.actor_kind == "citizen"]
    assert len(deaths) == 1 and deaths[0].actor_id == citizen.id
    sim.run(30)
    assert citizen.position == where  # the body stays where it fell
    assert citizen.id in sim.state.citizens
    with pytest.raises(ValueError):
        api.look_around()
    others = WorldApi(sim, sim.add_citizen(make_spec("finder", at=(-20.0, 56.0))).id).look_around()
    assert "the still body of a person in a tester cloak" in [p.label for p in others.people]


def test_recall_answers_in_world_until_minds_have_memories(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = WorldApi(sim, sim.add_citizen(make_spec(at=GATE)).id)
    assert api.recall("yesterday") == ActionResult(action="recall", outcome="failed", text="You can't do that yet.")


def test_wild_actions_fail_in_world_inside_the_town(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = WorldApi(sim, sim.add_citizen(make_spec(at=FAR_IN_TOWN)).id)
    handles = [api.fish(), api.hunt("unicorns"), api.make_fire(), api.feed_fire(), api.attack("someone")]
    results = [handle.result for handle in handles]
    assert [(r.outcome, r.text) for r in results if r is not None] == [
        ("failed", "There's no water to fish in here."),
        ("failed", "You don't see any unicorns around here."),
        ("failed", "You don't know how to make fire."),
        ("failed", "There's no fire within reach."),
        ("failed", "You don't see anyone or anything like that."),
    ]
    _assert_in_world(*(r.text for r in results if r is not None))


def test_giving_needs_reach_and_a_waking_receiver(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    giver = sim.add_citizen(make_spec("giver", at=WELL, knows_people=["taker"]))
    taker = sim.add_citizen(make_spec("taker", name="Taker", at=(-20.0, 54.0)))
    giver.inventory["roots"] = 4
    api = WorldApi(sim, "giver")
    taker.body.asleep = True
    assert api.give("roots", "Taker").text == "Taker is asleep."
    taker.body.asleep = False
    assert api.give("a root", "Taker").text == "Taker takes a root."
    assert (giver.inventory, taker.inventory) == ({"roots": 3}, {"roots": 1})
    assert api.give("roots", "Taker").text == "Taker takes a few roots."  # no amount said: all of them
    assert (giver.inventory, taker.inventory) == ({}, {"roots": 4})


@pytest.mark.parametrize(
    ("words", "given", "dropped"),  # of 10 berries: how many are given, then how many of those are put down
    [
        ("berries", 10, 10),
        ("a berry", 1, 1),
        ("two berries", 2, 2),
        ("3 berries", 3, 3),
        ("half the berries", 5, 3),
        ("a few berries", 3, 3),
        ("a handful of berries", 8, 8),
        ("a great many berries", 10, 10),
        ("some berries", 10, 10),
        ("all the berries", 10, 10),
        ("twelve berries", 10, 10),
    ],
)
def test_amounts_in_the_words_say_how_many_to_hand_over(
    new_sim: Callable[..., Simulation], words: str, given: int, dropped: int
) -> None:
    sim = new_sim()
    giver = sim.add_citizen(make_spec("giver", at=WELL, knows_people=["taker"]))
    taker = sim.add_citizen(make_spec("taker", name="Taker", at=(-20.0, 54.0)))
    giver.inventory["berries"] = 10
    assert WorldApi(sim, "giver").give(words, "Taker").outcome == "done"
    assert (giver.inventory.get("berries", 0), taker.inventory) == (10 - given, {"berries": given})
    taker_api = WorldApi(sim, "taker")
    assert taker_api.drop(words).outcome == "done"
    on_ground = sum(stack.count for stack in sim.state.ground.values() if stack.item == "berries")
    assert (taker.inventory.get("berries", 0), on_ground) == (given - dropped, dropped)
    assert taker_api.pick_up("a berry").text == "You pick up a berry."
    assert sum(stack.count for stack in sim.state.ground.values() if stack.item == "berries") == dropped - 1


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


def test_sight_shrinks_at_night_and_in_forest(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("seer", at=(0.0, 150.0)))
    sim.add_citizen(make_spec("seen", at=(0.0, 110.0), appearance="a woman in a red shawl"))  # 40 m away
    seer = WorldApi(sim, "seer")
    assert [p.label for p in seer.look_around().people] == ["a woman in a red shawl"]
    sim.run(16 * 60)  # midnight
    assert seer.look_around().people == []
    sim.run(8 * 60)  # 08:00 again
    assert len(seer.look_around().people) == 1

    world = sim.world
    forest = next(
        cell
        for cell in range(world.cell_count)
        if world.biome(cell) == "broadleaf_forest"
        and all(world.biome(o) == "broadleaf_forest" for o in world.neighbours[cell])
    )
    sim.core.place_at(sim.citizen("seer"), world.unit(forest))
    assert world.biome(sim.citizen("seer").cell) == "broadleaf_forest"
    sim.core.place_at(sim.citizen("seen"), step_towards(world.unit(forest), 0.0, 80.0, world.radius_m))
    assert seer.look_around().people == []  # 80 m: beyond forest sight (150 m x 0.4)
    sim.core.place_at(sim.citizen("seen"), step_towards(world.unit(forest), 0.0, 40.0, world.radius_m))
    assert len(seer.look_around().people) == 1


def test_giving_needs_the_receiver_within_reach(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    giver = sim.add_citizen(make_spec("giver", at=WELL, knows_people=["taker"]))
    sim.add_citizen(make_spec("taker", name="Taker", at=(-20.0, 62.0)))  # ~10 m off, in plain view
    giver.inventory["roots"] = 2
    assert WorldApi(sim, "giver").give("roots", "Taker").text == "Taker is too far away to hand anything to."
    assert giver.inventory == {"roots": 2}


def test_gathering_never_takes_more_than_grows_there(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())  # nothing comes into view to cut the gathering short
    citizen = sim.add_citizen(make_spec(at=GATE))
    world = sim.world
    cell = next(
        c for c in range(world.cell_count) if sim.state.resources[c, 0] > 0 and sim.core.planner.outer.allowed[c]
    )
    sim.core.place_at(citizen, world.unit(cell))
    sim.state.resources[cell, 0] = 2
    api = WorldApi(sim, citizen.id)
    assert run_until_done(sim, api.gather("berries"), 25).text == "You gather a few berries."
    assert citizen.inventory == {"berries": 2}
    assert sim.state.resources[cell, 0] == 0
    assert run_until_done(sim, api.gather("berries"), 1).text == "There are no berries within reach."


def _first_cell(sim: Simulation, test: Callable[[int], bool]) -> int:
    world = sim.world
    return next(c for c in range(world.cell_count) if sim.core.planner.outer.allowed[c] and test(c))


def test_rivers_are_drinkable_and_hot_ground_dries_you_out(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    world = sim.world
    drinker = sim.add_citizen(make_spec("drinker", at=GATE))
    sim.core.place_at(drinker, world.unit(_first_cell(sim, lambda c: bool(world.river[c]))))
    drinker.body.thirst = 50.0
    result = run_until_done(sim, WorldApi(sim, "drinker").drink(), 5)
    assert result.text == "You drink from the river until you are no longer thirsty."

    walker = sim.add_citizen(make_spec("walker", at=GATE))
    hot = sim.add_citizen(make_spec("hot", at=GATE))
    sim.core.place_at(hot, world.unit(_first_cell(sim, lambda c: world.biome(c) == "savanna")))
    sim.run(60)
    assert walker.body.thirst == pytest.approx(6.0)
    assert hot.body.thirst == pytest.approx(9.0)


def test_even_a_few_berries_are_seen(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(at=GATE))
    cell = _first_cell(sim, lambda c: sim.state.resources[c, 0] > 0)
    sim.core.place_at(citizen, sim.world.unit(cell))
    sim.state.resources[cell, 0] = 2
    things = WorldApi(sim, citizen.id).look_around().things
    assert ("a few berries on the bushes", "right beside you") in [(t.label, t.where) for t in things]


def test_names_are_only_learned_from_someone_you_can_see(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("ann", name="Ann", at=(0.0, 150.0)))
    sim.add_citizen(make_spec("bob", name="Bob", at=(1.0, 150.0)))
    listener = sim.add_citizen(make_spec("listener", at=(0.0, 60.0)))  # 90 m: seen by day, not at night
    WorldApi(sim, "ann").say("I am Ann!", "shout")
    assert listener.heard[-1].who == "a person in a ann cloak"
    assert "ann" in listener.people
    sim.run(16 * 60)  # midnight
    WorldApi(sim, "bob").say("I am Bob!", "shout")
    assert listener.heard[-1].who == "someone"
    assert "bob" not in listener.people


def test_known_people_walking_by_in_a_crowded_town_dont_interrupt(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    walkers = [f"walker{i}" for i in range(6)]
    for index, walker in enumerate(walkers):  # out of sight on the training ground (~160 m off)
        sim.add_citizen(make_spec(walker, at=(-78.0 + 3 * index, -70.0), knows_places=["town", "main-gate"]))
    watcher = sim.add_citizen(make_spec("watcher", at=(-3.0, 75.0), knows_people=walkers))  # on the main street
    wait = WorldApi(sim, "watcher").wait(30)
    assert not watcher.in_view
    for walker in walkers:  # down the main street, past the watcher, to the gate
        WorldApi(sim, walker).walk_to_place("the main gate")
    passed = False
    for _ in range(30):
        sim.step()
        passed = passed or set(walkers) <= watcher.in_view
    assert passed  # they all came into view
    assert run_until_done(sim, wait, 5).text == "You wait a while."


def test_a_stranger_among_known_people_interrupts(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("friend", at=(-78.0, -70.0)))
    sim.add_citizen(make_spec("stranger", at=(-72.0, -70.0), appearance="a tall man with a bow"))
    sim.add_citizen(make_spec("watcher", at=(-3.0, 75.0), knows_people=["friend"]))
    wait = WorldApi(sim, "watcher").wait(30)
    WorldApi(sim, "friend").walk_to_place("the main gate")
    WorldApi(sim, "stranger").walk_to_place("the main gate")
    result = run_until_done(sim, wait, 30)
    assert result.outcome == "interrupted"
    assert result.text.startswith("You stop waiting: a tall man with a bow comes into view")


def test_a_known_person_walking_up_to_you_interrupts_once_close(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    beside_well = (-20.0, 58.5)  # 6 m from where people stand at the well, on the cross street
    sim.add_citizen(make_spec("passer", name="Mio", at=(-90.0, 61.0), knows_places=["town", "market"]))
    sim.add_citizen(make_spec("visitor", name="Sora", at=(20.0, 56.0)))
    sim.add_citizen(make_spec("friend", name="Kenji", age=70, at=(-76.0, 61.0)))  # 56 m off along the street
    watcher = sim.add_citizen(make_spec("watcher", at=beside_well, knows_people=["friend", "passer", "visitor"]))

    wait = WorldApi(sim, "watcher").wait(60)
    WorldApi(sim, "passer").walk_to_place("the market")  # straight past the watcher along the cross street
    WorldApi(sim, "visitor").walk_to_place("the well")  # to the well, 6 m from the watcher
    closest = {"passer": 99.0, "visitor": 99.0}
    for _ in range(4):
        sim.step()
        for other in closest:
            distance = sim.world.distance_m(watcher.position, sim.citizen(other).position)
            closest[other] = min(closest[other], distance)
    assert max(closest.values()) < 10.0  # both came close...
    assert wait.result is None  # ...without stopping the watcher

    walk = WorldApi(sim, "friend").walk_to_person("a person in a watcher cloak")
    started = [e.payload.model_dump() for e in sim.drain() if e.type == "action_started" and e.actor_id == "friend"]
    assert started[-1]["label"] == "Watcher"  # spectators see who he walks to; Kenji only knows her looks
    assert "You are walking to a person in a watcher cloak." in WorldApi(sim, "friend").check_self().doing
    result = run_until_done(sim, wait, 10)
    assert result.text == "You stop waiting: Kenji is coming toward you."
    assert 3.0 < sim.world.distance_m(watcher.position, sim.citizen("friend").position) <= 10.0

    again = WorldApi(sim, "watcher").wait(10)  # already close: no second interrupt as he arrives
    assert run_until_done(sim, walk, 5).text == "You reach a person in a watcher cloak."
    assert run_until_done(sim, again, 12).text == "You wait a while."


def test_someone_coming_to_the_same_place_doesnt_stop_your_work(new_sim: Callable[..., Simulation]) -> None:
    """Regression (#30): a walk to a place that ends where you stand counted as walking up to you, so everyone
    arriving at the rice fields stopped the farmer's hour of work there."""
    sim = new_sim()
    fields = ["town", "rice-fields"]
    sim.add_citizen(make_spec("helper", name="Aiko", at=(-60.0, 61.0), knows_places=fields))
    sim.add_citizen(make_spec("friend", name="Kenji", at=(-80.0, 61.0)))
    known = ["helper", "friend"]
    farmer = sim.add_citizen(
        make_spec("farmer", at=(-90.0, 61.0), knows_places=fields, skills=["farming"], knows_people=known)
    )
    me = WorldApi(sim, "farmer")
    assert run_until_done(sim, me.walk_to_place("the rice fields"), 10).text == "You arrive at the rice fields."
    work = me.work("farm")
    helper = WorldApi(sim, "helper").walk_to_place("the rice fields")
    assert run_until_done(sim, helper, 30).text == "You arrive at the rice fields."
    assert sim.world.distance_m(farmer.position, sim.citizen("helper").position) < 3.0  # right where he works
    assert work.result is None

    WorldApi(sim, "friend").walk_to_person("Farmer")  # walking up to him still does
    result = run_until_done(sim, work, 30)
    assert result.text == "You stop working: Kenji is coming toward you."


def test_follow_keeps_beside_a_walker_until_they_stop(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    leader = sim.add_citizen(make_spec("leader", name="Aiko", home=None))
    follower = sim.add_citizen(make_spec("follower", home=None, knows_people=["leader"]))
    put_in_the_wild(sim, leader.id, wild_cell(sim))
    sim.core.place_at(follower, step_towards(leader.position, 90.0, 4.0, sim.world.radius_m))
    skip_to(sim, leader.position, night=False)
    walk = WorldApi(sim, leader.id).walk_towards("north", "a long walk")
    follow = WorldApi(sim, follower.id).follow("Aiko")
    started = [e.payload.model_dump() for e in sim.drain() if e.type == "action_started" and e.actor_id == follower.id]
    assert (started[-1]["action"], started[-1]["label"]) == ("follow", "Aiko")
    assert WorldApi(sim, follower.id).check_self().doing == "You are following Aiko."
    gaps = []
    while walk.result is None:
        sim.step()
        gaps.append(sim.world.distance_m(leader.position, follower.position))
        if walk.result is None:
            assert follow.result is None  # still following while she walks, even when beside her
    assert len(gaps) >= 2 and max(gaps) < 6.0  # keeps up with her all the way (they set off 4 m apart)
    result = run_until_done(sim, follow, 10)
    assert result == ActionResult(action="follow", outcome="done", text="Aiko stops, and you stop beside them.")
    assert sim.world.distance_m(leader.position, follower.position) <= 2.0


def test_follow_needs_someone_in_view_and_ends_when_they_are_lost(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    follower = sim.add_citizen(make_spec("follower", at=WELL))
    failed = run_until_done(sim, WorldApi(sim, follower.id).follow("a woman in red"), 1)
    assert failed == ActionResult(action="follow", outcome="failed", text="You don't see anyone like that.")
    stranger = sim.add_citizen(make_spec("stranger", at=(WELL[0] + 5.0, WELL[1]), appearance="a man with a bow"))
    follow = WorldApi(sim, follower.id).follow("the man with a bow")
    sim.core.place_at(stranger, sim.world.town.to_unit(-20.0, -140.0))  # suddenly far out of sight
    result = run_until_done(sim, follow, 3)
    assert result.outcome == "interrupted"
    assert result.text == "You stop following: you lose sight of a man with a bow."
