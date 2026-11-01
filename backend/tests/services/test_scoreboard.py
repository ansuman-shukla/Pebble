"""The spectator scoreboard (10-world-v1 §7) against a hand-computed world: wealth, flow, health, duty, status,
ambition, ties, skills, the groups, the money supply and the stall."""

from collections.abc import Callable
from typing import Any

import pytest

from app.observability.events import BodyValues, EventDraft
from app.observability.replay import ReplayState, from_snapshot
from app.services.ambitions import Facts, Record
from app.services.scoreboard import Board, CitizenScore, gini, record_of, score_board
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot
from app.sim.society import SOCIETY, Member
from app.sim.world import SimWorld
from app.world_api.models import Sell, Work
from tests.services.test_ambitions import Told, person
from tests.sim_helpers import make_spec, without_animals

NOW = 8 * DAY_MINUTES + 600  # day 9, 10:00


def _coins(count: int, source: dict[str, str], destination: dict[str, str]) -> dict[str, Any]:
    return {"item": "coins", "count": count, "source": source, "destination": destination}


def _purse(citizen_id: str) -> dict[str, str]:
    return {"kind": "inventory", "id": citizen_id}


def _store(store_id: str) -> dict[str, str]:
    return {"kind": "store", "id": store_id}


def _started(number: int, action: str, **args: str) -> dict[str, Any]:
    return {"number": number, "action": action, "args": args, "label": ""}


def _ended(number: int, action: str) -> dict[str, Any]:
    return {"number": number, "action": action, "outcome": "done", "text": ""}


def _sale(merchant: str) -> dict[str, Any]:
    return {"item": "rice", "count": 2, "lots": 1, "coins": 4, "stall": "market-stall", "merchant": merchant}


TAX = {"household": "farmhouse-1", "rice": 0, "coins": 0, "days": 0}
EVENTS: list[Told] = [
    (NOW - 8 * DAY_MINUTES, "tax_paid", "genzo", {**TAX, "coins": 50, "owed_rice": 0, "owed_coins": 0}),  # last week
    (NOW - 2000, "item_moved", "genzo", _coins(9, _purse("genzo"), _purse("fumiko"))),  # over a day ago
    (NOW - 1000, "sold", "ama", _sale("fumiko")),
    (NOW - 600, "action_started", "genzo", _started(1, "work", task="farm")),
    (NOW - 500, "tax_assessed", "genzo", {**TAX, "rice": 4, "owed_rice": 4, "owed_coins": 24}),
    (NOW - 480, "action_finished", "genzo", _ended(1, "work")),  # two hours farming
    (NOW - 300, "action_started", "genzo", _started(2, "gather", resource="berries")),
    (NOW - 300, "action_interrupted", "genzo", _ended(2, "gather")),  # no time at it
    (NOW - 200, "tax_paid", "genzo", {**TAX, "rice": 4, "owed_rice": 0, "owed_coins": 24}),
    (NOW - 150, "tax_paid", "genzo", {**TAX, "rice": 2, "coins": 10, "owed_rice": 0, "owed_coins": 14}),
    (NOW - 120, "action_started", "ama", _started(1, "gather", resource="berries")),
    (NOW - 100, "bought", "genzo", _sale("fumiko")),
    (NOW - 100, "item_moved", "genzo", _coins(4, _purse("genzo"), _purse("fumiko"))),
    (NOW - 100, "item_moved", "genzo", {**_coins(2, _purse("genzo"), _purse("fumiko")), "item": "rice"}),  # no coins
    (NOW - 80, "bought", "fumiko", _sale("fumiko")),  # at her own stall: no partner
    (
        NOW - 100,
        "stole",
        "ama",
        {"owner": "farmhouse-1", "store": "x", "item": "rice", "count": 1, "witnesses": ["aiko"]},
    ),
    (NOW - 90, "action_interrupted", "ama", _ended(1, "gather")),  # half an hour gathering
    (NOW - 60, "action_started", "fumiko", _started(4, "work", task="trade")),  # still at it: an hour by NOW
    (NOW - 50, "item_moved", "genzo", _coins(10, _purse("genzo"), _store("farmhouse-1-chest"))),  # his own chest
    (NOW - 30, "item_moved", "masanori", _coins(25, _store("castle-keep-chest"), _purse("genzo"))),
    (NOW - 20, "judged", "masanori", {"person": "ama", "sentence": "fine", "deeds": [10]}),
]
WELL: BodyValues = (10.0, 10.0, 90.0, 100.0)
BODIES: list[dict[str, BodyValues]] = [
    {"genzo": WELL, "fumiko": WELL},
    {"genzo": WELL, "fumiko": WELL},
    {"genzo": (65.0, 10.0, 90.0, 100.0), "fumiko": WELL},  # hungry
    {"genzo": (10.0, 10.0, 15.0, 100.0)},  # exhausted; Fumiko not in it
]
BONDS = {
    "aiko|genzo": 70,
    "fumiko|genzo": 5,
    "genzo|kenji": 80,
    "ama|genzo": 10,
    "genzo|tokuji": -20,
    "ama|fumiko": -30,
}


def _board(world: SimWorld, treasury: int = 2368, trading: bool = True) -> Board:
    fumiko = person(
        "fumiko",
        home="main-e-2",
        skills=("trade",),
        inventory={"coins": 500, "cloth": 2},
        action="work" if trading else None,
        action_args={"task": "trade"} if trading else {},
        standing={"town": 61},
        member=Member("town", 40, "main-e-2", 3),
    )
    genzo = person(
        "genzo",
        home="farmhouse-1",
        inventory={"coins": 60, "rice": 10},
        body=(10.0, 10.0, 90.0, 87.5),
        standing={"town": 50, "band_a": 10},
        member=Member("town", 28, "farmhouse-1", 2),
        people={"aiko", "fumiko"},
        places={"rice-fields": "visited", "market": "visited", "well": "visited"},
    )
    aiko = person("aiko", home="farmhouse-1", inventory={"coins": 60}, member=Member("town", 26, "farmhouse-1", 2))
    ama = person(
        "ama",
        "band_a",
        home="band_a_camp:shelter-n",
        inventory={"coins": 5, "hide": 1},
        standing={"band_a": 76, "town": 10},
        member=Member("band_a", 40, None, 2, ["leader"]),
    )
    akane = person("akane", home="main-e-2", member=Member("town", 30, "main-e-2", 2))  # the merchant's, no trader
    dead = person("dead", home="farmhouse-1", inventory={"coins": 7}, alive=False)
    stores = {
        "farmhouse-1-chest": {"rice": 20},
        "castle-keep-chest": {"coins": treasury},
        "market-stall": {"rice": 120, "cloth": 6},
    }
    citizens = {c.id: c for c in (akane, fumiko, genzo, aiko, ama, dead)}
    state = ReplayState(tick=NOW, citizens=citizens, ground={}, stores=stores)
    records = [Record(seq, at, kind, actor, data) for seq, (at, kind, actor, data) in enumerate(EVENTS, 1)]
    return score_board(Facts(tick=NOW, state=state, events=records), BODIES, BONDS, world)


def test_a_citizen_s_row_is_their_wealth_flow_health_duty_status_and_ties(sim_world: SimWorld) -> None:
    rows = {row.id: row for row in _board(sim_world).citizens}
    genzo = rows["genzo"]
    # coins + rice by the town's value (10 x 2) + half the household chest's 20 rice (the dead share nothing)
    assert (genzo.coins, genzo.wealth_mon) == (60, 60 + 20 + 20)
    # in: 25 from the treasury; out: 4 to Fumiko (the 9 is older than a day, the 10 went into his own chest)
    assert (genzo.income_24h, genzo.spent_24h) == (25, 4)
    assert (genzo.health, genzo.wellbeing_24h) == (87.5, 50)  # two of four samples well
    owed, paid = genzo.tax_owed, genzo.tax_paid_7d  # the latest change; this week's payments (not last week's 50)
    assert (owed.rice, owed.coins, paid.rice, paid.coins) == (0, 14, 6, 10)
    assert (genzo.rank, genzo.titles, genzo.standing, genzo.standing_word) == (2, [], 50, "well regarded")
    assert (genzo.trade_partners_7d, genzo.people_known, genzo.places_known) == (1, 2, 3)
    assert [(bond.name, bond.value) for bond in genzo.bonds_top3] == [("Aiko", 70), ("Ama", 10), ("Fumiko", 5)]
    assert genzo.skill_hours == {"farming": 2.0}
    assert genzo.ambition is not None and (genzo.ambition.progress, genzo.ambition.done) == (55, False)  # 10 % + 100 %

    fumiko = rows["fumiko"]
    assert (fumiko.wealth_mon, fumiko.income_24h, fumiko.spent_24h) == (500 + 2 * 25, 4, 0)
    assert (fumiko.trade_partners_7d, fumiko.skill_hours, fumiko.wellbeing_24h) == (2, {"trade": 1.0}, 100)
    assert (fumiko.standing_word, fumiko.ambition is not None and fumiko.ambition.done) == ("honoured", True)
    assert [(bond.name, bond.value) for bond in fumiko.bonds_top3] == [("Genzo", 5)]  # warm bonds only

    ama = rows["ama"]
    assert (ama.wealth_mon, ama.titles, ama.rank, ama.skill_hours) == (5 + 6, ["leader"], 4, {"gathering": 0.5})
    assert (ama.wellbeing_24h, ama.tax_owed.coins, ama.trade_partners_7d) == (None, 0, 1)  # no samples, no dues
    assert (ama.standing, ama.standing_word) == (76, "honoured")  # with her own band
    assert rows["dead"].alive is False


def test_groups_money_supply_and_the_stall(sim_world: SimWorld) -> None:
    board = _board(sim_world)
    groups = {group.group: group for group in board.groups}
    town = groups["town"]
    assert (town.alive, town.wealth_mon, town.gini_wealth) == (4, 550 + 100 + 80 + 0, 0.572)
    assert (groups["band_a"].deeds_7d, groups["band_a"].caught_7d) == (1, 1)
    assert (town.deeds_7d, town.caught_7d, groups["band_b"].alive) == (0, 0, 0)
    assert (board.money_supply, board.money_supply_ok) == (3000, True)
    assert _board(sim_world, treasury=2367).money_supply_ok is False

    (stall,) = board.stalls
    goods = {good.item: good for good in stall.goods}
    assert (stall.id, stall.keeper, stall.trading) == ("market-stall", "Fumiko", True)
    assert goods["rice"].model_dump() == {"item": "rice", "stock": 120, "lot": 2, "sell": 4, "buy": 3, "word": "fair"}
    assert (goods["gold"].stock, goods["gold"].word) == (0, "dear")  # none in stock: twice its value
    assert _board(sim_world, trading=False).stalls[0].trading is False


def test_gini() -> None:
    assert gini([]) == 0.0
    assert gini([0, 0]) == 0.0
    assert gini([5, 5, 5]) == 0.0
    assert gini([0, 0, 0, 100]) == 0.75
    assert gini([550, 100, 80]) == pytest.approx(0.429, abs=0.001)


def _live_board(sim: Simulation, events: list[EventDraft]) -> dict[str, CitizenScore]:
    facts = Facts(tick=sim.tick, state=from_snapshot(take_snapshot(sim.state)), events=[record_of(e) for e in events])
    board = score_board(facts, [], SOCIETY.of(sim.state).bonds, sim.world)
    return {row.id: row for row in board.citizens}


def test_after_a_sale_the_seller_s_coins_and_income_change(new_sim: Callable[..., Simulation]) -> None:
    """The critic's check (10 §7): a sale at the stall shows on both sides' rows at once."""
    sim = without_animals(new_sim(seed=3))
    sim.stock_store("market-stall", "hide", 6)
    behind_the_stall, before_it = (20.0, 52.2), (20.0, 56.0)
    merchant = {"home": "main-e-2", "skills": ["trade"], "inventory": {"coins": 100}}
    sim.add_citizen(make_spec("fumiko", name="Fumiko", at=behind_the_stall, **merchant))
    sim.add_citizen(make_spec("goro", name="Goro", at=before_it, inventory={"hide": 2}))
    sim.start("fumiko", Work(task="trade"))
    events = sim.drain()
    before = _live_board(sim, events)
    assert sim.instant("goro", Sell(item="hides", amount=1)).outcome == "done"
    events += sim.drain()
    after = _live_board(sim, events)
    paid = after["goro"].coins - before["goro"].coins
    assert paid > 0 and after["goro"].income_24h == before["goro"].income_24h + paid
    assert (after["fumiko"].coins, after["fumiko"].spent_24h) == (100 - paid, paid)
    assert (after["goro"].trade_partners_7d, after["fumiko"].trade_partners_7d) == (1, 1)
    hide = 15  # a hide's town value: carried wealth falls by it while the coins come in
    assert after["goro"].wealth_mon == before["goro"].wealth_mon - hide + paid
