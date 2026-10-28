"""A test citizen lives a normal day driven ONLY through `world_api` (the M5 done-when).

The test may read the simulation to check what happened, but every action goes through `WorldApi`; time passes by
ticking the simulation (as the engine does).
"""

from collections.abc import Callable

from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import HOME, compass_towards, local_hour, make_spec, nearest_cell_of

FORESTS = ("broadleaf_forest", "taiga")


def test_gate_to_well_and_drink(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec())
    api = WorldApi(sim, citizen.id)
    citizen.body.thirst = 75.0  # a dry walk in from the fields

    assert "the main gate" in api.look_around().place
    walk = run_until_done(sim, api.walk_to_place("the well"), max_ticks=30)
    assert walk.outcome == "done"
    assert walk.text == "You arrive at the well."
    assert sim.world.distance_m(citizen.position, sim.world.places["well"].stand) < 0.5
    assert api.look_around().place.startswith("at the well")

    drink = run_until_done(sim, api.drink(), max_ticks=10)
    assert drink.outcome == "done"
    assert "the well" in drink.text
    assert citizen.body.thirst < 1.0


def test_walk_to_a_forest_gather_and_eat_berries(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(at=(-20.0, 52.5)))
    api = WorldApi(sim, citizen.id)
    forest = nearest_cell_of(sim.world, FORESTS, citizen.position)
    direction = compass_towards(citizen.position, sim.world.unit(forest))

    for _ in range(8):  # head that way until nut trees (only forests have them) come into view
        if any("nut trees" in thing.label for thing in api.look_around().things):
            break
        assert run_until_done(sim, api.walk_towards(direction, "a short walk"), max_ticks=60).outcome == "done"
    reached = run_until_done(sim, api.walk_to_thing("nut trees"), max_ticks=60)
    assert reached.outcome == "done", reached.text
    assert sim.world.biome(citizen.cell) in FORESTS
    assert any("berr" in thing.label and thing.where == "right beside you" for thing in api.look_around().things)

    gathered = run_until_done(sim, api.gather("berries"), max_ticks=30)
    assert gathered.outcome == "done", gathered.text
    berries = citizen.inventory["berries"]
    assert 3 <= berries <= 6
    assert any("berries" in item for item in api.check_self().carrying)

    citizen.body.hunger = 2.0 * (berries - 1)  # a berry takes 2 hunger: one stays in the bag
    eaten = run_until_done(sim, api.eat("berries"), max_ticks=30)
    assert eaten.outcome == "done"
    assert eaten.text.startswith("You eat")
    assert citizen.body.hunger < 0.5  # only the drift of the last minute
    assert citizen.inventory == {"berries": 1}


def test_walk_home_and_sleep_through_the_night(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec())
    api = WorldApi(sim, citizen.id)

    home = run_until_done(sim, api.walk_to_place("home"), max_ticks=30)
    assert home.text == "You arrive home."
    assert sim.world.distance_m(citizen.position, sim.world.structures[HOME].door) < 0.5
    assert api.look_around().place.startswith("at your home")

    asleep_early = run_until_done(sim, api.sleep(), max_ticks=1)
    assert asleep_early.outcome == "failed"  # fresh at 08:00
    assert asleep_early.text == "You aren't tired enough to sleep."

    while "night" not in api.look_around().time:
        result = run_until_done(sim, api.wait(120), max_ticks=130)
        if result.outcome == "interrupted" and "thirsty" in result.text:
            run_until_done(sim, api.walk_to_place("the well"), max_ticks=30)
            run_until_done(sim, api.drink(), max_ticks=10)
            run_until_done(sim, api.walk_to_place("home"), max_ticks=30)
    went_to_bed = sim.tick
    sleep = run_until_done(sim, api.sleep(), max_ticks=14 * 60)
    assert sleep.outcome == "done"
    assert sleep.text == "You wake up; it is morning."
    assert 6.0 <= local_hour(sim, citizen.id) < 6.1
    assert sim.tick - went_to_bed > 8 * 60
    assert citizen.body.energy > 99.0  # full, less the minute awake since
    assert not citizen.body.asleep
    assert citizen.action is None
