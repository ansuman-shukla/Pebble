"""The 22 citizens' brain stubs (D130): every role of the World v1 cast routes to a routine, and the monk keeps to
the temple."""

from collections.abc import Callable

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile, Routine
from app.observability.events import ActionStarted
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec, without_animals

ROUTINES: dict[str, Routine] = {
    "masanori": "lord",
    "kenji": "samurai",
    "goro": "samurai",  # the ashigaru walks the samurai's rounds until the night watch
    "fumiko": "merchant",
    "genzo": "farmer",
    "aiko": "weaver",
    "hana": "town_child",
    "tokuji": "farmer",
    "tetsu": "townsperson",
    "daisuke": "townsperson",
    "ennen": "monk",
    "ama": "band_leader",
    "bo": "hunter",
    "oru": "healer",
    "tek": "hunter",
    "lia": "gatherer",
    "suna": "gatherer",
    "barro": "band_leader",
    "nim": "gatherer",
    "kaz": "hunter",
    "pip": "band_child",
    "vesa": "healer",
}
WELL = (-20.0, 56.0)


def test_every_citizen_of_the_cast_routes_to_their_routine() -> None:
    routines = {
        spec.id: BrainProfile(spec.id, spec.name, spec.role, spec.region, "home").routine
        for spec in load_citizens(CITIZENS).citizens
    }
    assert routines == ROUTINES


def test_the_monk_walks_to_the_temple_and_prays_there(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    ennen = sim.add_citizen(
        make_spec("ennen", at=WELL, home="temple-hall", skills=["healing"], knows_places=["town", "temple", "well"])
    )
    profile = BrainProfile(ennen.id, ennen.name, "monk of the temple", "town", "The castle town", ("healing",))
    brain = UtilityBrain(WorldApi(sim, ennen.id), profile, seed=3)
    sim.drain()
    started: list[ActionStarted] = []
    for _ in range(120):  # two hours of the morning
        brain.tick()
        sim.step()
        started += [e.payload for e in sim.drain() if isinstance(e.payload, ActionStarted) and e.actor_id == "ennen"]
    assert started[0].action == "walk_to" and started[0].label == "the temple"
    prayers = [action for action in started if action.action == "work"]
    assert prayers and {action.args["task"] for action in prayers} == {"pray"}
    temple = sim.world.places["temple"]
    assert sim.world.distance_m(sim.citizen("ennen").position, temple.centre) <= temple.radius_m
