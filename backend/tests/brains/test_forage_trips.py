"""Band forage trips (N1, D152): once the home ring is picked over (10 §1.2), foragers walk out to their band's food
grounds beyond it, a different way each trip, early enough in the day to be back by dusk; game cutting a walk short
doesn't end the trip, a refusal does; a forager badly bitten runs from a wolf instead of fighting it again."""

from collections.abc import Callable

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.brains.routines import TRIP_TIMES
from app.engine import GROUND_FOOD, GROUNDS_M, forage_grounds
from app.sim import nodes
from app.sim.simulation import Simulation
from app.sim.vec import Vec3, step_towards
from app.world_api.facade import WorldApi
from app.world_api.models import Compass
from tests.sim_helpers import add_animal, make_spec, nearest_node, skip_to, stand_at_node, without_animals

HOME_A = "band_a_camp:shelter-n"
CAMP = "band_a_camp"


def _brain(sim: Simulation, citizen_id: str, grounds: tuple[Compass, ...]) -> UtilityBrain:
    citizen = sim.citizen(citizen_id)
    profile = BrainProfile(
        citizen_id=citizen_id,
        name=citizen.name,
        role="gatherer",
        region="band_a",
        home_area=sim.world.places[CAMP].name,
        skills=citizen.skills,
        grounds=grounds,
    )
    return UtilityBrain(WorldApi(sim, citizen_id), profile, seed=1)


def _strip_food_near(sim: Simulation, centre: Vec3, metres: float, left: int = 0) -> None:
    """Every berry bush, root patch and oak within `metres` picked down to `left` (the home ring run thin)."""
    table = sim.world.nodes
    for _, node in table.near(sim.world.grid, centre, metres):
        if table.kind(node).item in GROUND_FOOD:
            nodes.change(sim.core, node, min(left, nodes.stock(sim.core, node)), None)


def _forager(new_sim: Callable[..., Simulation]) -> tuple[Simulation, str]:
    sim = without_animals(new_sim())
    forager = sim.add_citizen(
        make_spec("suna", site=CAMP, at=(0.0, 6.0), home=HOME_A, region="band_a", inventory={"wood": 2})
    )
    skip_to(sim, forager.position, night=False)
    return sim, forager.id


def _walked_towards(sim: Simulation, citizen_id: str) -> str:
    action = sim.citizen(citizen_id).action
    assert action is not None and action.kind == "walk_to"
    return action.label  # "to the east"


def test_the_grounds_are_the_ways_with_most_food_beyond_the_home_ring(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    grounds = forage_grounds(sim.world, "band_a")
    camp = sim.world.places[CAMP].centre
    totals = sim.world.nodes.food_by_bearing(sim.world.grid, camp, *GROUNDS_M, GROUND_FOOD)
    ways = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
    assert len(grounds) == 3 and len(set(grounds)) == 3
    picked = [totals[ways.index(way)] for way in grounds]
    assert picked == sorted(picked, reverse=True) and picked[0] == max(totals)  # most food first
    assert forage_grounds(sim.world, "town") == ()


def test_a_forager_with_nothing_left_about_camp_walks_out_to_its_grounds(new_sim: Callable[..., Simulation]) -> None:
    sim, suna = _forager(new_sim)
    _strip_food_near(sim, sim.world.places[CAMP].centre, 300.0)
    brain = _brain(sim, suna, ("south", "east"))
    brain.decide()
    assert brain.api.notes["last"] == "forage trip" and brain.api.notes["trip"] == "south"
    assert _walked_towards(sim, suna) == "to the south"
    while sim.citizen(suna).action is not None:
        sim.step()
    start = sim.citizen(suna).position
    assert sim.world.distance_m(start, sim.world.places[CAMP].centre) > 400  # a long walk out
    brain.api.notes.pop("trip")  # home again (the trip's end): the next one goes the next way
    sim.core.place_at(sim.citizen(suna), sim.world.places[CAMP].stand)
    brain.decide()
    assert brain.api.notes["trip"] == "east" and _walked_towards(sim, suna) == "to the east"


def test_scraps_about_camp_send_a_forager_out_but_plenty_keeps_it_there(new_sim: Callable[..., Simulation]) -> None:
    sim, suna = _forager(new_sim)
    camp = sim.world.places[CAMP].centre
    _strip_food_near(sim, camp, 300.0, left=1)  # a berry or a root left here and there: "a few berries left"
    brain = _brain(sim, suna, ("south",))
    brain.decide()
    assert brain.api.notes["last"] == "forage trip"
    sim2, suna2 = _forager(new_sim)  # the home ring untouched, at one of its full berry bushes: no trip
    stand_at_node(sim2, suna2, nearest_node(sim2, "berry_bush", sim2.world.places[CAMP].centre))
    brain2 = _brain(sim2, suna2, ("south",))
    brain2.decide()
    assert brain2.api.notes["last"] != "forage trip" and "trip" not in brain2.api.notes


def test_no_trip_starts_late_in_the_day(new_sim: Callable[..., Simulation]) -> None:
    sim, suna = _forager(new_sim)
    _strip_food_near(sim, sim.world.places[CAMP].centre, 300.0)
    brain = _brain(sim, suna, ("south",))
    tick = sim.tick
    while brain.api.look_around().time_of_day != "late afternoon":
        tick += 10
        sim.state.tick = tick
    assert "late afternoon" not in TRIP_TIMES
    brain.decide()
    assert brain.api.notes["last"] != "forage trip"  # a search about camp instead: back by dusk


def test_game_cutting_the_walk_short_keeps_the_trip_going(new_sim: Callable[..., Simulation]) -> None:
    sim, suna = _forager(new_sim)
    _strip_food_near(sim, sim.world.places[CAMP].centre, 300.0)
    brain = _brain(sim, suna, ("south",))
    brain.decide()
    sim.step()
    forager = sim.citizen(suna)
    add_animal(sim, "deer", step_towards(forager.position, 180.0, 60.0, sim.world.radius_m), until=10**9)
    for _ in range(3):  # the deer comes into view: the walk stops
        sim.step()
        if forager.action is None:
            break
    assert forager.action is None
    brain.decide()
    assert brain.api.notes["last"] == "forage trip" and _walked_towards(sim, suna) == "to the south"  # on out


def test_a_badly_bitten_spear_carrier_runs_from_the_wolf(new_sim: Callable[..., Simulation]) -> None:
    sim, suna = _forager(new_sim)
    forager = sim.citizen(suna)
    forager.inventory["flint spear"] = 1
    sim.core.place_at(forager, step_towards(sim.world.places[CAMP].centre, 0.0, 200.0, sim.world.radius_m))  # no fire
    beside = step_towards(forager.position, 90.0, 10.0, sim.world.radius_m)
    add_animal(sim, "wolf", beside, hunger=80.0, activity="hunting", target=suna, until=10**9)  # coming at her
    brain = _brain(sim, suna, ())
    brain.decide()
    assert brain.api.notes["last"] == "fight off"
    forager.body.health = 45.0  # "weak and aching": bitten twice already
    forager.action = None
    brain.decide()
    assert brain.api.notes["last"] == "flee"
