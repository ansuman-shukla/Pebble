"""E3's run checks: sales a day, the rice price's peak and return to fair, every recipe made."""

from collections.abc import Callable

from app.observability.events import Crafted, EventDraft, EventType, Traded
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from scripts.checks import CHECKS, e3
from scripts.checks.base import Outcome

STALL = "market-stall"


def _event(sim: Simulation, kind: EventType, payload: Traded | Crafted) -> EventDraft:
    return EventDraft(0, sim.tick, kind, "citizen", "goro", None, None, "public", None, payload)


def _sale(sim: Simulation, kind: EventType = "bought") -> EventDraft:
    return _event(sim, kind, Traded(item="rice", count=2, lots=1, coins=4, stall=STALL, merchant="fumiko"))


def test_sales_count_bought_and_sold_events_a_day(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = e3.Sales()
    check.start(sim)
    for tick in range(DAY_MINUTES // 2):  # half a day: 4 sales, 1 craft that isn't one
        sim.state.tick = tick
        events = [_sale(sim, "sold" if tick % 2 else "bought")] if tick < 4 else []
        check.after_step(sim, events + [_event(sim, "crafted", Crafted(recipe="cloth", item="cloth", count=1))])
    assert check.outcome(sim) == Outcome(8.0, False, "8.0/day (4 sales)")
    assert e3.Sales.overall({1: Outcome(8.0, False, "a"), 2: Outcome(10.0, True, "b")}) == Outcome(
        9.0, True, "9.0/day a seed (≥ 9)"
    )
    assert {e3.Sales, e3.RicePrice, e3.Recipes} <= set(CHECKS)
    # the town trades (BR1), the bands knap spears, an axe and dry meat and band B raids the racks (BR2): all count
    assert {check.name: check.pending for check in e3.CHECKS} == {
        "e3.sales": None,
        "e3.rice_price": None,
        "e3.recipes": None,
    }


def _rice(new_sim: Callable[..., Simulation]) -> tuple[Simulation, e3.RicePrice]:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    check = e3.RicePrice()
    check.start(sim)
    return sim, check


def _days(sim: Simulation, check: e3.RicePrice, stock: int, days: float) -> None:
    sim.state.stores[STALL]["rice"] = stock
    for _ in range(round(days * DAY_MINUTES)):
        sim.state.tick += 1
        check.after_step(sim, [])


def test_the_rice_price_needs_a_peak_then_fair_again_within_three_days(new_sim: Callable[..., Simulation]) -> None:
    sim, check = _rice(new_sim)
    _days(sim, check, 150, 1)
    _days(sim, check, 80, 2.4)  # a shock: factor √(121/81) = 1.22, dear for 2.4 days (into day 4, under half of it)
    _days(sim, check, 130, 10.6)
    assert check.outcome(sim) == Outcome(check.peak, True, "peak ×1.22, dear at most 2.4 d, fair 11/11 days from day 4")
    calm, never = _rice(new_sim)
    _days(calm, never, 150, 14)
    assert never.outcome(calm) == Outcome(
        never.peak, False, "peak ×0.90, dear at most 0.0 d, fair 11/11 days from day 4"
    )
    slow, stuck = _rice(new_sim)
    _days(slow, stuck, 80, 3.5)
    _days(slow, stuck, 150, 10.5)
    assert stuck.outcome(slow) == Outcome(
        stuck.peak, False, "peak ×1.22, dear at most 3.5 d, fair 10/11 days from day 4"
    )
    cheap, glut = _rice(new_sim)
    _days(cheap, glut, 80, 1)
    _days(cheap, glut, 400, 13)
    assert glut.outcome(cheap) == Outcome(glut.peak, False, "peak ×1.22, dear at most 1.0 d, fair 0/11 days from day 4")


def test_every_recipe_must_be_made_on_some_seed(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = e3.Recipes()
    check.start(sim)
    for recipe in ("flint spear", "obsidian spear", "iron spear", "stone axe", "iron axe", "sickle", "cloth", "cloth"):
        check.after_step(sim, [_event(sim, "crafted", Crafted(recipe=recipe, item=recipe, count=1))])
    first = check.outcome(sim)
    assert first == e3.RecipesMade(7, False, "7/9 recipes (not dried meat, pack)", frozenset({"dried meat", "pack"}))
    other = e3.RecipesMade(8, False, "8/9 recipes (not pack)", frozenset({"pack"}))
    assert e3.Recipes.overall({1: first, 2: other}) == Outcome(8, False, "8/9 recipes over all seeds (not pack)")
    assert e3.Recipes.overall({1: other, 2: first}) == Outcome(8, False, "8/9 recipes over all seeds (not pack)")
    every = e3.RecipesMade(9, True, "9/9 recipes")
    assert e3.Recipes.overall({1: first, 2: every}) == Outcome(9, True, "9/9 recipes over all seeds")
