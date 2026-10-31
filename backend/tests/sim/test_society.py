"""Society (10-world-v1 §3.2, 3.3, 3.5, 3.6): deeds and who knows of them, standing per group, bonds, leaders, the
week, the bell and the night law. Deed chains are scripted scenes: the deed events are emitted the way their
emitters (ownership, territory, justice) emit them, and the society system must learn everything from them."""

from collections.abc import Callable
from typing import Any

import pytest

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.observability.events import (
    Accused,
    ActionEnded,
    BellRang,
    EventDraft,
    ItemLocation,
    Judged,
    LeaderChanged,
    Seized,
    SentenceServed,
    StandingChanged,
    Stole,
    Tended,
    Took,
    Traded,
    Trespassed,
)
from app.sim import society
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.sim.society import SOCIETY, Laws, load_laws
from app.sim.state import ActionState, Citizen
from app.sim.wear import WEAR
from app.world_api.facade import WorldApi
from app.world_api.models import Work
from tests.sim_helpers import GATE, make_spec, without_animals

CAMP_A = {"site": "band_a_camp", "at": (1.5, 3.0), "home": "band_a_camp:shelter-n", "knows_places": ["band_a_camp"]}
CAMP_B = {"site": "band_b_camp", "at": (1.5, 3.0), "home": "band_b_camp:shelter-n", "knows_places": ["band_b_camp"]}


def _scene(new_sim: Callable[..., Simulation], *specs: dict[str, Any]) -> Simulation:
    sim = without_animals(new_sim(seed=11))
    for fields in specs:
        sim.add_citizen(make_spec(**fields))
    sim.drain()
    return sim


def _of(events: list[EventDraft], kind: type) -> list[Any]:
    return [event.payload for event in events if isinstance(event.payload, kind)]


def _changes(events: list[EventDraft]) -> list[tuple[str | None, str, int, int, str]]:
    return [
        (event.actor_id, event.payload.group, event.payload.before, event.payload.after, event.payload.cause)
        for event in events
        if isinstance(event.payload, StandingChanged)
    ]


def _steal(sim: Simulation, thief: str, owner: str = "farmhouse-1", count: int = 5) -> int:
    """What ownership emits for a `pick_up` from a store the thief doesn't own (§3.3)."""
    core = sim.core
    payload = Stole(
        owner=owner, store=f"{owner}-chest", item="rice", count=count, witnesses=society.witnesses(core, thief)
    )
    return core.emit("stole", payload, actor=sim.citizen(thief))


def _dawn(sim: Simulation, *who: str) -> None:
    """Their dawn, this tick (as the wear system's sun watch marks it), then the society's dawn hook."""
    WEAR.of(sim.state).rising = set(who)
    society.society_at_dawn(sim.core, lambda _unit: False)


def _town(new_sim: Callable[..., Simulation]) -> Simulation:
    """A theft scene at the main gate: Kaz (band B) with two town farmers of farmhouse-1 and Tek (band A) beside him;
    Fumiko is home far off in the castle town, Oru at band A's camp."""
    return _scene(
        new_sim,
        {"citizen_id": "kaz", "region": "band_b", "age": 19, **CAMP_B, "site": "town", "at": GATE},
        {"citizen_id": "genzo", "home": "farmhouse-1"},
        {"citizen_id": "aiko", "home": "farmhouse-1", "family": {"genzo": "mate"}},
        {"citizen_id": "tek", "region": "band_a", **CAMP_A, "site": "town", "at": GATE},
        {"citizen_id": "fumiko", "home": "main-e-2", "at": (70.0, -58.0)},
        {"citizen_id": "oru", "region": "band_a", "age": 63, **CAMP_A},
    )


# --- standing: starts and words ---


def test_standing_starts_by_group_and_title(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        {"citizen_id": "masanori", "titles": ["lord"], "rank": 5, "age": 55},
        {"citizen_id": "genzo"},
        {"citizen_id": "ama", "region": "band_a", "titles": ["leader"], "rank": 4, **CAMP_A},
        {"citizen_id": "tek", "region": "band_a", **CAMP_A},
        {"citizen_id": "kaz", "region": "band_b", **CAMP_B},
    )
    table = {who: SOCIETY.of(sim.state).standing[who] for who in ("masanori", "genzo", "ama", "tek", "kaz")}
    assert table == {
        "masanori": {"town": 70, "band_a": 0, "band_b": 0},
        "genzo": {"town": 50, "band_a": 0, "band_b": 0},
        "ama": {"town": 10, "band_a": 70, "band_b": 0},
        "tek": {"town": 10, "band_a": 50, "band_b": 0},
        "kaz": {"town": -10, "band_a": 0, "band_b": 50},
    }


@pytest.mark.parametrize(
    ("value", "word"),
    [
        (100, "honoured"),
        (60, "honoured"),
        (59, "well regarded"),
        (20, "well regarded"),
        (19, "nothing said"),
        (-19, "nothing said"),
        (-20, "distrusted"),
        (-59, "distrusted"),
        (-60, "outcast"),
        (-100, "outcast"),
    ],
)
def test_standing_words_follow_the_bible(value: int, word: str) -> None:
    assert society.standing_word(value) == word


# --- deeds: witnesses, known deeds, one change per wronged group ---


def test_a_witnessed_theft_is_known_by_exactly_its_witnesses_and_moves_the_robbed_group_once(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _town(new_sim)
    seq = _steal(sim, "kaz")
    events = sim.drain()

    assert _of(events, Stole)[0].witnesses == ["aiko", "genzo", "tek"]
    knowers = {who for who in sim.state.citizens if [d.seq for d in society.known_deeds(sim.core, who)] == [seq]}
    assert knowers == {"aiko", "genzo", "tek"}
    assert society.known_deeds(sim.core, "fumiko") == [] and society.known_deeds(sim.core, "kaz") == []
    assert _changes(events) == [("kaz", "town", -10, -25, "theft")]  # two town witnesses: one change
    change = next(e for e in events if isinstance(e.payload, StandingChanged))
    assert change.cause_seq == seq and _of([change], StandingChanged)[0].deed == seq
    assert _of([change], StandingChanged)[0].word == "distrusted"
    deed = society.deeds_by(sim.core, "kaz")[0]
    assert (deed.kind, deed.group, deed.owner, deed.doer) == ("theft", "town", "farmhouse-1", "kaz")


def test_an_unwitnessed_deed_stays_in_the_log_and_moves_nothing(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    payload = Stole(owner="farmhouse-1", store="farmhouse-1-chest", item="rice", count=5, witnesses=[])
    seq = sim.core.emit("stole", payload, actor=sim.citizen("kaz"))
    assert _changes(sim.drain()) == []
    assert [deed.seq for deed in society.deeds_by(sim.core, "kaz")] == [seq]
    assert all(society.known_deeds(sim.core, who) == [] for who in sim.state.citizens)


def test_hearsay_moves_the_wronged_group_once_when_its_first_member_hears(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    payload = Stole(owner="farmhouse-1", store="farmhouse-1-chest", item="rice", count=5, witnesses=["tek"])
    seq = sim.core.emit("stole", payload, actor=sim.citizen("kaz"))
    assert _changes(sim.drain()) == []  # only band A saw it: the town doesn't know yet

    sim.core.emit("accused", Accused(person="kaz", to="fumiko", deeds=[seq]), actor=sim.citizen("tek"))
    assert _changes(sim.drain()) == [("kaz", "town", -10, -25, "theft")]
    assert [d.seq for d in society.known_deeds(sim.core, "fumiko")] == [seq]

    sim.core.emit("accused", Accused(person="kaz", to="genzo", deeds=[seq]), actor=sim.citizen("tek"))
    assert _changes(sim.drain()) == []  # the town knew already
    assert [d.seq for d in society.known_deeds(sim.core, "genzo")] == [seq]


def test_an_accusation_passes_only_the_accused_s_deeds(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    payload = Stole(owner="farmhouse-1", store="farmhouse-1-chest", item="rice", count=1, witnesses=[])
    teks = sim.core.emit("stole", payload, actor=sim.citizen("tek"))
    sim.core.emit("accused", Accused(person="kaz", to="fumiko", deeds=[teks]), actor=sim.citizen("genzo"))
    assert society.known_deeds(sim.core, "fumiko") == []
    assert _changes(sim.drain()) == []


def test_the_doer_never_counts_as_a_witness_of_their_own_deed(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    poach = Trespassed(kind="ground", owner="band_a", place="band A's ground", took=Took(item="meat", count=1))
    sim.core.emit("trespassed", poach.model_copy(update={"witnesses": ["tek"]}), actor=sim.citizen("tek"))
    assert _changes(sim.drain()) == [] and society.known_deeds(sim.core, "tek") == []


def test_trespass_and_poaching_cost_the_owning_group(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    core = sim.core
    walls = Trespassed(kind="walls", owner="town", place="the castle town", witnesses=["genzo"])
    core.emit("trespassed", walls, actor=sim.citizen("kaz"))
    poach = Trespassed(kind="ground", owner="band_a", place="band A's ground", took=Took(item="meat", count=2))
    core.emit("trespassed", poach.model_copy(update={"witnesses": ["oru"]}), actor=sim.citizen("kaz"))
    assert _changes(sim.drain()) == [("kaz", "town", -10, -15, "trespass"), ("kaz", "band_a", 0, -10, "poaching")]
    assert [deed.kind for deed in society.deeds_by(core, "kaz")] == ["trespass", "poaching"]


def test_violence_is_known_by_the_victim_and_those_who_see_the_attacker(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    core = sim.core
    sim.citizen("genzo").in_view.discard("kaz")  # struck from behind: the victim knows all the same
    blow = core.injure(sim.citizen("genzo"), 10, "violence", "Kaz strikes you", attacker="kaz")
    events = sim.drain()
    assert _changes(events) == [("kaz", "town", -10, -35, "assault")]
    assert {who for who in sim.state.citizens if society.known_deeds(core, who)} == {"genzo", "aiko", "tek"}
    assert society.bond(core, "kaz", "genzo") == -30
    assert society.deeds_by(core, "kaz")[0].seq == blow


def test_a_killing_costs_sixty_with_its_killing_blow(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    core = sim.core
    core.injure(sim.citizen("genzo"), 100, "violence", "Kaz strikes you", attacker="kaz")
    events = sim.drain()
    assert _changes(events) == [("kaz", "town", -10, -35, "assault"), ("kaz", "town", -35, -70, "killing")]
    assert [deed.kind for deed in society.deeds_by(core, "kaz")] == ["assault", "killing"]
    assert society.known_deeds(core, "genzo") == []  # the dead tell nobody; Aiko and Tek saw it all
    assert [d.kind for d in society.known_deeds(core, "aiko")] == ["assault", "killing"]


def test_an_unwitnessed_killing_moves_no_standing(new_sim: Callable[..., Simulation]) -> None:
    """Regression: the killing blow's `injured` is emitted before the `died`, so the victim must not count as knowing
    the assault (they never tell anyone)."""
    sim = _scene(
        new_sim,
        {"citizen_id": "kaz", "region": "band_b", "age": 19, **CAMP_B, "site": "town", "at": GATE},
        {"citizen_id": "genzo", "home": "farmhouse-1"},
    )
    sim.core.injure(sim.citizen("genzo"), 100, "violence", "Kaz strikes you", attacker="kaz")
    assert _changes(sim.drain()) == []
    assert [deed.kind for deed in society.deeds_by(sim.core, "kaz")] == ["assault", "killing"]
    assert all(society.known_deeds(sim.core, who) == [] for who in sim.state.citizens)


def test_an_animal_s_bite_is_no_deed(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    sim.core.injure(sim.citizen("genzo"), 10, "animal attack", "a wolf bites you", attacker="wolf:1")
    sim.core.injure(sim.citizen("genzo"), 1, "accident", "Kaz's spear grazes you", attacker="kaz")  # no violence
    assert _changes(sim.drain()) == []
    assert all(society.deeds_by(sim.core, who) == [] for who in sim.state.citizens)


def test_a_child_s_deeds_still_move_standing(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        {"citizen_id": "pip", "region": "band_b", "age": 7, **CAMP_B, "site": "town", "at": GATE},
        {"citizen_id": "genzo", "home": "farmhouse-1"},
    )
    _steal(sim, "pip")
    assert _changes(sim.drain()) == [("pip", "town", -10, -25, "theft")]


def test_standing_stays_within_a_hundred(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    for _ in range(10):
        _steal(sim, "kaz")
    for _ in range(40):
        sim.core.emit("tended", Tended(person="genzo", health=3.0), actor=sim.citizen("tek"))
    standing = SOCIETY.of(sim.state).standing
    assert standing["kaz"]["town"] == -100 and standing["tek"]["town"] == 100
    changes = _changes(sim.drain())
    assert all(-100 <= after <= 100 for *_, after, _cause in changes)
    assert changes[-1] == ("tek", "town", 95, 100, "tended")  # clamped, and nothing once there


def test_a_theft_from_a_household_nobody_lives_in_wrongs_the_town(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)  # nobody of the keep is in this scene
    seq = _steal(sim, "kaz", owner="castle-keep")
    deed = SOCIETY.of(sim.state).deeds[seq]
    assert (deed.group, deed.owner) == ("town", "castle-keep")
    assert ("kaz", "town", -10, -25, "theft") in _changes(sim.drain())  # seen by the farmers beside him


def test_a_home_of_two_groups_can_t_own_a_theft(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, {"citizen_id": "kaz", "region": "band_b"}, {"citizen_id": "genzo"})  # both of main-w-3
    with pytest.raises(ValueError, match="a home of several groups"):
        sim.core.emit("stole", Stole(owner="main-w-3", store="x", item="rice", count=1), actor=sim.citizen("kaz"))


# --- good deeds ---


def test_sales_count_only_with_another_group(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    sale = Traded(item="rice", count=4, lots=1, coins=6, stall="market-stall", merchant="fumiko")
    sim.core.emit("bought", sale, actor=sim.citizen("tek"))
    sim.core.emit("bought", sale, actor=sim.citizen("genzo"))
    sim.core.emit("sold", sale, actor=sim.citizen("tek"))
    sim.core.emit("bought", sale, actor=sim.citizen("fumiko"))  # the merchant at her own stall
    assert _changes(sim.drain()) == [("tek", "town", 10, 13, "sale"), ("tek", "town", 13, 16, "sale")]
    assert society.bond(sim.core, "tek", "fumiko") == 6 and society.bond(sim.core, "genzo", "fumiko") == 3


def test_gifts_raise_standing_and_bonds_up_to_their_daily_caps(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    core = sim.core
    tek, genzo, oru = sim.citizen("tek"), sim.citizen("genzo"), sim.citizen("oru")

    def give(giver: Citizen, receiver: Citizen, item: str = "cloth", cause: int | None = None) -> None:
        source, destination = (
            ItemLocation(kind="inventory", id=giver.id),
            ItemLocation(kind="inventory", id=receiver.id),
        )
        core.item_moved(giver, item, 1, source, destination, cause_seq=cause)

    give(tek, genzo, cause=1)  # moved as part of something else (a fine): no gift
    assert _changes(sim.drain()) == [] and society.bond(core, "tek", "genzo") == 0
    for _ in range(4):
        give(tek, genzo)
    assert _changes(sim.drain()) == [("tek", "town", 10 + 2 * n, 12 + 2 * n, "gift") for n in range(3)]
    assert society.bond(core, "tek", "genzo") == 8
    give(tek, oru, "meat")  # food to your own band is sharing; the giver's cap is spent today
    assert _changes(sim.drain()) == []
    assert society.bond(core, "tek", "oru") == 4

    sim.state.tick += DAY_MINUTES  # a new day, new caps
    give(tek, oru, "meat")
    assert _changes(sim.drain()) == [("tek", "band_a", 50, 53, "shared food")]


def test_food_given_within_the_town_is_a_gift_not_band_sharing(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    source, destination = ItemLocation(kind="inventory", id="genzo"), ItemLocation(kind="inventory", id="aiko")
    sim.core.item_moved(sim.citizen("genzo"), "rice", 2, source, destination)
    assert _changes(sim.drain()) == [("genzo", "town", 50, 52, "gift")]


def test_judgement_rewards_true_accusers_and_serving_the_sentence(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        {"citizen_id": "kaz", "region": "band_b", **CAMP_B, "site": "town", "at": GATE},
        {"citizen_id": "goro", "titles": ["ashigaru"], "rank": 3, "home": "farmhouse-1"},
        {"citizen_id": "masanori", "titles": ["lord"], "rank": 5, "age": 55, "at": (0.0, 3.0), "home": "castle-keep"},
        {"citizen_id": "genzo", "at": (0.0, 3.0)},
    )
    core = sim.core
    seq = _steal(sim, "kaz")
    core.emit("accused", Accused(person="kaz", to="masanori", deeds=[seq]), actor=sim.citizen("goro"))
    core.emit("accused", Accused(person="kaz", to="genzo", deeds=[seq]), actor=sim.citizen("goro"))
    core.emit("seized", Seized(person="kaz", held=True), actor=sim.citizen("goro"))
    core.emit("accused", Accused(person="kaz", to="masanori", deeds=[seq + 999]), actor=sim.citizen("genzo"))
    sim.drain()
    assert society.bond(core, "kaz", "goro") == -10 - 10 - 15 - 20  # accused twice, seized, robbed (known)
    judged = Judged(person="kaz", sentence="fine", fine_mon=10, deeds=[seq])
    judgement = core.emit("judged", judged, actor=sim.citizen("masanori"))
    core.emit("sentence_served", SentenceServed(sentence="fine", judgement=judgement), actor=sim.citizen("kaz"))
    core.emit("sentence_served", SentenceServed(sentence="fine"), actor=sim.citizen("kaz"))  # no judgement: no group
    assert _changes(sim.drain()) == [("goro", "town", 50, 53, "accusation"), ("kaz", "town", -25, -20, "served")]

    core.emit("judged", judged, actor=sim.citizen("masanori"))  # judged again for the same deed: no new credit
    assert _changes(sim.drain()) == []
    again = _steal(sim, "kaz")
    core.emit("accused", Accused(person="kaz", to="masanori", deeds=[again]), actor=sim.citizen("goro"))
    sim.drain()
    core.emit("judged", judged.model_copy(update={"deeds": [seq, again]}), actor=sim.citizen("masanori"))
    assert _changes(sim.drain()) == [("goro", "town", 53, 56, "accusation")]  # a new deed proven: credit once more


def test_tending_raises_the_healer_with_the_tended_s_group(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    sim.core.emit("tended", Tended(person="kaz", health=3.0), actor=sim.citizen("oru"))
    assert _changes(sim.drain()) == [("oru", "band_b", 0, 5, "tended")]
    assert society.bond(sim.core, "oru", "kaz") == 10


# --- bonds ---


def test_bonds_start_from_kin_and_the_cast_s_word_beats_kin(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        {"citizen_id": "barro", "region": "band_b", **CAMP_B, "family": {"nim": "mate", "kaz": "sibling"}},
        {"citizen_id": "nim", "region": "band_b", **CAMP_B, "family": {"barro": "mate"}, "bonds": {"barro": 60}},
        {"citizen_id": "kaz", "region": "band_b", **CAMP_B, "family": {"barro": "sibling"}, "bonds": {"tek": -30}},
        {"citizen_id": "tek", "region": "band_a", **CAMP_A, "family": {"suna": "mate"}},
        {"citizen_id": "suna", "region": "band_a", **CAMP_A, "family": {"tek": "mate"}},
    )
    pairs = [("barro", "nim"), ("kaz", "barro"), ("tek", "kaz"), ("suna", "tek")]
    bonds = {pair: society.bond(sim.core, *pair) for pair in pairs}
    assert bonds == {("barro", "nim"): 60, ("kaz", "barro"): 60, ("tek", "kaz"): -30, ("suna", "tek"): 70}
    assert society.bond(sim.core, "tek", "nim") == 0


def test_a_theft_known_to_the_robbed_household_sours_their_bond(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    _steal(sim, "kaz")
    core = sim.core
    assert society.bond(core, "kaz", "genzo") == -20 and society.bond(core, "kaz", "aiko") == -20
    assert society.bond(core, "kaz", "tek") == 0  # a witness, not robbed


# --- leaders ---


def _band(new_sim: Callable[..., Simulation]) -> Simulation:
    return _scene(
        new_sim,
        {"citizen_id": "ama", "region": "band_a", "titles": ["leader"], "rank": 4, "age": 44, **CAMP_A},
        {"citizen_id": "tek", "region": "band_a", "age": 24, **CAMP_A},
        {"citizen_id": "suna", "region": "band_a", "age": 30, **CAMP_A},
        {"citizen_id": "lia", "region": "band_a", "age": 15, **CAMP_A},
    )


def test_the_band_leader_s_standing_follows_how_the_band_wakes(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    _dawn(sim, "ama")
    assert _changes(sim.drain()) == []  # praised (+1) and drifting back (-1): no change at her start
    SOCIETY.of(sim.state).standing["ama"]["band_a"] = 60
    _dawn(sim, "ama")
    assert _changes(sim.drain()) == [("ama", "band_a", 60, 62, "leader")]  # praise and drift, one change
    sim.citizen("lia").body.hunger = 59.9
    sim.citizen("suna").body.hunger = 60.0  # hungry: no praise, only the drift
    _dawn(sim, "ama")
    assert _changes(sim.drain()) == [("ama", "band_a", 62, 63, "drift")]
    sim.citizen("lia").body.hunger = 89.9
    sim.citizen("tek").body.hunger = 90.0  # starving: blame
    _dawn(sim, "ama")
    assert _changes(sim.drain()) == [("ama", "band_a", 63, 62, "leader")]


def test_drift_moves_each_value_one_toward_its_start_at_the_holder_s_dawn(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    standing = SOCIETY.of(sim.state).standing["tek"]
    standing.update({"town": 30, "band_a": 49, "band_b": 0})
    _dawn(sim, "suna")
    assert _changes(sim.drain()) == []  # not Tek's dawn
    _dawn(sim, "tek")
    assert _changes(sim.drain()) == [("tek", "town", 30, 29, "drift"), ("tek", "band_a", 49, 50, "drift")]


def test_leadership_passes_after_three_dawns_well_above_the_leader(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    standing = SOCIETY.of(sim.state).standing
    for dawn in range(3):
        standing["tek"]["band_a"] = 100  # stays far above Ama (70) though it drifts back a little each dawn
        standing["ama"]["band_a"] = 69  # her fed band's praise brings her to 70
        _dawn(sim, "ama")
        changed = _of(sim.drain(), LeaderChanged)
        assert changed == (
            [] if dawn < 2 else [LeaderChanged(group="band_a", title="leader", previous="ama", cause="standing")]
        )
    assert society.leader(sim.core, "band_a") == "tek"
    assert society.titles(sim.core, "tek") == ("leader",) and society.rank(sim.core, "tek") == 4
    assert society.titles(sim.core, "ama") == () and society.rank(sim.core, "ama") == 2


def test_exactly_the_margin_counts(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    standing = SOCIETY.of(sim.state).standing
    for _ in range(3):
        standing["tek"]["band_a"], standing["ama"]["band_a"] = 95, 70
        _dawn(sim, "ama")
    assert society.leader(sim.core, "band_a") == "tek"


def test_a_dawn_short_of_the_margin_starts_the_count_again(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    standing = SOCIETY.of(sim.state).standing
    for above in (True, True, False, True, True):
        standing["tek"]["band_a"] = 95 if above else 94  # Ama stays at 70: her fed band's praise and drift cancel
        standing["ama"]["band_a"] = 70
        _dawn(sim, "ama")
        assert _of(sim.drain(), LeaderChanged) == []
    assert society.leader(sim.core, "band_a") == "ama"


def test_teens_never_take_the_lead(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    standing = SOCIETY.of(sim.state).standing
    for _ in range(4):
        standing["lia"]["band_a"], standing["tek"]["band_a"] = 100, 80  # Tek, an adult, isn't far enough above
        _dawn(sim, "ama")
    assert society.leader(sim.core, "band_a") == "ama"


def test_a_dead_leader_passes_to_the_highest_standing_adult(new_sim: Callable[..., Simulation]) -> None:
    sim = _band(new_sim)
    SOCIETY.of(sim.state).standing["suna"]["band_a"] = 60
    SOCIETY.of(sim.state).standing["lia"]["band_a"] = 90  # a teen
    died = sim.core.die(sim.citizen("ama"), "starvation")
    events = sim.drain()
    changed = next(event for event in events if isinstance(event.payload, LeaderChanged))
    assert changed.actor_id == "suna" and changed.cause_seq == died
    assert changed.payload == LeaderChanged(group="band_a", title="leader", previous="ama", cause="death")
    assert society.leader(sim.core, "band_a") == "suna"


def test_the_lord_s_death_makes_the_highest_samurai_lord(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        {"citizen_id": "masanori", "titles": ["lord"], "rank": 5, "age": 55, "home": "castle-keep"},
        {"citizen_id": "kenji", "titles": ["samurai"], "rank": 4, "age": 34, "home": "castle-keep"},
        {"citizen_id": "akira", "titles": ["samurai"], "rank": 4, "age": 40, "home": "castle-keep"},
        {"citizen_id": "goro", "titles": ["ashigaru"], "rank": 3, "age": 22},
    )
    SOCIETY.of(sim.state).standing["goro"]["town"] = 100
    SOCIETY.of(sim.state).standing["akira"]["town"] = 60  # the more honoured of the two samurai
    sim.core.die(sim.citizen("masanori"), "starvation")
    assert _of(sim.drain(), LeaderChanged) == [
        LeaderChanged(group="town", title="lord", previous="masanori", cause="succession")
    ]
    assert society.leader(sim.core, "town") == "akira"
    assert society.titles(sim.core, "akira") == ("lord",) and society.rank(sim.core, "akira") == 5
    assert society.titles(sim.core, "kenji") == ("samurai",)


def test_leadership_passes_on_the_leader_s_real_dawns(new_sim: Callable[..., Simulation]) -> None:
    """The whole loop on the sim's own clock: Tek stays far above Ama for three of her dawns; her third passes it."""
    sim = _band(new_sim)
    standing = SOCIETY.of(sim.state).standing
    changed: list[EventDraft] = []
    for _ in range(3 * DAY_MINUTES):
        standing["tek"]["band_a"] = 100
        for citizen in sim.state.citizens.values():
            citizen.body.hunger = citizen.body.thirst = 0.0
            citizen.body.energy = 100.0
        sim.step()
        changed += [event for event in sim.drain() if isinstance(event.payload, LeaderChanged)]
    assert len(changed) == 1 and changed[0].actor_id == "tek"
    assert changed[0].tick > 2 * DAY_MINUTES - 8 * 60  # the third dawn: early on the third morning


# --- the week, the bell, the night law ---


@pytest.mark.parametrize(
    ("tick", "day"),
    [(0, 1), (DAY_MINUTES - START_MINUTE - 1, 1), (DAY_MINUTES - START_MINUTE, 2), (7 * DAY_MINUTES, 1)],
)
def test_the_week_counts_town_days_from_market_day(tick: int, day: int) -> None:
    assert society.day_of_week(tick) == day


def _at(minute: int, day: int = 1) -> int:
    """The tick at this minute of the town's clock on that day."""
    return day * DAY_MINUTES + minute - START_MINUTE


def _monk(new_sim: Callable[..., Simulation]) -> Simulation:
    return _scene(
        new_sim,
        {"citizen_id": "ennen", "home": "temple-hall", "at": (85.0, -71.5), "knows_places": ["town", "bell-tower"]},
    )


@pytest.mark.parametrize(
    ("minute", "timing"),
    [
        (12 * 60 - 91, "It isn't time for the bell."),
        (12 * 60 - 90, 90),
        (12 * 60 - 6, 6),
        (12 * 60 - 2, 5),
        (12 * 60 + 5, 5),
        (12 * 60 + 6, "It isn't time for the bell."),
        (6 * 60 - 30, 30),
        (18 * 60, 5),
        (3 * 60, "It isn't time for the bell."),
    ],
)
def test_the_ringer_keeps_the_hour(new_sim: Callable[..., Simulation], minute: int, timing: int | str) -> None:
    sim = _monk(new_sim)
    sim.state.tick = _at(minute)
    assert society.ring_timing(sim.core, sim.citizen("ennen")) == timing


def test_a_bell_rings_at_its_moment_once_and_the_dusk_bell_starts_the_night_law(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _monk(new_sim)
    sim.state.tick = _at(17 * 60 + 30)
    handle = sim.start("ennen", Work(task="ring bell"))
    events: list[EventDraft] = []
    while sim.result("ennen", handle) is None:
        sim.step()
        events += sim.drain()
    bells = [(event.tick, event.payload) for event in events if isinstance(event.payload, BellRang)]
    assert bells == [(_at(18 * 60), BellRang(kind="dusk"))]
    assert society.night_law(sim.core)
    assert society.ring_timing(sim.core, sim.citizen("ennen")) == "The dusk bell has been rung."
    sim.state.tick = _at(6 * 60, day=2)
    assert society.ring_bell(
        sim.core,
        sim.citizen("ennen"),
        ActionState(number=0, kind="work", started_tick=sim.tick, started_seq=0, args={}),
    ).startswith("You ring the dawn bell")
    assert not society.night_law(sim.core)
    assert (
        society.ring_bell(
            sim.core,
            sim.citizen("ennen"),
            ActionState(number=0, kind="work", started_tick=sim.tick, started_seq=0, args={}),
        )
        == "Someone has rung the dawn bell already."
    )


def test_without_bells_the_night_law_follows_the_sun_a_little_late(new_sim: Callable[..., Simulation]) -> None:
    sim = _monk(new_sim)
    night: dict[int, bool] = {}
    for minute in (17 * 60, 18 * 60 + 29, 18 * 60 + 30, 23 * 60, 6 * 60 + 29, 6 * 60 + 30, 12 * 60):
        sim.state.tick = _at(minute) + (DAY_MINUTES if minute < 12 * 60 else 0)
        society.keep_night(sim.core)
        night[minute] = society.night_law(sim.core)
    assert night == {
        17 * 60: False,
        18 * 60 + 29: False,
        18 * 60 + 30: True,
        23 * 60: True,
        6 * 60 + 29: True,
        6 * 60 + 30: False,
        12 * 60: False,
    }


def test_a_run_starting_in_the_small_hours_starts_under_the_night_law(new_sim: Callable[..., Simulation]) -> None:
    sim = _monk(new_sim)
    sim.state.tick = _at(3 * 60)
    society.keep_night(sim.core)
    assert society.night_law(sim.core)


def test_the_monk_rings_three_bells_a_day_near_dawn_noon_and_dusk(new_sim: Callable[..., Simulation]) -> None:
    """The scripted monk: three bells each town day, each within 10 minutes of its moment by the town's clock."""
    sim = _scene(
        new_sim,
        {
            "citizen_id": "ennen",
            "home": "temple-hall",
            "at": (70.0, -62.0),
            "skills": ["healing"],
            "knows_places": ["town", "temple", "bell-tower", "well", "storehouses"],
        },
    )
    sim.stock_store("store-2", "rice", 50)  # the granary he eats from
    profile = BrainProfile("ennen", "Ennen", "monk of the temple", "town", "The castle town", ("healing",))
    brain = UtilityBrain(WorldApi(sim, "ennen"), profile, seed=3)
    rung: list[tuple[int, str]] = []
    for _ in range(DAY_MINUTES + 10 * 60):  # 08:00 on day 0 to 18:00 on day 1
        brain.tick()
        sim.step()
        rung += [(event.tick, event.payload.kind) for event in sim.drain() if isinstance(event.payload, BellRang)]
    moments = {"dawn": 6 * 60, "noon": 12 * 60, "dusk": 18 * 60}
    assert [kind for _, kind in rung] == ["noon", "dusk", "dawn", "noon", "dusk"]
    for tick, kind in rung:
        assert 0 <= (tick + START_MINUTE) % DAY_MINUTES - moments[kind] <= 10


def test_a_monk_who_misses_the_bell_s_window_doesn_t_keep_trying(new_sim: Callable[..., Simulation]) -> None:
    """At the bell tower at 18:20 his sun still says dusk, but the dusk bell's window closed at 18:05: the refusal
    ends the dusk bell for him (no retrying for the rest of the dusk hour)."""
    sim = _scene(
        new_sim,
        {
            "citizen_id": "ennen",
            "home": "temple-hall",
            "at": (85.0, -71.5),
            "skills": ["healing"],
            "knows_places": ["town", "temple", "bell-tower", "well", "storehouses"],
        },
    )
    sim.state.tick = _at(18 * 60 + 20, day=0)
    profile = BrainProfile("ennen", "Ennen", "monk of the temple", "town", "The castle town", ("healing",))
    brain = UtilityBrain(WorldApi(sim, "ennen"), profile, seed=3)
    refused = 0
    for _ in range(40):
        brain.tick()
        sim.step()
        ended = _of(sim.drain(), ActionEnded)
        refused += sum(1 for end in ended if end.action == "work" and end.outcome == "failed")
    assert refused == 1


# --- determinism and snapshots ---


def _chain(new_sim: Callable[..., Simulation]) -> tuple[list[tuple[int, str, str | None, str]], str]:
    sim = _town(new_sim)
    core = sim.core
    seq = _steal(sim, "kaz")
    core.emit("accused", Accused(person="kaz", to="fumiko", deeds=[seq]), actor=sim.citizen("tek"))
    core.injure(sim.citizen("tek"), 5, "violence", "Kaz strikes you", attacker="kaz")
    sim.run(30)
    _dawn(sim, "kaz", "tek")
    events = [
        (e.seq, str(e.type), e.actor_id, e.payload.model_dump_json()) for e in sim.drain() if e.type != "tick_summary"
    ]
    return events, str(society._dump(SOCIETY.of(sim.state)))


def test_the_deed_sequence_is_deterministic(new_sim: Callable[..., Simulation]) -> None:
    assert _chain(new_sim) == _chain(new_sim)


def test_the_society_block_round_trips_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim = _town(new_sim)
    seq = _steal(sim, "kaz")
    sim.core.emit("accused", Accused(person="kaz", to="fumiko", deeds=[seq]), actor=sim.citizen("tek"))
    SOCIETY.of(sim.state).streaks["tek"] = 2
    SOCIETY.of(sim.state).rung["dusk"] = 7
    restored = restore(take_snapshot(sim.state))
    assert SOCIETY.of(restored) == SOCIETY.of(sim.state)
    assert take_snapshot(restored) == take_snapshot(sim.state)


def test_the_laws_check_their_words_and_bell() -> None:
    data = load_laws().model_dump()
    data["standing"]["words"] = list(reversed(data["standing"]["words"]))
    with pytest.raises(ValueError, match="highest floor down to -100"):
        Laws.model_validate(data)
    data = load_laws().model_dump()
    data["bell"]["early_minutes"] = 6 * 60
    with pytest.raises(ValueError, match="window must not reach two moments"):
        Laws.model_validate(data)
