"""E1's run checks: the money supply at every tick, food spoiling at dawn."""

from collections.abc import Callable

from app.sim import wear
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


def test_the_spoilage_check_needs_some_food_to_spoil(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    check = e1.Spoilage()
    check.start(sim)
    sim.step()
    check.after_step(sim, sim.drain())
    assert check.outcome(sim) == Outcome(0.0, False, "0.0/day (nothing)")
    sim.citizen("tek").inventory["meat"] = 9
    wear.WEAR.of(sim.state).rising = {"tek"}  # tek's dawn, as wear.watch_sun would find it
    wear.spoil_at_dawn(sim.core, lambda _unit: False)
    check.after_step(sim, sim.drain())
    assert check.outcome(sim) == Outcome(720.0, True, "720.0/day (5 meat)")  # one in two ticks
    outcomes = {1: Outcome(3.0, True, "a"), 2: Outcome(0.0, False, "b")}
    assert e1.Spoilage.overall(outcomes) == Outcome(0.0, False, "1/2 seeds spoil, least 0.0/day")
