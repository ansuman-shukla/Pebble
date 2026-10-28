"""Scripted brains in the wild: everyone runs from a predator (unless a fire or the walls keep it off), bands keep the
camp fire going at dusk, hunters stalk the game they see, and the guard lights the gate's fire baskets."""

from collections.abc import Callable

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.sim import fire as fires
from app.sim.simulation import Simulation
from app.sim.state import Fire
from app.sim.vec import step_towards
from app.world_api.facade import WorldApi
from tests.sim_helpers import add_animal, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals


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
