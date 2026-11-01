"""Q1's run checks: the world v1 critic checklist items (plan, "World v1 critic checklist", headless half) no other
stream's check measures, and the audit's probes (`.runtime/briefs/audit-1-probes/`) ported from replaying a dev run to
watching a headless one.

Already measured elsewhere (not repeated here): speed caps `b1.speed_cap`, streamed paths `b1.streamed` and
`a1.animal_streamed`, personal space `s1.crowded`, sleepers on the doorstep `s1.doorstep`, every gather, catch, felling,
mining and farm hour at a node's spot `n1.reach` (felling and mining are gathers), farming inside a paddy
`n1.in_paddies`, nodes regrowing `n1.regrowing`, herds kept `a1.herds_kept`/`a1.hunting_pressure`, animals near people
`t1.near_people` (the audit's animals_near probe), goals `br0.goals`, `said` `br0.said`, the watch `br1.night_watch`,
noon work `br1.noon_work`, wages `br1.wages`, tax and dues `br1.paid`, recipes `e3.recipes`, spoilage `e1.spoilage`,
coins `e1.coins`, the rice price `e3.rice_price`, band A's trips `br2.trade_trips`, gold `br2.gold_trips`, band B's
deeds `br2.deeds`, custody `j2.held_close`/`j2.custody`, bells `j1.bells`, standings in range `j1.standing`, number
leaks `k1.in_world_words`.
"""

from collections import Counter
from collections.abc import Mapping
from itertools import combinations
from typing import ClassVar, override

from app.observability.events import (
    ActionEnded,
    ActionStarted,
    Died,
    EventDraft,
    Injured,
    ItemMoved,
    NodeChanged,
    Stole,
    TaxChange,
    Traded,
    TreeFelled,
    Trespassed,
)
from app.sim import nodes, society
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.custody import in_custody
from app.sim.market import stalls
from app.sim.ownership import is_granary, owner_of
from app.sim.perception import HOME_RADIUS_M
from app.sim.simulation import Simulation
from app.sim.slots import held_slot, is_inside, is_moving, walkable
from app.sim.vec import Vec3
from app.world.roads import NONE as OFF_ROAD
from scripts.checks.base import Check, Outcome

CAST = 22  # 10 §3.1's roster
ALIVE_SHARE = 42 / 44  # ≥ 42 of 44 alive on day 14 over the two seeds (10 §4.6 expects ≈ 0.5 deaths)
OVERLAP_M = 0.01  # two bodies this close stand at the exact same point (audit F2)
IDLE_SHARE = 0.10  # "standing about": of each citizen's awake daytime ticks
TALKING_TICKS = 3  # someone who just spoke shows as talking this long (services.entities)
RAIDS_LEAST = 2  # band B raids on the racks over the seeds
OBSIDIAN_SALES_LEAST = 4  # band B's obsidian sales at the stall over the seeds
TOOLS_BROKEN_LEAST = 1
TRIP_M = 400.0  # a walk this long is a trip, whose metres should mostly lie on roads and paths
ROAD_SHARE = 0.6
FIELD_RACK = "field-rack"  # the town's hasa racks' store ids (field-rack-1, -2)
TREE_REGROW_DAYS = 10.0  # a felled tree stands again within this (stump 5 d → sapling 5 d → tree)
FLINT_A = "flint_seam"
FLINT_A_CAP = 30  # seam A (the Painted cave); B holds 10, the wall scar 40


def _night_of(tick: int) -> int:
    """The town night (noon to noon) a tick falls in: a raid's thefts after midnight count with its evening."""
    return (tick + START_MINUTE - 12 * 60) // DAY_MINUTES


def _region(sim: Simulation, citizen_id: str | None) -> str | None:
    citizen = sim.state.citizens.get(citizen_id) if citizen_id is not None else None
    return citizen.region if citizen is not None else None


def _home(sim: Simulation, citizen_id: str | None) -> str | None:
    citizen = sim.state.citizens.get(citizen_id) if citizen_id is not None else None
    return citizen.home if citizen is not None else None


class _OverSeeds(Check):
    """A count summed over the seeds that must reach `least` (each seed's own outcome only reports)."""

    least: ClassVar[int]

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        total = sum(outcome.value for outcome in outcomes.values())
        return Outcome(total, total >= cls.least, f"{total:g} over the seeds (≥ {cls.least})")


# --- bodies and lives ---


class Cast(Check):
    """22 citizens spawn; over the seeds at least 42 of every 44 are alive at the end (10 §4.6)."""

    name = "q1.cast"

    @override
    def start(self, sim: Simulation) -> None:
        self.spawned = len(sim.state.citizens)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        alive = sum(c.body.alive for c in sim.state.citizens.values())
        return Outcome(alive, self.spawned == CAST, f"{self.spawned} spawned, {alive} alive")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        alive = sum(outcome.value for outcome in outcomes.values())
        spawned_ok = all(outcome.ok for outcome in outcomes.values())
        share = alive / (CAST * len(outcomes))
        ok = spawned_ok and share >= ALIVE_SHARE - 1e-9
        return Outcome(alive, ok, f"{alive:g} of {CAST * len(outcomes)} alive (≥ {ALIVE_SHARE:.1%})")


class DeathCauses(Check):
    """Citizens dead at the end without a `died` event naming a cause, or killed by an animal or a person the event
    doesn't name (must be none)."""

    name = "q1.death_causes"

    @override
    def start(self, sim: Simulation) -> None:
        self.causes: dict[str, str] = {}
        self.unnamed: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Died) and event.actor_kind == "citizen" and event.actor_id is not None:
                died = event.payload
                self.causes[event.actor_id] = died.cause
                struck = died.cause == "violence" or died.cause.startswith(("killed by", "animal"))
                if not died.cause or (struck and died.attacker is None):
                    self.unnamed.append(f"{event.actor_id} ({died.cause or 'no cause'})")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        dead = [c.id for c in sim.state.citizens.values() if not c.body.alive]
        bad = [*self.unnamed, *(f"{who} (no died event)" for who in dead if who not in self.causes)]
        words = ", ".join(bad) or (", ".join(f"{w} {c}" for w, c in self.causes.items()) or "nobody died")
        return Outcome(len(bad), not bad, words)


class Assaults(Check):
    """Attacks a citizen started on a person, and people hurt or killed by a person (scripted brains never start an
    assault, D75): none allowed."""

    name = "q1.assaults"

    @override
    def start(self, sim: Simulation) -> None:
        self.found: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            payload = event.payload
            if isinstance(payload, ActionStarted) and payload.action == "attack" and event.actor_kind == "citizen":
                target = payload.target
                if target is not None and target.kind == "person":
                    self.found.append(f"{event.actor_id} attacked {target.id} at tick {event.tick}")
            elif isinstance(payload, Injured | Died) and payload.cause == "violence":
                self.found.append(f"{event.actor_id} hurt by {payload.attacker} at tick {event.tick}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.found), not self.found, self.found[0] if self.found else "none")


class Overlaps(Check):
    """Tick ends with two living bodies out in the world (inside a house aside) at the exact same point (the audit's
    overlaps probe: 88 % of samples had a pair). A pair with a body standing, sitting or lying fails (per tick); two
    walkers on one route coinciding for a tick are reported only, since the client keeps drawn walkers apart (D192,
    D191)."""

    name = "q1.overlaps"

    @override
    def start(self, sim: Simulation) -> None:
        self.ticks = 0
        self.walking = 0
        self.example = ""

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        core = sim.core
        out = [c for c in core.living() if not is_inside(core, c)]
        pairs = [(a, b) for a, b in combinations(out, 2) if core.distance_m(a.position, b.position) < OVERLAP_M]
        still = [(a, b) for a, b in pairs if not (is_moving(a) and is_moving(b))]
        self.walking += bool(pairs) and not still
        if still:
            self.ticks += 1
            a, b = still[0]
            self.example = self.example or f" (first: tick {sim.tick} {a.id}+{b.id})"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = f"{self.ticks} ticks{self.example}, {self.walking} with two walkers only"
        return Outcome(self.ticks, self.ticks == 0, words)


class Sleepers(Check):
    """Sleeper-ticks not where 10 §4.3 lays sleepers (per tick): at home a town sleeper is inside and a band sleeper on
    a mat; away from home anyone lies on open ground (a ring spot: walkable, not on a wall, bench or prop). The audit's
    spots probe found sleepers stacked on doorsteps and cell centres."""

    name = "q1.sleepers"

    @override
    def start(self, sim: Simulation) -> None:
        self.samples = 0
        self.asleep = 0
        self.who: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        core = sim.core
        for citizen in core.living():
            if not citizen.body.asleep:
                continue
            self.asleep += 1
            if is_inside(core, citizen):
                continue
            home = core.world.structures.get(citizen.home) if citizen.home is not None else None
            at_home = home is not None and core.distance_m(citizen.position, home.door) <= HOME_RADIUS_M
            slot = held_slot(core, citizen)
            on_mat = slot is not None and slot.kind == "mat" and core.distance_m(citizen.position, slot.position) < 0.05
            ok = on_mat if at_home else on_mat or walkable(core, citizen.position)
            if not ok:
                self.samples += 1
                self.who[citizen.id] += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        who = ", ".join(f"{c} {n}" for c, n in self.who.most_common(3)) or "none"
        return Outcome(self.samples, self.samples == 0, f"{self.samples} of {self.asleep} sleeper-ticks ({who})")


# --- brains ---


class StandingAbout(Check):
    """The largest share of one citizen's awake daytime ticks (sun up where they are) spent standing about: no action
    or waiting, and neither talking, moving nor ending an action that tick; the held and the confined aside (audit
    probe activity_share: the town stood still 92 % of the time). ≤ 10 % per citizen (D191)."""

    name = "q1.standing_about"

    @override
    def start(self, sim: Simulation) -> None:
        self.awake: Counter[str] = Counter()
        self.idle: Counter[str] = Counter()
        self.spoke: dict[str, int] = {}
        self.before: dict[str, Vec3] = {}

    @override
    def before_step(self, sim: Simulation) -> None:
        self.before = {c.id: c.position for c in sim.state.citizens.values()}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        core = sim.core
        busy: set[str] = set()  # an action ended within the tick (a few steps walked, a meal eaten): not stood
        for event in events:
            if event.type == "said" and event.actor_id is not None:
                self.spoke[event.actor_id] = sim.tick
            if isinstance(event.payload, ActionEnded) and event.actor_id is not None:
                busy.add(event.actor_id)
        for citizen in core.living():
            if citizen.body.asleep or core.is_night_at(citizen.position) or in_custody(core, citizen.id):
                continue
            self.awake[citizen.id] += 1
            waiting = citizen.action is None or citizen.action.kind == "wait"
            talking = sim.tick - self.spoke.get(citizen.id, -TALKING_TICKS) < TALKING_TICKS
            moved = self.before.get(citizen.id, citizen.position) != citizen.position
            self.idle[citizen.id] += waiting and not talking and not moved and citizen.id not in busy

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        shares = sorted(((self.idle[who] / n, who) for who, n in self.awake.items() if n), reverse=True)
        worst = shares[0][0] if shares else 0.0
        over = [(share, who) for share, who in shares if share > IDLE_SHARE][:5] or shares[:1]
        words = ", ".join(f"{who} {share:.1%}" for share, who in over) or "nobody awake"
        return Outcome(worst, worst <= IDLE_SHARE, words)


# --- contact and law ---


class Raids(_OverSeeds):
    """Band B raids on the town's field racks (nights with a theft from a rack by band B), over the seeds (≥ 2)."""

    name = "q1.raids"
    least = RAIDS_LEAST

    @override
    def start(self, sim: Simulation) -> None:
        self.nights: set[int] = set()
        self.rice = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            stole = event.payload
            if isinstance(stole, Stole) and stole.store.startswith(FIELD_RACK):
                if _region(sim, event.actor_id) == "band_b":
                    self.nights.add(_night_of(sim.tick))
                    self.rice += stole.count

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.nights), True, f"{len(self.nights)} raids ({self.rice} rice)")


class ObsidianSales(_OverSeeds):
    """Band B's obsidian sales at the stall (one `sold` each), over the seeds (≥ 4: Nim's treks, 10 §3.6)."""

    name = "q1.obsidian_sales"
    least = OBSIDIAN_SALES_LEAST

    @override
    def start(self, sim: Simulation) -> None:
        self.sales = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            traded = event.payload
            if event.type == "sold" and isinstance(traded, Traded) and traded.item == "obsidian":
                self.sales += _region(sim, event.actor_id) == "band_b"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(self.sales, True, f"{self.sales} sales")


class StandingDirection(Check):
    """Band B's mean standing with the town ends lower than it started iff some band B deed was witnessed by an
    outsider; band A's ends higher iff band A traded at the stall (10 §3.5, the checklist's society line)."""

    name = "q1.standing_direction"

    @override
    def start(self, sim: Simulation) -> None:
        self.start_mean = {band: self._mean(sim, band) for band in ("band_a", "band_b")}
        self.witnessed = 0
        self.traded = 0

    @staticmethod
    def _mean(sim: Simulation, band: str) -> float:
        members = [c.id for c in sim.state.citizens.values() if c.region == band and c.body.alive]
        return sum(society.standing(sim.core, who, "town") for who in members) / max(1, len(members))

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            payload, region = event.payload, _region(sim, event.actor_id)
            if isinstance(payload, Stole | Trespassed) and region == "band_b":
                self.witnessed += any(_region(sim, w) != "band_b" for w in payload.witnesses)
            elif event.type in ("sold", "bought") and region == "band_a":
                self.traded += 1

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        b_moved = self._mean(sim, "band_b") - self.start_mean["band_b"]
        a_moved = self._mean(sim, "band_a") - self.start_mean["band_a"]
        ok = (b_moved < 0) == (self.witnessed > 0) and (a_moved > 0) == (self.traded > 0)
        words = f"band B {b_moved:+.1f} ({self.witnessed} witnessed deeds), band A {a_moved:+.1f} ({self.traded} sales)"
        return Outcome(0 if ok else 1, ok, words)


# --- economy and ecology ---


class ToolsBroken(_OverSeeds):
    """`tool_broke` events, over the seeds (≥ 1: tools wear out, 10 §2.4)."""

    name = "q1.tools_broken"
    least = TOOLS_BROKEN_LEAST

    @override
    def start(self, sim: Simulation) -> None:
        self.broken: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.broken.update(str(getattr(e.payload, "item", "")) for e in events if e.type == "tool_broke")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        words = ", ".join(f"{n} {item}" for item, n in self.broken.most_common()) or "none"
        return Outcome(self.broken.total(), True, words)


class RoadShare(Check):
    """Of the metres walked on trips longer than 400 m (one walk each), the share on roads and paths (≥ 60 %: routes
    take roads, D80)."""

    name = "q1.road_share"

    @override
    def start(self, sim: Simulation) -> None:
        self.walks: dict[str, list[float]] = {}  # citizen -> [metres, on roads] of the walk under way
        self.before: dict[str, Vec3] = {}
        self.metres = 0.0
        self.on_roads = 0.0

    @override
    def before_step(self, sim: Simulation) -> None:
        self.before = {c.id: c.position for c in sim.state.citizens.values()}

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        world = sim.world
        for citizen in sim.state.citizens.values():
            walk = self.walks.get(citizen.id)
            if walk is None or citizen.id not in self.before:
                continue
            step = world.distance_m(self.before[citizen.id], citizen.position)
            walk[0] += step
            walk[1] += step if world.road_kinds[citizen.cell] != OFF_ROAD else 0.0
        for event in events:
            if event.actor_kind != "citizen" or event.actor_id is None:
                continue
            if isinstance(event.payload, ActionStarted) and event.payload.action == "walk_to":
                self.walks[event.actor_id] = [0.0, 0.0]
            elif isinstance(event.payload, ActionEnded) and event.payload.action == "walk_to":
                metres, on_roads = self.walks.pop(event.actor_id, [0.0, 0.0])
                if metres > TRIP_M:
                    self.metres += metres
                    self.on_roads += on_roads

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        share = self.on_roads / self.metres if self.metres else 1.0
        return Outcome(share, share >= ROAD_SHARE, f"{share:.0%} of {self.metres / 1000:.1f} km on trips")


class Ecology(Check):
    """Felled trees stand again within 10 days (a tree felled too late in the run to come back isn't judged), gold
    only falls, and flint seam A both falls and regrows (10 §1.1): faults found (must be none)."""

    name = "q1.ecology"

    @override
    def start(self, sim: Simulation) -> None:
        self.felled: dict[str, int] = {}  # tree node -> tick felled
        self.slow: list[str] = []
        self.gold_rose: list[str] = []
        self.flint_fell = self.flint_rose = False
        table = sim.world.nodes
        self.flint_a = {
            node_id
            for node_id, kind, cap in zip(table.ids, table.kinds, table.caps, strict=True)
            if kind == FLINT_A and int(cap) == FLINT_A_CAP
        }
        self.trees = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, TreeFelled):
                self.felled[event.payload.node] = sim.tick
                self.trees += 1
            changed = event.payload
            if not isinstance(changed, NodeChanged):
                continue
            if changed.kind == "gold_pool" and changed.after > changed.before:
                self.gold_rose.append(f"gold {changed.node} at tick {sim.tick}")
            if changed.node in self.flint_a:
                self.flint_fell |= changed.after < changed.before
                self.flint_rose |= changed.after > changed.before
        late = sim.tick - TREE_REGROW_DAYS * DAY_MINUTES
        for node, felled in list(self.felled.items()):
            if nodes.stock(sim.core, sim.world.nodes.index[node]) > 0:
                self.felled.pop(node)
            elif felled < late:
                self.slow.append(f"tree {node} felled at tick {felled}")
                self.felled.pop(node)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        bad = [*self.slow, *self.gold_rose] + ([] if self.flint_fell == self.flint_rose else ["flint seam A one way"])
        flint = "flint A fell and regrew" if self.flint_fell and self.flint_rose else "flint A untouched"
        words = "; ".join(bad) if bad else f"{self.trees} trees felled, {flint}, gold only fell"
        return Outcome(len(bad), not bad, words)


class RiceFlows(Check):
    """Rice flows a day over days 4-14 against 10 §1.4's balance: harvest 120, tax paid into the granary 48, the stall's
    rice in 45 (sales to it) and out 45 (purchases, and the merchant's own rice off it); each within ±15 % on every
    seed."""

    name = "q1.rice_flows"
    FLOWS: ClassVar[dict[str, float]] = {"harvest": 120.0, "tax": 48.0, "stall in": 45.0, "stall out": 45.0}
    BAND: ClassVar[float] = 0.15
    FROM_DAY, TO_DAY = 4, 14

    @override
    def start(self, sim: Simulation) -> None:
        self.flows: Counter[str] = Counter()
        self.days: set[int] = set()
        self.stalls = {stall.id: owner_of(sim.world, stall.id) for stall in stalls(sim.core)}  # -> its household

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        day = sim.tick // DAY_MINUTES
        if not self.FROM_DAY <= day < self.TO_DAY:
            return
        self.days.add(day)
        for event in events:
            payload = event.payload
            if isinstance(payload, NodeChanged) and payload.kind == "rice_paddy" and event.actor_kind == "citizen":
                self.flows["harvest"] += max(0, payload.before - payload.after)
            elif isinstance(payload, TaxChange) and event.type == "tax_paid":
                self.flows["tax"] += payload.rice
            elif isinstance(payload, Traded) and payload.item == "rice":
                self.flows["stall in" if event.type == "sold" else "stall out"] += payload.count
            elif isinstance(payload, ItemMoved) and payload.item == "rice" and payload.source.kind == "store":
                store = str(payload.source.id)
                if is_granary(sim.world, store):
                    self.flows["granary out"] += payload.count
                elif store in self.stalls and _home(sim, event.actor_id) == self.stalls[store] and not event.cause_seq:
                    self.flows["stall out"] += payload.count  # the merchant's own rice off the stall (§1.4: 10 a day)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        days = max(1, len(self.days))
        per_day = {flow: self.flows[flow] / days for flow in (*self.FLOWS, "granary out")}
        worst = max(abs(per_day[f] / want - 1) for f, want in self.FLOWS.items())
        words = ", ".join(f"{flow} {n:.0f}" for flow, n in per_day.items())
        return Outcome(worst, worst <= self.BAND, words)

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        worst = max(outcome.value for outcome in outcomes.values())
        mean = sum(outcome.value for outcome in outcomes.values()) / len(outcomes)
        return Outcome(mean, all(o.ok for o in outcomes.values()), f"worst flow off by {worst:.0%} (≤ {cls.BAND:.0%})")


CHECKS: tuple[type[Check], ...] = (
    Cast,
    DeathCauses,
    Assaults,
    Overlaps,
    Sleepers,
    StandingAbout,
    Raids,
    ObsidianSales,
    StandingDirection,
    ToolsBroken,
    RoadShare,
    Ecology,
    RiceFlows,
)
