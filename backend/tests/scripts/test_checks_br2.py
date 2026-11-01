"""BR2's run checks: band hunger deaths fail, band A's trading days count over the seeds, outings past the ring."""

from collections.abc import Callable

from app.observability.events import Died, EventDraft, EventType, Payload, Traded
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from scripts.checks import CHECKS, br2
from scripts.checks.base import Outcome
from tests.sim_helpers import make_spec


def _event(sim: Simulation, kind: EventType, who: str, payload: Payload) -> EventDraft:
    return EventDraft(0, sim.tick, kind, "citizen", who, None, None, "public", None, payload)


def _band(sim: Simulation, who: str, region: str) -> str:
    camp = f"{region}_camp"
    return sim.add_citizen(make_spec(who, site=camp, at=(0.0, 6.0), home=f"{camp}:shelter-n", region=region)).id


def test_a_band_member_dead_of_hunger_fails_but_a_town_death_or_a_bite_doesn_t(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    lia, goro = _band(sim, "lia", "band_a"), sim.add_citizen(make_spec("goro")).id
    check = br2.BandHunger()
    check.start(sim)
    check.after_step(sim, [_event(sim, "died", goro, Died(cause="starvation"))])
    check.after_step(sim, [_event(sim, "died", lia, Died(cause="animal attack", attacker="lion:1"))])
    assert check.outcome(sim).ok
    check.after_step(sim, [_event(sim, "died", lia, Died(cause="dehydration"))])
    assert not check.outcome(sim).ok and "lia" in check.outcome(sim).words


def test_band_a_trading_days_count_once_a_day_and_add_up_over_the_seeds(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    ama, nim = _band(sim, "ama", "band_a"), _band(sim, "nim", "band_b")
    check = br2.TradeTrips()
    check.start(sim)
    sale = Traded(item="hide", count=1, lots=1, coins=11, stall="market-stall", merchant="fumiko")
    check.after_step(sim, [_event(sim, "sold", ama, sale), _event(sim, "sold", ama, sale)])
    check.after_step(sim, [_event(sim, "sold", nim, sale), _event(sim, "bought", ama, sale)])
    sim.state.tick = DAY_MINUTES * 4
    check.after_step(sim, [_event(sim, "sold", ama, sale)])
    assert check.outcome(sim).value == 2
    assert br2.TradeTrips.overall({1: Outcome(3, True, ""), 7: Outcome(3, True, "")}).ok
    assert not br2.TradeTrips.overall({1: Outcome(3, True, ""), 7: Outcome(2, True, "")}).ok


def test_a_day_with_nobody_out_at_a_far_hotspot_counts_against_the_band(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    _band(sim, "suna", "band_a")
    check = br2.Outings()
    check.start(sim)
    sim.state.tick = DAY_MINUTES * br2.OUTINGS_FROM_DAY
    check.after_step(sim, [])  # the last minute of the day before: not counted
    assert check.outcome(sim).value == 0
    sim.state.tick += 10
    check.after_step(sim, [])  # everyone at camp
    assert check.outcome(sim).value == 2  # neither band was out that day
    far = next(c for c, r in check.far["band_a"])
    sim.core.place_at(sim.citizen("suna"), far)
    check.after_step(sim, [])
    assert check.outcome(sim).value == 1  # band A was
    assert {c.name for c in CHECKS} >= {"br2.outings", "br2.trade_trips", "br2.band_hunger"}


def test_band_b_deeds_need_six_one_seen_and_judged_and_one_unseen(new_sim: Callable[..., Simulation]) -> None:
    from app.observability.events import Judged, Trespassed

    sim = new_sim()
    kaz, nim, goro = _band(sim, "kaz", "band_b"), _band(sim, "nim", "band_b"), sim.add_citizen(make_spec("goro")).id
    check = br2.BandBDeeds()
    check.start(sim)
    seen = Trespassed(kind="walls", owner="town", place="the castle town", witnesses=[goro])
    unseen = Trespassed(kind="ground", owner="town", place="the Lord's woods")
    mates = Trespassed(kind="walls", owner="town", place="the castle town", witnesses=[nim])  # only a fellow raider
    check.after_step(sim, [_event(sim, "trespassed", kaz, seen), _event(sim, "trespassed", kaz, unseen)])
    check.after_step(sim, [_event(sim, "trespassed", kaz, mates)])
    check.after_step(sim, [_event(sim, "judged", "masanori", Judged(person=kaz, sentence="fine", fine_mon=5))])
    one = check.outcome(sim)
    assert (one.value, one.judged, one.unseen) == (3, 1, 2)
    assert not br2.BandBDeeds.overall({1: one}).ok  # only 3 deeds
    assert br2.BandBDeeds.overall({1: one, 7: br2.DeedsSeen(4, True, "", 0, 4)}).ok
    assert not br2.BandBDeeds.overall({1: br2.DeedsSeen(6, True, "", 0, 6)}).ok  # none judged


def test_band_b_gold_days_count_its_gold_sales_and_pans_once_a_day(new_sim: Callable[..., Simulation]) -> None:
    from app.observability.events import ItemLocation, ItemMoved

    sim = new_sim()
    nim, ama = _band(sim, "nim", "band_b"), _band(sim, "ama", "band_a")
    check = br2.GoldTrips()
    check.start(sim)
    gold = Traded(item="gold", count=1, lots=1, coins=40, stall="market-stall", merchant="fumiko")
    hide = Traded(item="hide", count=1, lots=1, coins=11, stall="market-stall", merchant="fumiko")
    check.after_step(sim, [_event(sim, "sold", ama, gold), _event(sim, "sold", nim, hide)])  # band A's, or no gold
    assert check.outcome(sim).value == 0
    check.after_step(sim, [_event(sim, "sold", nim, gold), _event(sim, "sold", nim, gold)])
    sim.state.tick = DAY_MINUTES
    panned = ItemMoved(
        item="gold",
        count=1,
        source=ItemLocation(kind="resource", id="gold:1"),
        destination=ItemLocation(kind="inventory", id=nim),
    )
    check.after_step(sim, [_event(sim, "item_moved", nim, panned)])
    assert check.outcome(sim).value == 2
