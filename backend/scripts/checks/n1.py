"""N1's run checks (10-world-v1 §1.1, §1.4): every gather, catch and farm hour happens at a node's spot, nothing short
of its cap is stuck, the paddies yield the rice balance and the camps' home rings run thin."""

from collections.abc import Mapping
from typing import override

from app.observability.events import ActionEnded, ActionStarted, EventDraft, NodeChanged
from app.sim import nodes, paddies
from app.sim.clock import DAY_MINUTES
from app.sim.node_table import PADDY_KIND
from app.sim.simulation import Simulation
from scripts.checks.base import Check, Outcome

REACH_M = 3.2  # the most a worker may stand from the spot (and a gatherer from the node) they work at
NODE_ACTIONS = frozenset({"gather", "fish"})
# the bible's harvest: six paddies × 60 ÷ a 3-day cycle (10 §1.4; back from N1's tuned 152 with BR1, D180)
RICE_A_DAY = 120.0
RICE_BAND = 0.15
RICE_DAYS = (4, 14)  # the balance is judged once the start's ripe paddies are in
HOME_RING_M = 400.0
HOME_RING_DAY = 4
HOME_RING_SHARE = 0.4
FOOD = frozenset({"berries", "roots", "nuts"})


class Reach(Check):
    """Gather, fish and farm completions with the worker more than 3.2 m from the spot (or a gatherer from the node)
    they worked at, or naming no node: none allowed (audit F3: every berry gather had no bush within 8 m)."""

    name = "n1.reach"

    @override
    def start(self, sim: Simulation) -> None:
        self.started: dict[str, dict[str, object]] = {}
        self.done = 0
        self.bad: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        table = sim.world.nodes
        for event in events:
            if isinstance(event.payload, ActionStarted) and event.actor_id is not None:
                self.started[event.actor_id] = {"action": event.payload.action, **event.payload.args}
            if not isinstance(event.payload, ActionEnded) or event.payload.outcome != "done":
                continue
            args = self.started.get(str(event.actor_id), {})
            action = event.payload.action
            if action not in NODE_ACTIONS and not (action == "work" and args.get("task") == "farm"):
                continue
            self.done += 1
            slot, position = str(args.get("slot")), event.position
            node_id = slot.rpartition("#")[0]
            if position is None or node_id not in table.index:
                self.bad.append(f"{event.actor_id} {action} at tick {event.tick} names no node")
                continue
            spot = table.spots(table.index[node_id])[int(slot.rpartition("#")[2])].position
            off = sim.world.distance_m(position, spot)
            if action in NODE_ACTIONS:
                off = max(off, sim.world.distance_m(position, table.unit(table.index[node_id])))
            if off > REACH_M:
                self.bad.append(f"{event.actor_id} {action} {off:.1f} m off {node_id} at tick {event.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = f"{len(self.bad)} of {self.done}" + (f" (first: {self.bad[0]})" if self.bad else "")
        return Outcome(len(self.bad), not self.bad and self.done > 0, words)


class InPaddies(Check):
    """Farm completions with the farmer standing outside every paddy: none allowed (audit F4)."""

    name = "n1.in_paddies"

    @override
    def start(self, sim: Simulation) -> None:
        self.working: set[str] = set()
        self.farmed = 0
        self.outside: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, ActionStarted) and event.actor_id is not None:
                if event.payload.action == "work" and event.payload.args.get("task") == "farm":
                    self.working.add(event.actor_id)
                else:
                    self.working.discard(event.actor_id)
            if isinstance(event.payload, ActionEnded) and event.actor_id in self.working:
                self.working.discard(event.actor_id)
                if event.payload.outcome == "done" and event.position is not None:
                    self.farmed += 1
                    if paddies.paddy_at(sim.core, event.position) is None:
                        self.outside.append(f"{event.actor_id} at tick {event.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = f"{len(self.outside)} of {self.farmed}" + (f" (first: {self.outside[0]})" if self.outside else "")
        return Outcome(len(self.outside), not self.outside and self.farmed > 0, words)


class Regrowing(Check):
    """Ticks ending with a node short of its cap and nothing growing it back (gold and the paddies aside): none
    allowed (per tick)."""

    name = "n1.regrowing"

    @override
    def start(self, sim: Simulation) -> None:
        self.ticks = 0
        self.example = ""

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        stuck = nodes.below_cap(sim.core)
        if stuck:
            self.ticks += 1
            self.example = self.example or f" (first: {stuck[0]} at tick {sim.tick})"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.ticks, self.ticks == 0, f"{self.ticks} ticks{self.example}")


class Rice(Check):
    """Rice harvested from the paddies a game day over days 4-14: RICE_A_DAY ±15 % over all seeds together (the
    bible's balance of §1.4)."""

    name = "n1.rice"

    @override
    def start(self, sim: Simulation) -> None:
        self.harvested = 0
        self.days: set[int] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        day = sim.tick // DAY_MINUTES
        if not RICE_DAYS[0] <= day < RICE_DAYS[1]:
            return
        self.days.add(day)
        for event in events:
            payload = event.payload
            if isinstance(payload, NodeChanged) and payload.kind == PADDY_KIND and event.actor_kind == "citizen":
                self.harvested += max(0, payload.before - payload.after)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        per_day = self.harvested / len(self.days) if self.days else 0.0
        return Outcome(per_day, _in_band(per_day), f"{per_day:.0f} a day over {len(self.days)} days")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        mean = sum(outcome.value for outcome in outcomes.values()) / len(outcomes)
        return Outcome(mean, _in_band(mean), f"{mean:.0f} a day (target {RICE_A_DAY:.0f} ± {RICE_BAND:.0%})")


def _in_band(per_day: float) -> bool:
    return abs(per_day - RICE_A_DAY) <= RICE_BAND * RICE_A_DAY


class HomeRing(Check):
    """Share of the food the camps' home rings (≤ 400 m) hold when full that is left at the start of day 4: under
    40 % at each camp (10 §1.2: the home ring runs thin on day 3-4 and foragers go farther)."""

    name = "n1.home_ring"
    pending = "BR2 band trips"

    @override
    def start(self, sim: Simulation) -> None:
        table = sim.world.nodes
        self.rings: dict[str, list[int]] = {}
        for camp in ("band_a_camp", "band_b_camp"):
            centre = sim.world.places[camp].centre
            near = table.near(sim.world.grid, centre, HOME_RING_M)
            self.rings[camp] = [node for _, node in near if table.kind(node).item in FOOD]
        self.shares: dict[str, float] = {}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        if sim.tick != HOME_RING_DAY * DAY_MINUTES:
            return
        caps = sim.world.nodes.caps
        for camp, ring in self.rings.items():
            full = sum(int(caps[node]) for node in ring)
            self.shares[camp] = sum(nodes.stock(sim.core, node) for node in ring) / full if full else 0.0

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        worst = max(self.shares.values(), default=1.0)
        words = ", ".join(f"{camp} {share:.0%}" for camp, share in sorted(self.shares.items())) or "day 4 not reached"
        return Outcome(worst, bool(self.shares) and worst < HOME_RING_SHARE, words)


CHECKS: tuple[type[Check], ...] = (Reach, InPaddies, Regrowing, Rice, HomeRing)
