"""E2's run checks catch what they guard: a take from someone else's store with no `stole`, books that drift from
their events, a wrong rice tax, an overdue owing nothing and a missing ledger."""

from collections.abc import Callable

import pytest

from app.observability.events import ItemLocation, TaxChange
from app.sim import tax
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from scripts.checks import CHECKS, e2
from scripts.checks.base import Check


@pytest.fixture
def town(new_sim: Callable[..., Simulation]) -> Simulation:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    sim.drain()
    return sim


def _judge(check: Check, sim: Simulation, plant: Callable[[], object]) -> None:
    check.start(sim)
    sim.step()
    check.after_step(sim, sim.drain())
    plant()
    check.after_step(sim, sim.drain())


def _take_unseen(sim: Simulation, citizen_id: str, store_id: str) -> None:
    """A take that skips ownership: the goods move with no `stole`."""
    sim.state.stores[store_id]["rice"] -= 2
    citizen = sim.citizen(citizen_id)
    where = ItemLocation(kind="store", id=store_id)
    sim.core.item_moved(citizen, "rice", 2, where, ItemLocation(kind="inventory", id=citizen_id))


def test_the_checks_are_registered() -> None:
    assert set(e2.CHECKS) <= set(CHECKS)


def test_the_theft_check_catches_a_take_from_another_household_with_no_theft_told(town: Simulation) -> None:
    check = e2.Theft()
    _judge(check, town, lambda: _take_unseen(town, "goro", "farmhouse-1-chest"))
    assert not check.outcome(town).ok and "goro took 2 rice from farmhouse-1-chest" in check.outcome(town).words
    told = e2.Theft()
    _judge(told, town, lambda: WorldApi(town, "goro").pick_up("2 rice"))  # out of reach: nothing happens
    _judge(told, town, lambda: _take_unseen(town, "genzo", "farmhouse-1-chest"))  # their own
    assert told.outcome(town).ok


def test_the_theft_check_counts_goods_bought_at_the_stall_as_no_take(town: Simulation) -> None:
    """A purchase moves the stall's goods to the buyer, caused by its `bought` (regression: BR1's buyers were flagged)."""
    town.core.place_at(town.citizen("fumiko"), town.world.town.to_unit(20.0, 52.3))  # behind the stall
    town.core.place_at(town.citizen("goro"), town.world.town.to_unit(20.0, 55.0))  # before it
    WorldApi(town, "fumiko").work("trade")
    check = e2.Theft()
    _judge(check, town, lambda: WorldApi(town, "goro").buy("rice", 4))
    assert town.citizen("goro").inventory.get("rice") == 4
    assert check.outcome(town).ok, check.outcome(town).words


def test_the_granary_check_catches_rice_its_eaters_don_t_get(town: Simulation) -> None:
    check = e2.Granary()
    _judge(check, town, lambda: _take_unseen(town, "kenji", "store-2"))
    assert check.outcome(town).ok and check.outcome(town).words == "0 taken unseen by the books, 2 fed, 0 stolen"
    _judge(check, town, lambda: _take_unseen(town, "genzo", "store-2"))
    assert check.outcome(town).value == 2 and not check.outcome(town).ok


def test_the_books_check_catches_an_account_changed_without_its_event(town: Simulation) -> None:
    check = e2.Books()
    _judge(check, town, lambda: tax.assess_harvest(town.core, town.citizen("genzo"), 10))
    assert check.outcome(town).ok and check.outcome(town).words == "owed at the end: farmhouse-1 4 rice 0 mon"
    tax.account(town.core, "farmhouse-1").rice = 1  # forgiven without a word
    town.step()
    check.after_step(town, town.drain())
    assert not check.outcome(town).ok


def test_the_rice_tax_check_catches_a_wrong_assessment(town: Simulation) -> None:
    check = e2.RiceTax()
    _judge(check, town, lambda: None)
    assert not check.outcome(town).ok  # nothing assessed in the run
    genzo = town.citizen("genzo")
    harvest = town.core.item_moved(genzo, "rice", 12, ItemLocation(kind="world"), ItemLocation(kind="inventory"))
    tax.assess_harvest(town.core, genzo, 12, harvest)
    check.after_step(town, town.drain())
    assert check.outcome(town).ok and check.outcome(town).words == "5 assessed, 0% paid"
    owed = TaxChange(household="farmhouse-1", rice=4, owed_rice=9)
    town.core.emit("tax_assessed", owed, actor=genzo, cause_seq=harvest)
    check.after_step(town, town.drain())
    assert check.outcome(town).words == "tick 1: 4 rice owed on a harvest of 12"


def test_the_overdue_check_catches_an_overdue_owing_nothing(town: Simulation) -> None:
    check = e2.Overdue()
    _judge(check, town, lambda: town.core.emit("tax_overdue", TaxChange(household="farmhouse-1", rice=3, days=1)))
    assert check.outcome(town).ok
    _judge(check, town, lambda: town.core.emit("tax_overdue", TaxChange(household="farmhouse-1", days=1)))
    assert not check.outcome(town).ok


def test_the_ledger_check_wants_one_a_day_each(town: Simulation) -> None:
    check = e2.Ledgers()
    check.start(town)
    check.ticks = 2 * DAY_MINUTES
    check.counts.update(dict.fromkeys(town.state.citizens, 2))
    assert check.outcome(town).ok
    check.counts["goro"] = 0
    assert not check.outcome(town).ok and check.outcome(town).value == 2
