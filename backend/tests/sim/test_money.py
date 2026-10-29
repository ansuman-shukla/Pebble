"""Money (10-world-v1 §2.1): the cast starts with the whole supply of 3 000 mon in purses and the treasury, and the
closed supply's check catches any coin minted or lost."""

from collections.abc import Callable

import pytest

from app.observability.events import ItemMoved
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.economy import MoneyLeak, check_money_supply, coins_held
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi

TREASURY = "castle-keep-chest"


def _town(new_sim: Callable[..., Simulation]) -> Simulation:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    return sim


def test_the_cast_starts_with_the_whole_money_supply_in_purses_and_the_treasury(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _town(new_sim)
    events = sim.drain()
    assert sim.state.stores[TREASURY] == {"coins": 2015}
    assert sim.state.stores["farmhouse-1-chest"] == sim.state.stores["farmhouse-2-chest"] == {"rice": 20}
    assert sim.citizen("fumiko").inventory == {"coins": 500}
    assert sim.citizen("hana").inventory == {"coins": 5}
    assert "coins" not in sim.citizen("masanori").inventory and "coins" not in sim.citizen("tek").inventory
    assert coins_held(sim.state) == 3000
    check_money_supply(sim.state)
    minted = [e.payload for e in events if isinstance(e.payload, ItemMoved) and e.payload.item == "coins"]
    assert {(m.destination.kind, m.destination.id, m.count) for m in minted if m.source.kind == "world"} == {
        ("store", TREASURY, 2015)
    }  # purses come with their spawn; the treasury is stocked from the world


def test_a_purse_is_carried_and_said(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    assert "five strings of coins" in WorldApi(sim, "fumiko").check_self().carrying
    assert "five coins" in WorldApi(sim, "hana").check_self().carrying


def test_only_stores_can_be_stocked(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.stock_store("main-e-2-chest", "coins", 3)
    with pytest.raises(ValueError, match="castle-keep is not a store"):
        sim.stock_store("castle-keep", "coins", 3)  # the keep itself; its chest is the store


@pytest.mark.parametrize(
    "plant",
    [
        lambda sim: sim.citizen("goro").inventory.update(coins=61),  # a coin minted into a purse
        lambda sim: sim.state.stores[TREASURY].update(coins=2014),  # one gone from the treasury
        lambda sim: sim.core.new_stack("coins", 1, sim.citizen("hana").position, sim.citizen("hana").cell),
    ],
)
def test_the_money_supply_check_catches_a_mint_or_a_loss(
    new_sim: Callable[..., Simulation], plant: Callable[[Simulation], object]
) -> None:
    sim = _town(new_sim)
    plant(sim)
    with pytest.raises(MoneyLeak, match="not 3000"):
        check_money_supply(sim.state)


def test_the_dead_still_hold_their_coins(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    sim.core.injure(sim.citizen("goro"), 200, "animal attack", "a wolf attacks you")
    assert not sim.citizen("goro").body.alive
    assert coins_held(sim.state) == 3000


def test_coins_moved_between_holders_keep_the_supply(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    hana = WorldApi(sim, "hana")
    assert hana.drop("two coins").outcome == "done"  # two on the ground, three in her purse
    assert sim.citizen("hana").inventory == {"coins": 3}
    assert coins_held(sim.state) == 3000
    check_money_supply(sim.state)
    check_money_supply(sim.state, supply=3000)
    with pytest.raises(MoneyLeak):
        check_money_supply(sim.state, supply=2999)
