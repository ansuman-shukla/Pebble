"""K1's run checks (10-world-v1 §6.2, D63): every look and self-check a citizen gets is in-world words (no digits,
no ids), and what is seen still fits the sight budget: the lines listing people, animals and things take at most
LOOK_WORDS at the median. Over the seeds: any leak fails, and the worst seed's median counts."""

import re
import statistics
from collections.abc import Mapping
from typing import override

from app.observability.events import EventDraft, Perceived
from app.sim.simulation import Simulation
from scripts.checks.base import Check, Outcome

LOOK_WORDS = 130  # the median look's sight lines (D63's budget is 120 for things; people are never dropped)
SIGHT_LEADS = {"You see ": 2, "Animals: ": 1, "Around you: ": 2}  # the words that start the lines of what is seen
LEAK = re.compile(r"[0-9_]|:\S|stack-|main-w|shelter-|band_")  # digits, ids and id fragments


def _looks(events: list[EventDraft]) -> list[Perceived]:
    return [event.payload for event in events if isinstance(event.payload, Perceived)]


def sight_words(text: str) -> int:
    return sum(
        len(line.split()) - lead
        for line in text.splitlines()
        for start, lead in SIGHT_LEADS.items()
        if line.startswith(start)
    )


class LookWords(Check):
    """The median awake look's sight lines in words (≤ LOOK_WORDS on every seed)."""

    name = "k1.look_words"

    @override
    def start(self, sim: Simulation) -> None:
        self.sight: list[int] = []
        self.total: list[int] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for look in _looks(events):
            if look.kind == "look_around" and not look.text.startswith("You are asleep"):
                self.sight.append(sight_words(look.text))
                self.total.append(len(look.text.split()))

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        if not self.sight:
            return Outcome(0.0, False, "nobody looked around")
        median = statistics.median(self.sight)
        words = f"median {median:g} sight words, {statistics.median(self.total):g} in all, {len(self.sight)} looks"
        return Outcome(median, median <= LOOK_WORDS, words)


class InWorldWords(Check):
    """Looks and self-checks holding a digit or an id (none)."""

    name = "k1.in_world_words"

    @override
    def start(self, sim: Simulation) -> None:
        self.leaks: list[str] = []
        self.seen = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for look in _looks(events):
            self.seen += 1
            if LEAK.search(look.text):
                self.leaks.append(look.text)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        first = f": {self.leaks[0]!r}" if self.leaks else ""
        return Outcome(len(self.leaks), not self.leaks, f"{len(self.leaks)} of {self.seen} leak{first}")

    @classmethod
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        leaks = sum(outcome.value for outcome in outcomes.values())
        return Outcome(leaks, leaks == 0, f"{leaks:g} leaks over {len(outcomes)} seeds")


CHECKS: tuple[type[Check], ...] = (LookWords, InWorldWords)
