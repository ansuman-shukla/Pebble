"""Scripted brains in the wild: everyone runs from a predator (unless a fire or the walls keep it off), bands keep the
camp fire going at dusk, hunters stalk the game they see, and the guard lights the gate's fire baskets."""

from collections.abc import Callable

import pytest

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.brains.senses import water_way
from app.sim import fire as fires
from app.sim.items import RESOURCE_INDEX
from app.sim.simulation import Simulation
from app.sim.state import Fire
from app.sim.vec import step_towards
from app.world_api.facade import WorldApi
from app.world_api.models import Compass
from tests.sim_helpers import add_animal, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

HOME_A = "band_a_camp:shelter-n"
HOME_B = "band_b_camp:shelter-n"


def _brain(sim: Simulation, citizen_id: str, region: str = "band_a", role: str = "hunter") -> UtilityBrain:
    citizen = sim.citizen(citizen_id)
    home_area = sim.world.places["town" if region == "town" else f"{region}_camp"].name
    profile = BrainProfile(
        citizen_id=citizen_id,
        name=citizen.name,
        role=role,
        region=region,  # type: ignore[arg-type]  # one of the three regions
        home_area=home_area,
        skills=citizen.skills,
    )
    return UtilityBrain(WorldApi(sim, citizen_id), profile, seed=1)


def _started(sim: Simulation, citizen_id: str) -> str | None:
    action = sim.citizen(citizen_id).action
    return action.kind if action is not None else None


def test_a_lone_forager_runs_from_a_wolf_but_not_by_a_fire(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    citizen = sim.add_citizen(make_spec("forager", home=None, region="band_a"))
    put_in_the_wild(sim, citizen.id, wild_cell(sim))
    skip_to(sim, citizen.position, night=False)
    add_animal(sim, "wolf", step_towards(citizen.position, 0.0, 30.0, sim.world.radius_m), until=10**9)
    brain = _brain(sim, citizen.id)
    brain.decide()
    assert _started(sim, citizen.id) == "flee"

    calm = sim.add_citizen(make_spec("calm", home=None, region="band_a"))
    sim.core.place_at(calm, step_towards(citizen.position, 90.0, 60.0, sim.world.radius_m))
    camp = Fire(id="fire:5", kind="campfire", position=calm.position, cell=calm.cell, height_m=calm.height_m)
    fires.add_fuel(camp, 300)
    sim.state.fires[camp.id] = camp
    add_animal(sim, "wolf", step_towards(calm.position, 0.0, 30.0, sim.world.radius_m), until=10**9)
    _brain(sim, calm.id).decide()
    assert _started(sim, calm.id) != "flee"


def test_town_folk_behind_the_walls_dont_run(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    citizen = sim.add_citizen(make_spec("townie", at=(0.0, 98.0)))  # inside the main gate
    add_animal(sim, "wolf", sim.world.town.to_unit(0.0, 125.0), until=10**9)  # on the approach outside
    assert any(a.doing == "watching you" for a in WorldApi(sim, citizen.id).look_around().animals)
    _brain(sim, citizen.id, region="town", role="townsperson").decide()
    assert _started(sim, citizen.id) != "flee"


def test_a_band_keeps_its_fire_going_at_dusk(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    keeper = sim.add_citizen(
        make_spec("keeper", site="band_a_camp", at=(0.0, 1.5), home=None, region="band_a", skills=["fire"])
    )
    pit = sim.state.fires["band_a_camp:fire-pit"]
    pit.fuel, pit.level = 100, fires.fuel_level(100)
    skip_to(sim, keeper.position, night=False)
    while sim.core.altitude(keeper.position) > -1:  # on to just after the local sunset: dusk
        sim.state.tick += 1
    brain = _brain(sim, keeper.id, role="gatherer")
    brain.decide()
    assert _started(sim, keeper.id) == "feed_fire"
    sim.run(3)
    assert pit.fuel > 100 + 5 * fires.WOOD_MINUTES  # fed from the woodpile

    pit.fuel, pit.lit, pit.level = 0, False, 0
    brain.decide()
    assert _started(sim, keeper.id) == "make_fire"
    unskilled = sim.add_citizen(make_spec("child", site="band_a_camp", at=(0.5, 1.5), home=None, region="band_a"))
    _brain(sim, unskilled.id, role="child").decide()
    assert _started(sim, unskilled.id) != "make_fire"  # only those with the skill make fire


def test_a_hunter_stalks_the_game_in_view(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    hunter = sim.add_citizen(
        make_spec("tek", site="band_a_camp", at=(0.0, 30.0), home=None, region="band_a", skills=["hunting"])
    )
    skip_to(sim, hunter.position, night=False)  # the sun well up: daytime
    add_animal(sim, "deer", step_towards(hunter.position, 45.0, 35.0, sim.world.radius_m), until=10**9)
    _brain(sim, hunter.id).decide()
    action = sim.citizen(hunter.id).action
    assert action is not None and action.kind == "hunt" and action.label == "a deer"


def test_a_spear_carrier_drives_off_a_wolf_that_comes_close(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    armed = sim.add_citizen(make_spec("armed", home=None, region="band_a", inventory={"spear": 1}))
    put_in_the_wild(sim, armed.id, wild_cell(sim))
    skip_to(sim, armed.position, night=False)
    add_animal(sim, "wolf", step_towards(armed.position, 0.0, 12.0, sim.world.radius_m), until=10**9)
    _brain(sim, armed.id).decide()
    action = sim.citizen(armed.id).action
    assert action is not None and action.kind == "attack" and action.label == "a wolf"

    unarmed = sim.add_citizen(make_spec("unarmed", home=None, region="band_a"))
    sim.core.place_at(unarmed, step_towards(armed.position, 180.0, 300.0, sim.world.radius_m))
    add_animal(sim, "wolf", step_towards(unarmed.position, 0.0, 12.0, sim.world.radius_m), until=10**9)
    _brain(sim, unarmed.id).decide()
    assert _started(sim, unarmed.id) == "flee"


def test_a_hunter_back_at_camp_shares_half_the_meat(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    camp = {"site": "band_a_camp", "home": None, "region": "band_a"}
    hunter = sim.add_citizen(make_spec("tek", at=(0.0, 30.0), skills=["hunting"], inventory={"meat": 4}, **camp))
    other = sim.add_citizen(make_spec("suna", at=(1.0, 30.0), **camp))
    skip_to(sim, hunter.position, night=False)
    brain = _brain(sim, hunter.id)
    brain.decide()
    assert other.inventory.get("meat") == 2 and hunter.inventory["meat"] == 2
    assert _started(sim, hunter.id) == "rest"
    sim.run(21)  # the rest is over
    brain.decide()
    assert other.inventory["meat"] == 2  # once a day


def _gathers(sim: Simulation, brain: UtilityBrain, minutes: int) -> list[str]:
    """Run the brain for a while; how each of its gathers ended, in order."""
    ended: list[str] = []
    for _ in range(minutes):
        brain.tick()
        sim.step()
        for event in sim.drain():
            payload = event.payload.model_dump()
            if event.type == "action_finished" and event.actor_id == brain.profile.citizen_id:
                if payload["action"] == "gather":
                    ended.append(payload["text"])
    return ended


@pytest.mark.parametrize(
    ("role", "age", "meat"),
    [("child", 9, 10), ("gatherer", 30, 50)],  # 5 and 25 kg: all they can carry (a gatherer also has a wood chore)
)
def test_a_forager_with_a_full_load_stops_gathering_until_it_carries_less(
    new_sim: Callable[..., Simulation], role: str, age: int, meat: int
) -> None:
    sim = without_animals(new_sim())
    forager = sim.add_citizen(
        make_spec(
            "pip", age=age, site="band_a_camp", at=(0.0, 30.0), home=HOME_A, region="band_a", inventory={"meat": meat}
        )
    )
    bushes = forager.cell
    sim.state.resources[bushes, RESOURCE_INDEX["berries"]] = 40  # bushes heavy with berries right here
    skip_to(sim, forager.position, night=False)
    brain = _brain(sim, forager.id, role=role)
    full = _gathers(sim, brain, 2 * 60)
    assert full == ["You can't carry any more."]  # told once, it stops trying (and strolls off)

    put_in_the_wild(sim, forager.id, bushes)  # back by the bushes
    brain.api.notes["asleep"] = True  # a new day (just woken): it tries once more
    brain.decide()
    assert str(brain.api.notes["last"]).startswith("gather")

    forager.inventory["meat"] = 3  # carrying less now ("a little meat", say some was eaten): room to gather again
    lighter = _gathers(sim, brain, 3 * 60)
    assert any(text.startswith("You gather") for text in lighter)


def test_a_forager_walks_to_the_fallen_wood_it_saw_not_the_camp_woodpile(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    gatherer = sim.add_citizen(
        make_spec("suna", site="band_a_camp", at=(0.0, 1.5), home=HOME_A, region="band_a", inventory={"roots": 30})
    )  # food enough for the outing: only the day's wood chore is left
    wood = RESOURCE_INDEX["wood"]
    sim.state.resources[:, wood] = 0
    plant = sim.world.neighbours[gatherer.cell][0]
    sim.state.resources[plant, wood] = 40  # fallen wood a short way off; the woodpile by the fire is closer
    api = WorldApi(sim, gatherer.id)
    skip_to(sim, gatherer.position, night=False)
    seen = api.look_around().things
    assert any(thing.resource == "wood" and thing.nearness != "right beside you" for thing in seen)
    assert any(thing.label.endswith("wood on the ground") for thing in seen)
    brain = _brain(sim, gatherer.id, role="gatherer")
    assert any(text.startswith("You gather") and text.endswith("wood.") for text in _gathers(sim, brain, 60))


def _drinks_in_the_dark(sim: Simulation, brain: UtilityBrain, sun: float) -> bool:
    """Skip on into the dark (the sun at `sun`°) and make the citizen thirsty: does it drink within the hour?"""
    citizen = sim.citizen(brain.profile.citizen_id)
    while sim.core.altitude(citizen.position) > sun:
        sim.state.tick += 1
    assert not any(thing.kind == "water" for thing in brain.api.look_around().things)  # too dark to see it now
    sim.drain()
    citizen.body.thirst = 70  # thirsty before bed
    drank = False
    for _ in range(60):
        brain.tick()
        sim.step()
        drank |= any(
            event.type == "action_finished"
            and event.actor_id == citizen.id
            and event.payload.model_dump()["action"] == "drink"
            for event in sim.drain()
        )
    return drank and citizen.body.thirst < 30


@pytest.mark.parametrize("sun", [-5.5, -15.0])  # deep dusk; the dead of night
def test_a_band_finds_its_water_after_dark_the_way_it_lay_by_day(
    new_sim: Callable[..., Simulation], sun: float
) -> None:
    sim = without_animals(new_sim())
    child = sim.add_citizen(make_spec("pip", age=7, site="band_b_camp", at=(-1.0, -3.0), home=HOME_B, region="band_b"))
    skip_to(sim, child.position, night=False)
    brain = _brain(sim, child.id, region="band_b", role="child")
    brain.decide()  # by day the river is in view from home
    while child.action is not None:
        sim.step()
    assert _drinks_in_the_dark(sim, brain, sun)


def test_a_band_notes_the_way_to_its_water_only_at_home(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    child = sim.add_citizen(make_spec("pip", age=7, site="band_b_camp", at=(-1.0, -3.0), home=HOME_B, region="band_b"))
    home = child.cell
    skip_to(sim, child.position, night=False)
    brain = _brain(sim, child.id, region="band_b", role="child")
    seen_from_home = water_way(brain.api.look_around())
    assert seen_from_home is not None
    brain.decide()
    assert brain.api.notes["water_way"] == seen_from_home

    def elsewhere(cell: int) -> tuple[str, Compass | None]:
        put_in_the_wild(sim, child.id, cell)
        seen = brain.api.look_around()
        return seen.place, water_way(seen)

    rings = {home}
    for _ in range(4):
        rings |= {n for cell in rings for n in sim.world.neighbours[cell]}
    looks = {cell: elsewhere(cell) for cell in sorted(rings)}
    other_ways = [cell for cell, (place, way) in looks.items() if way not in (None, seen_from_home)]
    in_camp = next(c for c in other_ways if looks[c][0].startswith("at Band B camp"))  # in camp, not at home
    out_of_camp = next(c for c in other_ways if not looks[c][0].startswith(("at your home", "at Band B camp")))
    for cell in (in_camp, out_of_camp):  # by day, from there the water (or other water) lies another way
        put_in_the_wild(sim, child.id, cell)
        brain.decide()
        while child.action is not None:
            sim.step()
        assert brain.api.notes["water_way"] == seen_from_home  # from there, it would be the wrong way from home
    put_in_the_wild(sim, child.id, home)
    assert _drinks_in_the_dark(sim, brain, -15.0)


def test_a_full_forager_at_camp_looks_around_after_one_rest(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = without_animals(new_sim())
    child = sim.add_citizen(
        make_spec("pip", age=9, site="band_a_camp", at=(0.0, 1.5), home=HOME_A, region="band_a", inventory={"meat": 10})
    )
    skip_to(sim, child.position, night=False)
    brain = _brain(sim, child.id, role="child")
    monkeypatch.setattr(brain, "chance", lambda _p: False)  # never the lucky roll that sends it for a stroll
    brain.api.notes["full"] = list(brain.api.look_around().you.carrying)  # told it can carry no more
    brain.decide()
    assert brain.api.notes["last"] == "rest at camp"
    while child.action is not None:
        sim.step()
    brain.decide()
    assert brain.api.notes["last"] == "stroll"  # not a second rest, and a third... (seed 1: Pip stood 5 h)
