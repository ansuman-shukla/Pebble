"""Tax, dues and the ledger (10-world-v1 §2.7): ⌈40 %⌉ of each harvest owed and paid first at the granary, dues
owed daily and settled with the lord, overdue only when unpaid, and each citizen's daily ledger."""

from collections.abc import Callable
from typing import Any

import pytest

from app.observability.events import EventDraft, ItemMoved, Ledger, TaxChange
from app.sim import paddies, slots, tax
from app.sim.clock import DAY_MINUTES, START_MINUTE, local_minute
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.sim.state import ActionState
from app.sim.systems import midnight_at
from app.sim.tax import TAX, Account
from app.sim.vec import lat_lon_deg
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import make_spec, stand_at_node, without_animals

COURT_ENDS = 7 * DAY_MINUTES - START_MINUTE  # the tick local midnight ends week day 7 (court day) in town
TOWN = ["town", "well", "main-gate", "storehouses", "rice-fields", "castle"]


def _scene(new_sim: Callable[..., Simulation], *people: tuple[str, str, str], **extra: dict[str, Any]) -> Simulation:
    sim = without_animals(new_sim(seed=5))
    for citizen_id, home, at in people:
        x, z = sim.world.structures[at].door_xz
        fields = {"home": home, "at": (x, z), "knows_places": TOWN} | extra.get(citizen_id, {})
        sim.add_citizen(make_spec(citizen_id, **fields))
    sim.drain()
    return sim


def _tax(events: list[EventDraft]) -> list[tuple[str, str | None, TaxChange]]:
    return [(str(e.type), e.actor_id, e.payload) for e in events if isinstance(e.payload, TaxChange)]


def _midnight(sim: Simulation, tick: int) -> list[EventDraft]:
    """The town's midnight at `tick` and the minutes round it, each household settling at its own local midnight."""
    for minute in range(tick - 20, tick + 20):
        sim.state.tick = minute
        tax.settle_at_midnight(sim.core, lambda unit: midnight_at(sim.core, unit))
    return sim.drain()


def _night(day: int) -> int:
    """The tick of the town's midnight that ends day `day` (0-based)."""
    return (day + 1) * DAY_MINUTES - START_MINUTE


@pytest.mark.parametrize(("harvest", "owed"), [(12, 5), (10, 4), (1, 1), (25, 10), (0, 0)])
def test_each_harvest_owes_forty_percent_rounded_up(
    new_sim: Callable[..., Simulation], harvest: int, owed: int
) -> None:
    sim = _scene(new_sim, ("genzo", "farmhouse-1", "farmhouse-1"))
    tax.assess_harvest(sim.core, sim.citizen("genzo"), harvest)
    tax.assess_harvest(sim.core, sim.citizen("genzo"), harvest)
    assert tax.account(sim.core, "farmhouse-1").rice == 2 * owed
    assert len(_tax(sim.drain())) == (2 if owed else 0)


def test_a_harvest_session_assesses_its_rice_on_the_farmer_s_household(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("aiko", "farmhouse-1", "farmhouse-1"))
    aiko = sim.citizen("aiko")
    ripe = sim.world.nodes.index["paddy-6"]  # a ripe paddy: the session harvests (N1, paddies.harvest)
    stand_at_node(sim, aiko.id, ripe)
    slots.claim(sim.core, aiko, slots.node_slots(sim.core, ripe)[0], aiko.position)
    paddies.farm(sim.core, aiko, ActionState(1, "work", 0, 0, {}))
    events = sim.drain()
    harvested = next(
        e for e in events if isinstance(e.payload, ItemMoved) and e.payload.destination.kind == "inventory"
    )
    assessed = [e for e in events if e.type == "tax_assessed"]
    assert len(assessed) == 1 and assessed[0].cause_seq == harvested.seq and assessed[0].actor_id == "aiko"
    assert assessed[0].payload == TaxChange(household="farmhouse-1", rice=4, owed_rice=4)  # ⌈0.4 × 10⌉


def test_a_band_s_harvest_owes_the_town_nothing(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("kaz", "band_b_camp:shelter-e", "farmhouse-1"), kaz={"region": "band_b"})
    assert tax.assess_harvest(sim.core, sim.citizen("kaz"), 12) is None


def test_storing_food_at_the_granary_pays_the_rice_tax_first_and_keeps_the_rest(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(new_sim, ("genzo", "farmhouse-1", "store-2"), genzo={"inventory": {"rice": 12, "berries": 3}})
    tax.account(sim.core, "farmhouse-1").rice = 5
    sim.drain()
    result = run_until_done(sim, WorldApi(sim, "genzo").work("store food"), 10)
    events = sim.drain()
    assert result.text == "You pay some rice as rice tax."
    assert sim.citizen("genzo").inventory == {"rice": 7, "berries": 3}
    assert sim.state.stores["store-2"] == {"rice": 5}
    paid = [e for e in events if e.type == "tax_paid"]
    assert [e.payload for e in paid] == [TaxChange(household="farmhouse-1", rice=5)]
    moved = [(e.payload.count, e.cause_seq) for e in events if isinstance(e.payload, ItemMoved)]
    assert moved == [(5, paid[0].seq)]


def test_short_of_rice_pays_what_it_carries_and_still_owes(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("tokuji", "farmhouse-2", "store-2"), tokuji={"inventory": {"rice": 3}})
    tax.account(sim.core, "farmhouse-2").rice = 8
    result = run_until_done(sim, WorldApi(sim, "tokuji").work("store food"), 10)
    assert result.text == "You pay a little rice as rice tax. Your household still owes more."
    assert tax.account(sim.core, "farmhouse-2").rice == 5


def test_owing_rice_but_carrying_none_is_told_so(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("tokuji", "farmhouse-2", "store-2"), tokuji={"inventory": {"berries": 3}})
    tax.account(sim.core, "farmhouse-2").rice = 4
    assert run_until_done(sim, WorldApi(sim, "tokuji").work("store food"), 10).text == "You carry no rice for the tax."
    assert tax.account(sim.core, "farmhouse-2").rice == 4


def test_the_keep_fills_its_own_granary_and_others_owing_nothing_keep_their_food(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(
        new_sim,
        ("kenji", "castle-keep", "store-2"),
        ("goro", "cross-s-1", "store-2"),
        kenji={"inventory": {"rice": 4}},
        goro={"inventory": {"rice": 4}},
    )
    assert run_until_done(sim, WorldApi(sim, "kenji").work("store food"), 10).text == (
        "You put some rice in the storehouse."
    )
    assert run_until_done(sim, WorldApi(sim, "goro").work("store food"), 10).text == (
        "You owe no rice tax, and the storehouse isn't yours to fill."
    )
    assert sim.state.stores["store-2"] == {"rice": 4} and sim.citizen("goro").inventory == {"rice": 4}


@pytest.mark.parametrize(
    ("household", "dues"),
    [
        ("main-e-2", 5),
        ("cross-s-1", 5),
        ("farmhouse-1", 24),
        ("farmhouse-2", 12),
        ("castle-keep", 0),
        ("temple-hall", 0),
    ],
)
def test_dues_by_household(household: str, dues: int) -> None:
    assert tax.dues_of(household) == dues


def test_dues_are_owed_daily_and_overdue_only_once_court_day_passes_unpaid(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("tetsu", "cross-n-9", "cross-n-9"), ("ennen", "temple-hall", "temple-hall"))
    for day in range(1, 7):  # the midnights before court day ends
        events = _midnight(sim, COURT_ENDS - (7 - day) * DAY_MINUTES)
        assert [(kind, change.household, change.coins) for kind, _, change in _tax(events)] == [
            ("tax_assessed", "cross-n-9", 5)
        ]
    assert tax.account(sim.core, "cross-n-9") == Account(coins=30)
    events = _midnight(sim, COURT_ENDS)
    assert [(kind, change.coins, change.days) for kind, _, change in _tax(events)] == [
        ("tax_overdue", 30, 1),
        ("tax_assessed", 5, 0),
    ]
    events = _midnight(sim, COURT_ENDS + DAY_MINUTES)
    assert [(kind, change.coins, change.days) for kind, _, change in _tax(events)] == [
        ("tax_overdue", 30, 2),  # the arrears; the new week's dues aren't overdue yet
        ("tax_assessed", 5, 0),
    ]
    assert tax.account(sim.core, "temple-hall") == Account()


def test_a_house_west_of_the_castle_puts_its_dues_in_arrears_at_its_own_midnight_after_court_day(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(new_sim, ("genzo", "farmhouse-1", "farmhouse-1"), ("tetsu", "temple-hall", "temple-hall"))
    door = sim.world.structures["farmhouse-1"].door
    assert local_minute(COURT_ENDS, sim.world.town_lon_deg, lat_lon_deg(door)[1]) > DAY_MINUTES - 15  # still day 7
    tax.account(sim.core, "farmhouse-1").coins = 30
    told: list[tuple[int, str, TaxChange]] = []
    for tick in range(COURT_ENDS - 5, COURT_ENDS + 30):  # the town's midnight, then the house's a few minutes later
        sim.state.tick = tick
        tax.settle_at_midnight(sim.core, lambda unit: midnight_at(sim.core, unit))
        told += [(tick, kind, change) for kind, _, change in _tax(sim.drain())]
    assert told
    assert [(kind, change.household, change.coins) for _, kind, change in told] == [
        ("tax_overdue", "farmhouse-1", 30),
        ("tax_assessed", "farmhouse-1", 24),
    ]
    assert told[0][0] > COURT_ENDS
    assert tax.account(sim.core, "farmhouse-1") == Account(coins=54, arrears=30, days=1)


def test_paying_the_lord_clears_the_arrears_and_the_overdue_count(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ("tetsu", "cross-n-9", "castle-keep"),
        ("masanori", "castle-keep", "castle-keep"),
        ("kenji", "castle-keep", "castle-keep"),
        tetsu={"inventory": {"coins": 60}},
        masanori={"titles": ["lord"], "rank": 5},
        kenji={"titles": ["samurai"], "rank": 4},
    )
    tax.account(sim.core, "cross-n-9").coins = 30
    _midnight(sim, COURT_ENDS)
    tetsu = WorldApi(sim, "tetsu")
    tetsu.give("10 coins", "Kenji")  # not the lord: a gift
    assert _tax(sim.drain()) == [] and tax.account(sim.core, "cross-n-9").arrears == 30
    tetsu.give("20 coins", "Masanori")
    events = sim.drain()
    paid = [e for e in events if e.type == "tax_paid"]
    assert [e.payload for e in paid] == [TaxChange(household="cross-n-9", coins=20, owed_coins=15)]
    assert next(e for e in events if isinstance(e.payload, ItemMoved)).cause_seq == paid[0].seq
    assert tax.account(sim.core, "cross-n-9") == Account(coins=15, arrears=10, days=1)  # 30 in arrears + 5 today
    tetsu.give("20 coins", "Masanori")  # 15 pays the rest; 5 more is a gift
    assert [change.coins for kind, _, change in _tax(sim.drain()) if kind == "tax_paid"] == [15]
    assert tax.account(sim.core, "cross-n-9") == Account()
    assert [kind for kind, _, _ in _tax(_midnight(sim, COURT_ENDS + DAY_MINUTES))] == ["tax_assessed"]
    assert sim.citizen("masanori").inventory["coins"] == 40


def test_rice_still_owed_at_midnight_is_overdue_and_counts_the_days(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("genzo", "farmhouse-1", "farmhouse-1"))
    tax.account(sim.core, "farmhouse-1").rice = 5
    for day in (1, 2):
        overdue = [c for kind, _, c in _tax(_midnight(sim, _night(day))) if kind == "tax_overdue"]
        assert overdue == [TaxChange(household="farmhouse-1", rice=5, owed_rice=5, owed_coins=24 * (day - 1), days=day)]
    tax.account(sim.core, "farmhouse-1").rice = 0
    assert [kind for kind, _, _ in _tax(_midnight(sim, _night(3)))] == ["tax_assessed"]
    assert tax.account(sim.core, "farmhouse-1").days == 0


def test_the_ledger_tells_coins_wealth_flows_and_debts_at_midnight(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ("genzo", "farmhouse-1", "farmhouse-1"),
        ("hana", "farmhouse-1", "farmhouse-1"),
        genzo={"inventory": {"coins": 20, "rice": 3}},
        hana={"inventory": {"coins": 5}},
    )
    sim.stock_store("farmhouse-1-chest", "rice", 10)  # 20 mon: 10 each
    genzo = WorldApi(sim, "genzo")
    genzo.give("4 coins", "Hana")
    genzo.stash("coins", 6)  # into their own chest: neither spent nor earned
    tax.account(sim.core, "farmhouse-1").rice = 2
    sim.drain()
    tax.ledger_at_midnight(sim.core, lambda _unit: True)
    ledgers = {e.actor_id: e.payload for e in sim.drain() if isinstance(e.payload, Ledger)}
    assert ledgers["genzo"] == Ledger(
        coins=10, wealth_mon=10 + 6 + 13, income_24h=0, spent_24h=4, owed_rice=2, owed_coins=0
    )  # 10 coins + 3 rice (6) + half the chest (10 rice and 6 coins = 26)
    assert ledgers["hana"] == Ledger(coins=9, wealth_mon=9 + 13, income_24h=4, spent_24h=0, owed_rice=2)
    sim.state.tick += 60
    tax.ledger_at_midnight(sim.core, lambda _unit: True)  # walked west across midnight: met again an hour on
    assert not [e for e in sim.drain() if isinstance(e.payload, Ledger)]
    sim.state.tick += DAY_MINUTES
    tax.ledger_at_midnight(sim.core, lambda _unit: True)
    again = {e.actor_id: e.payload for e in sim.drain() if isinstance(e.payload, Ledger)}
    assert again["hana"].income_24h == 0  # counted afresh after each ledger


@pytest.mark.parametrize("site", ["town", "band_a_camp", "band_b_camp"])  # clocks up to hours off the town's
def test_someone_walking_east_across_their_midnight_still_gets_the_day_s_ledger(
    new_sim: Callable[..., Simulation], site: str
) -> None:
    home = "farmhouse-1" if site == "town" else f"{site}:shelter-e"
    sim = _scene(new_sim, ("genzo", home, home), genzo={"site": site})
    sim.drain()
    _, lon = lat_lon_deg(sim.citizen("genzo").position)
    sim.state.tick = round(DAY_MINUTES - 1 - local_minute(0, sim.world.town_lon_deg, lon)) % DAY_MINUTES
    tax.ledger_at_midnight(sim.core, lambda _unit: True)  # told a minute before midnight where they stand
    assert [e.actor_id for e in sim.drain() if isinstance(e.payload, Ledger)] == ["genzo"]
    sim.state.tick += tax.LEDGER_GAP + 60
    tax.ledger_at_midnight(sim.core, lambda _unit: False)  # that midnight is the one just told
    assert not [e for e in sim.drain() if isinstance(e.payload, Ledger)]
    sim.state.tick += DAY_MINUTES - tax.LEDGER_GAP - 55  # walking east, their next midnight fell on no tick of theirs
    tax.ledger_at_midnight(sim.core, lambda _unit: False)
    assert [e.actor_id for e in sim.drain() if isinstance(e.payload, Ledger)] == ["genzo"]
    sim.state.tick += 60
    tax.ledger_at_midnight(sim.core, lambda _unit: False)  # and only once
    assert not [e for e in sim.drain() if isinstance(e.payload, Ledger)]


def test_the_tax_block_round_trips_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("genzo", "farmhouse-1", "farmhouse-1"), genzo={"inventory": {"coins": 3}})
    tax.assess_harvest(sim.core, sim.citizen("genzo"), 12)
    _midnight(sim, COURT_ENDS)
    back = restore(take_snapshot(sim.state))
    assert TAX.of(back) == TAX.of(sim.state) and TAX.of(back).accounts["farmhouse-1"].days == 1
