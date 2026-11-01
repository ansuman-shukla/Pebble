"""T1's run checks (10-world-v1 §1.5, 1.6, 3.3, 4.6): herds drink at their waterholes at dawn, animals live where
people meet them, every `trespassed` is a deed the rules name (and poaching happens), and whoever a den charged knows
that den. Over the seeds: poaching counts are summed, the waterhole share is the seeds' mean and the near-people share
the worst seed's."""

from collections import Counter
from collections.abc import Mapping
from typing import override

import numpy as np

from app.observability.events import EventDraft, ItemMoved, Trespassed
from app.sim import society
from app.sim.animals import WILDLIFE
from app.sim.clock import sun_altitude_deg, sun_direction
from app.sim.fauna import SPECIES, pin_of, waterhole_of
from app.sim.simulation import Simulation
from app.sim.state import Citizen
from app.sim.territory import CASTLE_TITLES, TERRITORY, poached
from app.sim.vec import Vec3
from scripts.checks.a1 import CAMP_M, EXPOSURE
from scripts.checks.base import Check, Outcome

LIVING_SITES = ("town", "band_a_camp", "band_b_camp")
DRINK_WINDOW_TICKS = 180  # a herd counts as at its waterhole at dawn if it drinks there within this long of sunrise
AT_WATERHOLE_M = 40.0
NEAR_M = 100.0  # "some animal within 100 m of a person" (10 §4.6, audit F9)
SAMPLE_TICKS = 5  # the near-people share is sampled every this many ticks


def _rose(sim: Simulation, unit: Vec3) -> bool:
    before = sun_altitude_deg(unit, sun_direction(sim.tick - 1, sim.world.town_lon_deg))
    return before <= 0 < sim.core.altitude(unit)


class Waterholes(Check):
    """Dawns (sunrise at its home) on which a herd with a waterhole drank there within 3 h, as a share of its dawns
    (≥ 70 % over the seeds, 10 §4.6: herds drink at dawn and dusk; the waterhole is the ambush spot)."""

    name = "t1.waterholes"
    least = 0.7

    @override
    def start(self, sim: Simulation) -> None:
        self.hits = self.dawns = 0
        self.open: dict[str, tuple[int, bool]] = {}  # herd -> (its window's last tick, drank yet)

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        world = sim.world
        for group in sim.state.groups.values():
            species = SPECIES[group.kind]
            hole = waterhole_of(world, group) if not species.predator and not species.swims else None
            if hole is None:
                continue
            window = self.open.get(group.id)
            if window is None and _rose(sim, world.unit(group.home)):
                window = self.open[group.id] = (sim.tick + DRINK_WINDOW_TICKS, False)
            if window is None:
                continue
            last, drank = window
            drank = drank or any(
                (animal := sim.state.animals[m]).alive
                and animal.activity == "drinking"
                and world.distance_m(animal.position, hole) <= AT_WATERHOLE_M
                for m in group.members
            )
            if sim.tick < last:
                self.open[group.id] = (last, drank)
                continue
            del self.open[group.id]
            self.dawns += 1
            self.hits += drank

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        share = self.hits / self.dawns if self.dawns else 0.0
        return Outcome(share, share >= self.least, f"{share:.0%} of {self.dawns} herd dawns")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        share = sum(outcome.value for outcome in outcomes.values()) / len(outcomes)
        return Outcome(share, share >= cls.least, f"{share:.0%} over the seeds (≥ {cls.least:.0%})")


class NearPeople(Check):
    """Daytime ticks (sun up there) on which some animal stood within 100 m of a person within 1 km of a settlement,
    as a share of that settlement's daytime ticks; the worst settlement's share over the seeds must be ≥ 50 % (audit
    F9 measured 20 % within 100 m)."""

    name = "t1.near_people"
    pending = EXPOSURE
    least = 0.5

    @override
    def start(self, sim: Simulation) -> None:
        self.hits: Counter[str] = Counter()
        self.ticks: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        if sim.tick % SAMPLE_TICKS:
            return
        world = sim.world
        animals = np.array(
            [a.position for a in sim.state.animals.values() if a.alive and a.kind not in ("fish", "shark")]
        )
        living = sim.core.living()
        cos_near = np.cos(NEAR_M / world.radius_m)
        for site in LIVING_SITES:
            centre = world.places[site].centre
            if sim.core.altitude(centre) <= 0:
                continue
            self.ticks[site] += 1
            people = np.array([p.position for p in living if world.distance_m(p.position, centre) <= CAMP_M])
            if people.size and animals.size and bool((people @ animals.T >= cos_near).any()):
                self.hits[site] += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        shares = {site: self.hits[site] / max(1, self.ticks[site]) for site in LIVING_SITES}
        worst = min(shares, key=lambda site: shares[site])
        words = ", ".join(f"{site} {self.hits[site]}/{self.ticks[site]}" for site in LIVING_SITES)
        return Outcome(shares[worst], shares[worst] >= self.least, words)

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, worst >= cls.least, f"worst settlement on the worst seed {worst:.0%} (≥ 50 %)")


class Trespasses(Check):
    """`trespassed` deeds that break the rules' own words (must be none): a `walls` by a town member or by day, a
    `castle` by the lord, a samurai or an ashigaru, a `ground` without a take or on ground the taker may take from."""

    name = "t1.trespasses"

    @override
    def start(self, sim: Simulation) -> None:
        self.kinds: Counter[str] = Counter()
        self.wrong: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        by_seq = {event.seq: event for event in events}
        for event in events:
            if not isinstance(event.payload, Trespassed) or event.actor_id is None:
                continue
            deed, doer = event.payload, sim.state.citizens[event.actor_id]
            self.kinds[f"{deed.kind} by {doer.region}"] += 1
            why = ""
            if deed.kind != "ground" and not society.night_law(sim.core):
                why = "by day"
            elif deed.kind == "walls" and doer.region == "town":
                why = "a town member in the walls"
            elif deed.kind == "castle" and CASTLE_TITLES & set(society.titles(sim.core, doer.id)):
                why = "a castle title in the castle"
            elif deed.kind == "ground" and deed.took is None:
                why = "poaching without a take"
            elif deed.kind == "ground" and not self._wronged(sim, doer, by_seq.get(event.cause_seq or -1)):
                why = "a take on ground the taker may take from"
            if why:
                self.wrong.append(f"{doer.id} {deed.kind} at tick {sim.tick}: {why}")

    @staticmethod
    def _wronged(sim: Simulation, doer: Citizen, cause: EventDraft | None) -> bool:
        """The take the deed names (its cause, an `item_moved` out of the wild) wronged a ground where it was made:
        a hunt if it came from an animal, else a gathering or a felling."""
        if cause is None or not isinstance(cause.payload, ItemMoved) or cause.position is None:
            return False
        hunting = cause.payload.source.kind == "animal"
        return poached(sim.core, doer, cause.position, hunting=hunting) is not None

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        counts = ", ".join(f"{count} {kind}" for kind, count in sorted(self.kinds.items())) or "none"
        return Outcome(len(self.wrong), not self.wrong, self.wrong[0] if self.wrong else counts)


class Poaching(Check):
    """Poaching deeds (`trespassed` with a take), over the seeds (≥ 1: Kaz's hunts in the Lord's woods, 10 §3.6)."""

    name = "t1.poaching"
    least = 1

    @override
    def start(self, sim: Simulation) -> None:
        self.count = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.count += sum(isinstance(e.payload, Trespassed) and e.payload.took is not None for e in events)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.count, True, str(self.count))

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= cls.least, f"{total:.0f} over the seeds (≥ {cls.least})")


class DensLearned(Check):
    """People a predator charged at its den who don't know that den by the end of the tick (must be none)."""

    name = "t1.dens_learned"

    @override
    def start(self, sim: Simulation) -> None:
        self.charged: set[tuple[str, str]] = set()
        self.unlearned: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        dens = TERRITORY.of(sim.state).dens
        for animal_id, why in WILDLIFE.of(sim.state).charges.items():
            animal = sim.state.animals[animal_id]
            pin = pin_of(sim.world, sim.state.groups[animal.group])
            if why != "den" or animal.target not in sim.state.citizens or pin is None:
                continue
            self.charged.add((animal.target, pin.place))
            if pin.place not in dens.get(animal.target, []):
                self.unlearned.append(f"{animal.target} charged by {animal_id} at tick {sim.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = self.unlearned[0] if self.unlearned else f"{len(self.charged)} charged, all learned"
        return Outcome(len(self.unlearned), not self.unlearned, words)


CHECKS: tuple[type[Check], ...] = (Waterholes, NearPeople, Trespasses, Poaching, DensLearned)
