"""X0's run checks: the whole-run statistics `tests/brains/test_living.py` holds to on its one seed, measured the
same way on any seeds, so a chaotic flip can be told from a regression (probe-first triage)."""

from typing import override

from app.observability.events import EventDraft, Injured
from app.sim.simulation import Simulation
from app.sim.vec import Vec3
from scripts.checks.base import Check, Outcome

PROGRESS = frozenset({"walk_to", "gather", "eat", "drink", "work", "sleep"})
MAX_STALL_H = 6.0  # test_living's MAX_STALL_TICKS
MAX_NEED_DAMAGE = 10.0  # health lost to hunger and thirst
USED_ACTIONS = frozenset(
    {"walk_to", "follow", "gather", "hunt", "eat", "drink", "make_fire", "feed_fire", "rest", "sleep", "work"}
    | {"wait"}
)  # the durative actions a run must use (test_the_brains_use_every_action_but_recall)
# reported, not required: a predator must happen to come close (D107); a forager must happen to stand at one of the
# few drawn fishing spots (D152)
LUCKY_ACTIONS = frozenset({"attack", "flee", "fish"})


class Stall(Check):
    """The longest an awake citizen went without progress (moving, sleeping or a progress action), in hours."""

    name = "x0.stall"

    @override
    def start(self, sim: Simulation) -> None:
        self.last = dict.fromkeys(sim.state.citizens, 0)
        self.worst = dict.fromkeys(sim.state.citizens, 0)
        self.before: dict[str, Vec3] = {}

    @override
    def before_step(self, sim: Simulation) -> None:
        self.before = {c.id: c.position for c in sim.state.citizens.values()}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for citizen in sim.state.citizens.values():
            if not citizen.body.alive:
                continue
            moved = citizen.position != self.before[citizen.id]
            busy = citizen.action is not None and citizen.action.kind in PROGRESS
            if citizen.body.asleep or moved or busy:
                self.last[citizen.id] = sim.tick
            self.worst[citizen.id] = max(self.worst[citizen.id], sim.tick - self.last[citizen.id])

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        who, ticks = max(self.worst.items(), key=lambda item: item[1])
        hours = ticks / 60
        return Outcome(hours, hours < MAX_STALL_H, f"{hours:.1f} h ({who})" if ticks else "none")


class NeedDamage(Check):
    """The most health one citizen lost to hunger and thirst (drops in ticks without an injury)."""

    name = "x0.need_damage"

    @override
    def start(self, sim: Simulation) -> None:
        self.lost = dict.fromkeys(sim.state.citizens, 0.0)
        self.health: dict[str, float] = {}

    @override
    def before_step(self, sim: Simulation) -> None:
        self.health = {c.id: c.body.health for c in sim.state.citizens.values()}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        injured = {e.actor_id for e in events if isinstance(e.payload, Injured) and e.actor_kind == "citizen"}
        for citizen in sim.state.citizens.values():
            if citizen.id not in injured:
                self.lost[citizen.id] += max(0.0, self.health[citizen.id] - citizen.body.health)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        who, lost = max(self.lost.items(), key=lambda item: item[1])
        return Outcome(lost, lost <= MAX_NEED_DAMAGE, f"{lost:.1f} health ({who})" if lost else "none")


class Deaths(Check):
    """Citizens who died."""

    name = "x0.deaths"

    @override
    def start(self, sim: Simulation) -> None:
        self.dead: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.dead += [f"{e.actor_id}" for e in events if e.type == "died" and e.actor_kind == "citizen"]

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.dead), not self.dead, ", ".join(self.dead) or "none")


class Actions(Check):
    """Durative actions the brains never started: fails on a required one; the lucky ones are only reported."""

    name = "x0.actions"

    @override
    def start(self, sim: Simulation) -> None:
        self.started: set[str] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.started |= {str(getattr(e.payload, "action", "")) for e in events if e.type == "action_started"}

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        missing = sorted((USED_ACTIONS | LUCKY_ACTIONS) - self.started)
        required = USED_ACTIONS - self.started
        return Outcome(len(required), not required, ", ".join(missing) or "all used")


CHECKS: tuple[type[Check], ...] = (Stall, NeedDamage, Deaths, Actions)
