"""B1's run checks (10-world-v1 §4.1): nobody outruns their gait's cap, every move is streamed as a path, elders stay
slow and heavy loads never run. Per tick, over every citizen who moved."""

from typing import override

from app.observability.events import EventDraft, TickSummary
from app.sim.core import Stride
from app.sim.simulation import Simulation
from app.sim.vec import Vec3
from scripts.checks.base import Check, Outcome

CAPS_M = {"walk": 84.0, "jog": 150.0, "run": 210.0, "stalk": 48.0}  # metres a tick
ELDER_MAX_MPS = 2.0
HEAVY = 0.9  # carried kg / carry kg


def _metres(sim: Simulation, stride: Stride) -> float:
    spots = [unit for unit, _ in stride.walked]
    return sum(sim.world.distance_m(a, b) for a, b in zip(spots, spots[1:], strict=False))


class SpeedCap(Check):
    """The most anyone walked in a tick as a share of their gait's cap (≤ 1.01 passes)."""

    name = "b1.speed_cap"

    @override
    def start(self, sim: Simulation) -> None:
        self.worst, self.who = 0.0, "nobody"

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for citizen_id, stride in sim.core.strides.items():
            share = _metres(sim, stride) / CAPS_M[stride.gait]
            if share > self.worst:
                self.worst, self.who = share, f"{citizen_id} {stride.gait}"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.worst, self.worst <= 1.01, f"{self.worst:.3f} of the cap ({self.who})")


class Streamed(Check):
    """Moves of a millimetre or more with no streamed path to draw them by (0 passes)."""

    name = "b1.streamed"

    @override
    def start(self, sim: Simulation) -> None:
        self.unstreamed = 0
        self.before: dict[str, Vec3] = {}

    @override
    def before_step(self, sim: Simulation) -> None:
        self.before = {c.id: c.position for c in sim.state.citizens.values() if c.body.alive}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        summary = next(e.payload for e in events if isinstance(e.payload, TickSummary))
        for citizen_id, start in self.before.items():
            now = sim.state.citizens[citizen_id].position
            moved = summary.moved.get(citizen_id)
            if sim.world.distance_m(start, now) >= 0.001 and (moved is None or len(moved.route) < 2):
                self.unstreamed += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.unstreamed, self.unstreamed == 0, f"{self.unstreamed} moves without a path")


class ElderSpeed(Check):
    """The fastest an elder went in a tick, metres a second (≤ 2.0 passes)."""

    name = "b1.elder_speed"

    @override
    def start(self, sim: Simulation) -> None:
        self.fastest = 0.0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for citizen_id, stride in sim.core.strides.items():
            if sim.state.citizens[citizen_id].group == "elder" and stride.walked[-1][1] > 0:
                self.fastest = max(self.fastest, _metres(sim, stride) / stride.walked[-1][1])

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.fastest, self.fastest <= ELDER_MAX_MPS, f"{self.fastest:.2f} m/s")


class HeavyRun(Check):
    """Minutes someone carrying 90 % of what they can ran (0 passes)."""

    name = "b1.heavy_run"

    @override
    def start(self, sim: Simulation) -> None:
        self.runs = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for citizen_id, stride in sim.core.strides.items():
            citizen = sim.state.citizens[citizen_id]
            if stride.gait == "run" and sim.core.carried_kg(citizen) >= HEAVY * citizen.traits.carry_kg:
                self.runs += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.runs, self.runs == 0, f"{self.runs} heavy runs")


CHECKS: tuple[type[Check], ...] = (SpeedCap, Streamed, ElderSpeed, HeavyRun)
