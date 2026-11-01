"""J2's run checks (10-world-v1 §3.4): the held stay within 3 m of their seizer, no custody outlasts 12 h, every
judgement has a known deed or overdue tax behind it, and (summed over both seeds) deeds get witnessed and judged and
the healers tend. The chains themselves are proven by the scenario tests (`tests/sim/test_justice.py`); the last two
checks count what the brains that seize, judge and tend (BR1, BR2) bring about in a run."""

from collections.abc import Mapping
from typing import override

from app.observability.events import EventDraft, Judged, Released, SentenceServed, Tended
from app.sim.clock import TICKS_PER_HOUR
from app.sim.custody import CUSTODY, CUSTODY_HOURS, held_pairs
from app.sim.simulation import Simulation
from app.sim.society import SOCIETY
from scripts.checks.base import Check, Outcome

HELD_M = 3.0
CUSTODY_TICKS = CUSTODY_HOURS * TICKS_PER_HOUR
SERVED_LEAST = 2  # both seeds together
TENDS_LEAST = 2  # both seeds together: the monk and the band healers tend someone hurt


class HeldClose(Check):
    """Ticks at whose end someone held stood more than 3 m from their seizer (per tick)."""

    name = "j2.held_close"

    @override
    def start(self, sim: Simulation) -> None:
        self.far: list[str] = []
        self.held_ticks = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for person, keeper in held_pairs(sim.core):
            self.held_ticks += 1
            metres = sim.core.distance_m(sim.state.citizens[person].position, sim.state.citizens[keeper].position)
            if metres > HELD_M:
                self.far.append(f"{person} {metres:.1f} m from {keeper} at tick {sim.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = self.far[0] if self.far else f"{self.held_ticks} held ticks, all within {HELD_M:g} m"
        return Outcome(len(self.far), not self.far, words)


class Custody(Check):
    """Custodies that lasted longer than 12 h, from the seizure to the release (per tick)."""

    name = "j2.custody"

    @override
    def start(self, sim: Simulation) -> None:
        self.longest = 0
        self.ended = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for custody in CUSTODY.of(sim.state).values():
            self.longest = max(self.longest, sim.tick - custody.since)
        self.ended += sum(isinstance(event.payload, Released) for event in events)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        hours = self.longest / TICKS_PER_HOUR
        words = f"{self.ended} released, longest {hours:.1f} h"
        return Outcome(hours, self.longest <= CUSTODY_TICKS, words)


class Grounds(Check):
    """Judgements with neither a deed nor overdue tax behind them, and judged deeds the judge didn't know of."""

    name = "j2.grounds"

    @override
    def start(self, sim: Simulation) -> None:
        self.bad: list[str] = []
        self.count = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        known = SOCIETY.of(sim.state).known
        for event in events:
            if not isinstance(event.payload, Judged):
                continue
            self.count += 1
            judged = event.payload
            unknown = set(judged.deeds) - set(known.get(str(event.actor_id), []))
            if (not judged.deeds and not judged.arrears) or unknown:
                self.bad.append(f"{event.actor_id} judged {judged.person} at tick {event.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = self.bad[0] if self.bad else f"{self.count} judgements, all on known grounds"
        return Outcome(len(self.bad), not self.bad, words)


class Served(Check):
    """Sentences served (a deed or overdue tax judged, the fine paid or the confinement over), summed over the seeds
    (≥ 2: the critic's "≥ 2 witnessed and judged")."""

    name = "j2.served"

    @override
    def start(self, sim: Simulation) -> None:
        self.served = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.served += sum(isinstance(event.payload, SentenceServed) for event in events)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.served, self.served >= SERVED_LEAST, f"{self.served} sentences served")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= SERVED_LEAST, f"{total:g} served over the seeds")


class Tends(Check):
    """Half hours of tending done, summed over the seeds (≥ 2)."""

    name = "j2.tends"

    @override
    def start(self, sim: Simulation) -> None:
        self.tends = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.tends += sum(isinstance(event.payload, Tended) for event in events)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.tends, self.tends >= TENDS_LEAST, f"{self.tends} tended")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= TENDS_LEAST, f"{total:g} tended over the seeds")


CHECKS: tuple[type[Check], ...] = (HeldClose, Custody, Grounds, Served, Tends)
