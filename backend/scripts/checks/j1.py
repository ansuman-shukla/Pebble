"""J1's run checks: the temple bell keeps the town's day, standing stays in its range, and every group keeps one
leader (10-world-v1 §3.2, 3.5, 3.6)."""

from collections import Counter
from collections.abc import Mapping
from typing import override

from app.observability.events import BellRang, EventDraft, LeaderChanged, StandingChanged
from app.sim.clock import DAY_MINUTES, game_minute
from app.sim.simulation import Simulation
from app.sim.society import GROUPS, SOCIETY, load_laws
from scripts.checks.base import Check, Outcome

ON_TIME_MINUTES = 10  # a bell within this long after its moment by the town's clock (§3.6 acceptance)
LEADER_CHANGES_MAX = 2  # per group in a run: more is a flapping succession


class Bells(Check):
    """Share of the bells of each whole town day (dawn, noon, dusk) that rang once, within 10 minutes of their moment;
    the run must keep ≥ 95 % of them."""

    name = "j1.bells"
    least = 0.95

    @override
    def start(self, sim: Simulation) -> None:
        self.rung: Counter[tuple[int, str]] = Counter()  # (day, kind) -> bells rung on time
        self.late: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        moments = load_laws().bell.moments
        for event in events:
            if isinstance(event.payload, BellRang):
                day, minute = divmod(game_minute(event.tick), DAY_MINUTES)
                if 0 <= minute - moments[event.payload.kind] <= ON_TIME_MINUTES:
                    self.rung[(day, event.payload.kind)] += 1
                else:
                    self.late.append(f"day {day} {event.payload.kind} at {minute // 60:02d}:{minute % 60:02d}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        first, last = 1, game_minute(sim.tick) // DAY_MINUTES - 1  # whole days only (day 0 starts at 08:00)
        due = [(day, kind) for day in range(first, last + 1) for kind in load_laws().bell.moments]
        missed = [f"day {day} {kind}" for day, kind in due if self.rung[(day, kind)] != 1]
        share = 1 - len(missed) / max(1, len(due))
        off = f", missed {', '.join(missed[:3])}" if missed else ""
        off += f", off time {', '.join(self.late[:3])}" if self.late else ""
        return Outcome(share, share >= self.least, f"{len(due) - len(missed)}/{len(due)} on time{off}")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        passed = sum(outcome.ok for outcome in outcomes.values())
        least = min(outcome.value for outcome in outcomes.values())
        return Outcome(least, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds pass, least {least:.0%}")


class Standing(Check):
    """Ticks at whose end some standing lay outside -100..100 (per tick); also counts the deed-driven changes."""

    name = "j1.standing"

    @override
    def start(self, sim: Simulation) -> None:
        self.outside: list[str] = []
        self.causes: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for citizen_id, values in SOCIETY.of(sim.state).standing.items():
            for group, value in values.items():
                if not -100 <= value <= 100:
                    self.outside.append(f"{citizen_id} {value} with {group} at tick {sim.tick}")
        self.causes.update(event.payload.cause for event in events if isinstance(event.payload, StandingChanged))

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        causes = ", ".join(f"{count} {cause}" for cause, count in self.causes.most_common(4))
        words = self.outside[0] if self.outside else f"in range ({causes or 'no changes'})"
        return Outcome(len(self.outside), not self.outside, words)


class Leaders(Check):
    """Ticks at whose end a group with a living adult had no living lord or leader, or more than one (per tick);
    and at most two leader changes per group in a run."""

    name = "j1.leaders"

    @override
    def start(self, sim: Simulation) -> None:
        self.bad: list[str] = []
        self.changes: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.changes.update(event.payload.group for event in events if isinstance(event.payload, LeaderChanged))
        state = SOCIETY.of(sim.state)
        for group in GROUPS:
            title = "lord" if group == "town" else "leader"
            living = [m for m, member in state.members.items() if member.group == group and _alive(sim, m)]
            heads = [m for m in living if title in state.members[m].titles]
            if len(heads) > 1 or (not heads and group != "town" and any(state.members[m].adult for m in living)):
                self.bad.append(f"{group} led by {heads or 'nobody'} at tick {sim.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        flapping = [group for group, count in self.changes.items() if count > LEADER_CHANGES_MAX]
        bad = len(self.bad) + len(flapping)
        changes = ", ".join(f"{group} {count}" for group, count in sorted(self.changes.items())) or "none"
        words = self.bad[0] if self.bad else f"{changes} changed" if not flapping else f"flapping: {changes}"
        return Outcome(bad, bad == 0, words)


def _alive(sim: Simulation, citizen_id: str) -> bool:
    return sim.state.citizens[citizen_id].body.alive


CHECKS: tuple[type[Check], ...] = (Bells, Standing, Leaders)
