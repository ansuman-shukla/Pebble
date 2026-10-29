"""E1's run checks: the closed money supply holds at every tick, and food visibly spoils at dawn (10-world-v1 §2.1,
§2.4)."""

from collections import Counter
from collections.abc import Mapping
from typing import override

from app.observability.events import EventDraft, Spoiled
from app.sim.clock import DAY_MINUTES
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


class Spoilage(Check):
    """`spoiled` events a game day, and what went off: the run must show some food spoiling at dawn."""

    name = "e1.spoilage"

    @override
    def start(self, sim: Simulation) -> None:
        self.events = 0
        self.lost: Counter[str] = Counter()
        self.ticks = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.ticks += 1
        for event in events:
            if isinstance(event.payload, Spoiled):
                self.events += 1
                self.lost.update(event.payload.items)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        per_day = self.events / max(1, self.ticks) * DAY_MINUTES
        lost = ", ".join(f"{count} {item}" for item, count in self.lost.most_common())
        return Outcome(per_day, self.events > 0, f"{per_day:.1f}/day ({lost or 'nothing'})")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        passed = sum(outcome.ok for outcome in outcomes.values())
        least = min(outcome.value for outcome in outcomes.values())
        return Outcome(least, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds spoil, least {least:.1f}/day")


CHECKS: tuple[type[Check], ...] = (Coins, Spoilage)
