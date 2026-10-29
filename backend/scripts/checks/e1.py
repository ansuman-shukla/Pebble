"""E1's run checks: the closed money supply holds at every tick (10-world-v1 §2.1)."""

from typing import override

from app.observability.events import EventDraft
from app.sim.economy import MoneyLeak, check_money_supply
from app.sim.simulation import Simulation
from scripts.checks.base import Check, Outcome


class Coins(Check):
    """Ticks at whose end the coins in inventories, stores and on the ground didn't add up to the money supply (per
    tick)."""

    name = "e1.coins"

    @override
    def start(self, sim: Simulation) -> None:
        self.leaks: list[str] = []
        self._check(sim)

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self._check(sim)

    def _check(self, sim: Simulation) -> None:
        try:
            check_money_supply(sim.state)
        except MoneyLeak as leak:
            self.leaks.append(str(leak))

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.leaks), not self.leaks, self.leaks[0] if self.leaks else "3 000 every tick")


CHECKS: tuple[type[Check], ...] = (Coins,)
