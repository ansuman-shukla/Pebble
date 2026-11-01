"""SC1's run checks (10-world-v1 §7): the spectator scoreboard, built every few game hours from the run's state and
events the way the endpoint builds it, always finds the closed money supply whole (`money_supply_ok`)."""

from typing import override

from app.observability.events import EventDraft, TickSummary
from app.observability.replay import from_snapshot
from app.services.ambitions import Facts, Record
from app.services.scoreboard import record_of, score_board
from app.sim.clock import DAY_MINUTES, TICKS_PER_HOUR
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot
from app.sim.society import SOCIETY
from scripts.checks.base import Check, Outcome

EVERY = 6 * TICKS_PER_HOUR  # ticks between boards
SKIPPED = frozenset({"tick_summary", "perceived", "said", "gestured", "goal_set"})  # nothing the board reads


class MoneySupply(Check):
    """Boards whose money supply wasn't whole (must be none)."""

    name = "sc1.money_supply"

    @override
    def start(self, sim: Simulation) -> None:
        self.records: list[Record] = []
        self.bodies: list[tuple[int, TickSummary]] = []
        self.boards = 0
        self.broken: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, TickSummary):
                self.bodies.append((event.tick, event.payload))
            elif event.type not in SKIPPED:
                self.records.append(record_of(event))
        if sim.tick % EVERY:
            return
        self.bodies = [(tick, summary) for tick, summary in self.bodies if tick > sim.tick - DAY_MINUTES]
        facts = Facts(tick=sim.tick, state=from_snapshot(take_snapshot(sim.state)), events=self.records)
        samples = [summary.bodies for _, summary in self.bodies]
        board = score_board(facts, samples, SOCIETY.of(sim.state).bonds, sim.world)
        self.boards += 1
        if not board.money_supply_ok:
            self.broken.append(f"tick {sim.tick}: {board.money_supply}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = self.broken[0] if self.broken else f"whole on all {self.boards} boards"
        return Outcome(len(self.broken), not self.broken, words)


CHECKS: tuple[type[Check], ...] = (MoneySupply,)
