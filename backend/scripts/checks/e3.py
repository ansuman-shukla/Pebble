"""E3's run checks (10-world-v1 §2.3, §2.5; the plan's money and rice lines): the stall sells every day, the rice
price answers a shock and settles back to fair, and every recipe gets made.

They read what the scripted citizens do, so they pass only once the town and band brains trade and craft (BR1, BR2);
until then they report how far off the run is.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import get_args, override

from app.observability.events import Crafted, EventDraft
from app.sim.clock import DAY_MINUTES
from app.sim.economy import load_economy
from app.sim.market import factor, price_word, stalls, stock_of
from app.sim.simulation import Simulation
from app.world_api.models import RecipeName
from scripts.checks.base import Check, Outcome

MIN_SALES_A_DAY = 9.0  # per seed: the checklist's ≥ 18 a day over both seeds (expected ≈ 13 a seed, §2.7)
RICE = "rice"
MIN_RICE_PEAK = 1.2  # the factor a shock lifts rice to (the rice-shock scenario, §1.4)
MAX_DEAR_DAYS = 3.0  # and fair again within this
MIN_FAIR_SHARE = 0.8  # of days 4-14 on which rice is mostly fair
FAIR_FROM_DAY = 4
RECIPES = get_args(RecipeName)


class Sales(Check):
    """Sales a game day (one `bought` or `sold` each, however many lots)."""

    name = "e3.sales"

    @override
    def start(self, sim: Simulation) -> None:
        self.sales = 0
        self.ticks = 0

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.ticks += 1
        self.sales += sum(event.type in ("bought", "sold") for event in events)

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        per_day = self.sales / max(1, self.ticks) * DAY_MINUTES
        return Outcome(per_day, per_day >= MIN_SALES_A_DAY, f"{per_day:.1f}/day ({self.sales} sales)")

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        mean = sum(outcome.value for outcome in outcomes.values()) / len(outcomes)
        return Outcome(mean, mean >= MIN_SALES_A_DAY, f"{mean:.1f}/day a seed (≥ {MIN_SALES_A_DAY:g})")


class RicePrice(Check):
    """The stall's rice price factor: its peak, the longest it stayed dear (days) and the share of days from day 4 on
    which it was mostly fair."""

    name = "e3.rice_price"

    @override
    def start(self, sim: Simulation) -> None:
        self.peak = 0.0
        self.dear_run = 0
        self.longest_dear = 0
        self.fair_ticks: Counter[int] = Counter()  # day -> ticks rice was fair
        self.ticks: Counter[int] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        stall = stalls(sim.core)[0]
        lot = load_economy().goods[RICE].stall
        if lot is None:
            raise ValueError("the stall doesn't sell rice")
        stock = stock_of(sim.core, stall, RICE)
        word = price_word(RICE, stock)
        self.peak = max(self.peak, factor(stock, lot.target))
        self.dear_run = self.dear_run + 1 if word == "dear" else 0
        self.longest_dear = max(self.longest_dear, self.dear_run)
        day = (sim.tick - 1) // DAY_MINUTES + 1  # tick t ends the t-th minute of the run
        self.ticks[day] += 1
        self.fair_ticks[day] += word == "fair"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        dear_days = self.longest_dear / DAY_MINUTES
        days = [day for day in self.ticks if day >= FAIR_FROM_DAY]
        fair = sum(self.fair_ticks[day] * 2 > self.ticks[day] for day in days)
        share = fair / len(days) if days else 1.0
        ok = self.peak >= MIN_RICE_PEAK and dear_days <= MAX_DEAR_DAYS and share >= MIN_FAIR_SHARE
        words = f"peak ×{self.peak:.2f}, dear at most {dear_days:.1f} d, fair {fair}/{len(days)} days from day 4"
        return Outcome(self.peak, ok, words)


@dataclass(frozen=True)
class RecipesMade(Outcome):
    missing: frozenset[str] = frozenset()  # the recipes this seed never made


class Recipes(Check):
    """Recipes crafted (each counted once); over all seeds every recipe must have been made."""

    name = "e3.recipes"

    @override
    def start(self, sim: Simulation) -> None:
        self.made: Counter[str] = Counter()

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.made.update(event.payload.recipe for event in events if isinstance(event.payload, Crafted))

    @override
    def outcome(self, sim: Simulation) -> RecipesMade:
        missing = frozenset(RECIPES) - set(self.made)
        words = f"{len(self.made)}/{len(RECIPES)} recipes{missing_words(missing)}"
        return RecipesMade(len(self.made), not missing, words, missing)

    @classmethod
    @override
    def overall(cls, outcomes: Mapping[int, Outcome]) -> Outcome:
        never = frozenset(RECIPES)
        for outcome in outcomes.values():
            if not isinstance(outcome, RecipesMade):
                raise TypeError(f"e3.recipes judges its own outcomes, not {outcome!r}")
            never &= outcome.missing
        made = len(RECIPES) - len(never)
        return Outcome(made, not never, f"{made}/{len(RECIPES)} recipes over all seeds{missing_words(never)}")


def missing_words(recipes: frozenset[str]) -> str:
    return f" (not {', '.join(sorted(recipes))})" if recipes else ""


CHECKS: tuple[type[Check], ...] = (Sales, RicePrice, Recipes)
