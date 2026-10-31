"""The market stall (10-world-v1 §2.5): prices follow the stock, the stall opens only while its merchant trades at it,
and `buy`/`sell` move whole lots and coins between holders, never more than each holds."""

from collections.abc import Callable

import pytest

from app.observability.events import ItemMoved, PricesChanged, Traded
from app.observability.replay import ReplayEvent, replay
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.economy import coins_held, load_economy
from app.sim.market import (
    MARKET,
    buy_price,
    factor,
    market_view,
    price_word,
    sell_price,
    stall_goods,
)
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.world_api.models import Buy, PriceSeen, Sell, Work
from tests.sim_helpers import make_spec, without_animals

STALL = "market-stall"
BEHIND = (20.0, 52.2)  # the merchant's spot behind the counter
BEFORE = (20.0, 56.0)  # the buyer side of the stall
# §2.5: at the target stock each good sells for its value a lot and is bought for ⌊0.75 × that⌋
AT_TARGET = {
    "rice": (4, 3),
    "wood": (4, 3),
    "hide": (15, 11),
    "obsidian": (6, 4),
    "iron sand": (4, 3),
    "gold": (20, 15),
    "cloth": (25, 18),
    "pack": (30, 22),
    "sickle": (50, 37),
    "iron axe": (60, 45),
    "iron spear": (40, 30),
    "dried meat": (6, 4),
}


def test_the_price_factor_is_one_at_the_target_and_clamped_to_half_and_double() -> None:
    assert factor(120, 120) == 1.0
    assert factor(0, 120) == 2.0  # √121 = 11, clamped
    assert factor(29, 120) == 2.0 and factor(30, 120) < 2.0  # up to ×2 below 30 measures (§1.4)
    assert factor(480, 120) == pytest.approx(0.5016, abs=1e-4)  # 4 × the target: just above the floor
    assert factor(2000, 120) == 0.5
    assert factor(6, 6) == factor(2, 2) == 1.0


@pytest.mark.parametrize(("item", "prices"), sorted(AT_TARGET.items()))
def test_at_the_target_stock_a_lot_sells_for_its_value_and_the_stall_pays_three_quarters(
    item: str, prices: tuple[int, int]
) -> None:
    target = load_economy().goods[item].stall
    assert target is not None
    assert (sell_price(item, target.target), buy_price(item, target.target)) == prices
    assert price_word(item, target.target) == "fair"


def test_prices_at_an_empty_and_an_overfull_stall() -> None:
    assert (sell_price("rice", 0), buy_price("rice", 0), price_word("rice", 0)) == (8, 6, "dear")
    assert (sell_price("rice", 480), buy_price("rice", 480), price_word("rice", 480)) == (3, 2, "cheap")
    assert (sell_price("hide", 0), buy_price("hide", 0)) == (30, 22)
    assert (sell_price("wood", 2000), buy_price("wood", 2000)) == (2, 1)
    assert buy_price("wood", 10_000) == 1  # the stall always pays at least a coin a lot


@pytest.mark.parametrize(
    ("stock", "word", "sell"),
    [(0, "dear", 8), (119, "dear", 5), (120, "fair", 4), (214, "fair", 4), (215, "cheap", 3), (480, "cheap", 3)],
)
def test_rice_is_dear_below_its_target_fair_up_to_214_and_cheap_beyond(stock: int, word: str, sell: int) -> None:
    assert (price_word("rice", stock), sell_price("rice", stock)) == (word, sell)


def test_the_stall_trades_exactly_the_goods_with_a_stall_row() -> None:
    goods = load_economy().goods
    assert stall_goods() == tuple(sorted(item for item, good in goods.items() if good.stall is not None))
    assert "berries" not in stall_goods() and "flint" not in stall_goods() and "coins" not in stall_goods()


def test_the_cast_s_stall_opens_with_every_good_at_its_target_but_the_finite_gold() -> None:
    goods = load_economy().goods
    targets = {item: good.stall.target for item, good in goods.items() if good.stall is not None and item != "gold"}
    assert load_citizens(CITIZENS).stores[STALL] == targets
    assert all(price_word(item, count) == "fair" for item, count in targets.items())


# --- the stall in the world ---


def _market(new_sim: Callable[..., Simulation], merchant_coins: int = 100, **buyer: object) -> Simulation:
    sim = without_animals(new_sim(seed=3))
    for item, good in sorted(load_economy().goods.items()):
        if good.stall is not None and item != "gold":
            sim.stock_store(STALL, item, good.stall.target)
    sim.add_citizen(
        make_spec("fumiko", name="Fumiko", at=BEHIND, skills=["trade"], inventory={"coins": merchant_coins})
    )
    sim.add_citizen(make_spec("goro", name="Goro", at=BEFORE, **buyer))
    sim.drain()
    return sim


def _open(sim: Simulation) -> None:
    sim.start("fumiko", Work(task="trade"))
    sim.drain()


def test_a_shut_stall_refuses_and_so_does_one_out_of_reach(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50, "hide": 2})
    shut = sim.instant("goro", Buy(item="rice", amount=2))
    assert (shut.outcome, shut.text) == ("failed", "The stall is shut.")
    assert sim.instant("goro", Sell(item="hide", amount=1)).text == "The stall is shut."
    assert market_view(sim.core, sim.citizen("goro")) is None
    _open(sim)
    sim.core.place_at(sim.citizen("goro"), sim.world.town.to_unit(20.0, 62.0))  # 8.5 m off
    assert sim.instant("goro", Buy(item="rice", amount=2)).text == "There's no stall here."
    assert sim.citizen("goro").inventory == {"coins": 50, "hide": 2}


def test_the_stall_is_open_only_while_the_merchant_works_trade_at_it(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50})
    _open(sim)
    assert sim.instant("goro", Buy(item="rice", amount=2)).outcome == "done"
    sim.core.end_action(sim.citizen("fumiko"), "interrupted", "You stop.")
    assert sim.instant("goro", Buy(item="rice", amount=2)).text == "The stall is shut."
    _open(sim)
    sim.core.place_at(sim.citizen("fumiko"), sim.world.town.to_unit(20.0, 46.0))  # 7.5 m behind: off her post
    assert sim.instant("goro", Buy(item="rice", amount=2)).text == "The stall is shut."


def test_a_purchase_moves_whole_lots_and_pays_the_merchant_lot_by_lot(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50})
    _open(sim)
    coins = coins_held(sim.state)
    result = sim.instant("goro", Buy(item="rice", amount=5))  # two lots of two: the odd measure isn't sold
    # the first lot at the target (4), the second at 118 left (dear: 5)
    assert (result.outcome, result.text) == ("done", "You buy four measures of rice for nine coins.")
    assert sim.citizen("goro").inventory == {"coins": 41, "rice": 4}
    assert sim.citizen("fumiko").inventory == {"coins": 109}
    assert sim.state.stores[STALL]["rice"] == 116
    assert coins_held(sim.state) == coins
    events = sim.drain()
    bought = next(e for e in events if e.type == "bought")
    assert (bought.actor_id, bought.payload) == (
        "goro",
        Traded(item="rice", count=4, lots=2, coins=9, stall=STALL, merchant="fumiko"),
    )
    moves = [(e.cause_seq, e.payload) for e in events if isinstance(e.payload, ItemMoved)]
    assert [(cause, move.item, move.count, move.source.id, move.destination.id) for cause, move in moves] == [
        (bought.seq, "rice", 4, STALL, "goro"),
        (bought.seq, "coins", 9, "goro", "fumiko"),
    ]


def test_a_purchase_stops_at_what_the_buyer_can_pay_and_carry(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 10})
    _open(sim)
    short = sim.instant("goro", Buy(item="hide", amount=1))
    assert (short.outcome, short.text) == ("failed", "You can't pay for more.")
    partial = sim.instant("goro", Buy(item="rice", amount=20))  # 4 + 5 = 9 coins for two lots, a third costs 5
    assert partial.text == "You buy four measures of rice for nine coins. You can't pay for more."
    assert sim.citizen("goro").inventory == {"coins": 1, "rice": 4}
    heavy = _market(new_sim, inventory={"coins": 100, "iron sand": 22})  # 22.4 kg of the 25 kg he can carry
    _open(heavy)
    assert heavy.instant("goro", Buy(item="iron sand", amount=5)).text == (
        "You buy two measures of iron sand for nine coins. You can't carry any more."  # 4 at 20 in stock, 5 at 19
    )
    assert heavy.citizen("goro").inventory["iron sand"] == 24
    assert heavy.instant("goro", Buy(item="iron sand", amount=1)).text == "You can't carry any more."


def test_a_purchase_stops_when_the_stall_runs_out(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 500})
    _open(sim)
    result = sim.instant("goro", Buy(item="sickle", amount=3))
    assert result.text == "You buy two sickles for 112 coins. The stall has no more sickles."  # 50 + 62
    assert STALL in sim.state.stores and "sickle" not in sim.state.stores[STALL]
    assert sim.instant("goro", Buy(item="gold", amount=1)).text == "The stall has no more gold."


def test_buying_names_the_lot_and_the_goods_the_stall_sells(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50})
    _open(sim)
    assert sim.instant("goro", Buy(item="rice", amount=1)).text == "Rice is sold two measures at a time."
    assert sim.instant("goro", Buy(item="wood", amount=3)).text == "Wood is sold four pieces at a time."
    assert sim.instant("goro", Buy(item="berries", amount=3)).text == "The stall doesn't sell berries."
    assert sim.instant("goro", Buy(item="moonstones", amount=3)).text == "The stall doesn't sell moonstones."
    assert sim.instant("goro", Buy(item="two measures of rice", amount=2)).outcome == "done"
    assert sim.citizen("goro").inventory == {"coins": 46, "rice": 2}


def test_a_sale_to_the_stall_is_paid_from_the_merchant_s_purse(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"hide": 3, "rice": 7})
    _open(sim)
    result = sim.instant("goro", Sell(item="hides", amount=2))  # the stall pays 11 at 6 in stock and at 7
    assert (result.outcome, result.text) == ("done", "You sell two hides for twenty-two coins.")
    assert sim.citizen("goro").inventory == {"coins": 22, "hide": 1, "rice": 7}
    assert sim.citizen("fumiko").inventory == {"coins": 78}
    assert sim.state.stores[STALL]["hide"] == 8
    sold = next(e for e in sim.drain() if e.type == "sold")
    assert sold.payload == Traded(item="hide", count=2, lots=2, coins=22, stall=STALL, merchant="fumiko")
    rice = sim.instant("goro", Sell(item="rice", amount=9))  # 7 carried: 3 lots
    assert rice.text == "You sell six measures of rice for nine coins."
    assert sim.citizen("goro").inventory == {"coins": 31, "hide": 1, "rice": 1}


def test_the_stall_buys_only_what_it_sells_up_to_twice_its_target(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"hide": 8, "berries": 5, "flint": 2, "coins": 3})
    _open(sim)
    assert sim.instant("goro", Sell(item="berries", amount=5)).text == "The stall doesn't buy berries."
    assert sim.instant("goro", Sell(item="flint", amount=2)).text == "The stall doesn't buy flint."
    assert sim.instant("goro", Sell(item="coins", amount=3)).text == "The stall doesn't buy coins."
    full = sim.instant("goro", Sell(item="hide", amount=8))  # 6 in stock, room for 6 more: 11 + 11 + 10 + 9 + 9 + 9
    assert full.text == "You sell six hides for fifty-nine coins. The stall has all the hides it wants."
    assert sim.state.stores[STALL]["hide"] == 12 and sim.citizen("goro").inventory["hide"] == 2
    assert sim.instant("goro", Sell(item="hide", amount=1)).text == "The stall has all the hides it wants."


def test_the_stall_never_pays_more_than_its_till_holds(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, merchant_coins=14, inventory={"hide": 3})
    _open(sim)
    first = sim.instant("goro", Sell(item="hide", amount=3))
    assert first.text == "You sell a hide for eleven coins. The stall can't pay for more."
    assert sim.citizen("fumiko").inventory == {"coins": 3}
    assert sim.instant("goro", Sell(item="hide", amount=1)).text == "The stall can't pay for more."
    assert sim.citizen("goro").inventory == {"hide": 2, "coins": 11}


def test_selling_needs_a_lot_in_hand_and_the_merchant_can_t_trade_with_herself(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _market(new_sim, inventory={"rice": 1, "coins": 20})
    _open(sim)
    assert sim.instant("goro", Sell(item="rice", amount=1)).text == "You don't have two measures of rice to sell."
    assert sim.instant("goro", Sell(item="cloth", amount=1)).text == "You don't have a length of cloth to sell."
    sim.citizen("goro").inventory["rice"] = 3
    assert sim.instant("goro", Sell(item="rice", amount=1)).text == "Rice is bought two measures at a time."
    assert sim.instant("fumiko", Buy(item="rice", amount=2)).text == (
        "You keep this stall; you can't trade with yourself."
    )


def test_a_sale_that_moves_a_price_word_tells_it(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50})
    _open(sim)
    sim.instant("goro", Buy(item="rice", amount=2))  # 120 → 118: dear
    events = sim.drain()
    bought = next(e for e in events if e.type == "bought")
    changed = [e for e in events if e.type == "prices_changed"]
    assert [(e.actor_id, e.cause_seq, e.payload) for e in changed] == [
        (None, bought.seq, PricesChanged(stall=STALL, item="rice", word="dear", before="fair", lot=2, sell=5, buy=3))
    ]
    sim.instant("goro", Buy(item="rice", amount=2))  # still dear: nothing new to tell
    assert not [e for e in sim.drain() if e.type == "prices_changed"]


def test_a_word_moved_by_anything_but_a_sale_is_told_at_the_tick_s_end(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim)
    sim.step()  # the opening words are noted, not told
    assert not [e for e in sim.drain() if e.type == "prices_changed"]
    sim.state.stores[STALL]["cloth"] = 1  # as if taken from the stall
    sim.step()
    changed = [e.payload for e in sim.drain() if isinstance(e.payload, PricesChanged)]
    assert changed == [PricesChanged(stall=STALL, item="cloth", word="dear", before="fair", lot=1, sell=47, buy=35)]


def test_someone_at_the_open_stall_sees_each_good_s_price_and_word(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim)
    _open(sim)
    view = market_view(sim.core, sim.citizen("goro"))
    assert view is not None
    seen = {price.item: price for price in view.items}
    assert set(seen) == set(stall_goods())
    assert seen["rice"] == PriceSeen(item="rice", price="four coins for two measures; it pays three coins", word="fair")
    assert seen["wood"].price == "four coins for four pieces; it pays three coins"
    assert seen["dried meat"].price == "six coins for two strips; it pays four coins"
    assert seen["hide"].price == "fifteen coins each; it pays eleven coins"
    assert seen["gold"] == PriceSeen(item="gold", price="none left; it pays thirty coins", word="dear")
    assert seen["iron axe"].price == "sixty coins each; it pays forty-five coins"


def test_the_merchant_s_session_tells_how_many_sales_she_made(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50, "hide": 1})
    _open(sim)
    session = sim.citizen("fumiko").action
    assert session is not None
    sim.instant("goro", Buy(item="rice", amount=2))
    sim.instant("goro", Sell(item="hide", amount=1))
    sim.run(60)
    result = sim.result("fumiko", session.number)
    assert result is not None and result.text == "You keep the stall a while and make two sales."
    assert MARKET.of(sim.state).sales == {}
    _open(sim)
    quiet = sim.citizen("fumiko").action
    assert quiet is not None
    sim.run(60)
    again = sim.result("fumiko", quiet.number)
    assert again is not None and again.text == "You keep the stall a while; nobody comes to trade."


def test_an_interrupted_session_s_sales_are_let_go(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50})
    _open(sim)
    sim.instant("goro", Buy(item="rice", amount=2))
    assert len(MARKET.of(sim.state).sales) == 1
    sim.core.end_action(sim.citizen("fumiko"), "interrupted", "You stop.")
    sim.step()
    assert MARKET.of(sim.state).sales == {}


def test_trades_replay_exactly_and_the_market_s_state_round_trips(new_sim: Callable[..., Simulation]) -> None:
    sim = _market(new_sim, inventory={"coins": 50, "hide": 2})
    snapshot = take_snapshot(sim.state)
    events = []
    _open(sim)
    sim.instant("goro", Buy(item="rice", amount=6))
    sim.instant("goro", Sell(item="hide", amount=2))
    events = sim.drain()
    replayed = replay(
        snapshot, [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    )
    assert replayed.citizens["goro"].inventory == sim.citizen("goro").inventory
    assert replayed.citizens["fumiko"].inventory == sim.citizen("fumiko").inventory
    assert replayed.stores == sim.state.stores
    market = MARKET.of(sim.state)
    restored = MARKET.of(restore(take_snapshot(sim.state)))
    assert (restored.words, restored.sales) == (market.words, market.sales)
    assert market.words[STALL]["rice"] == "dear" and market.sales == {
        f"fumiko#{sim.citizen('fumiko').next_action - 1}": 2
    }
