"""What every scripted brain does whatever its role (World v1 plan, BR0): it says what it is after whenever its aim
changes, greets with a bow to its betters and a wave to the rest, passes the time of day, runs only when desperate or
with a predator about, takes up meat left lying, and walks onto its work slot itself before it works."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import JsonValue

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile, known_titles
from app.brains.routines import ROUTINES, Context, _scavenge
from app.brains.senses import Needs
from app.observability.events import Gestured, GoalSet, Said
from app.sim import fire as fires
from app.sim.simulation import Simulation
from app.sim.slots import OCCUPY_M, held_slot
from app.sim.state import Fire
from app.sim.vec import step_towards
from app.world_api.facade import ActionHandle, WorldApi
from app.world_api.models import ActionResult, Perception, Seen, SelfView
from tests.sim_helpers import (
    add_animal,
    make_spec,
    move_animal,
    put_in_the_wild,
    skip_to,
    wild_cell,
    without_animals,
)

SEED = 7
ROAD = (0.0, 150.0)  # on the approach road, outside the walls
BY_THE_WELL = (-25.9, 52.75)  # "at the well", out of its reach
CAMP_HOME = "band_a_camp:shelter-n"


def _brain(sim: Simulation, citizen_id: str, role: str, region: str = "town", **fields: object) -> UtilityBrain:
    citizen = sim.citizen(citizen_id)
    home_area = sim.world.places["town" if region == "town" else f"{region}_camp"].name
    profile = BrainProfile(
        citizen_id, citizen.name, role, region, home_area, citizen.skills,  # type: ignore[arg-type]  # a region
        **fields,  # type: ignore[arg-type]  # titled
    )  # fmt: skip
    return UtilityBrain(WorldApi(sim, citizen_id), profile, SEED)


def _events[T](sim: Simulation, kind: type[T]) -> list[T]:
    return [event.payload for event in sim.drain() if isinstance(event.payload, kind)]


def test_a_brain_sets_a_goal_when_its_aim_changes_and_only_then(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    hana = sim.add_citizen(make_spec("hana", name="Hana", at=BY_THE_WELL, home=None))
    brain = _brain(sim, hana.id, "child")
    sim.drain()
    hana.body.thirst = 70.0
    brain.decide()
    assert [(goal.text, goal.driver) for goal in _events(sim, GoalSet)] == [("Get a drink", "thirst")]
    brain.decide()  # the same aim (drinking on): nothing new to say
    assert _events(sim, GoalSet) == []
    hana.body.thirst, hana.body.hunger = 0.0, 70.0
    brain.decide()
    assert [(goal.text, goal.driver) for goal in _events(sim, GoalSet)] == [("Get something to eat", "hunger")]
    brain.api.notes["asleep"] = True  # woken from a night's sleep: the aim is told afresh
    brain.decide()
    assert [goal.text for goal in _events(sim, GoalSet)] == ["Get something to eat"]


def test_betters_are_bowed_to_and_everyone_else_waved_to() -> None:
    town = known_titles([("Masanori", ["lord"]), ("Kenji", ["samurai"]), ("Goro", ["ashigaru"])])
    town += known_titles([("Fumiko", [])])
    hana = BrainProfile("hana", "Hana", "the farmer's child", "town", "The castle town", titled=town)
    assert [name for name in ("Masanori", "Kenji", "Goro", "Fumiko") if hana.bows_to(name)] == ["Masanori", "Kenji"]
    kenji = BrainProfile(
        "kenji", "Kenji", "samurai retainer", "town", "The castle town", titled=town, titles=("samurai",)
    )
    assert kenji.bows_to("Masanori") and not kenji.bows_to("Goro")
    assert not kenji.bows_to("Kenji")  # nor to a fellow samurai: the same rank
    lord = BrainProfile(
        "masanori", "Masanori", "lord of the castle", "town", "The castle town", titled=town, titles=("lord",)
    )
    assert not any(lord.bows_to(name) for name in ("Kenji", "Goro", "Fumiko"))
    band = known_titles([("Ama", ["leader"]), ("Bo", [])])
    lia = BrainProfile("lia", "Lia", "teen gatherer", "band_a", "Band A camp", titled=band)
    assert lia.bows_to("Ama") and not lia.bows_to("Bo")
    assert [hana.officer(name) for name in ("Masanori", "Goro", "Fumiko")] == [True, True, False]


@pytest.fixture
def three(new_sim: Callable[..., Simulation]) -> tuple[Simulation, UtilityBrain]:
    """Aiko (a brain) on the road with the lord 3 m off and Bo 6 m off; all know each other."""
    sim = new_sim()
    aiko = sim.add_citizen(make_spec("aiko", name="Aiko", at=ROAD, knows_people=["masanori", "bo"]))
    sim.add_citizen(make_spec("masanori", name="Masanori", at=(ROAD[0], ROAD[1] - 3), knows_people=["aiko"]))
    sim.add_citizen(make_spec("bo", name="Bo", at=(ROAD[0], ROAD[1] - 6), knows_people=["aiko"]))
    titled = known_titles([("Masanori", ["lord"]), ("Bo", [])])
    brain = _brain(sim, aiko.id, "weaver", titled=titled)
    sim.drain()
    return sim, brain


def test_a_greeting_comes_with_a_bow_to_the_lord_and_a_wave_to_a_neighbour(
    three: tuple[Simulation, UtilityBrain],
) -> None:
    sim, aiko = three
    assert aiko.socialise(aiko.api.look_around())
    events = sim.drain()
    gestures = [e.payload for e in events if isinstance(e.payload, Gestured)]
    assert [(g.kind, g.to) for g in gestures] == [("bow", "masanori")]
    assert set(gestures[0].seen_by) == {"masanori", "bo"}
    assert ["Masanori" in e.payload.words for e in events if isinstance(e.payload, Said)] == [True]
    assert aiko.socialise(aiko.api.look_around())
    assert [(g.kind, g.to) for g in _events(sim, Gestured)] == [("wave", "bo")]


def test_a_reply_to_a_greeting_bows_back_to_a_better(three: tuple[Simulation, UtilityBrain]) -> None:
    sim, aiko = three
    WorldApi(sim, "masanori").say("Good morning, Aiko!")
    sim.drain()
    assert aiko.socialise(aiko.api.look_around())
    assert [(g.kind, g.to) for g in _events(sim, Gestured)] == [("bow", "masanori")]


def test_small_talk_comes_once_each_part_of_the_day_and_questions_get_an_answer(
    three: tuple[Simulation, UtilityBrain], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, aiko = three
    monkeypatch.setattr(aiko, "chance", lambda _odds: True)
    aiko.api.notes["greeted"] = ["Masanori", "Bo"]
    assert aiko.socialise(aiko.api.look_around())
    [said] = _events(sim, Said)
    assert any(name in said.words for name in ("Masanori", "Bo"))
    assert not aiko.socialise(aiko.api.look_around())  # once is enough till the next part of the day

    WorldApi(sim, "bo").say("Busy day, Aiko.")
    sim.drain()
    assert not aiko.socialise(aiko.api.look_around())  # nothing asked: nothing to answer
    WorldApi(sim, "bo").say("Aiko, how goes the work?")
    sim.drain()
    assert aiko.socialise(aiko.api.look_around())
    [answer] = _events(sim, Said)
    assert answer.words.endswith("Bo.") and "bo" in answer.heard_by


@pytest.mark.parametrize(("thirst", "pace"), [(95.0, "run"), (70.0, "walk")])
def test_only_the_desperate_run_for_water(new_sim: Callable[..., Simulation], thirst: float, pace: str) -> None:
    sim = new_sim()
    hana = sim.add_citizen(make_spec("hana", name="Hana", home=None, knows_places=["town", "well", "main-gate"]))
    hana.body.thirst = thirst
    _brain(sim, hana.id, "child").decide()
    action = hana.action
    assert action is not None and action.kind == "walk_to" and action.label == "the well"
    assert action.args["pace"] == pace


def test_a_predator_prowling_in_view_hurries_you_unless_walls_or_a_fire_keep_it_off(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = without_animals(new_sim())
    forager = sim.add_citizen(make_spec("forager", home=None, region="band_a"))
    put_in_the_wild(sim, forager.id, wild_cell(sim))
    skip_to(sim, forager.position, night=False)
    brain = _brain(sim, forager.id, "gatherer", region="band_a")
    calm = Needs(0, 0, 0)
    assert brain.pace(brain.api.look_around(), calm) == "walk"
    wolf = add_animal(sim, "wolf", step_towards(forager.position, 0.0, 100.0, sim.world.radius_m), activity="walking")
    seen = brain.api.look_around()
    assert [(a.label, a.doing) for a in seen.animals] == [("a wolf", "on the move")]
    assert brain.pace(seen, calm) == "run"
    assert brain.pace(seen, Needs(3, 0, 0)) == "run"
    wolf.activity = "sleeping"
    assert brain.pace(brain.api.look_around(), calm) == "walk"
    assert brain.pace(brain.api.look_around(), Needs(0, 3, 0)) == "run"  # desperate for water

    wolf.activity = "walking"
    camp = Fire(id="fire:9", kind="campfire", position=forager.position, cell=forager.cell, height_m=forager.height_m)
    fires.add_fuel(camp, 300)
    sim.state.fires[camp.id] = camp
    seen = brain.api.look_around()
    assert any(t.kind == "fire" and t.doing == "burning" for t in seen.things)
    assert brain.pace(seen, calm) == "walk"  # a burning fire keeps it off

    townie = sim.add_citizen(make_spec("townie", at=(0.0, 98.0)))  # inside the main gate
    skip_to(sim, townie.position, night=False)
    move_animal(sim, wolf, sim.world.town.to_unit(0.0, 170.0))  # out on the approach road, 72 m off
    town = _brain(sim, townie.id, "townsperson")
    seen = town.api.look_around()
    assert [(a.label, a.doing) for a in seen.animals] == [("a wolf", "on the move")]
    assert town.pace(seen, calm) == "walk"  # the walls keep it out


def _forager_ctx(look: Perception, chance: bool, notes: dict[str, JsonValue]) -> Context:
    api = cast(WorldApi, SimpleNamespace(notes=notes))
    profile = BrainProfile("suna", "Suna", "gatherer", "band_a", "Band A camp")
    return Context(api, profile, look, Needs(0, 0, 0), "day", lambda _p: chance, lambda _n: 0)


def _camp_look(place: str, *things: Seen) -> Perception:
    you = SelfView(feeling=[], carrying=["plenty of roots"], doing="You are standing about.")
    return Perception(
        you=you, place=place, time="It is midday.", time_of_day="midday", people=[], animals=[], things=list(things),
        heard=[],
    )  # fmt: skip


def test_a_forager_at_ease_keeps_one_goal_while_it_rests_looks_about_and_heads_back() -> None:
    """Review of #102: resting, strolling and heading back each told a goal of their own, 80-103 set_goal a day for
    each band member; they are one aim."""
    full: dict[str, JsonValue] = {"full": ["plenty of roots"]}  # told it can carry no more
    at_home = _camp_look("at your home, at Band A camp")
    out = _camp_look("not far from Band A camp")
    picked = {
        name: (option.name, option.aim, option.driver)
        for name, ctx in (
            ("rest", _forager_ctx(at_home, chance=False, notes=dict(full))),
            ("stroll", _forager_ctx(at_home, chance=True, notes=dict(full))),
            ("back", _forager_ctx(out, chance=False, notes=dict(full))),
        )
        for option in ROUTINES["gatherer"](ctx)
    }
    assert {name: step for name, (step, _, _) in picked.items()} == {
        "rest": "rest at camp", "stroll": "stroll", "back": "go home",
    }  # fmt: skip
    assert {(aim, driver) for _, aim, driver in picked.values()} == {("Take it easy about camp", "rest")}


def test_dried_meat_lying_about_is_not_taken_for_remains() -> None:
    dried = Seen(label="some dried meat on the ground", where="right beside you", nearness="right beside you")
    fresh = Seen(label="some meat on the ground", where="right beside you", nearness="right beside you")
    look = _camp_look("in the wild")
    assert _scavenge(_forager_ctx(look.model_copy(update={"things": [dried]}), False, {})) == []
    [take] = _scavenge(_forager_ctx(look.model_copy(update={"things": [fresh]}), False, {}))
    assert take.name == "pick up the meat"


def _near_camp(sim: Simulation) -> int:
    """An open cell some 150 m out from band A's camp, to walk home from."""
    centre = sim.world.places["band_a_camp"].centre
    for bearing in range(0, 360, 45):
        cell = sim.world.nearest_cell(step_towards(centre, float(bearing), 150.0, sim.world.radius_m))
        if sim.core.planner.outer.allowed[cell] and not sim.world.river[cell]:
            return cell
    raise LookupError("no open ground round the camp")


def test_a_forager_takes_meat_left_lying_home_unless_a_predator_prowls(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    forager = sim.add_citizen(make_spec("forager", home=CAMP_HOME, region="band_a", knows_places=["band_a_camp"]))
    put_in_the_wild(sim, forager.id, _near_camp(sim))
    skip_to(sim, forager.position, night=False)
    spot = step_towards(forager.position, 90.0, 12.0, sim.world.radius_m)
    sim.core.new_stack("meat", 4, spot, sim.world.nearest_cell(spot))
    brain = _brain(sim, forager.id, "gatherer", region="band_a")
    brain.decide()
    walk = forager.action
    assert walk is not None and walk.kind == "walk_to" and walk.label.endswith("meat on the ground")
    for _ in range(10):
        if brain.api.handle(walk.number).result is not None:
            break
        sim.step()
    brain.decide()
    assert forager.inventory.get("meat") == 4
    home = forager.action
    assert home is not None and home.kind == "walk_to" and home.label == "home"
    assert brain.api.notes["goal"] == ["Take the meat lying there home", "duty"]

    wolf = add_animal(sim, "wolf", step_towards(forager.position, 0.0, 100.0, sim.world.radius_m), activity="walking")
    assert wolf.alive
    sim.core.new_stack("meat", 4, spot, sim.world.nearest_cell(spot))
    forager.action = None
    brain.decide()
    assert brain.api.notes["last"] not in ("go to the meat", "pick up the meat")


def test_a_farmer_in_the_fields_walks_onto_a_paddy_slot_before_farming(new_sim: Callable[..., Simulation]) -> None:
    """Issue #89: a farmer already in the fields but off any slot was walked 14-37 m to one at the tick's end, under
    the work's label; now the brain walks there first (the walk lands on a free slot) and works on it."""
    sim = without_animals(new_sim())
    fields = sim.world.places["rice-fields"]
    town = sim.world.town_point(fields.stand)
    assert town is not None
    genzo = sim.add_citizen(
        make_spec("genzo", name="Genzo", at=town, skills=["farming"], knows_places=["town", "rice-fields"])
    )
    skip_to(sim, genzo.position, night=False)
    brain = _brain(sim, genzo.id, "rice farmer")
    assert "at the rice fields" in brain.api.look_around().place
    brain.decide()
    cut_short = genzo.action
    assert cut_short is not None and cut_short.kind == "walk_to"
    sim.core.end_action(genzo, "interrupted", "You stop walking.")  # a walk cut short is no arrival
    brain.decide()
    walk = genzo.action
    assert walk is not None and walk.kind == "walk_to" and walk.label == "the rice fields"
    for _ in range(60):
        if brain.api.handle(walk.number).result is not None:
            break
        sim.step()
    brain.decide()
    work = genzo.action
    slot = held_slot(sim.core, genzo)
    assert work is not None and work.kind == "work" and work.item == "farm"
    assert slot is not None and slot.kind == "work"
    assert sim.core.distance_m(genzo.position, slot.position) <= OCCUPY_M


class _Handles:
    """A world api whose action number 3 ended as told."""

    def __init__(self, outcome: str) -> None:
        self.notes: dict[str, object] = {"last": "feed the fire", "chosen": 3}
        self.outcome = outcome

    def handle(self, number: int) -> ActionHandle:
        result = ActionResult(action="feed_fire", outcome=self.outcome, text="")
        return cast(ActionHandle, SimpleNamespace(result=result if number == 3 else None))


@pytest.mark.parametrize(
    ("outcome", "last", "counts"),
    [("done", "feed the fire", True), ("interrupted", "feed the fire", False), ("done", "rest by the fire", False)],
)
def test_a_chore_counts_only_when_its_action_ran_to_its_end(outcome: str, last: str, counts: bool) -> None:
    """Every word said cuts short the actions of everyone awake in earshot (03): a fire feeding or wood gathering
    counted at its start was lost to talk, and band B's fire died before dawn (D165)."""
    api = _Handles(outcome)
    api.notes["last"] = last
    look = cast(Perception, None)
    ctx = Context(cast(WorldApi, api), cast(BrainProfile, None), look, Needs(0, 0, 0), "dusk", bool, int)
    assert ctx.finished("feed the fire") is counts
