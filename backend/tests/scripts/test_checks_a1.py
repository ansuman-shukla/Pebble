"""A1's herd checks: predators' kills count against `a1.herds_kept`, hunters' against `a1.hunting_pressure`; moves at
rest count against `a1.resting_moves`, trotted travel against `a1.herd_trots`."""

from collections.abc import Callable

import pytest

from app.observability.events import AnimalGait, EventDraft
from app.sim import animals
from app.sim.animals import Walk
from app.sim.clock import DAY_MINUTES, SECONDS_PER_TICK
from app.sim.fauna import SPECIES, near_people
from app.sim.simulation import Simulation
from app.sim.state import Animal
from app.sim.vec import step_towards
from scripts.checks import CHECKS, a1
from tests.sim_helpers import make_spec


def _day_end(sim: Simulation, checks: list[a1._HerdLosses], events: list[EventDraft]) -> None:
    sim.state.tick = DAY_MINUTES
    for check in checks:
        check.after_step(sim, events)


def test_only_predator_kills_cost_a_herd_its_keep_and_only_hunter_kills_its_hunting_pressure(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    hunter = sim.add_citizen(make_spec("hunter"))
    herd = next(
        g for g in sorted(sim.state.groups.values(), key=lambda g: g.id)
        if not SPECIES[g.kind].predator and g.kind != "fish" and near_people(sim.world, g) and g.size >= 4
    )  # fmt: skip
    kept, pressure = a1.HerdsKept(), a1.HuntingPressure()
    for check in (kept, pressure):
        check.start(sim)
    sim.drain()
    first, second, third = (sim.state.animals[m] for m in herd.members[:3])
    animals.kill(sim.core, first, "killed by a wolf", attacker="wolf:1")
    animals.kill(sim.core, second, "hunted", attacker=hunter.id, remains=True)
    animals.kill(sim.core, third, "hunted", attacker=hunter.id, remains=True)
    _day_end(sim, [kept, pressure], sim.drain())
    assert kept.outcome(sim).value <= 1 - 1 / herd.size + 1e-9  # the wolf's kill counts
    assert kept.outcome(sim).value > 1 - 2 / herd.size  # the hunters' don't
    assert pressure.outcome(sim).value <= 1 - 2 / herd.size + 1e-9


def test_hunting_pressure_and_herds_kept_count() -> None:
    by_name = {check.name: check for check in CHECKS}
    assert by_name["a1.hunting_pressure"].pending is None  # the band hunters spread over the herds (BR2)
    assert by_name["a1.herds_kept"].pending is None


def _walked(sim: Simulation, animal: Animal, metres: float, gait: AnimalGait) -> Walk:
    end = step_towards(animal.position, 90.0, metres, sim.world.radius_m)
    return Walk(((animal.position, 0.0), (end, float(SECONDS_PER_TICK))), 1, gait, metres / SECONDS_PER_TICK)


def test_resting_moves_counts_a_move_faster_than_a_walk_shown_at_rest_both_ends(
    new_sim: Callable[..., Simulation],
) -> None:
    """Regression: deer:77 was shown grazing at both ends of a tick it trotted 286 m in, and a1 passed."""
    sim = new_sim()
    deer = [a for a in sorted(sim.state.animals.values(), key=lambda a: a.id) if a.kind == "deer"][:4]
    check = a1.RestingMoves()
    check.start(sim)
    for animal in deer:
        animal.activity = "grazing"
    check.before_step(sim)
    walk_m = SPECIES["deer"].walk_mps * SECONDS_PER_TICK
    walks = animals.WILDLIFE.of(sim.state).walks
    walks.clear()
    walks[deer[0].id] = _walked(sim, deer[0], 286.0, "trot")  # grazing to grazing: counted
    walks[deer[1].id] = _walked(sim, deer[1], walk_m, "walk")  # a walk's minute to a new spot: fine
    walks[deer[2].id] = _walked(sim, deer[2], 286.0, "trot")  # setting off at a trot: fine
    deer[2].activity = "trotting"
    deer[3].activity = "sleeping"
    walks[deer[3].id] = _walked(sim, deer[3], walk_m * 1.05, "walk")  # grazing to sleeping, a little fast: counted
    check.after_step(sim, [])
    outcome = check.outcome(sim)
    assert outcome.value == 2 and not outcome.ok


def test_herd_trots_is_the_share_of_herbivore_travel_trotted_flights_and_predators_aside(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    living = sorted(sim.state.animals.values(), key=lambda a: a.id)
    deer = [a for a in living if a.kind == "deer"][:3]
    wolf = next(a for a in living if a.kind == "wolf")
    check = a1.HerdTrots()
    check.start(sim)
    walks = animals.WILDLIFE.of(sim.state).walks
    walks.clear()
    walks[deer[0].id] = _walked(sim, deer[0], 100.0, "trot")
    walks[deer[1].id] = _walked(sim, deer[1], 200.0, "walk")
    walks[deer[2].id] = _walked(sim, deer[2], 500.0, "run")  # a flight
    walks[wolf.id] = _walked(sim, wolf, 500.0, "trot")
    check.after_step(sim, [])
    assert check.outcome(sim).value == pytest.approx(1 / 3, rel=1e-6) and not check.outcome(sim).ok
    walks[deer[0].id] = _walked(sim, deer[0], 40.0, "trot")
    check.after_step(sim, [])
    assert check.outcome(sim).value == pytest.approx(140 / 540, rel=1e-6) and not check.outcome(sim).ok
    walks.pop(deer[0].id)
    check.after_step(sim, [])
    assert check.outcome(sim).value == pytest.approx(140 / 740, rel=1e-6) and check.outcome(sim).ok
