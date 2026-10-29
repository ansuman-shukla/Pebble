"""Walking up to a person (10-world-v1 §4.3, D193): whoever walks up to or catches up with someone ends a pace in front
of them, facing them, never on their spot; a group walking up to one person from one side stands round them."""

from collections.abc import Callable

from app.sim.destinations import BESIDE_M
from app.sim.simulation import Simulation
from app.sim.slots import PERSONAL_M
from app.sim.state import Citizen
from app.sim.vec import bearing_deg
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec, without_animals


def _facing_error(walker: Citizen, person: Citizen) -> float:
    to_person = (180.0 - bearing_deg(walker.position, person.position)) % 360.0
    return abs((walker.heading_deg - to_person + 180) % 360 - 180)


def test_a_group_walking_up_to_one_person_stands_round_them_facing_them(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = without_animals(new_sim(seed=4))
    person = sim.add_citizen(make_spec("person", at=(-30.0, 61.0)))
    walkers = [sim.add_citizen(make_spec(f"walker{k}", at=(-45.0 - k * 0.5, 61.0 + k * 0.7))) for k in range(4)]
    for walker in walkers:
        WorldApi(sim, walker.id).walk_to_person("a person in a person cloak")
    for _ in range(5):
        sim.step()
    for walker in walkers:
        assert walker.action is None  # arrived
        assert abs(sim.world.distance_m(walker.position, person.position) - BESIDE_M) < 0.05, walker.id
        assert _facing_error(walker, person) < 1.0, walker.id
    people = [person, *walkers]
    apart = min(sim.world.distance_m(a.position, b.position) for i, a in enumerate(people) for b in people[i + 1 :])
    assert apart >= PERSONAL_M
    # someone stands on the side they all came from (west); the rest spread round from there
    sides = sorted(bearing_deg(person.position, walker.position) for walker in walkers)
    assert any(abs(side - 270.0) < 15.0 for side in sides), sides


def test_catching_up_with_a_walker_who_stops_ends_beside_them_facing_them(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = without_animals(new_sim(seed=4))
    leader = sim.add_citizen(make_spec("leader", at=(-30.0, 61.0)))
    follower = sim.add_citizen(make_spec("follower", at=(-40.0, 61.0)))
    WorldApi(sim, leader.id).walk_to_place("the well")
    WorldApi(sim, follower.id).follow("a person in a leader cloak")
    for _ in range(8):
        sim.step()
    assert leader.action is None and follower.action is None
    assert abs(sim.world.distance_m(follower.position, leader.position) - BESIDE_M) < 0.05
    assert _facing_error(follower, leader) < 1.0
