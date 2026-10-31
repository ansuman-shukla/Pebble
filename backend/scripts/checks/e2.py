"""E2's run checks (10-world-v1 §2.6-2.7): the granary feeds only its eaters unless someone steals, every take from
someone else's store is a `stole`, the tax books replay exactly from their events, each harvest owes ⌈40 %⌉, overdue
only when owed, and every citizen gets a ledger a day."""

import math
from collections import Counter
from collections.abc import Mapping
from typing import override

from app.observability.events import EventDraft, ItemMoved, TaxChange
from app.sim.clock import DAY_MINUTES
from app.sim.ownership import fed_by_granary, free_to_take, is_granary, owner_of
from app.sim.simulation import Simulation
from app.sim.tax import RICE_TAX, TAX
from scripts.checks.base import Check, Outcome

TAKEN = frozenset({"inventory", "eaten"})


class Granary(Check):
    """Rice taken from the granary by citizens it doesn't feed, without a `stole` (must be none), and the measures
    stolen from it."""

    name = "e2.granary"

    @override
    def start(self, sim: Simulation) -> None:
        self.unpaid = 0
        self.stolen = 0
        self.fed = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        stole = {event.seq for event in events if event.type == "stole"}
        for event in events:
            moved = event.payload
            if not isinstance(moved, ItemMoved) or moved.source.kind != "store" or moved.destination.kind not in TAKEN:
                continue
            if not is_granary(sim.world, str(moved.source.id)) or event.actor_id is None:
                continue
            if event.cause_seq in stole:
                self.stolen += moved.count
            elif fed_by_granary(sim.state.citizens[event.actor_id]):
                self.fed += moved.count
            else:
                self.unpaid += moved.count

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = f"{self.unpaid} taken unseen by the books, {self.fed} fed, {self.stolen} stolen"
        return Outcome(self.unpaid, self.unpaid == 0, words)


class Theft(Check):
    """Takes from a store the taker neither owns nor has a grant at, that emitted no `stole` (must be none)."""

    name = "e2.theft"

    @override
    def start(self, sim: Simulation) -> None:
        self.missed: list[str] = []
        self.thefts = 0

    @override
    def before_step(self, sim: Simulation) -> None:
        self._free: dict[tuple[str, str, str], int | None] = {}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        stole = {event.seq for event in events if event.type == "stole"}
        self.thefts += len(stole)
        for event in events:
            moved = event.payload
            if not isinstance(moved, ItemMoved) or moved.source.kind != "store" or moved.destination.kind not in TAKEN:
                continue
            store, actor = str(moved.source.id), event.actor_id
            if actor is None or owner_of(sim.world, store) is None or event.cause_seq in stole:
                continue
            citizen = sim.state.citizens[actor]
            if free_to_take(sim.core, citizen, store, moved.item) == 0 and not is_granary(sim.world, store):
                self.missed.append(f"tick {event.tick}: {actor} took {moved.count} {moved.item} from {store}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        missed = len(self.missed)
        return Outcome(missed, not missed, self.missed[0] if missed else f"{self.thefts} thefts, each told")


class Books(Check):
    """Ticks whose end the households' accounts differ from what their tax events say they owe (per tick)."""

    name = "e2.books"

    @override
    def start(self, sim: Simulation) -> None:
        self.owed: dict[str, tuple[int, int]] = {}
        self.wrong: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, TaxChange):
                self.owed[event.payload.household] = (event.payload.owed_rice, event.payload.owed_coins)
        accounts = TAX.of(sim.state).accounts
        books = {household: (account.rice, account.coins) for household, account in accounts.items()}
        books = {household: owed for household, owed in books.items() if owed != (0, 0) or household in self.owed}
        if books != self.owed and not self.wrong:
            self.wrong.append(f"tick {sim.state.tick}: books {books} but the events say {self.owed}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        owed = ", ".join(f"{h} {r} rice {c} mon" for h, (r, c) in sorted(self.owed.items()) if r or c)
        return Outcome(len(self.wrong), not self.wrong, self.wrong[0] if self.wrong else f"owed at the end: {owed}")


class RiceTax(Check):
    """Rice tax assessments that aren't ⌈40 %⌉ of the harvest they follow (must be none), and the share of the
    assessed rice paid."""

    name = "e2.rice_tax"

    @override
    def start(self, sim: Simulation) -> None:
        self.harvests: dict[int, int] = {}
        self.wrong: list[str] = []
        self.assessed = 0
        self.paid = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            payload = event.payload
            if isinstance(payload, ItemMoved) and payload.item == "rice" and payload.destination.kind == "inventory":
                self.harvests[event.seq] = payload.count
            elif isinstance(payload, TaxChange) and payload.rice and event.type == "tax_assessed":
                self.assessed += payload.rice
                harvest = self.harvests.get(event.cause_seq or -1)
                if harvest is None or payload.rice != math.ceil(RICE_TAX * harvest):
                    self.wrong.append(f"tick {event.tick}: {payload.rice} rice owed on a harvest of {harvest}")
            elif isinstance(payload, TaxChange) and event.type == "tax_paid":
                self.paid += payload.rice

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        share = self.paid / self.assessed if self.assessed else 0.0
        words = self.wrong[0] if self.wrong else f"{self.assessed} assessed, {share:.0%} paid"
        return Outcome(len(self.wrong), not self.wrong and self.assessed > 0, words)


class Overdue(Check):
    """`tax_overdue` events that owe nothing overdue (must be none); how many a day."""

    name = "e2.overdue"

    @override
    def start(self, sim: Simulation) -> None:
        self.empty = 0
        self.told = 0
        self.ticks = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.ticks += 1
        for event in events:
            if event.type == "tax_overdue" and isinstance(event.payload, TaxChange):
                self.told += 1
                self.empty += not (event.payload.rice or event.payload.coins)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        per_day = self.told / max(1, self.ticks) * DAY_MINUTES
        return Outcome(self.empty, self.empty == 0, f"{per_day:.1f}/day, {self.empty} owing nothing")


class Ledgers(Check):
    """Living citizens whose ledgers a day were not one each (the worst gap from a whole day's count)."""

    name = "e2.ledgers"

    @override
    def start(self, sim: Simulation) -> None:
        self.counts: Counter[str] = Counter()
        self.ticks = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.ticks += 1
        self.counts.update(str(event.actor_id) for event in events if event.type == "ledger")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        days = self.ticks // DAY_MINUTES
        living = [citizen.id for citizen in sim.core.living()]
        worst = max((abs(self.counts[citizen] - days) for citizen in living), default=0)
        return Outcome(worst, worst <= 1, f"{sum(self.counts.values())} ledgers over {days} days, worst gap {worst}")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        passed = sum(outcome.ok for outcome in outcomes.values())
        worst = max(outcome.value for outcome in outcomes.values())
        return Outcome(worst, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds pass, worst gap {worst:.0f}")


CHECKS: tuple[type[Check], ...] = (Granary, Theft, Books, RiceTax, Overdue, Ledgers)
