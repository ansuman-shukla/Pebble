"""BR1's run checks catch what they guard: town sales, a missed wage, unpaid dues, a town recipe never made, coins
running away, a watchman off his beat, too few at work at noon, a town death of hunger."""

from collections.abc import Callable

import pytest

from app.observability.events import Crafted, Died, EventDraft, EventType, ItemLocation, ItemMoved, Payload, Traded
from app.sim import tax
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.simulation import Simulation
from scripts.checks import CHECKS, br1
from scripts.checks.base import Outcome


@pytest.fixture
def town(new_sim: Callable[..., Simulation]) -> Simulation:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    sim.drain()
    return sim


def _event(sim: Simulation, kind: EventType, payload: Payload, actor: str = "goro") -> EventDraft:
    return EventDraft(0, sim.tick, kind, "citizen", actor, None, None, "public", None, payload)


def test_the_checks_are_registered() -> None:
    assert set(br1.CHECKS) <= set(CHECKS)
    assert all(check.pending is None for check in br1.CHECKS)


def test_sales_count_the_town_s_and_add_the_seeds_up(town: Simulation) -> None:
    check = br1.Sales()
    check.start(town)
    sale = Traded(item="rice", count=2, lots=1, coins=4, stall="market-stall", merchant="fumiko")
    for tick in range(DAY_MINUTES):
        town.state.tick = tick
        events = [_event(town, "bought", sale), _event(town, "sold", sale, actor="nim")] if tick < 7 else []
        check.after_step(town, events)
    assert check.outcome(town) == Outcome(7.0, False, "7.0/day (7 sales)")  # nim's (band B) don't count
    assert br1.Sales.overall({1: Outcome(7.0, False, ""), 2: Outcome(8.0, True, "")}).ok
    assert not br1.Sales.overall({1: Outcome(7.0, False, ""), 2: Outcome(7.9, True, "")}).ok


def _coins(town: Simulation, payer: str, payee: str) -> EventDraft:
    move = ItemMoved(
        item="coins",
        count=25,
        source=ItemLocation(kind="inventory", id=payer),
        destination=ItemLocation(kind="inventory", id=payee),
    )
    return _event(town, "item_moved", move, actor=payer)


def test_wages_are_the_lord_s_coins_to_the_watchman_every_day(town: Simulation) -> None:
    check = br1.Wages()
    check.start(town)
    for day in range(3):
        town.state.tick = day * DAY_MINUTES + 600
        payer = "fumiko" if day == 1 else "masanori"  # someone else's coins are no wage
        check.after_step(town, [_coins(town, payer, "goro"), _coins(town, "masanori", "kenji")])
    town.state.tick = 3 * DAY_MINUTES
    assert check.outcome(town) == Outcome(1, False, "2/3 days (not [1])")  # one day missed


def test_paid_counts_the_rice_tax_and_the_dues_in_arrears(town: Simulation) -> None:
    check = br1.Paid()
    check.start(town)
    tax.assess_harvest(town.core, town.citizen("genzo"), 10)  # 4 rice owed
    check.after_step(town, town.drain())
    assert check.outcome(town).value == 0.0  # none paid
    tax.account(town.core, "farmhouse-1").rice = 0
    check.rice_paid, check.coins_paid = 4, 30
    tax.account(town.core, "cross-s-1").arrears = 10
    outcome = check.outcome(town)
    assert outcome.value == pytest.approx(0.75) and not outcome.ok  # dues 30 of 40


def test_recipes_want_every_town_recipe_over_the_seeds(town: Simulation) -> None:
    made = []
    for recipes in (("iron spear", "iron axe", "sickle"), ("cloth", "pack", "dried meat")):
        check = br1.Recipes()
        check.start(town)
        check.after_step(town, [_event(town, "crafted", Crafted(recipe=r, item=r, count=1)) for r in recipes])
        made.append(check.outcome(town))
    assert not made[0].ok and br1.Recipes.overall(dict(enumerate(made))).ok
    assert not br1.Recipes.overall({0: made[0]}).ok


def test_a_steep_coin_trend_is_caught(town: Simulation) -> None:
    assert br1.slope([100, 90, 80, 70]) == pytest.approx(-10.0)
    assert br1.slope([5]) == 0.0
    check = br1.CoinTrend()
    check.start(town)
    for day in range(3, 9):
        town.state.tick = day * DAY_MINUTES
        town.citizen("goro").inventory["coins"] = 100 + 11 * day
        check.after_step(town, [])
    outcome = check.outcome(town)
    assert outcome.value == pytest.approx(11.0) and not outcome.ok and "cross-s-1" in outcome.words


def test_the_night_watch_counts_the_gate_and_the_racks(town: Simulation) -> None:
    check = br1.NightWatch()
    check.start(town)
    town.state.tick = 20 * 60 - START_MINUTE  # 20:00, night at the town
    goro = town.citizen("goro")
    for at in ((-104.0, 80.0), (-120.0, 60.0), (20.0, 56.0), (40.0, 30.0)):
        town.core.place_at(goro, town.world.town.to_unit(*at))
        check.after_step(town, [])
    assert check.outcome(town) == Outcome(0.5, False, "50% of 4 night ticks (goro)")


def test_noon_work_counts_those_at_their_own_workplaces(town: Simulation) -> None:
    town.core.place_at(town.citizen("fumiko"), town.world.town.to_unit(-20.0, 52.5))
    assert br1.at_work(town, town.citizen("fumiko")) is None  # at the well
    town.core.place_at(town.citizen("fumiko"), town.world.town.to_unit(20.0, 56.0))
    assert br1.at_work(town, town.citizen("fumiko")) == "market"
    town.core.place_at(town.citizen("tetsu"), town.world.town.to_unit(20.0, 56.0))
    assert br1.at_work(town, town.citizen("tetsu")) is None  # the market is no smith's work
    check = br1.NoonWork()
    check.start(town)
    town.state.tick = 12 * 60 - START_MINUTE
    check.after_step(town, [])  # the cast starts at its workplaces: 8 of them (the smith stands at the market)
    town.state.tick += 1
    check.after_step(town, [])  # not noon
    assert check.counts == [8] and check.outcome(town).ok
    town.core.place_at(town.citizen("fumiko"), town.world.town.to_unit(-20.0, 52.5))
    town.state.tick += DAY_MINUTES - 1
    check.after_step(town, [])
    assert check.counts == [8, 7] and not check.outcome(town).ok  # 7.5 on average


def test_a_town_death_of_hunger_is_caught_and_others_are_not(town: Simulation) -> None:
    check = br1.Starvation()
    check.start(town)
    check.after_step(town, [_event(town, "died", Died(cause="killed by a wolf"), actor="genzo")])
    check.after_step(town, [_event(town, "died", Died(cause="starvation"), actor="nim")])
    assert check.outcome(town).ok
    check.after_step(town, [_event(town, "died", Died(cause="dehydration"), actor="hana")])
    assert check.outcome(town) == Outcome(1, False, "hana (dehydration)")
