"""What a run check is: it sees one seed's run tick by tick and gives that seed's `Outcome`."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from app.observability.events import EventDraft
from app.sim.simulation import Simulation


@dataclass(frozen=True)
class Outcome:
    value: float  # the measured number (for sweeps)
    ok: bool
    words: str  # what was measured, briefly ("3.2 h (kenji)")


class Check(ABC):
    """One check over one seed's run; a new instance per seed."""

    name: ClassVar[str]  # "<stream>.<what>"

    def start(self, sim: Simulation) -> None:  # noqa: B027  # optional hook
        """Once the citizens are in and their brains made, before the first tick."""

    def before_step(self, sim: Simulation) -> None:  # noqa: B027  # optional hook
        """Each tick after the brains acted, just before the simulation steps."""

    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:  # noqa: B027  # optional hook
        """Each tick after the step, with the events it emitted."""

    @abstractmethod
    def outcome(self, sim: Simulation) -> Outcome:
        """This seed's outcome, at the end of its run."""

    @classmethod
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        """All seeds together (seed -> outcome)."""
        passed = sum(outcome.ok for outcome in outcomes.values())
        worst = max(outcome.value for outcome in outcomes.values())
        return Outcome(worst, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds pass, worst {worst:.3g}")
