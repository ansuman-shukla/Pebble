"""A1's herd checks: predators' kills count against `a1.herds_kept`, hunters' against `a1.hunting_pressure`."""

from collections.abc import Callable

from app.observability.events import EventDraft
from app.sim import animals
from app.sim.clock import DAY_MINUTES
from app.sim.fauna import SPECIES, near_people
from app.sim.simulation import Simulation
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
