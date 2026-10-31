"""S1's run checks (10-world-v1 §4.3): bodies keep their personal space at every tick's end, everyone working at a
task done at slots stands on one of its slots, and town folk asleep at home are inside, not on the doorstep."""

from typing import override

from app.observability.events import EventDraft
from app.sim.perception import HOME_RADIUS_M
from app.sim.simulation import Simulation
from app.sim.slots import crowded, is_inside, off_work_slot
from scripts.checks.base import Check, Outcome


class Crowded(Check):
    """Tick ends with two bodies (not walking, not inside) closer than 0.8 m: none allowed (audit F2: 88 %)."""

    name = "s1.crowded"

    @override
    def start(self, sim: Simulation) -> None:
        self.ticks = 0
        self.example = ""

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        pairs = crowded(sim.core)
        if pairs:
            self.ticks += 1
            if not self.example:
                a, b, metres = pairs[0]
                self.example = f" (first: tick {sim.tick} {a}+{b} {metres:.2f} m)"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.ticks, self.ticks == 0, f"{self.ticks} ticks{self.example}")


class OffSlot(Check):
    """Worker-ticks at a slotted task (farm, weave, trade, guard, govern, pray) off its slots: none allowed."""

    name = "s1.off_slot"

    @override
    def start(self, sim: Simulation) -> None:
        self.samples = 0
        self.who: set[str] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        off = off_work_slot(sim.core)
        self.samples += len(off)
        self.who |= set(off)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.samples, self.samples == 0, f"{self.samples} ({', '.join(sorted(self.who)) or 'none'})")


class Doorstep(Check):
    """Sleeper-ticks of town folk asleep at their house's door but not inside it (audit F16): none allowed."""

    name = "s1.doorstep"

    @override
    def start(self, sim: Simulation) -> None:
        self.samples = 0
        self.who: set[str] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        core = sim.core
        for citizen in core.living():
            home = core.world.structures.get(citizen.home) if citizen.home is not None else None
            if not citizen.body.asleep or home is None or home.kind == "lean_to":
                continue
            at_door = core.distance_m(citizen.position, home.door) <= HOME_RADIUS_M
            if at_door and not is_inside(core, citizen):
                self.samples += 1
                self.who.add(citizen.id)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.samples, self.samples == 0, f"{self.samples} ({', '.join(sorted(self.who)) or 'none'})")


CHECKS: tuple[type[Check], ...] = (Crowded, OffSlot, Doorstep)
