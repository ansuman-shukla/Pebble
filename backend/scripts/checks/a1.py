"""A1's run checks (10-world-v1 §4.6, §1.6): animals move only along streamed paths and never faster than their
gaits; a herd bolts together; herds by the settlements stay at half their cap or more every day; predators hunt and
kill near the camps; threats meet people (approaches, attacks with a bite, den-defence charges) and bite only where
the rules allow. Counts marked "over the seeds" are summed over both seeds."""

from abc import abstractmethod
from collections.abc import Mapping
from typing import ClassVar, override

from app.observability.events import Died, EventDraft, Injured, TickSummary
from app.sim.animals import ALARM_M, DEN_CHASE_M, DUSK_ALTITUDE_DEG, GROUP_M, WILDLIFE
from app.sim.clock import DAY_MINUTES, SECONDS_PER_TICK
from app.sim.courses import metres
from app.sim.fauna import LIVING_SITES, SPECIES, den_of, near_people
from app.sim.fire import SAFE_M, near_lit_fire
from app.sim.simulation import Simulation
from app.sim.state import Citizen
from app.sim.vec import Vec3
from scripts.checks.base import Check, Outcome

CAMP_M = 1000.0  # "near a camp": this close to a living site


EXPOSURE = "BR1/BR2 exposure schedules"  # people out where predators and herds are (10 §1.6), not there yet


def _kind(animal_id: str) -> str:
    return animal_id.partition(":")[0]


def _cap_m(kind: str) -> float:
    """The farthest an animal of the kind can go in a tick: its burst, then its sustained speed."""
    species = SPECIES[kind]
    burst = min(species.burst_s, SECONDS_PER_TICK)
    return species.run_mps * burst + species.trot_mps * (SECONDS_PER_TICK - burst)


class AnimalSpeed(Check):
    """The most any animal walked in a tick as a share of run × burst + sustained × the rest (≤ 1.01 passes)."""

    name = "a1.animal_speed"

    @override
    def start(self, sim: Simulation) -> None:
        self.worst, self.who = 0.0, "nobody"

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for animal_id, walk in WILDLIFE.of(sim.state).walks.items():
            share = metres(list(walk.points[: walk.walked_to + 1]), sim.world.radius_m) / _cap_m(_kind(animal_id))
            if share > self.worst:
                self.worst, self.who = share, animal_id

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.worst, self.worst <= 1.01, f"{self.worst:.3f} of the cap ({self.who})")


class AnimalStreamed(Check):
    """Animal moves of a millimetre or more with no streamed path (0 passes; respawns aren't moves)."""

    name = "a1.animal_streamed"

    @override
    def start(self, sim: Simulation) -> None:
        self.unstreamed = 0
        self.before: dict[str, Vec3] = {}

    @override
    def before_step(self, sim: Simulation) -> None:
        self.before = {a.id: a.position for a in sim.state.animals.values()}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        summary = next(e.payload for e in events if isinstance(e.payload, TickSummary))
        for animal_id, start in self.before.items():
            animal = sim.state.animals.get(animal_id)
            if animal is None or sim.world.distance_m(start, animal.position) < 0.001:
                continue
            pose = summary.animals.get(animal_id)
            if pose is None or len(pose.route) < 2:
                self.unstreamed += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.unstreamed, self.unstreamed == 0, f"{self.unstreamed} moves without a path")


class HerdAlarm(Check):
    """Of the group mates within 60 m of an animal that bolts, the share that bolt in the same tick (≥ 0.8 passes)."""

    name = "a1.herd_alarm"

    @override
    def start(self, sim: Simulation) -> None:
        self.near = self.fled = 0
        self.fleeing: set[str] = set()
        self.positions: dict[str, Vec3] = {}

    @override
    def before_step(self, sim: Simulation) -> None:
        courses = WILDLIFE.of(sim.state).courses
        self.fleeing = {a for a, course in courses.items() if course.moving == "fleeing"}
        self.positions = {a.id: a.position for a in sim.state.animals.values() if a.alive}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        summary = next(e.payload for e in events if isinstance(e.payload, TickSummary))
        bolted = {  # herbivores that ran this tick (a flight is the only run they make)
            animal_id
            for animal_id, pose in summary.animals.items()
            if pose.gait == "run" and animal_id not in self.fleeing and not SPECIES[_kind(animal_id)].predator
        }
        for group in sim.state.groups.values():
            starters = [m for m in group.members if m in bolted and m in self.positions]
            if not starters or SPECIES[group.kind].predator:
                continue
            first = self.positions[starters[0]]
            mates = [
                m
                for m in group.members
                if m != starters[0]
                and m in self.positions
                and m not in self.fleeing
                and sim.world.distance_m(self.positions[m], first) <= ALARM_M
            ]
            self.near += len(mates)
            self.fled += sum(m in bolted for m in mates)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        share = self.fled / self.near if self.near else 1.0
        return Outcome(share, share >= 0.8, f"{share:.0%} of {self.near} mates bolted with them")


class _HerdLosses(Check):
    """The lowest share of its cap a herd living by a settlement had left at the end of a day, counting as lost only
    the members whose death `_taken_by` says (deaths carry their attacker; a dead member is lost until replaced)."""

    @abstractmethod
    def _taken_by(self, sim: Simulation, attacker: str) -> bool:
        """Whether a death by this attacker (an animal or citizen id, "" for none) costs the herd."""

    @override
    def start(self, sim: Simulation) -> None:
        self.worst, self.which = 1.0, "none"
        self.taken: set[str] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Died) and event.actor_kind == "animal" and event.actor_id is not None:
                if self._taken_by(sim, event.payload.attacker or ""):
                    self.taken.add(event.actor_id)
        if sim.tick % DAY_MINUTES:
            return
        for group in sim.state.groups.values():
            if SPECIES[group.kind].predator or group.kind == "fish" or not near_people(sim.world, group):
                continue
            lost = sum(not sim.state.animals[m].alive and m in self.taken for m in group.members)
            share = 1.0 - lost / group.size
            if share < self.worst:
                self.worst, self.which = share, f"{group.id} day {sim.tick // DAY_MINUTES}"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.worst, self.worst >= 0.5, f"{self.worst:.0%} ({self.which})")


class HerdsKept(_HerdLosses):
    """Herds by the settlements keep half their cap or more every day against the predators (≥ 0.5 passes): only
    members predators killed count as lost (hunters' kills are `a1.hunting_pressure`'s)."""

    name = "a1.herds_kept"

    @override
    def _taken_by(self, sim: Simulation, attacker: str) -> bool:
        return _kind(attacker) in SPECIES


class HuntingPressure(_HerdLosses):
    """Herds by the settlements keep half their cap or more every day against the hunters (≥ 0.5 passes): only
    members people brought down count as lost."""

    name = "a1.hunting_pressure"
    pending = "BR2 spreading hunters over the herds"

    @override
    def _taken_by(self, sim: Simulation, attacker: str) -> bool:
        return attacker in sim.state.citizens


class _Counted(Check):
    """A count over the seeds that must reach `least`."""

    least: ClassVar[int]

    @override
    def start(self, sim: Simulation) -> None:
        self.count = 0

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.count, True, str(self.count))

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= cls.least, f"{total:.0f} over the seeds (≥ {cls.least})")


def _came_at(sim: Simulation, citizen_id: str) -> bool:
    """The citizen was hurt this tick by a predator that went for them (a hunt or a den charge), not by game or a
    predator fighting back against their own hunt or blow (D70)."""
    words, _ = sim.core.hurt.get(citizen_id, ("", 0))
    return words.endswith(("attacks you", "charges you"))


class Kills(Check):
    """Predator kill sequences within 1 km of the settlements on each seed: 10 §4.6 expects ≈ 3 a night near people
    from the six pinned predator groups (42 in 14 nights); ≥ 30 a seed, and ≥ 4 by every settlement (the den-pinned
    wolves, bears and lions do most of them, so a lost den shows)."""

    name = "a1.kills"
    least = 30
    least_per_camp = 4

    @override
    def start(self, sim: Simulation) -> None:
        self.counts = dict.fromkeys(LIVING_SITES, 0)

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Died) and event.actor_kind == "animal" and event.actor_id is not None:
                if _kind(event.payload.attacker or "") not in SPECIES:
                    continue
                where = sim.state.animals[event.actor_id].position
                for site in LIVING_SITES:
                    if sim.world.distance_m(where, sim.world.places[site].centre) <= CAMP_M:
                        self.counts[site] += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        total = sum(self.counts.values())
        words = ", ".join(f"{site} {count}" for site, count in self.counts.items())
        ok = total >= self.least and min(self.counts.values()) >= self.least_per_camp
        return Outcome(total, ok, f"{total} ({words})")


class Approaches(_Counted):
    """Predators setting out for a person ("coming at" them), over the seeds (≥ 16)."""

    name = "a1.approaches"
    pending = EXPOSURE
    least = 16

    @override
    def start(self, sim: Simulation) -> None:
        super().start(sim)
        self.going: dict[str, str | None] = {}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for animal in sim.state.animals.values():
            target = animal.target if animal.target in sim.state.citizens else None
            if target is not None and self.going.get(animal.id) != target:
                self.count += 1
            self.going[animal.id] = target


class Attacks(_Counted):
    """Predator attacks on a person that came to a bite (one per predator and person), over the seeds (≥ 4)."""

    name = "a1.attacks"
    pending = EXPOSURE
    least = 4

    @override
    def start(self, sim: Simulation) -> None:
        super().start(sim)
        self.seen: set[tuple[str, str, int]] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Injured) and event.actor_kind == "citizen" and event.actor_id is not None:
                attacker = event.payload.attacker or ""
                if _came_at(sim, event.actor_id):
                    key = (attacker, event.actor_id, sim.tick // 60)
                    if not any(k[:2] == key[:2] and key[2] - k[2] <= 1 for k in self.seen):
                        self.count += 1
                    self.seen.add(key)


class DenCharges(_Counted):
    """Predators charging someone near their den by day, over the seeds (≥ 1)."""

    name = "a1.den_charges"
    pending = EXPOSURE
    least = 1

    @override
    def start(self, sim: Simulation) -> None:
        super().start(sim)
        self.charging: set[str] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        charges = WILDLIFE.of(sim.state).charges
        now = {animal_id for animal_id, why in charges.items() if why == "den"}
        self.count += len(now - self.charging)
        self.charging = now


class SafeBites(Check):
    """Bites on people where the rules forbid them (0 passes): inside the walls, within 15 m of a lit fire, with two
    others within 10 m, or a hunting bite by day (a den charge is allowed by day within DEN_CHASE_M of its den)."""

    name = "a1.safe_bites"

    @override
    def start(self, sim: Simulation) -> None:
        self.wrong: list[str] = []
        self.bites = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if not (isinstance(event.payload, Injured) and event.actor_kind == "citizen" and event.actor_id):
                continue
            attacker = sim.state.animals.get(event.payload.attacker or "")
            if attacker is None or not _came_at(sim, event.actor_id):
                continue
            self.bites += 1
            victim = sim.state.citizens[event.actor_id]
            why = self._wrong(sim, victim, attacker.position, attacker.group)
            if why:
                self.wrong.append(f"{attacker.id} on {victim.id} at tick {sim.tick}: {why}")

    def _wrong(self, sim: Simulation, victim: Citizen, at: Vec3, group_id: str) -> str:
        if sim.world.town_point(victim.position) is not None:
            return "inside the walls"
        if near_lit_fire(sim.core, victim.position, SAFE_M):
            return "by a fire"
        company = sum(sim.world.distance_m(o.position, victim.position) <= GROUP_M for o in sim.core.living())
        if company >= 3:
            return f"in a group of {company}"
        den = den_of(sim.world, sim.state.groups[group_id])
        by_den = den is not None and sim.world.distance_m(victim.position, den) <= DEN_CHASE_M + 1e-6
        if sim.core.altitude(at) >= DUSK_ALTITUDE_DEG and not by_den:
            return "by day, away from its den"
        return ""

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = self.wrong[0] if self.wrong else f"none of {self.bites} bites"
        return Outcome(len(self.wrong), not self.wrong, words)


class PeopleFlights(Check):
    """Days on which some herd near each camp bolted from a person, as a share of the days (≥ 1 a day per camp)."""

    name = "a1.people_flights"

    @override
    def start(self, sim: Simulation) -> None:
        self.days: dict[str, set[int]] = {site: set() for site in LIVING_SITES}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        shied = WILDLIFE.of(sim.state).shied
        summary = next(e.payload for e in events if isinstance(e.payload, TickSummary))
        for animal_id, pose in summary.animals.items():
            by_person = shied.get(animal_id) in sim.state.citizens
            if pose.gait != "run" or SPECIES[_kind(animal_id)].predator or not by_person:
                continue
            for site in LIVING_SITES:
                if sim.world.distance_m(pose.position, sim.world.places[site].centre) <= CAMP_M:
                    self.days[site].add(sim.tick // DAY_MINUTES)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        days = max(1, sim.tick // DAY_MINUTES)
        share = min(len(seen) for seen in self.days.values()) / days
        words = ", ".join(f"{site} {len(seen)}/{days}" for site, seen in self.days.items())
        return Outcome(share, share >= 0.99, words)


CHECKS: tuple[type[Check], ...] = (
    AnimalSpeed,
    AnimalStreamed,
    HerdAlarm,
    HerdsKept,
    HuntingPressure,
    Kills,
    Approaches,
    Attacks,
    DenCharges,
    SafeBites,
    PeopleFlights,
)
