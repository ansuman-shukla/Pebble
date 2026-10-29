"""E1's run checks: the money supply at every tick."""

from collections.abc import Callable

from app.sim.citizens import CITIZENS, load_citizens
from app.sim.simulation import Simulation
from scripts.checks import CHECKS, e1
from scripts.checks.base import Outcome


def test_the_coins_check_holds_while_the_supply_does_and_names_the_first_leak(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    check = e1.Coins()
    check.start(sim)
    sim.step()
    check.after_step(sim, sim.drain())
    assert check.outcome(sim) == Outcome(0, True, "3 000 every tick")
    sim.citizen("tetsu").inventory["coins"] += 2  # minted
    sim.step()
    check.after_step(sim, sim.drain())
    sim.step()
    check.after_step(sim, sim.drain())
    assert check.outcome(sim) == Outcome(2, False, "tick 2: the world holds 3002 coins, not 3000 (+2)")
    assert e1.Coins in CHECKS
