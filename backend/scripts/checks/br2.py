"""BR2's run checks (the plan's BR2 acceptance, both seeds together): the bands go out to their hotspots, band A's
trading trips sell, and nobody in a band starves. Band B's deeds (raids, judged at the fire) and gold trips wait for
the band-B hunger choice."""

from collections.abc import Mapping
from typing import ClassVar, override

from app.observability.events import Died, EventDraft
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


CHECKS: tuple[type[Check], ...] = (Outings, TradeTrips, BandHunger)
