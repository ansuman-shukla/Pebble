"""The brain stubs of the World v1 roles (D130): the monk keeps to the temple."""

from collections.abc import Callable

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.observability.events import ActionStarted
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec, without_animals

WELL = (-20.0, 56.0)


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
