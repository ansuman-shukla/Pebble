"""Band forage trips (N1, D152): once the home ring is picked over (10 §1.2), foragers walk out to their band's food
grounds beyond it, a different way each trip, early enough in the day to be back by dusk; game cutting a walk short
doesn't end the trip, a refusal does; a forager badly bitten runs from a wolf instead of fighting it again."""

from collections.abc import Callable

from app.brains.brain import UtilityBrain
from app.brains.grounds import DEN_CLEAR_M, GROUND_FOOD, GROUNDS_M, STOP_CLEAR_M, WAYS, forage_grounds
from app.brains.profile import BrainProfile, Ground
from app.brains.routines import TRIP_LEGS, TRIP_TIMES
from app.sim import nodes
from app.sim.destinations import COMPASS_BEARING, ROUGH_DISTANCE_M
from app.sim.simulation import Simulation
from app.sim.vec import Vec3, step_towards
from app.world_api.facade import WorldApi
from app.world_api.models import Compass
from tests.sim_helpers import add_animal, make_spec, nearest_node, skip_to, stand_at_node, without_animals

HOME_A = "band_a_camp:shelter-n"
CAMP = "band_a_camp"


def _brain(sim: Simulation, citizen_id: str, ways: tuple[Compass, ...], legs: int = TRIP_LEGS) -> UtilityBrain:
    citizen = sim.citizen(citizen_id)
    profile = BrainProfile(
        citizen_id=citizen_id,
        name=citizen.name,
        role="gatherer",
        region="band_a",
        home_area=sim.world.places[CAMP].name,
        skills=citizen.skills,
        grounds=tuple(Ground(way, legs) for way in ways),
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
    kept = forage_grounds(sim.world, CAMP)
    camp = sim.world.places[CAMP].centre
    dens = _dens(sim)
    totals = sim.world.nodes.food_by_bearing(
        sim.world.grid, camp, *GROUNDS_M, GROUND_FOOD, avoid=dens, clear_m=DEN_CLEAR_M
    )
    assert len(kept) == 3 and len({ground.way for ground in kept}) == 3
    picked = [totals[WAYS.index(ground.way)] for ground in kept]
    assert picked == sorted(picked, reverse=True) and picked[0] == max(totals)  # most food first


def _dens(sim: Simulation) -> list[Vec3]:
    return [feature.position for feature in sim.world.features if feature.kind == "den"]


def _stop(sim: Simulation, region: str, way: Compass, leg: int) -> Vec3:
    camp = sim.world.places[f"{region}_camp"].centre
    metres = ROUGH_DISTANCE_M["a long walk"] + leg * ROUGH_DISTANCE_M["a short walk"]
    return step_towards(camp, COMPASS_BEARING[way], metres, sim.world.radius_m)


def test_forage_trips_stop_short_of_the_dens(new_sim: Callable[..., Simulation]) -> None:
    """Band B's richest ways run at the wolves' and the bears' dens (Kaz walked into one): every stop of a trip keeps
    300 m from every den (so the food seen from there lies 150 m clear), and the walks on end before the first stop
    that wouldn't."""
    sim = new_sim()
    dens = _dens(sim)

    def clear(region: str, way: Compass, leg: int) -> bool:
        return all(sim.world.distance_m(_stop(sim, region, way, leg), den) >= STOP_CLEAR_M for den in dens)

    for region in ("band_a", "band_b"):
        for ground in forage_grounds(sim.world, f"{region}_camp"):
            assert all(clear(region, ground.way, leg) for leg in range(ground.legs + 1))
            assert ground.legs == TRIP_LEGS or not clear(region, ground.way, ground.legs + 1)
    camp = sim.world.places["band_b_camp"].centre
    near_dens = sim.world.nodes.food_by_bearing(sim.world.grid, camp, *GROUNDS_M, GROUND_FOOD)
    richest = [WAYS[sector] for sector in sorted(range(len(WAYS)), key=lambda sector: -near_dens[sector])[:3]]
    by_dens = [way for way in richest if not all(clear("band_b", way, leg) for leg in range(TRIP_LEGS + 1))]
    kept = {ground.way: ground.legs for ground in forage_grounds(sim.world, "band_b_camp")}
    assert by_dens  # the wolves' and the bears' dens lie on band B's richest ways
    assert all(kept.get(way, -1) < TRIP_LEGS for way in by_dens)  # dropped, or walked on only so far
    away = sim.world.nodes.food_by_bearing(
        sim.world.grid, camp, *GROUNDS_M, GROUND_FOOD, avoid=dens, clear_m=DEN_CLEAR_M
    )
    assert sum(away) < sum(near_dens)  # food by a den doesn't draw a trip


def test_a_trip_goes_no_further_than_its_ground_allows(new_sim: Callable[..., Simulation]) -> None:
    for legs, searches in ((1, False), (2, True)):
        sim, suna = _forager(new_sim)
        _strip_food_near(sim, sim.world.places[CAMP].centre, 2000.0)
        brain = _brain(sim, suna, ("south",), legs=legs)
        brain.api.notes.update(trip="south", trip_legs=1)  # out on a trip, one short walk on already
        brain.decide()
        assert (brain.api.notes["last"] == "search further") is searches


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
