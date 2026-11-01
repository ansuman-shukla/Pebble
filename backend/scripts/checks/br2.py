"""BR2's run checks (the plan's BR2 acceptance, both seeds together): the bands go out to their hotspots, band A's
trading trips sell, nobody in a band starves, band B's deeds happen (some seen and judged, some not) and band B pans
gold when hunger chooses it."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, override

from app.observability.events import Died, EventDraft, ItemMoved, Judged, Stole, Traded, Trespassed
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from app.sim.vec import Vec3, as_vec
from scripts.checks.base import Check, Outcome

OUTING_M = 500.0  # a hotspot this far from the camp is an outing past the home ring
OUTINGS_FROM_DAY = 4  # the home ring runs thin by then (10 §1.2)
HUNGER_DEATHS = frozenset({"starvation", "dehydration"})
CAMPS = {"band_a": "band_a_camp", "band_b": "band_b_camp"}


class Outings(Check):
    """Days from day 4 on which no member of a band stood in one of its hotspots ≥ 500 m from camp (must be none)."""

    name = "br2.outings"

    @override
    def start(self, sim: Simulation) -> None:
        world = sim.world
        self.far: dict[str, list[tuple[Vec3, float]]] = {
            region: [
                (as_vec(spot.centre), spot.radius_m)
                for spot in world.hotspots
                if world.distance_m(world.places[camp].centre, spot.centre) >= OUTING_M
            ]
            for region, camp in CAMPS.items()
        }
        self.out: dict[str, set[int]] = {region: set() for region in CAMPS}
        self.days: set[int] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        day = (sim.tick - 1) // DAY_MINUTES  # tick t ends the t-th minute of the run
        if day < OUTINGS_FROM_DAY or sim.tick % 10:
            return
        self.days.add(day)
        for citizen in sim.core.living():
            spots = self.far.get(citizen.region)
            if spots and any(sim.world.distance_m(citizen.position, at) <= r for at, r in spots):
                self.out[citizen.region].add(day)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        missed = {region: sorted(self.days - out) for region, out in self.out.items()}
        count = sum(len(days) for days in missed.values())
        words = ", ".join(f"{region} {len(self.days) - len(days)}/{len(self.days)}" for region, days in missed.items())
        return Outcome(count, count == 0, f"days out: {words}")


class TradeTrips(Check):
    """Band A's trading trips that sold something (a trader's day with a `sold`), over the seeds (≥ 6)."""

    name = "br2.trade_trips"
    least: ClassVar[int] = 6

    @override
    def start(self, sim: Simulation) -> None:
        self.trips: set[tuple[str, int]] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if event.type == "sold" and event.actor_id is not None:
                if sim.state.citizens[event.actor_id].region == "band_a":
                    self.trips.add((event.actor_id, sim.tick // DAY_MINUTES))

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        days = {day for _, day in self.trips}
        return Outcome(len(days), True, f"{len(days)} trip days ({len(self.trips)} traders' sales days)")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= cls.least, f"{total:.0f} over the seeds (≥ {cls.least})")


class BandHunger(Check):
    """Band members dead of hunger or thirst (must be none)."""

    name = "br2.band_hunger"

    @override
    def start(self, sim: Simulation) -> None:
        self.dead: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Died) and event.actor_kind == "citizen" and event.actor_id is not None:
                if event.payload.cause in HUNGER_DEATHS and sim.state.citizens[event.actor_id].region in CAMPS:
                    self.dead.append(f"{event.actor_id} ({event.payload.cause})")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.dead), not self.dead, ", ".join(self.dead) or "none")


class _OverSeeds(Check):
    """A count over the seeds that must reach `least`."""

    least: ClassVar[int]

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= cls.least, f"{total:.0f} over the seeds (≥ {cls.least})")


@dataclass(frozen=True)
class DeedsSeen(Outcome):
    judged: int = 0  # witnessed deeds whose doer was judged after
    unseen: int = 0  # deeds nobody saw


class BandBDeeds(_OverSeeds):
    """Band B's deeds (thefts and trespasses) over the seeds: ≥ 6, at least one witnessed and its doer judged after,
    and at least one nobody saw (10 §3.3, §3.6)."""

    name = "br2.deeds"
    pending = "witnessed-and-judged raid needs Q1 tuning"
    least = 6

    @override
    def start(self, sim: Simulation) -> None:
        self.seen: dict[str, int] = {}  # doer -> witnessed deeds not yet judged
        self.count = self.judged = self.unseen = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            payload, doer = event.payload, event.actor_id
            if isinstance(payload, Stole | Trespassed) and doer and sim.state.citizens[doer].region == "band_b":
                self.count += 1
                if payload.witnesses:
                    self.seen[doer] = self.seen.get(doer, 0) + 1
                else:
                    self.unseen += 1
            elif isinstance(payload, Judged) and self.seen.get(payload.person):
                self.judged += self.seen.pop(payload.person)

    @override
    def outcome(self, sim: Simulation) -> DeedsSeen:
        words = f"{self.count} deeds, {self.judged} seen and judged, {self.unseen} unseen"
        return DeedsSeen(self.count, True, words, self.judged, self.unseen)

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        judged = sum(o.judged for o in outcomes.values() if isinstance(o, DeedsSeen))
        unseen = sum(o.unseen for o in outcomes.values() if isinstance(o, DeedsSeen))
        ok = total >= cls.least and judged >= 1 and unseen >= 1
        return Outcome(total, ok, f"{total:.0f} deeds ({judged} seen and judged, {unseen} unseen) over the seeds")


class GoldTrips(_OverSeeds):
    """Days band B took gold from the falls pool or sold it at the stall, over the seeds (≥ 2)."""

    name = "br2.gold_trips"
    least = 2

    @override
    def start(self, sim: Simulation) -> None:
        self.days: set[int] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            doer = event.actor_id
            if doer is None or doer not in sim.state.citizens or sim.state.citizens[doer].region != "band_b":
                continue
            moved = isinstance(event.payload, ItemMoved) and event.payload.item == "gold"
            sold = event.type == "sold" and isinstance(event.payload, Traded) and event.payload.item == "gold"
            if moved or sold:
                self.days.add(sim.tick // DAY_MINUTES)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.days), True, f"{len(self.days)} days")


CHECKS: tuple[type[Check], ...] = (Outings, TradeTrips, BandHunger, BandBDeeds, GoldTrips)
