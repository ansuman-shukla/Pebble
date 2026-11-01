"""BR1's run checks (10-world-v1 plan, BR1; bible §1.4, §2.7, §3.1): the town trades at the stall every day, the
watchman is paid every day and keeps the night watch, households pay their rice tax and dues, the town's recipes all
get made, nobody's coins run away, the town is at work at noon and nobody in town starves.

Counts are per seed unless an `overall` says how the seeds add up (sales: both seeds together, as the plan says).
"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import override

from app.brains.profile import BrainProfile, Routine
from app.observability.events import Crafted, Died, EventDraft, ItemMoved, TaxChange
from app.sim import society, tax
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.ownership import CHEST
from app.sim.simulation import Simulation
from app.sim.state import Citizen
from scripts.checks.base import Check, Outcome

TOWN = "town"
SALES_A_DAY = 15.0  # town sales a day, both seeds together (the plan: ≥ 15, expected ≈ 22)
PAID_SHARE = 0.8  # of the rice tax assessed and of the dues fallen due
TOWN_RECIPES = frozenset({"iron spear", "iron axe", "sickle", "cloth", "pack"})
TREND_FROM_DAY = 4  # coins trends are judged over days 4-14 (§2.7)
MAX_TREND = 10.0  # mon a day either way
WATCH_SHARE = 0.8  # of the night the watchman is at the west gate or the racks
WATCH_M = 20.0  # within this of the west gate's centre, or inside the rice fields
NOON = 12 * 60  # town clock minutes
AT_WORK = 8.0  # town citizens at their own workplaces at noon, on average over the days
HOME_M = 8.0  # at the loom: this near the home's door
# where each town routine's work is done (place ids; "home": at their own door, the loom)
WORKPLACES: dict[Routine, tuple[str, ...]] = {
    "lord": ("castle", "market", "storehouses"),
    "samurai": ("main-gate", "west-gate", "castle", "training-ground"),
    "night_watch": ("west-gate", "rice-fields"),
    "merchant": ("market",),
    "farmer": ("rice-fields", "storehouses", "market"),  # tending, paying the tax, selling the spare rice
    "weaver": ("home", "rice-fields", "storehouses", "market"),
    "monk": ("temple", "bell-tower"),
    "smith": ("forge", "market"),  # forging, buying his iron sand and wood
    "digger": ("south_marsh", "north_woods", "falls_pool", "market"),
}
STARVED = frozenset({"starvation", "dehydration"})


def _town_day(tick: int) -> int:
    return (tick - 1) // DAY_MINUTES  # tick t ends the t-th minute of the run


class Sales(Check):
    """Sales a game day made by town citizens (one `bought` or `sold` each)."""

    name = "br1.sales"

    @override
    def start(self, sim: Simulation) -> None:
        self.sales = 0
        self.ticks = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.ticks += 1
        for event in events:
            if event.type in ("bought", "sold") and event.actor_id is not None:
                self.sales += sim.state.citizens[event.actor_id].region == TOWN

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        per_day = self.sales / max(1, self.ticks) * DAY_MINUTES
        return Outcome(per_day, per_day >= SALES_A_DAY / 2, f"{per_day:.1f}/day ({self.sales} sales)")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        both = sum(outcome.value for outcome in outcomes.values()) / len(outcomes) * 2
        return Outcome(both, both >= SALES_A_DAY, f"{both:.1f}/day over two seeds (≥ {SALES_A_DAY:g})")


class Wages(Check):
    """Days the lord paid the watchman's wage (coins from the lord to the ashigaru), out of the run's days."""

    name = "br1.wages"

    @override
    def start(self, sim: Simulation) -> None:
        self.days: set[int] = set()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            moved = event.payload
            if not isinstance(moved, ItemMoved) or moved.item != "coins" or moved.destination.kind != "inventory":
                continue
            payer, payee = moved.source.id or "", moved.destination.id or ""
            if moved.source.kind == "inventory" and _titled(sim, payer, "lord") and _titled(sim, payee, "ashigaru"):
                self.days.add(_town_day(sim.tick))

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        days = sim.tick // DAY_MINUTES
        missed = sorted(set(range(days)) - self.days)
        return Outcome(
            len(missed), not missed, f"{len(self.days)}/{days} days" + (f" (not {missed})" if missed else "")
        )


def _titled(sim: Simulation, citizen_id: str, title: str) -> bool:
    return citizen_id in sim.state.citizens and title in society.titles(sim.core, citizen_id)


class Paid(Check):
    """The share of the rice tax assessed that was paid, and of the dues fallen due (paid, or in arrears at the end)
    that was paid; the lower counts."""

    name = "br1.paid"

    @override
    def start(self, sim: Simulation) -> None:
        self.rice_owed = self.rice_paid = self.coins_paid = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            change = event.payload
            if not isinstance(change, TaxChange):
                continue
            if event.type == "tax_assessed":
                self.rice_owed += change.rice
            elif event.type == "tax_paid":
                self.rice_paid += change.rice
                self.coins_paid += change.coins

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        arrears = sum(tax.account(sim.core, home).arrears for home in tax.households(sim.core))
        rice = self.rice_paid / self.rice_owed if self.rice_owed else 1.0
        dues = self.coins_paid / (self.coins_paid + arrears) if self.coins_paid + arrears else 1.0
        share = min(rice, dues)
        words = f"rice tax {rice:.0%} paid, dues {dues:.0%} ({self.coins_paid} mon paid, {arrears} in arrears)"
        return Outcome(share, share >= PAID_SHARE, words)

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, worst >= PAID_SHARE, f"worst {worst:.0%} (≥ {PAID_SHARE:.0%})")


@dataclass(frozen=True)
class Made(Outcome):
    missing: frozenset[str] = frozenset()


class Recipes(Check):
    """The town's recipes (the forge's iron tools, the loom's cloth and pack) crafted; all of them over the seeds."""

    name = "br1.recipes"

    @override
    def start(self, sim: Simulation) -> None:
        self.made: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.made.update(event.payload.recipe for event in events if isinstance(event.payload, Crafted))

    @override
    def outcome(self, sim: Simulation) -> Made:
        missing = TOWN_RECIPES - set(self.made)
        made = ", ".join(f"{count} {recipe}" for recipe, count in sorted(self.made.items()) if recipe in TOWN_RECIPES)
        return Made(len(TOWN_RECIPES - missing), not missing, made or "none", frozenset(missing))

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        never = frozenset(TOWN_RECIPES)
        for outcome in outcomes.values():
            if not isinstance(outcome, Made):
                raise TypeError(f"br1.recipes judges its own outcomes, not {outcome!r}")
            never &= outcome.missing
        made = len(TOWN_RECIPES) - len(never)
        return Outcome(
            made, not never, f"{made}/{len(TOWN_RECIPES)} town recipes" + (f" (not {sorted(never)})" * bool(never))
        )


def holdings(sim: Simulation) -> dict[str, int]:
    """Coins each town household holds: its residents' purses and its chest (the keep's chest is the treasury)."""
    coins: Counter[str] = Counter()
    for citizen in sim.core.citizens():
        if citizen.region == TOWN and citizen.home is not None:
            coins[citizen.home] += citizen.inventory.get("coins", 0)
    for home in list(coins):
        coins[home] += sim.state.stores.get(home + CHEST, {}).get("coins", 0)
    return dict(coins)


def slope(values: list[int]) -> float:
    """Least-squares change a day of a daily series."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x, mean_y = (n - 1) / 2, sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values))
    return num / sum((x - mean_x) ** 2 for x in range(n))


class CoinTrend(Check):
    """The steepest trend of a town household's coins over days 4-14 (mon a day, either way; §2.7: ≤ 10)."""

    name = "br1.coin_trend"
    pending = "BR2 band purchases (about 7 rice a day of the stall's balance)"

    @override
    def start(self, sim: Simulation) -> None:
        self.days: dict[str, list[int]] = defaultdict(list)

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        if sim.tick % DAY_MINUTES or sim.tick // DAY_MINUTES < TREND_FROM_DAY - 1:
            return
        for home, coins in holdings(sim).items():
            self.days[home].append(coins)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        trends = {home: slope(days) for home, days in self.days.items()}
        home = max(trends, key=lambda h: abs(trends[h]), default="nobody")
        worst = trends.get(home, 0.0)
        return Outcome(abs(worst), abs(worst) <= MAX_TREND, f"steepest {home} {worst:+.1f} mon/day")


class NightWatch(Check):
    """The share of the town's night ticks the watchman (the ashigaru) stood at the west gate or by the racks."""

    name = "br1.night_watch"

    @override
    def start(self, sim: Simulation) -> None:
        self.night = self.watched = 0
        self.watch = next((c.id for c in sim.core.citizens() if _titled(sim, c.id, "ashigaru")), None)

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        town = sim.world.places["town"].centre
        if self.watch is None or not sim.core.is_night_at(town):
            return
        watch = sim.state.citizens[self.watch]
        if not watch.body.alive:
            return
        self.night += 1
        gate, fields = sim.world.places["west-gate"], sim.world.places["rice-fields"]
        near_gate = sim.world.distance_m(watch.position, gate.centre) <= WATCH_M
        self.watched += near_gate or sim.world.distance_m(watch.position, fields.centre) <= fields.radius_m

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        share = self.watched / self.night if self.night else 0.0
        return Outcome(share, share >= WATCH_SHARE, f"{share:.0%} of {self.night} night ticks ({self.watch})")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, worst >= WATCH_SHARE, f"worst {worst:.0%} (≥ {WATCH_SHARE:.0%})")


def at_work(sim: Simulation, citizen: Citizen) -> str | None:
    """The workplace of their own job a town citizen stands in, if any."""
    routine = BrainProfile(citizen.id, citizen.name, citizen.role, citizen.region, "").routine
    for place_id in WORKPLACES.get(routine, ()):
        if place_id == "home":
            home = sim.world.structures.get(citizen.home or "")
            if home is not None and sim.world.distance_m(citizen.position, home.door) <= HOME_M:
                return citizen.home
            continue
        place = sim.world.places[place_id]
        if sim.world.distance_m(citizen.position, place.centre) <= place.radius_m:
            return place_id
    return None


class NoonWork(Check):
    """Town citizens at their own workplaces at the town's noon, on average over the days (≥ 8: fields, stall,
    forge, gates, temple, the iron-sand bar)."""

    name = "br1.noon_work"

    @override
    def start(self, sim: Simulation) -> None:
        self.counts: list[int] = []
        self.places: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        if (sim.tick + START_MINUTE) % DAY_MINUTES != NOON:
            return
        working = [place for c in sim.core.living() if c.region == TOWN and (place := at_work(sim, c)) is not None]
        self.counts.append(len(working))
        self.places.update(working)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        mean = sum(self.counts) / len(self.counts) if self.counts else 0.0
        where = ", ".join(f"{place} {n}" for place, n in self.places.most_common(6))
        return Outcome(
            mean, mean >= AT_WORK, f"{mean:.1f} at work at noon, least {min(self.counts, default=0)} ({where})"
        )

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        worst = min(outcome.value for outcome in outcomes.values())
        return Outcome(worst, worst >= AT_WORK, f"worst seed {worst:.1f} at work at noon (≥ {AT_WORK:g})")


class Starvation(Check):
    """Town citizens dead of hunger or thirst (must be none)."""

    name = "br1.starvation"

    @override
    def start(self, sim: Simulation) -> None:
        self.dead: list[str] = []

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        for event in events:
            if isinstance(event.payload, Died) and event.actor_id in sim.state.citizens:
                if sim.state.citizens[event.actor_id].region == TOWN and event.payload.cause in STARVED:
                    self.dead.append(f"{event.actor_id} ({event.payload.cause})")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.dead), not self.dead, ", ".join(self.dead) or "none")


CHECKS: tuple[type[Check], ...] = (Sales, Wages, Paid, Recipes, CoinTrend, NightWatch, NoonWork, Starvation)
