"""Band errands (World v1 plan BR2, 10 §2.3, §2.7, §3.6): meat is dried on the camp's rack and the band's goods kept
there; band A's leader and toolmaker take hides and strips to the stall every 4th day; Nim treks for obsidian every
6th; a hunter without a spear knaps one (the toolmaker an axe too), and a felled tree's logs go home."""

from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import JsonValue

from app.brains.bands import (
    FLINT_TRIES,
    KEEP_STRIPS,
    RACK,
    RICE_BOUGHT,
    STALL_WAITS,
    TREK_SHARDS,
)
from app.brains.profile import BrainProfile, Spot
from app.brains.senses import Needs
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from app.world_api.models import ActionResult, MarketView, Perception, PriceSeen, Seen, TimeOfDay
from tests.brains.test_band_outings import MARSH, SAVANNA, FakeApi, _choose, _ctx, _ended, _look, _start
from tests.sim_helpers import make_spec, without_animals

CAMP = "at your home, at Band A camp"
CAVE = Spot("the painted cave", 387, ("flint",))
FIELD = Spot("the Obsidian field", 535, ("obsidian", "wood"))
BESIDE_RACK = Seen(label=RACK, where="right beside you", nearness="right beside you", kind="building")
RACK_NEAR = BESIDE_RACK.model_copy(update={"where": "a few paces to the east", "nearness": "a few paces"})
FIRE = Seen(label="the fire pit", where="right beside you", nearness="right beside you", kind="fire", doing="burning")
OPEN = MarketView(items=[PriceSeen(item="rice", price="four coins a lot", word="fair")])


def _band(who: str, role: str, region: Literal["band_a", "band_b"] = "band_a", **fields: Any) -> BrainProfile:
    home = "Band A camp" if region == "band_a" else "Band B camp"
    skills = ("gathering", "hunting", "fire")
    return BrainProfile(who, who.capitalize(), role, region, home, skills, **fields)


def _day(day: int) -> dict[str, JsonValue]:
    """Notes on the band's `day`-th day, after the morning's fishing."""
    return {"night": False, "days": day, "chores": ["fished"]}


def _camp(when: TimeOfDay = "midday", carrying: tuple[str, ...] = ("a flint spear",), *things: Seen) -> Perception:
    return _look(CAMP, when, carrying, things=list(things))


# --- the rack ---


def test_a_hunter_back_with_meat_dries_it_on_the_rack_and_leaves_the_goods_there() -> None:
    api = FakeApi(_day(1))
    tek = _band("tek", "hunter")
    meat = ("a flint spear", "some meat", "a hide")
    walk = _choose(_ctx(_camp("midday", meat, RACK_NEAR), tek, api))
    assert walk.name == "go to the drying rack"
    ctx = _ctx(_camp("midday", meat, RACK_NEAR), tek, api)
    assert _start(ctx, walk) == ("walk_to_thing", (RACK,))
    _ended(ctx, "done")
    ctx = _ctx(_camp("midday", meat, RACK_NEAR), tek, api)
    dry = _choose(ctx)
    assert dry.name == "dry meat" and _start(ctx, dry) == ("craft", ("dried meat",))
    _ended(ctx, "done", "craft")
    goods = ("a flint spear", "some dried meat", "a hide")  # some = 8 strips
    ctx = _ctx(_camp("midday", goods, RACK_NEAR), tek, api)
    store = _choose(ctx)
    assert store.name == "put the goods on the rack"
    _start(ctx, store)
    assert api.calls[-3:] == [("stash", ("hide", 9)), ("stash", ("dried meat", 8 - KEEP_STRIPS)), ("rest", (5,))]


def test_a_refused_drying_isn_t_tried_again_at_once() -> None:
    api = FakeApi(_day(1))
    tek = _band("tek", "hunter")
    ctx = _ctx(_camp("midday", ("a flint spear", "some meat"), BESIDE_RACK), tek, api)
    _start(ctx, _choose(ctx))
    _ended(ctx, "failed", "craft")  # someone else at the rack
    assert _choose(_ctx(_camp("midday", ("a flint spear", "some meat"), BESIDE_RACK), tek, api)).name != "dry meat"


# --- band A's trading trip ---


def test_band_a_trades_every_fourth_day_in_its_early_afternoon() -> None:
    ama = _band("ama", "band leader")
    cases: list[tuple[int, TimeOfDay, bool]] = [
        (2, "early afternoon", True),
        (6, "early afternoon", True),
        (3, "early afternoon", False),
        (2, "midday", False),
        (2, "late afternoon", False),
    ]
    for day, when, trades in cases:
        picked = _choose(_ctx(_camp(when, ("a flint spear",), RACK_NEAR), ama, _day(day)))
        assert (picked.name == "go to the drying rack") is trades, (day, when)
    oru = _band("oru", "elder healer")
    assert _choose(_ctx(_camp("early afternoon", (), RACK_NEAR), oru, _day(2))).name != "go to the drying rack"


def test_the_traders_take_the_band_s_goods_sell_them_buy_rice_and_head_home() -> None:
    api = FakeApi(_day(2) | {"last": "go to the drying rack", "chosen": 1})
    api.results[1] = ActionResult(action="walk_to", outcome="done", text="")
    bo = _band("bo", "toolmaker and hunter")
    ctx = _ctx(_camp("early afternoon", ("a flint spear",), RACK_NEAR), bo, api)
    take = _choose(ctx)
    assert take.name == "take the goods to town"
    _start(ctx, take)
    assert api.calls[-1] == ("rest", (10,)) and "trading" not in api.notes  # the rack was bare: no trip
    api.notes["chores"] = ["fished"]
    api.carrying = ["two hides", "some dried meat"]
    ctx = _ctx(_camp("early afternoon", ("a flint spear",), BESIDE_RACK), bo, api)
    _start(ctx, _choose(ctx))
    assert api.calls[-3:] == [
        ("pick_up", ("2 hides",)),
        ("pick_up", (f"{2 * KEEP_STRIPS} dried meat",)),
        ("walk_to_place", ("the market", "walk")),
    ]
    assert api.notes["trading"] is True
    on_the_way = _choose(_ctx(_look("on the road", "late afternoon"), bo, api))
    assert on_the_way.name != "go to the market"  # too late now: the trip is over
    api.notes["trading"] = True
    api.notes["chores"] = ["fished"]
    for _ in range(STALL_WAITS):  # in town the sun is the town's: waits are counted
        ctx = _ctx(_look("at the market", "early afternoon"), bo, api)
        shut = _choose(ctx)
        assert shut.name == "wait for the stall"
        _start(ctx, shut)
    ctx = _ctx(_look("at the market", "early afternoon"), bo, api)
    assert _choose(ctx).name == "go home"
    api.notes["chores"] = ["fished"]
    ctx = _ctx(_look("at the market", "early afternoon", market=OPEN), bo, api)
    deal = _choose(ctx)
    assert deal.name == "trade at the stall"
    _start(ctx, deal)
    assert api.calls[-5:] == [
        ("sell", ("hide", 99)),
        ("sell", ("dried meat", 2 * KEEP_STRIPS)),
        ("buy", ("obsidian", 1)),  # the toolmaker: for spears
        ("buy", ("rice", RICE_BOUGHT)),
        ("walk_to_place", ("home", "walk")),
    ]
    assert "trading" not in api.notes
    home = _choose(_ctx(_look("in open grassland", "early afternoon"), bo, api))
    assert home.name == "go home"  # straight back: nothing taken on the town's ground


# --- Nim's obsidian trek ---


def test_nim_treks_for_obsidian_every_sixth_day_and_sells_it_on_the_way_back() -> None:
    nim = _band("nim", "mother", "band_b", spots=(FIELD,))
    api = FakeApi(_day(3))
    ctx = _ctx(_look("at your home, at Band B camp", "dawn"), nim, api)
    out = _choose(ctx)
    assert out.name == "go to the Obsidian field"
    assert _choose(_ctx(_look("at your home, at Band B camp", "dawn"), nim, _day(4))).name != out.name
    _start(ctx, out)
    shard = Seen(label="an obsidian field", where="right beside you", nearness="right beside you", kind="node",
                 resource="obsidian")  # fmt: skip
    mined = 0
    while True:
        ctx = _ctx(_look("at the Obsidian field", "early morning", things=[shard]), nim, api)
        option = _choose(ctx)
        if option.name != "mine obsidian":
            break
        assert _start(ctx, option) == ("gather", ("obsidian",))
        mined += 1
    assert mined == TREK_SHARDS and option.name == "go to the market"
    ctx = _ctx(_look("at the market", "mid-morning", market=OPEN), nim, api)
    _start(ctx, _choose(ctx))
    assert api.calls[-4:] == [
        ("sell", ("obsidian", 99)),
        ("sell", ("hide", 99)),
        ("buy", ("rice", RICE_BOUGHT)),
        ("walk_to_place", ("home", "walk")),
    ]


# --- knapping and felling ---


def test_a_hunter_without_a_spear_fetches_flint_and_knaps_one_at_the_fire() -> None:
    tek = _band("tek", "hunter", spots=(SAVANNA, CAVE, MARSH))
    api = FakeApi(_day(1))
    ctx = _ctx(_camp("mid-morning", ("some wood",)), tek, api)
    fetch = _choose(ctx)
    assert fetch.name == "go to the painted cave"
    flint = Seen(label="a flint seam", where="right beside you", nearness="right beside you", kind="node",
                 resource="flint")  # fmt: skip
    ctx = _ctx(_look("at the painted cave", "mid-morning", ("some wood",), things=[flint]), tek, api)
    mine = _choose(ctx)
    assert mine.name == "mine flint" and _start(ctx, mine) == ("gather", ("flint",))
    ctx = _ctx(_camp("mid-morning", ("some wood", "a flint nodule"), FIRE), tek, api)
    knap = _choose(ctx)
    assert knap.name == "knap" and _start(ctx, knap) == ("craft", ("flint spear",))
    ctx = _ctx(_camp("mid-morning", ("some wood", "an obsidian shard", "a flint nodule"), FIRE), tek, FakeApi(_day(1)))
    assert _start(ctx, _choose(ctx)) == ("craft", ("obsidian spear",))  # the better stone first


def test_the_toolmaker_knaps_a_stone_axe_and_fetches_more_flint_when_one_is_short() -> None:
    bo = _band("bo", "toolmaker and hunter", spots=(CAVE,))
    api = FakeApi(_day(1))
    ctx = _ctx(_camp("mid-morning", ("a flint spear", "some wood", "a flint nodule"), FIRE), bo, api)
    knap = _choose(ctx)
    assert knap.name == "knap" and _start(ctx, knap) == ("craft", ("stone axe",))
    _ended(ctx, "failed", "craft")  # an axe takes two
    more = _choose(_ctx(_camp("mid-morning", ("a flint spear", "some wood", "a flint nodule"), FIRE), bo, api))
    assert more.name == "go to the painted cave"
    api.notes["chores"] = ["fished", *(["flint"] * FLINT_TRIES)]  # mined enough today: no more fetching
    done = _choose(_ctx(_camp("mid-morning", ("a flint spear", "some wood", "a flint nodule"), FIRE), bo, api))
    assert done.name != "go to the painted cave"
    with_axe = _camp("mid-morning", ("a flint spear", "a stone axe", "some wood"), FIRE)
    assert _choose(_ctx(with_axe, bo, _day(1))).name != "knap"


def test_a_felled_tree_s_logs_are_carried_home() -> None:
    api = FakeApi(_day(1) | {"last": "gather wood", "chosen": 1})
    api.results[1] = ActionResult(
        action="gather", outcome="done", text="The tree falls with a crash; ten pieces of wood lie by the stump."
    )
    bo = _band("bo", "toolmaker and hunter")
    ctx = _ctx(_look("in a broadleaf forest", "mid-morning", ("a flint spear", "a stone axe")), bo, api)
    carry = _choose(ctx)
    assert carry.name == "carry the logs home"
    _start(ctx, carry)
    assert api.calls[-2:] == [("pick_up", ("wood",)), ("walk_to_place", ("home", "walk"))]


# --- the rack is a place one walks up to ---


def test_a_band_member_walks_up_to_the_camp_s_drying_rack_and_dries_meat_there(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = without_animals(new_sim())
    spec: dict[str, Any] = {
        "site": "band_a_camp",
        "at": (0.0, 6.0),
        "home": "band_a_camp:shelter-n",
        "region": "band_a",
    }
    suna = sim.add_citizen(make_spec("suna", knows_places=["band_a_camp"], inventory={"meat": 3}, **spec))
    api = WorldApi(sim, suna.id)
    assert any(thing.label == RACK for thing in api.look_around().things)
    walk = api.walk_to_thing(RACK)
    while walk.result is None:
        sim.step()
    assert walk.result.outcome == "done"
    craft = api.craft("dried meat")
    while craft.result is None:
        sim.step()
    assert craft.result.outcome == "done" and sim.citizen(suna.id).inventory.get("dried meat") == 3
    sim.stock_store("band_a_camp:drying-rack", "dried meat", 1)  # the cast's starting strips (a store once stocked)
    stashed = api.stash("dried meat", 2)
    assert stashed.outcome == "done" and sim.state.stores["band_a_camp:drying-rack"]["dried meat"] == 3


# --- spreading the hunt ---


def test_band_b_s_hunters_take_turns_on_the_grass_round_camp() -> None:
    herd = Seen(label="a herd of deer", where="close by to the north", nearness="close by", doing="grazing")
    look = _look("not far from Band B camp", "mid-morning", ("a flint spear",), animals=[herd])
    barro = _band("barro", "band leader", "band_b", hunt_turn=(0, 2))
    kaz = _band("kaz", "young hunter", "band_b", hunt_turn=(1, 2))
    hunts = {day: [_choose(_ctx(look, who, _day(day))).name == "hunt deer" for who in (barro, kaz)] for day in (2, 3)}
    assert hunts == {2: [True, False], 3: [False, True]}  # one of them a day


def test_a_hunter_with_grounds_hunts_only_at_the_day_s_ground_or_about_camp() -> None:
    herd = Seen(label="a herd of goats", where="close by to the north", nearness="close by", doing="grazing")
    tek = _band("tek", "hunter", hunting_grounds=("the A savanna", "the Bridge meadows"))
    elsewhere = _look("at the Eastern wall scar", "mid-morning", ("a flint spear",), animals=[herd])
    there = elsewhere.model_copy(update={"place": "at the A savanna"})
    assert _choose(_ctx(elsewhere, tek, _day(1))).name != "hunt goat"  # another hunter's ground today
    assert _choose(_ctx(there, tek, _day(1))).name == "hunt goat"


def test_kaz_poaches_in_the_lord_s_woods_when_band_b_s_grass_is_empty_and_temptation_wins() -> None:
    lords = Spot("the Lord's woods", 853, ("berries",), 337, ("deer", "boar"), "town")
    kaz = _band("kaz", "young hunter", "band_b", spots=(lords,), honesty=0.3)

    def searched(*chores: str) -> dict[str, JsonValue]:
        return {"night": False, "days": 1, "chores": ["fished", *chores]}

    look = _look("not far from Band B camp", "mid-morning", ("a flint spear",))

    def pick(chance: bool, notes: dict[str, JsonValue]) -> str:
        ctx = _ctx(look, kaz, notes)
        ctx.chance = lambda _p: chance
        return _choose(ctx).name

    assert pick(True, searched("game-search", "game-search")) == "go to the Lord's woods"
    assert pick(False, searched("game-search", "game-search")) != "go to the Lord's woods"
    assert pick(True, searched("game-search")) != "go to the Lord's woods"  # one search
    honest = _band("barro", "band leader", "band_b", spots=(lords,))
    assert _choose(_ctx(look, honest, searched("game-search", "game-search"))).name != ("go to the Lord's woods")
    herd = Seen(label="a herd of deer", where="close by to the north", nearness="close by", doing="grazing")
    there = _look("at the Lord's woods", "mid-morning", ("a flint spear",), animals=[herd])
    assert _choose(_ctx(there, kaz, searched("game-search", "game-search"))).name == "hunt deer"


def test_hungry_at_camp_with_nothing_carried_eats_from_the_rack_until_it_is_bare() -> None:
    api = FakeApi(_day(1))
    oru = _band("vesa", "elder healer", "band_b")  # band B's rack is its food store (band A's its trading stock)
    hungry = _look("at your home, at Band B camp", "mid-morning", (), things=[RACK_NEAR])

    def ctx(look: Perception) -> Any:
        made = _ctx(look, oru, api)
        made.needs = Needs(hunger=2, thirst=0, tiredness=0)
        return made

    walk_ctx = ctx(hungry)
    walk = _choose(walk_ctx)
    assert (walk.name, walk.driver) == ("go to the drying rack", "hunger")
    assert _start(walk_ctx, walk) == ("walk_to_thing", (RACK,))
    _ended(walk_ctx, "done")
    eat_ctx = ctx(hungry)
    eat = _choose(eat_ctx)
    assert eat.name == "eat at the rack" and _start(eat_ctx, eat) == ("eat", ("dried meat",))
    _ended(eat_ctx, "done", "eat")
    again = ctx(hungry)
    assert _choose(again).name == "eat at the rack"  # still hungry: on eating
    _start(again, _choose(again))
    _ended(again, "failed", "eat")  # nothing left on it
    bare = ctx(hungry)
    assert _choose(bare).name not in ("eat at the rack", "go to the drying rack")
    assert "rack bare" in cast(list[str], api.notes["chores"])
    fed = _ctx(hungry, oru, FakeApi(_day(1)))  # not hungry: no reason to eat the band's store
    assert _choose(fed).name not in ("eat at the rack", "go to the drying rack")
    for day, eats in ((1, False), (2, False), (3, True), (4, True), (5, False)):  # band A keeps its stock for trading
        band_a = _ctx(_camp("mid-morning", (), RACK_NEAR), _band("oru", "elder healer"), FakeApi(_day(day)))
        band_a.needs = Needs(hunger=2, thirst=0, tiredness=0)
        assert (_choose(band_a).name == "go to the drying rack") is eats, day


def test_kaz_is_tempted_with_one_minus_his_honesty_rolled_once_a_day() -> None:
    lords = Spot("the Lord's woods", 853, ("berries",), 337, ("deer", "boar"), "town")
    kaz = _band("kaz", "young hunter", "band_b", spots=(lords,), honesty=0.3)
    notes: dict[str, JsonValue] = {"night": False, "days": 1, "chores": ["fished", "game-search", "game-search"]}
    rolls: list[float] = []

    def roll(p: float) -> bool:
        rolls.append(p)
        return True

    look = _look("not far from Band B camp", "mid-morning", ("a flint spear",))
    for _ in range(3):
        ctx = _ctx(look, kaz, notes)
        ctx.chance = roll
        assert _choose(ctx).name == "go to the Lord's woods"
    assert rolls == [0.7]  # p = 1 - honesty, once a day


# --- band B's hunger choice, the healers and the fire ---


def test_two_lean_days_running_make_band_b_choose_a_raid_or_gold_alike_for_all() -> None:
    from app.brains import bands

    barro = _band("barro", "band leader", "band_b")
    notes: dict[str, JsonValue] = {"night": False, "days": 5, "chores": [bands.NIGHT_SHARE], "lean": 1}
    dusk = _look("at your home, at Band B camp", "dusk", ())  # nothing carried: a lean day
    bands._reckon_lean(_ctx(dusk, barro, notes), {})
    assert notes["lean"] == 2
    choices = {bands._hungry_choice(_ctx(dusk, _band(who, "x", "band_b"), dict(notes))) for who in ("barro", "nim")}
    assert len(choices) == 1 and choices <= {"raid", "gold"}  # one choice for the band that day
    fed: dict[str, JsonValue] = {"night": False, "days": 5, "chores": [bands.NIGHT_SHARE], "lean": 1}
    bands._reckon_lean(
        _ctx(_look("at your home, at Band B camp", "dusk", ("plenty of roots",)), barro, fed), {"roots": 25}
    )
    assert fed["lean"] == 0
    town = _band("ama", "band leader")  # band A never raids
    assert bands._hungry_choice(_ctx(dusk, town, {"lean": 5})) is None


def test_a_raider_walks_to_the_rice_fields_at_night_and_takes_rice_from_the_racks(
    monkeypatch: Any,
) -> None:
    from app.brains import bands

    monkeypatch.setattr(bands, "_hungry_choice", lambda _ctx: "raid")
    kaz = _band("kaz", "young hunter", "band_b")
    api = FakeApi({"night": False, "days": 5, "chores": [], "lean": 2})
    ctx = _ctx(_look("at your home, at Band B camp", "dusk", ()), kaz, api)
    go = _choose(ctx)
    assert go.name == "go to the rice fields" and go.score > 70.0  # over sleep
    ctx = _ctx(_look("at the rice fields", "night", ()), kaz, api)
    take = _choose(ctx)
    assert take.name == "take rice from the racks"
    _start(ctx, take)
    assert api.calls[-2:] == [("pick_up", ("5 rice",)), ("walk_to_place", ("home", "walk"))]
    assert _choose(_ctx(_look("at the rice fields", "night", ()), kaz, api)).name != "take rice from the racks"
