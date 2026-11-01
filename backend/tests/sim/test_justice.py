"""Justice (10-world-v1 §3.4): accuse, seize, custody (held, the gaol, tied at the fire), judge with a fine or
confinement, and tend. The chains are scripted scenes: the thief, the witness, the officer and the judge are placed
and act through the contract, and the whole chain runs in a few game hours."""

from collections.abc import Callable
from typing import Any

import pytest

from app.observability.events import (
    Accused,
    Confined,
    EventDraft,
    ItemMoved,
    Judged,
    Released,
    Seized,
    SentenceServed,
    StandingChanged,
    Stole,
    TaxChange,
    Tended,
    Trespassed,
)
from app.observability.lines import Resident, Told, namer, tell
from app.sim import justice, slots, society, tax
from app.sim.clock import START_MINUTE, TICKS_PER_HOUR, sun_altitude_deg, sun_direction
from app.sim.coins import number_words
from app.sim.custody import CUSTODY, CUSTODY_HOURS, Custody, custody_ends, custody_of, in_custody
from app.sim.economy import coins_held
from app.sim.justice import JUSTICE
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.sim.vec import step_towards
from app.world_api.facade import ActionHandle, WorldApi, run_until_done
from app.world_api.models import ActionResult, Confinement, Fine
from tests.sim_helpers import make_spec, without_animals

PLACES = ["town", "well", "main-gate", "west-gate", "castle", "gaol", "storehouses", "rice-fields"]
CAMP_B = {"region": "band_b", "home": "band_b_camp:shelter-e", "knows_places": ["band_b_camp", *PLACES]}
RACK = (-106.5, 36.0)  # beside field-rack-1, farmhouse-1's hasa rack outside the west wall
COURT = (-9.0, -15.0)  # inside the castle walls, before the gaol's pen
LORD = {"titles": ["lord"], "rank": 5, "age": 55, "home": "castle-keep", "skills": ["governing", "arms"]}
ASHIGARU = {"titles": ["ashigaru"], "rank": 3, "age": 22, "home": "cross-s-1", "skills": ["arms"]}
SAMURAI = {"titles": ["samurai"], "rank": 4, "age": 34, "home": "castle-keep", "skills": ["arms"]}
CAST = ["kaz", "genzo", "goro", "masanori", "kenji", "tokuji", "ennen", "pip", "barro", "nim", "tek"]


def _scene(new_sim: Callable[..., Simulation], **people: dict[str, Any]) -> Simulation:
    """Each person by id with their fields; everyone knows everyone by name."""
    sim = without_animals(new_sim(seed=17))
    for citizen_id, fields in people.items():
        spec = {"knows_places": PLACES, "knows_people": CAST} | fields
        sim.add_citizen(make_spec(citizen_id, **spec))
    sim.drain()
    return sim


def _of[T](events: list[EventDraft], kind: type[T]) -> list[tuple[str | None, T]]:
    return [(event.actor_id, event.payload) for event in events if isinstance(event.payload, kind)]


def _done(sim: Simulation, handle: ActionHandle | ActionResult, ticks: int = 30) -> ActionResult:
    return handle if isinstance(handle, ActionResult) else run_until_done(sim, handle, ticks)


def _distance(sim: Simulation, a: str, b: str) -> float:
    return sim.core.distance_m(sim.citizen(a).position, sim.citizen(b).position)


def _seize(sim: Simulation, seizer: str, person: str, monkeypatch: pytest.MonkeyPatch) -> ActionResult:
    """The seizer walks up to the person and seizes them (every seizure holds)."""
    monkeypatch.setattr(justice, "seize_chance", lambda *_: 1.0)
    me = WorldApi(sim, seizer)
    if _distance(sim, seizer, person) > justice.SEIZE_REACH_M:
        assert _done(sim, me.walk_to_person(person.capitalize())).outcome == "done"
    return _done(sim, me.seize(person.capitalize()), 5)


def _lead_to_gaol(sim: Simulation, seizer: str, person: str) -> tuple[list[EventDraft], float]:
    """The seizer walks to the gaol with the held person: the events, and the farthest the held one was from them at
    any tick's end while held."""
    walk = WorldApi(sim, seizer).walk_to_place("gaol")
    events: list[EventDraft] = []
    farthest = 0.0
    for _ in range(40):
        sim.step()
        events += sim.drain()
        custody = custody_of(sim.core, person)
        if custody is not None and custody.keeper is not None:
            farthest = max(farthest, _distance(sim, seizer, person))
        if walk.done and custody is not None and custody.place == "gaol":
            break
    return events, farthest


def _theft_scene(new_sim: Callable[..., Simulation]) -> Simulation:
    sim = _scene(
        new_sim,
        kaz={**CAMP_B, "age": 19, "at": RACK, "inventory": {"coins": 40}},
        genzo={"home": "farmhouse-1", "at": (-104.0, 40.0), "skills": ["farming"]},
        goro={**ASHIGARU, "at": (-103.0, 33.0)},
        masanori={**LORD, "at": COURT},
    )
    sim.stock_store("field-rack-1", "rice", 40)
    sim.citizen("masanori").in_view.discard("kaz")  # the lord, over a hundred metres off in the castle, misses it
    sim.drain()
    return sim


def test_theft_witness_accuse_seize_judge_fine_and_served(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    money = coins_held(sim.state)
    took = WorldApi(sim, "kaz").pick_up("5 rice")
    assert took.outcome == "done"
    events = sim.drain()
    [stole] = [event for event in events if event.type == "stole"]
    [(thief, theft)] = _of(events, Stole)
    assert thief == "kaz" and set(theft.witnesses) >= {"genzo", "goro"}

    told = WorldApi(sim, "genzo").accuse("Kaz", "Goro")
    assert told == ActionResult(action="accuse", outcome="done", text='You tell Goro: "Kaz stole rice from the rack."')
    assert _of(sim.drain(), Accused) == [("genzo", Accused(person="kaz", to="goro", deeds=[stole.seq]))]

    seized = _seize(sim, "goro", "kaz", monkeypatch)
    assert seized.text == "You seize Kaz; you hold them fast."
    assert custody_of(sim.core, "kaz") is not None

    events, farthest = _lead_to_gaol(sim, "goro", "kaz")
    assert 0 < farthest <= 3.0  # led, never more than 3 m behind
    assert _of(events, Confined) == [
        ("kaz", Confined(place="the gaol", until_tick=_custody_end(sim, "kaz"), by="goro"))
    ]

    accused = WorldApi(sim, "goro").accuse("Kaz", "Masanori")
    assert accused.outcome == "done", accused.text
    rack_owner_before = sim.state.stores.get("farmhouse-1-chest", {}).get("coins", 0)
    treasury_before = sim.state.stores.get("castle-keep-chest", {}).get("coins", 0)
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"
    sim.drain()
    judged = _done(sim, lord.judge("Kaz", Fine(mon=20)), 20)
    assert judged.text == "You fine Kaz twenty coins; it is paid."
    events = sim.drain()
    [(judge, verdict)] = _of(events, Judged)
    assert judge == "masanori"
    assert verdict == Judged(person="kaz", sentence="fine", fine_mon=20, deeds=[stole.seq])
    # the robbed household first: five rice at two mon each; the rest to the treasury
    assert sim.state.stores["farmhouse-1-chest"]["coins"] - rack_owner_before == 10
    assert sim.state.stores["castle-keep-chest"]["coins"] - treasury_before == 10
    assert sim.citizen("kaz").inventory["coins"] == 20
    assert [type(e.payload).__name__ for e in events if e.type in ("sentence_served", "released")] == [
        "SentenceServed",
        "Released",
    ]
    assert _of(events, Released) == [("kaz", Released(cause="judged", by="masanori"))]
    assert not in_custody(sim.core, "kaz")
    assert coins_held(sim.state) == money
    assert ("goro", "town", "accusation") in [
        (actor, change.group, change.cause) for actor, change in _of(events, StandingChanged)
    ]
    walk = _done(sim, WorldApi(sim, "kaz").walk_to_place("castle"), 3)  # free again
    assert walk.text != "Goro holds you fast."


def _custody_end(sim: Simulation, person: str) -> int:
    custody = custody_of(sim.core, person)
    assert custody is not None
    return custody_ends(custody)


# --- the night law, the gaol and the dawn ---


def _at(minute: int, day: int = 0) -> int:
    """The tick at this minute of the town's clock on that day (day 0 starts at 08:00)."""
    return day * 24 * 60 + minute - START_MINUTE


def test_night_trespass_seize_confine_and_served_at_dawn(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = without_animals(new_sim(seed=17))
    sim.state.tick = _at(23 * 60)
    for citizen_id, fields in {
        "kaz": {**CAMP_B, "age": 19, "at": (-30.0, 50.0)},
        "goro": {**ASHIGARU, "at": (-31.5, 50.0)},
        "masanori": {**LORD, "at": COURT},
    }.items():
        sim.add_citizen(make_spec(citizen_id, **({"knows_places": PLACES, "knows_people": CAST} | fields)))
    sim.drain()
    sim.run(2)
    [(_, trespass)] = [(a, t) for a, t in _of(sim.drain(), Trespassed)]
    assert trespass.kind == "walls" and trespass.witnesses == ["goro"]

    _seize(sim, "goro", "kaz", monkeypatch)
    events, farthest = _lead_to_gaol(sim, "goro", "kaz")
    assert farthest <= 3.0
    assert custody_of(sim.core, "kaz") is not None
    assert [t.kind for a, t in _of(events, Trespassed) if a == "kaz"] == []  # led into the castle: no entry of his
    assert WorldApi(sim, "goro").accuse("Kaz", "Masanori").outcome == "done"
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"
    dawn = next(t for t in range(sim.tick, sim.tick + 12 * TICKS_PER_HOUR) if _sun(sim, t))
    hours = -(-(dawn - sim.tick - justice.JUDGE_MINUTES) // TICKS_PER_HOUR)
    sentence = _done(sim, lord.judge("Kaz", Confinement(hours=hours)), 20)
    assert sentence.text == f"You sentence Kaz to {number_words(hours)} hours confined."  # words, never digits
    custody = custody_of(sim.core, "kaz")
    assert custody is not None and custody.place == "gaol" and custody.judgement is not None
    events = []
    while in_custody(sim.core, "kaz"):
        sim.step()
        events += sim.drain()
    assert _of(events, SentenceServed) == [("kaz", SentenceServed(sentence="confine", judgement=custody.judgement))]
    assert _of(events, Released) == [("kaz", Released(cause="judged"))]
    assert dawn <= sim.tick < dawn + TICKS_PER_HOUR  # served at dawn
    assert sim.tick - custody.since <= CUSTODY_HOURS * TICKS_PER_HOUR
    sim.run(3)
    assert [a for a, _ in _of(events + sim.drain(), Trespassed)] == []  # walking free inside: no new entry


def _sun(sim: Simulation, tick: int) -> bool:
    """The sun is up at the gaol at this tick."""
    return sun_altitude_deg(sim.world.places["gaol"].centre, sun_direction(tick, sim.world.town_lon_deg)) > 0


# --- tax arrears, and no judgement without grounds ---


def _arrears(sim: Simulation, household: str, coins: int, days: int = 3) -> None:
    owed = tax.account(sim.core, household)
    owed.coins, owed.arrears, owed.days = coins, coins, days


def _court_scene(new_sim: Callable[..., Simulation], **more: dict[str, Any]) -> Simulation:
    """Tokuji held by Kenji at the castle's court before the lord."""
    return _scene(
        new_sim,
        masanori={**LORD, "at": COURT},
        kenji={**SAMURAI, "at": (-8.0, -13.0)},
        tokuji={"home": "farmhouse-2", "age": 58, "at": (-7.5, -14.5), "inventory": {"coins": 20}},
        **more,
    )


def test_tax_arrears_are_fined_into_the_treasury_and_clear_the_account(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _court_scene(new_sim)
    _arrears(sim, "farmhouse-2", 12)
    money, treasury = coins_held(sim.state), sim.state.stores.get("castle-keep-chest", {}).get("coins", 0)
    _seize(sim, "kenji", "tokuji", monkeypatch)
    judged = _done(sim, WorldApi(sim, "masanori").judge("Tokuji", Fine(mon=12)), 20)
    assert judged.text == "You fine Tokuji twelve coins; it is paid."
    events = sim.drain()
    assert _of(events, Judged) == [("masanori", Judged(person="tokuji", sentence="fine", fine_mon=12, arrears=True))]
    [(payer, paid)] = _of(events, TaxChange)
    assert payer == "tokuji" and (paid.household, paid.coins, paid.rice, paid.owed_coins) == ("farmhouse-2", 12, 0, 0)
    assert tax.account(sim.core, "farmhouse-2").days == 0
    assert sim.state.stores["castle-keep-chest"]["coins"] - treasury == 12
    assert coins_held(sim.state) == money and not in_custody(sim.core, "tokuji")


def test_nobody_is_judged_without_a_known_deed_or_arrears(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _court_scene(new_sim)
    _arrears(sim, "farmhouse-2", 12, days=0)  # owed, but not yet overdue
    _seize(sim, "kenji", "tokuji", monkeypatch)
    lord = WorldApi(sim, "masanori")
    for sentence in (Fine(mon=5), Confinement(hours=2)):
        refused = _done(sim, lord.judge("Tokuji", sentence), 20)
        assert (refused.outcome, refused.text) == ("failed", "You know of no wrong done by Tokuji.")
    _arrears(sim, "farmhouse-2", 12, days=justice.ARREARS_DAYS)
    confined = _done(sim, lord.judge("Tokuji", Confinement(hours=2)), 20)
    assert confined.text == "Tax owed is paid in coin or rice, not in confinement."
    assert _of(sim.drain(), Judged) == []


@pytest.mark.parametrize(("days", "fined"), [(2, False), (3, True)])
def test_overdue_tax_is_fined_only_after_three_days(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch, days: int, fined: bool
) -> None:
    sim = _court_scene(new_sim)
    _arrears(sim, "farmhouse-2", 12, days=days)
    _seize(sim, "kenji", "tokuji", monkeypatch)
    judged = _done(sim, WorldApi(sim, "masanori").judge("Tokuji", Fine(mon=12)), 20)
    assert (judged.outcome == "done") == fined
    assert judged.text == (
        "You fine Tokuji twelve coins; it is paid." if fined else "You know of no wrong done by Tokuji."
    )


def test_a_judged_deed_is_never_judged_twice(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    sim.citizen("masanori").in_view.add("kaz")  # the lord sees it himself
    WorldApi(sim, "kaz").pick_up("5 rice")
    _seize(sim, "goro", "kaz", monkeypatch)
    _lead_to_gaol(sim, "goro", "kaz")
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"
    assert _done(sim, lord.judge("Kaz", Fine(mon=8)), 20).text == "You fine Kaz eight coins; it is paid."
    assert sim.citizen("kaz").inventory["coins"] == 32
    _seize(sim, "goro", "kaz", monkeypatch)
    again = _done(sim, lord.judge("Kaz", Fine(mon=8)), 20)
    assert again.text == "You know of no wrong done by Kaz." and sim.citizen("kaz").inventory["coins"] == 32


def test_only_the_lord_inside_the_castle_walls_judges_in_town(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _court_scene(new_sim, genzo={"home": "farmhouse-1", "at": (-9.0, -12.0)})
    _arrears(sim, "farmhouse-2", 12)
    _seize(sim, "kenji", "tokuji", monkeypatch)
    assert _done(sim, WorldApi(sim, "genzo").judge("Tokuji", Fine(mon=5))).text == "You have no right to judge anyone."
    assert _done(sim, WorldApi(sim, "kenji").judge("Tokuji", Fine(mon=5))).text == "You have no right to judge anyone."
    lord = sim.citizen("masanori")
    sim.core.place_at(lord, sim.world.town.to_unit(-8.0, 31.0))  # just outside the castle gate
    sim.core.place_at(sim.citizen("tokuji"), sim.world.town.to_unit(-8.0, 33.0))
    refused = _done(sim, WorldApi(sim, "masanori").judge("Tokuji", Fine(mon=5)))
    assert refused.text == "You judge inside the castle walls."


# --- custody: 12 hours at most, fines paid short ---


def test_custody_never_outlasts_twelve_hours(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    _seize(sim, "goro", "kaz", monkeypatch)
    _lead_to_gaol(sim, "goro", "kaz")
    custody = custody_of(sim.core, "kaz")
    assert custody is not None and custody.place == "gaol"
    sim.state.tick = custody.since + 12 * TICKS_PER_HOUR - 2
    sim.drain()
    sim.step()
    assert in_custody(sim.core, "kaz")
    sim.step()
    assert _of(sim.drain(), Released) == [("kaz", Released(cause="timeout"))]
    assert sim.tick == custody.since + 12 * TICKS_PER_HOUR
    assert _done(sim, WorldApi(sim, "kaz").walk_to_place("castle"), 1).text != "You are confined in the gaol."


def test_a_confinement_ends_when_the_custody_s_twelve_hours_do(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    sim.citizen("masanori").in_view.add("kaz")
    WorldApi(sim, "kaz").pick_up("5 rice")
    _seize(sim, "goro", "kaz", monkeypatch)
    _lead_to_gaol(sim, "goro", "kaz")
    custody = custody_of(sim.core, "kaz")
    assert custody is not None
    sim.state.tick = custody.since + 10 * TICKS_PER_HOUR
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"
    assert _done(sim, lord.judge("Kaz", Confinement(hours=12)), 20).outcome == "done"
    assert custody_ends(custody) == custody.since + 12 * TICKS_PER_HOUR  # not 12 h from the judgement
    sim.drain()
    while in_custody(sim.core, "kaz"):
        sim.step()
    assert sim.tick == custody.since + 12 * TICKS_PER_HOUR
    events = sim.drain()
    assert _of(events, SentenceServed) == [("kaz", SentenceServed(sentence="confine", judgement=custody.judgement))]
    assert _of(events, Released) == [("kaz", Released(cause="judged"))]


def test_a_fine_paid_short_keeps_them_held_and_leaves_the_deed_open_to_confinement(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    kaz = sim.citizen("kaz")
    kaz.inventory["coins"] = 3
    sim.citizen("masanori").in_view.add("kaz")
    WorldApi(sim, "kaz").pick_up("5 rice")
    _seize(sim, "goro", "kaz", monkeypatch)
    _lead_to_gaol(sim, "goro", "kaz")
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"
    sim.drain()
    short = _done(sim, lord.judge("Kaz", Fine(mon=50)), 20)
    assert short.text == "You fine Kaz fifty coins; they can pay only thirteen coins."  # 3 coins and 5 rice
    assert kaz.inventory == {}
    events = sim.drain()
    assert _of(events, SentenceServed) == [] and _of(events, Released) == []
    assert in_custody(sim.core, "kaz")
    assert _done(sim, lord.judge("Kaz", Confinement(hours=6)), 20).text == "You sentence Kaz to six hours confined."
    [(_, verdict)] = _of(sim.drain(), Judged)
    assert verdict.sentence == "confine" and len(verdict.deeds) == 1


def test_a_victim_paid_in_part_is_paid_only_the_rest_by_the_next_fine(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    sim.citizen("masanori").in_view.add("kaz")
    WorldApi(sim, "kaz").pick_up("5 rice")  # ten mon of rice from farmhouse-1's rack
    kaz = sim.citizen("kaz")
    kaz.inventory = {"coins": 6}
    _seize(sim, "goro", "kaz", monkeypatch)
    _lead_to_gaol(sim, "goro", "kaz")
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"

    def coins(store: str) -> int:
        return sim.state.stores.get(store, {}).get("coins", 0)

    chest, treasury = coins("farmhouse-1-chest"), coins("castle-keep-chest")
    assert _done(sim, lord.judge("Kaz", Fine(mon=50)), 20).text.endswith("they can pay only six coins.")
    assert (coins("farmhouse-1-chest") - chest, coins("castle-keep-chest") - treasury) == (6, 0)
    kaz.inventory["coins"] = 20
    assert _done(sim, lord.judge("Kaz", Fine(mon=20)), 20).text.endswith("it is paid.")
    assert (coins("farmhouse-1-chest") - chest, coins("castle-keep-chest") - treasury) == (10, 16)


def test_a_fine_takes_the_purse_then_the_household_chest_then_goods(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _court_scene(new_sim)
    tokuji = sim.citizen("tokuji")
    tokuji.inventory = {"coins": 5, "dried meat": 4}
    sim.stock_store("farmhouse-2-chest", "coins", 10)
    sim.stock_store("farmhouse-2-chest", "rice", 30)
    _arrears(sim, "farmhouse-2", 40)
    _seize(sim, "kenji", "tokuji", monkeypatch)
    sim.drain()
    assert _done(sim, WorldApi(sim, "masanori").judge("Tokuji", Fine(mon=20)), 20).text.endswith("it is paid.")
    moved = [(m.item, m.count, m.source.id) for _, m in _of(sim.drain(), ItemMoved)]
    assert moved == [("coins", 5, "tokuji"), ("coins", 10, "farmhouse-2-chest"), ("dried meat", 2, "tokuji")]
    assert sim.state.stores["farmhouse-2-chest"]["rice"] == 30


# --- seize ---


@pytest.mark.parametrize(
    ("seizer", "target", "helpers", "chance"),
    [
        ({"skills": ["arms"]}, {}, 0, 0.8),  # armed young adults: 0.5 + 0.3
        ({}, {"skills": ["arms"]}, 0, 0.2),
        ({}, {}, 0, 0.5),
        ({"inventory": {"flint spear": 1}}, {}, 1, 1.0 - 0.05),  # a spear arms them; a helper: clamped at 0.95
        ({"age": 60}, {"inventory": {"iron spear": 1}}, 0, 0.1),  # an elder (0.5) on a spearman: clamped at 0.1
        ({"age": 40}, {"age": 15}, 1, 0.5 + 0.3 * 0.2 + 0.2),  # strength 0.9 vs a teen's 0.7, a helper
    ],
)
def test_the_seize_chance_follows_arms_strength_and_helpers(
    new_sim: Callable[..., Simulation], seizer: dict[str, Any], target: dict[str, Any], helpers: int, chance: float
) -> None:
    sim = _scene(new_sim, a={"at": (-30.0, 50.0), **seizer}, b={"at": (-31.0, 50.0), **target})
    assert justice.seize_chance(sim.citizen("a"), sim.citizen("b"), helpers) == pytest.approx(chance)


def test_armed_helpers_of_the_seizer_s_group_near_the_target_count(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        goro={**ASHIGARU, "at": (-30.0, 50.0)},
        kaz={**CAMP_B, "at": (-31.0, 50.0)},
        kenji={**SAMURAI, "at": (-32.5, 50.0)},  # armed, 1.5 m from Kaz
        genzo={"home": "farmhouse-1", "at": (-31.0, 51.5)},  # unarmed
        tek={"region": "band_a", "home": "band_a_camp:shelter-e", "at": (-31.0, 48.5), "skills": ["arms"]},
        masanori={**LORD, "at": (-40.0, 50.0)},  # armed but 9 m off
    )
    assert justice._helpers(sim.core, sim.citizen("goro"), sim.citizen("kaz")) == ["kenji"]


def test_children_can_t_be_seized(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, goro={**ASHIGARU, "at": (-30.0, 50.0)}, pip={**CAMP_B, "age": 7, "at": (-31.0, 50.0)})
    refused = _done(sim, WorldApi(sim, "goro").seize("Pip"), 3)
    assert (refused.outcome, refused.text) == ("failed", "You can't seize a child.")
    assert _of(sim.drain(), Seized) == []


def test_a_failed_seizure_interrupts_the_target_who_stays_free(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _scene(new_sim, goro={**ASHIGARU, "at": (-30.0, 50.0)}, kaz={**CAMP_B, "at": (-31.0, 50.0)})
    resting = WorldApi(sim, "kaz").rest(30)
    monkeypatch.setattr(justice, "seize_chance", lambda *_: 0.0)
    failed = _done(sim, WorldApi(sim, "goro").seize("Kaz"), 3)
    assert (failed.outcome, failed.text) == ("failed", "Kaz twists free of your grip.")
    assert resting.result is not None and resting.result.text == "Goro tries to seize you!"
    assert _of(sim.drain(), Seized) == [("goro", Seized(person="kaz", held=False))]
    assert not in_custody(sim.core, "kaz")


def test_a_seizure_holds_by_its_roll(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _scene(new_sim, goro={**ASHIGARU, "at": (-30.0, 50.0)}, kaz={**CAMP_B, "at": (-31.0, 50.0)})
    monkeypatch.setattr(justice, "seize_chance", lambda *_: 0.5)
    rolls = iter([0.49, 0.5])  # under the chance holds; the chance itself doesn't
    monkeypatch.setattr(type(sim.state.rng("justice.seize")), "random", lambda _self: next(rolls))
    assert _done(sim, WorldApi(sim, "goro").seize("Kaz"), 3).outcome == "done"
    _release_now(sim, "kaz")
    assert _done(sim, WorldApi(sim, "goro").seize("Kaz"), 3).outcome == "failed"


def _release_now(sim: Simulation, person: str) -> None:
    CUSTODY.of(sim.state).pop(person)


@pytest.mark.parametrize("down", ["hurt", "asleep", "dead"])
def test_the_held_go_free_when_the_seizer_is_down(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch, down: str
) -> None:
    sim = _scene(new_sim, goro={**ASHIGARU, "at": (-30.0, 50.0)}, kaz={**CAMP_B, "at": (-31.0, 50.0)})
    _seize(sim, "goro", "kaz", monkeypatch)
    sim.step()
    assert in_custody(sim.core, "kaz")
    goro = sim.citizen("goro")
    sim.drain()
    if down == "hurt":
        sim.core.injure(goro, 5.0, "violence", "someone strikes you")
    elif down == "asleep":
        goro.body.asleep = True
    else:
        sim.core.die(goro, "violence")
    justice.keep_custody(sim.core)  # the hook, in the tick that hurt them
    assert _of(sim.drain(), Released) == [("kaz", Released(cause="seizer_down", by="goro"))]
    assert not in_custody(sim.core, "kaz")


def test_a_seizer_seized_lets_their_prisoner_go(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _scene(
        new_sim,
        goro={**ASHIGARU, "at": (-30.0, 50.0)},
        kaz={**CAMP_B, "at": (-31.0, 50.0)},
        barro={**CAMP_B, "at": (-29.0, 50.0)},
    )
    _seize(sim, "goro", "kaz", monkeypatch)
    sim.drain()
    sim.core.place_at(sim.citizen("barro"), sim.world.town.to_unit(-29.5, 51.0))
    _seize(sim, "barro", "goro", monkeypatch)
    assert _of(sim.drain(), Released) == [("kaz", Released(cause="seizer_down", by="goro"))]
    assert not in_custody(sim.core, "kaz") and in_custody(sim.core, "goro")


def test_a_seizer_in_custody_holds_nobody(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _scene(new_sim, goro={**ASHIGARU, "at": (-30.0, 50.0)}, kaz={**CAMP_B, "at": (-31.0, 50.0)})
    _seize(sim, "goro", "kaz", monkeypatch)
    CUSTODY.of(sim.state)["goro"] = Custody(since=sim.tick, keeper=None, place="gaol")
    sim.drain()
    justice.keep_custody(sim.core)
    assert ("kaz", Released(cause="seizer_down", by="goro")) in _of(sim.drain(), Released)


def test_a_death_in_custody_ends_it_with_one_release(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _scene(new_sim, goro={**ASHIGARU, "at": (-30.0, 50.0)}, kaz={**CAMP_B, "at": (-31.0, 50.0)})
    _seize(sim, "goro", "kaz", monkeypatch)
    sim.drain()
    sim.core.die(sim.citizen("kaz"), "thirst")
    sim.step()
    assert _of(sim.drain(), Released) == [("kaz", Released(cause="died"))]
    assert not in_custody(sim.core, "kaz")


def test_a_wrong_done_before_a_witness_s_eyes_stops_what_they_are_doing(new_sim: Callable[..., Simulation]) -> None:
    """A watchman standing a long watch by the racks reacts to a theft at once (Q1: he waited out his quarter hour
    while the thief bundled the rice and left); only the wrong done that minute stops anyone."""
    sim = _theft_scene(new_sim)
    watch = WorldApi(sim, "goro").wait(15)
    sim.step()
    sim.drain()
    assert WorldApi(sim, "kaz").pick_up("5 rice").outcome == "done"
    sim.step()
    sim.drain()
    assert watch.done and watch.result is not None and watch.result.outcome == "interrupted"
    assert watch.result.text == "You stop waiting: Kaz stole rice from the rack!"
    sim.step()
    assert WorldApi(sim, "goro").wait(5).result is None  # an old wrong stops nobody again


def test_the_held_may_only_look_speak_and_wait_and_the_confined_drink_from_the_bucket(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    _seize(sim, "goro", "kaz", monkeypatch)
    kaz = WorldApi(sim, "kaz")
    assert _done(sim, kaz.walk_to_place("well")).text == "Goro holds you fast."
    assert kaz.pick_up("rice").text == "Goro holds you fast."
    assert _done(sim, kaz.drink()).text == "Goro holds you fast."
    assert kaz.say("Let me go!").outcome == "done"
    assert _done(sim, kaz.wait(1), 3).outcome == "done"
    _lead_to_gaol(sim, "goro", "kaz")
    assert _done(sim, kaz.walk_to_place("well")).text == "You are confined in the gaol."
    sim.citizen("kaz").body.thirst = 60.0
    assert _done(sim, kaz.drink(), 10).text != "There's no water within reach."
    assert sim.citizen("kaz").body.thirst < 60.0


def test_the_seizer_leads_at_four_fifths_of_their_pace_with_every_step_drawn(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    def first_step(lead: bool) -> tuple[float, Simulation]:
        sim = _theft_scene(new_sim)
        if lead:
            _seize(sim, "goro", "kaz", monkeypatch)
        else:
            sim.core.place_at(sim.citizen("goro"), sim.citizen("kaz").position)
            sim.core.place_at(sim.citizen("kaz"), sim.world.town.to_unit(-104.0, 60.0))
        WorldApi(sim, "goro").walk_to_place("gaol")
        before = sim.citizen("kaz").position
        sim.step()
        walked = sim.core.strides["goro"].walked
        metres = sum(sim.core.distance_m(a[0], b[0]) for a, b in zip(walked, walked[1:], strict=False))
        if lead:
            led = sim.core.strides["kaz"].walked
            assert led[0][0] == before and led[-1][0] == sim.citizen("kaz").position
            assert [t for _, t in led] == sorted(t for _, t in led)
        return metres, sim

    alone, _ = first_step(lead=False)
    leading, _ = first_step(lead=True)
    assert leading == pytest.approx(0.8 * alone, rel=0.02)


# --- the band's fire ---


def _camp_scene(new_sim: Callable[..., Simulation]) -> Simulation:
    camp = {"site": "band_b_camp", "knows_places": ["band_b_camp"], "knows_people": CAST}
    sim = without_animals(new_sim(seed=17))
    people: dict[str, dict[str, Any]] = {
        "barro": {
            **camp,
            "region": "band_b",
            "home": "band_b_camp:shelter-n",
            "titles": ["leader"],
            "rank": 4,
            "at": (1.5, 3.0),
            "skills": ["hunting"],
        },
        "nim": {**camp, "region": "band_b", "home": "band_b_camp:shelter-n", "at": (-2.0, 2.0)},
        "tek": {
            **camp,
            "region": "band_a",
            "home": "band_a_camp:shelter-e",
            "at": (3.0, 5.0),
            "inventory": {"coins": 12},
        },
    }
    for citizen_id, fields in people.items():
        sim.add_citizen(make_spec(citizen_id, **fields))
    sim.stock_store("band_b_camp:drying-rack", "dried meat", 10)
    sim.drain()
    return sim


def test_a_band_leader_judges_by_the_fire_and_the_fine_goes_to_the_band(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _camp_scene(new_sim)
    assert WorldApi(sim, "tek").pick_up("2 dried meat").outcome == "done"  # band B's rack, seen by Barro
    _seize(sim, "barro", "tek", monkeypatch)
    money = coins_held(sim.state)
    assert (
        _done(sim, WorldApi(sim, "barro").judge("Tek", Fine(mon=10)), 20).text == "You fine Tek ten coins; it is paid."
    )
    assert sim.citizen("barro").inventory["coins"] == 10 and sim.citizen("tek").inventory["coins"] == 2
    assert coins_held(sim.state) == money


def test_a_band_court_pays_the_whole_fine_to_the_victim(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _camp_scene(new_sim)
    sim.core.injure(sim.citizen("nim"), 5.0, "violence", "Tek strikes you", attacker="tek")  # seen by Barro
    _seize(sim, "barro", "tek", monkeypatch)
    fined = _done(sim, WorldApi(sim, "barro").judge("Tek", Fine(mon=10)), 20)
    assert fined.text == "You fine Tek ten coins; it is paid."
    assert sim.citizen("nim").inventory.get("coins") == 10 and "coins" not in sim.citizen("barro").inventory


def test_a_band_confines_by_tying_them_at_the_fire(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _camp_scene(new_sim)
    WorldApi(sim, "tek").pick_up("2 dried meat")
    _seize(sim, "barro", "tek", monkeypatch)
    sim.drain()
    assert (
        _done(sim, WorldApi(sim, "barro").judge("Tek", Confinement(hours=1)), 20).text
        == "You sentence Tek to an hour confined."
    )
    [(_, confined)] = _of(sim.drain(), Confined)
    assert confined.place == "the band's fire" and confined.by == "barro"
    assert _done(sim, WorldApi(sim, "tek").walk_to_place("band_b_camp")).text == "You are tied at the fire."
    sim.run(TICKS_PER_HOUR)
    assert not in_custody(sim.core, "tek")


def test_a_leader_away_from_the_fire_can_t_judge(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _camp_scene(new_sim)
    WorldApi(sim, "tek").pick_up("2 dried meat")
    _seize(sim, "barro", "tek", monkeypatch)
    barro = sim.citizen("barro")
    pit = sim.world.structures["band_b_camp:fire-pit"].centre
    sim.core.place_at(barro, step_towards(pit, 90.0, 16.0, sim.world.radius_m))
    sim.core.place_at(sim.citizen("tek"), step_towards(pit, 90.0, 17.5, sim.world.radius_m))
    assert _done(sim, WorldApi(sim, "barro").judge("Tek", Fine(mon=5))).text == "You judge by your band's fire."


# --- accuse ---


def test_an_accusation_needs_a_known_deed_and_an_awake_listener_in_earshot(new_sim: Callable[..., Simulation]) -> None:
    sim = _theft_scene(new_sim)
    genzo = WorldApi(sim, "genzo")
    assert genzo.accuse("Kaz", "Goro").text == "You know of no wrong done by Kaz."
    WorldApi(sim, "kaz").pick_up("5 rice")
    assert genzo.accuse("Kaz", "Masanori").text == "Masanori is too far away to hear you."  # across town
    assert genzo.accuse("Kaz", "Kaz").text == "You can't accuse Kaz before themselves."
    sim.citizen("goro").body.asleep = True
    assert genzo.accuse("Kaz", "Goro").text == "Goro is asleep."
    assert _of(sim.drain(), Accused) == []


def test_the_one_accused_before_hears_it_and_stops_what_they_do(new_sim: Callable[..., Simulation]) -> None:
    sim = _theft_scene(new_sim)
    WorldApi(sim, "kaz").pick_up("5 rice")
    sim.step()  # the theft is old news by the time he sits down
    resting = WorldApi(sim, "goro").rest(30)
    sim.step()
    WorldApi(sim, "genzo").accuse("Kaz", "Goro")
    sim.step()
    assert (
        resting.result is not None
        and resting.result.text == 'You stop resting: Genzo says, "Kaz stole rice from the rack."'
    )
    assert [deed.doer for deed in society.known_deeds(sim.core, "goro")] == ["kaz"]


def test_an_accusation_says_each_deed_once_in_the_listener_s_words(new_sim: Callable[..., Simulation]) -> None:
    sim = _theft_scene(new_sim)
    kaz = WorldApi(sim, "kaz")
    kaz.pick_up("2 rice")
    kaz.pick_up("2 rice")  # the same deed twice: said once
    assert WorldApi(sim, "genzo").accuse("Kaz", "Goro").text == 'You tell Goro: "Kaz stole rice from the rack."'
    trespass = Trespassed(kind="walls", owner="town", place="the castle town", witnesses=["genzo"])
    sim.core.emit("trespassed", trespass, actor=sim.citizen("kaz"))
    told = WorldApi(sim, "genzo").accuse("Kaz", "Goro")
    assert told.text == 'You tell Goro: "Kaz stole rice from the rack and was in the castle town at night."'


# --- tend ---


def test_tending_heals_three_health_an_hour(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ennen={"age": 50, "home": "temple-hall", "skills": ["healing"], "at": (-30.0, 50.0)},
        genzo={"home": "farmhouse-1", "at": (-31.0, 50.0)},
        tokuji={"home": "farmhouse-2", "at": (-50.0, 50.0)},  # as hurt, untended
    )
    for hurt in ("genzo", "tokuji"):
        sim.citizen(hurt).body.health = 60.0
    tended = _done(sim, WorldApi(sim, "ennen").tend("Genzo"), 40)
    assert tended.text == "You tend Genzo; they look a little better."
    [(healer, payload)] = _of(sim.drain(), Tended)
    assert healer == "ennen" and payload == Tended(person="genzo", health=1.5)
    gained = sim.citizen("genzo").body.health - sim.citizen("tokuji").body.health
    assert gained == pytest.approx(justice.TEND_PER_HOUR * justice.TEND_MINUTES / 60)


def test_only_a_healer_tends_someone_hurt_within_reach(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ennen={"age": 50, "home": "temple-hall", "skills": ["healing"], "at": (-30.0, 50.0)},
        genzo={"home": "farmhouse-1", "at": (-31.0, 50.0)},
        tokuji={"home": "farmhouse-2", "at": (-35.0, 50.0)},
    )
    assert _done(sim, WorldApi(sim, "ennen").tend("Genzo")).text == "Genzo isn't hurt."
    sim.citizen("genzo").body.health = 70.0
    sim.citizen("tokuji").body.health = 70.0
    assert _done(sim, WorldApi(sim, "tokuji").tend("Genzo")).text == "You don't know how to tend the hurt."
    assert _done(sim, WorldApi(sim, "ennen").tend("Tokuji")).text == "Tokuji is out of your reach."
    tending = WorldApi(sim, "ennen").tend("Genzo")
    sim.step()
    sim.core.place_at(sim.citizen("genzo"), sim.world.town.to_unit(-40.0, 50.0))
    assert _done(sim, tending).text == "You stop tending: Genzo is out of your reach."
    assert _of(sim.drain(), Tended) == []


def test_an_interrupted_tend_forgets_what_it_gave(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ennen={"age": 50, "home": "temple-hall", "skills": ["healing"], "at": (-30.0, 50.0)},
        genzo={"home": "farmhouse-1", "at": (-31.0, 50.0)},
    )
    sim.citizen("genzo").body.health = 60.0
    WorldApi(sim, "ennen").tend("Genzo")
    sim.run(3)
    assert JUSTICE.of(sim.state).tended["ennen"] == pytest.approx(3 * justice.TEND_PER_HOUR / 60)
    WorldApi(sim, "ennen").rest(10)  # stops tending
    sim.step()
    assert JUSTICE.of(sim.state).tended == {}


# --- the snapshot ---


def test_custody_and_the_judged_deeds_survive_a_snapshot(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    WorldApi(sim, "kaz").pick_up("5 rice")
    _seize(sim, "goro", "kaz", monkeypatch)
    JUSTICE.of(sim.state).unpaid["kaz"] = [3, 7]
    restored = restore(take_snapshot(sim.state))
    assert JUSTICE.of(restored) == JUSTICE.of(sim.state)
    assert CUSTODY.of(restored) == CUSTODY.of(sim.state) and CUSTODY.of(restored)["kaz"].keeper == "goro"


# --- the feed ---


def test_the_feed_tells_the_chain_from_the_theft_to_the_fine(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    feed: list[EventDraft] = []
    WorldApi(sim, "kaz").pick_up("5 rice")
    feed += sim.drain()
    WorldApi(sim, "genzo").accuse("Kaz", "Goro")
    _seize(sim, "goro", "kaz", monkeypatch)
    feed += sim.drain()
    feed += _lead_to_gaol(sim, "goro", "kaz")[0]
    WorldApi(sim, "goro").accuse("Kaz", "Masanori")
    lord = WorldApi(sim, "masanori")
    _done(sim, lord.walk_to_place("gaol"))
    _done(sim, lord.judge("Kaz", Fine(mon=20)), 20)
    feed += sim.drain()
    names = namer({c.id: Resident(c.name, c.home, c.age) for c in sim.state.citizens.values()})
    justice_types = {"stole", "accused", "seized", "confined", "judged", "sentence_served", "released"}
    lines = [
        tell(Told(e.type, e.actor_kind, e.actor_id, e.payload.model_dump(mode="json")), names)[0]
        for e in feed
        if e.type in justice_types
    ]
    assert lines == [
        "Kaz steals 5 rice from Genzo's house, seen by Genzo and Goro",
        "Genzo accuses Kaz before Goro",
        "Goro seizes Kaz",
        "Kaz is confined in the gaol",
        "Goro accuses Kaz before Masanori",
        "Masanori sentences Kaz to a fine of 20 mon",
        "Kaz has served the sentence (fine)",
        "Kaz goes free (judged)",
    ]


def test_a_seizure_needs_reach_and_a_free_hand_and_stops_what_the_held_were_doing(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _scene(
        new_sim,
        goro={**ASHIGARU, "at": (-30.0, 50.0)},
        kaz={**CAMP_B, "at": (-31.0, 50.0)},
        nim={**CAMP_B, "at": (-32.5, 50.0)},
    )
    sim.core.place_at(sim.citizen("kaz"), sim.world.town.to_unit(-32.2, 50.0))
    assert _done(sim, WorldApi(sim, "goro").seize("Kaz"), 3).text == "Kaz is out of your reach."
    sim.core.place_at(sim.citizen("kaz"), sim.world.town.to_unit(-31.0, 50.0))
    resting = WorldApi(sim, "kaz").rest(30)
    assert _seize(sim, "goro", "kaz", monkeypatch).outcome == "done"
    assert resting.result is not None and resting.result.text == "Goro seizes you; you are held fast."
    sim.core.place_at(sim.citizen("nim"), sim.world.town.to_unit(-29.0, 50.0))
    assert _done(sim, WorldApi(sim, "goro").seize("Nim"), 3).text == "You already hold someone."


def test_the_held_hold_their_spot_behind_the_seizer_along_the_seizer_s_corners(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    _seize(sim, "goro", "kaz", monkeypatch)
    walk = WorldApi(sim, "goro").walk_to_place("gaol")
    corners = 0
    while not walk.done:
        sim.step()
        led = [point for point, _ in sim.core.strides["kaz"].walked]
        corners += len(sim.core.strides["goro"].walked) - 2
        assert all(point in led for point, _ in sim.core.strides["goro"].walked[1:-1])
        claim = slots.claim_of(sim.core, sim.citizen("kaz"))
        assert claim is not None and claim.position == sim.citizen("kaz").position
        held = custody_of(sim.core, "kaz")
        if held is not None and held.keeper == "goro":  # (not once seated in the gaol)
            assert _distance(sim, "goro", "kaz") == pytest.approx(1.0, abs=0.01)  # a metre behind
    assert corners > 0  # the walk turned some corners on the way


def test_with_no_free_spot_the_held_walk_right_behind_the_seizer(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    _seize(sim, "goro", "kaz", monkeypatch)
    monkeypatch.setattr(slots, "free_round", lambda *_: None)
    walk = WorldApi(sim, "goro").walk_to_place("gaol")
    while not walk.done:
        sim.step()
        goro, kaz = sim.citizen("goro"), sim.citizen("kaz")
        held = custody_of(sim.core, "kaz")
        if held is None or held.keeper is None:  # seated in the gaol
            break
        assert _distance(sim, "goro", "kaz") == pytest.approx(1.0, abs=0.01)
        behind = sim.core.strides["goro"].walked[-2][0]
        assert sim.core.distance_m(kaz.position, behind) < sim.core.distance_m(goro.position, behind)


def test_a_full_gaol_takes_nobody(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _theft_scene(new_sim)
    sim.citizen("masanori").in_view.add("kaz")
    WorldApi(sim, "kaz").pick_up("5 rice")
    seats = slots.layout(sim.core).places["gaol"]
    for number, seat in enumerate(seats):  # two others sit in the gaol's two seats
        other = sim.add_citizen(make_spec(f"inmate-{number}", at=(-30.0 - number, 50.0)))
        sim.core.place_at(other, seat.position)
        slots.claim(sim.core, other, seat, seat.position)
    _seize(sim, "goro", "kaz", monkeypatch)
    _lead_to_gaol(sim, "goro", "kaz")
    custody = custody_of(sim.core, "kaz")
    assert custody is not None and custody.keeper == "goro"  # still held
    lord = WorldApi(sim, "masanori")
    assert _done(sim, lord.walk_to_place("gaol")).outcome == "done"
    assert _done(sim, lord.judge("Kaz", Confinement(hours=3)), 20).text == "The gaol is full."


def test_a_confinement_with_no_way_into_the_gaol_is_no_judgement(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    sim.citizen("masanori").in_view.add("kaz")
    WorldApi(sim, "kaz").pick_up("5 rice")
    _seize(sim, "goro", "kaz", monkeypatch)
    sim.core.place_at(sim.citizen("goro"), sim.world.town.to_unit(-8.0, -13.0))  # brought before the lord
    sim.core.place_at(sim.citizen("kaz"), sim.world.town.to_unit(-8.0, -14.5))
    monkeypatch.setattr(slots, "take_first_free", lambda *_: None)  # both seats free, but no path to either
    sim.drain()
    refused = _done(sim, WorldApi(sim, "masanori").judge("Kaz", Confinement(hours=3)), 20)
    assert (refused.outcome, refused.text) == ("failed", "You can't get Kaz into the gaol.")
    assert _of(sim.drain(), Judged) == []
    custody = custody_of(sim.core, "kaz")
    assert custody is not None and custody.keeper == "goro" and custody.judgement is None


def test_the_judge_must_be_within_four_metres(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _court_scene(new_sim)
    _arrears(sim, "farmhouse-2", 12)
    _seize(sim, "kenji", "tokuji", monkeypatch)
    sim.core.place_at(sim.citizen("masanori"), sim.world.town.to_unit(-12.0, -10.0))
    assert _done(sim, WorldApi(sim, "masanori").judge("Tokuji", Fine(mon=5))).text == "Tokuji is too far away to judge."


def test_only_the_lord_fines_overdue_tax(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _camp_scene(new_sim)
    tek = sim.citizen("tek")
    tek.home = "farmhouse-2"  # as if his household owed the town tax
    _arrears(sim, "farmhouse-2", 12)
    _seize(sim, "barro", "tek", monkeypatch)
    assert _done(sim, WorldApi(sim, "barro").judge("Tek", Fine(mon=5))).text == "You know of no wrong done by Tek."


def test_a_fine_paid_short_counts_only_whole_coins_paid(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _court_scene(new_sim)
    sim.citizen("tokuji").inventory = {"coins": 3, "reeds": 3}  # reeds are worth half a coin
    _arrears(sim, "farmhouse-2", 40)
    _seize(sim, "kenji", "tokuji", monkeypatch)
    short = _done(sim, WorldApi(sim, "masanori").judge("Tokuji", Fine(mon=10)), 20)
    assert short.text == "You fine Tokuji ten coins; they can pay only four coins."


# --- what the held, the confined and those who see them perceive ---


def test_the_held_and_the_confined_know_it_and_others_see_it(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _theft_scene(new_sim)
    kaz = WorldApi(sim, "kaz")
    assert (kaz.check_self().held, kaz.check_self().confined) == (None, None)
    _seize(sim, "goro", "kaz", monkeypatch)
    me = kaz.check_self()
    assert (me.held, me.confined) == ("Goro holds you fast.", None)
    assert "Goro holds you fast." in me.text()
    seen = {person.label: person for person in WorldApi(sim, "genzo").look_around().people}
    assert seen["Kaz"].doing == "held by Goro"
    _lead_to_gaol(sim, "goro", "kaz")
    me = kaz.check_self()
    assert (me.held, me.confined) == (None, "You are confined in the gaol.")
    seen = {person.label: person for person in WorldApi(sim, "masanori").look_around().people}
    assert seen["Kaz"].doing == "confined in the gaol"
