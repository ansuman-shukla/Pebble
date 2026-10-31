"""BR0's run checks (10-world-v1 plan, BR0): every brain says what it is after, greets with a gesture, talks, runs
only when it must, and walks to its work slot itself instead of being walked there at the tick's end."""

from collections import Counter
from collections.abc import Mapping
from typing import override

from app.observability.events import EventDraft, Gestured
from app.sim.bodies import body_words
from app.sim.clock import DAY_MINUTES
from app.sim.perception import nearest_danger
from app.sim.simulation import Simulation
from app.sim.slots import STEP_MAX_M, held_slot
from scripts.checks.base import Check, Outcome

GOAL_SHARE = 0.95  # of awake non-idle citizen-ticks with a goal set since waking
GESTURES_PER_DAY = 1.0  # waves and bows per citizen-day
BOWS_TO_THE_LORD = 1.0  # bows to Masanori per day, over the run (critic: townsfolk bow to Masanori)
SAID_PER_DAY = 3.0  # per citizen-day (audit F8: about one)
DESPERATE = frozenset({"starving", "terribly thirsty"})
LORD = "masanori"
CAMP_FIRES = ("band_a_camp:fire-pit", "band_b_camp:fire-pit")
CAMP_FIRE_SHARE = 0.8  # of the night each camp fire burns


class Goals(Check):
    """The share of awake citizen-ticks busy at something other than waiting with a goal set since they woke."""

    name = "br0.goals"

    @override
    def start(self, sim: Simulation) -> None:
        self.aimed: set[str] = set()
        self.busy = 0
        self.with_goal = 0
        self.missing: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.aimed |= {event.actor_id for event in events if event.type == "goal_set" and event.actor_id is not None}
        for citizen in sim.core.living():
            if citizen.body.asleep:
                self.aimed.discard(citizen.id)
                continue
            if citizen.action is None or citizen.action.kind == "wait":
                continue
            self.busy += 1
            if citizen.id in self.aimed:
                self.with_goal += 1
            else:
                self.missing[citizen.id] += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        share = self.with_goal / self.busy if self.busy else 0.0
        worst = ", ".join(f"{who} {ticks}" for who, ticks in self.missing.most_common(2))
        return Outcome(share, share >= GOAL_SHARE, f"{share:.1%} ({worst or 'none without'})")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:  # the lowest share is worst
        passed = sum(outcome.ok for outcome in outcomes.values())
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds pass, worst {worst:.1%}")


class _PerDay(Check):
    """A count over the run per citizen-day, with at least `floor` needed; the lowest seed is the worst."""

    floor: float

    def per_day(self, sim: Simulation, count: float) -> float:
        days = sim.tick / DAY_MINUTES
        return count / (len(sim.state.citizens) * days) if days else 0.0

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:  # the lowest rate is worst
        passed = sum(outcome.ok for outcome in outcomes.values())
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds pass, worst {worst:.2f}")


class Gestures(_PerDay):
    """Waves and bows per citizen-day (greetings come with one), and bows to the lord per day."""

    name = "br0.gestures"
    floor = GESTURES_PER_DAY

    @override
    def start(self, sim: Simulation) -> None:
        self.kinds: Counter[str] = Counter()
        self.to_lord = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Gestured) and event.payload.kind in ("wave", "bow"):
                self.kinds[event.payload.kind] += 1
                self.to_lord += event.payload.kind == "bow" and event.payload.to == LORD

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        rate = self.per_day(sim, self.kinds["wave"] + self.kinds["bow"])
        lord = self.to_lord / (sim.tick / DAY_MINUTES)
        ok = rate >= self.floor and self.kinds["bow"] > 0 and lord >= BOWS_TO_THE_LORD
        return Outcome(rate, ok, f"{rate:.2f}/citizen-day ({self.kinds['bow']} bows, {lord:.1f}/day to the lord)")


class Said(_PerDay):
    """Things said per citizen-day (greetings, replies, small talk)."""

    name = "br0.said"
    floor = SAID_PER_DAY

    @override
    def start(self, sim: Simulation) -> None:
        self.said = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.said += sum(event.type == "said" for event in events)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        rate = self.per_day(sim, self.said)
        return Outcome(rate, rate >= self.floor, f"{rate:.2f}/citizen-day")


class Runners(Check):
    """Walks and follows set off at a run by someone neither desperate (starving, terribly thirsty) nor with a
    predator in view: none allowed."""

    name = "br0.runners"

    @override
    def start(self, sim: Simulation) -> None:
        self.runs = 0
        self.wrong: Counter[str] = Counter()

    @override
    def before_step(self, sim: Simulation) -> None:
        core = sim.core
        for citizen in core.living():
            action = citizen.action
            if action is None or action.started_tick != sim.tick or action.args.get("pace") != "run":
                continue
            self.runs += 1
            if not DESPERATE & set(body_words(citizen.body)) and nearest_danger(core, citizen) is None:
                self.wrong[citizen.id] += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        wrong = sum(self.wrong.values())
        who = ", ".join(sorted(self.wrong)) or "none"
        return Outcome(wrong, wrong == 0, f"{wrong} of {self.runs} runs without cause ({who})")


class WorkWalks(Check):
    """Work started more than a tick's-end step (8 m) from the work slot it took, so the worker is walked there at
    the tick's end under the work's label (issue #89): none allowed."""

    name = "br0.work_walks"

    @override
    def start(self, sim: Simulation) -> None:
        self.far: Counter[str] = Counter()
        self.worst = 0.0

    @override
    def before_step(self, sim: Simulation) -> None:
        core = sim.core
        for citizen in core.living():
            action = citizen.action
            if action is None or action.kind != "work" or action.started_tick != sim.tick:
                continue
            slot = held_slot(core, citizen)
            if slot is None or slot.kind != "work":
                continue
            metres = core.distance_m(citizen.position, slot.position)
            if metres > STEP_MAX_M:
                self.far[citizen.id] += 1
                self.worst = max(self.worst, metres)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        count = sum(self.far.values())
        who = ", ".join(sorted(self.far)) or "none"
        return Outcome(count, count == 0, f"{count} (worst {self.worst:.0f} m; {who})")


class CampFires(Check):
    """The share of night minutes each camp's fire burns (test_living's: over 0.8), the worse camp's."""

    name = "br0.camp_fires"

    @override
    def start(self, sim: Simulation) -> None:
        self.lit: Counter[str] = Counter()
        self.night: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for camp in CAMP_FIRES:
            fire = sim.state.fires[camp]
            if sim.core.is_night_at(fire.position):
                self.night[camp] += 1
                self.lit[camp] += fire.lit

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        shares = {camp.split("_camp")[0]: self.lit[camp] / self.night[camp] for camp in CAMP_FIRES if self.night[camp]}
        worst = min(shares.values(), default=0.0)
        words = ", ".join(f"{camp} {share:.0%}" for camp, share in shares.items())
        return Outcome(worst, worst > CAMP_FIRE_SHARE, words)

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:  # the lowest share is worst
        passed = sum(outcome.ok for outcome in outcomes.values())
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, passed == len(outcomes), f"{passed}/{len(outcomes)} seeds pass, worst {worst:.0%}")


CHECKS: tuple[type[Check], ...] = (Goals, Gestures, Said, Runners, WorkWalks, CampFires)
