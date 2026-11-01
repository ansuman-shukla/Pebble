"""BR1's town brains (10-world-v1 §3.1, §2): who they know holds a title, buying and selling at the stall, dues on
court day, the smith's forge, the weaver's reeds, the digger's trips and the night watch."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import JsonValue

from app.brains import town
from app.brains.profile import BrainProfile, known_titles
from app.brains.routines import WORK, Context
from app.brains.senses import Needs, Phase
from app.engine import citizen_brains, town_households
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.market import factor, price_word, stall_lot, stalls, stock_of
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from app.world_api.models import (
    ActionResult,
    ChestView,
    Confinement,
    Fine,
    HeardWords,
    MarketView,
    Nearness,
    Perception,
    PriceSeen,
    PriceWord,
    Seen,
    SelfView,
    TimeOfDay,
)
from tests.sim_helpers import make_spec


def test_brains_know_titles_from_what_people_hold_not_from_their_role_words(
    new_sim: Callable[..., Simulation],
) -> None:
    """A title held (spawned with it) is known whatever the role says; role words alone give none (D165 note)."""
    sim = new_sim()
    sim.add_citizen(
        make_spec("kenji", name="Kenji", role="retainer", rank=4, titles=["samurai"], knows_people=["aiko"])
    )
    sim.add_citizen(make_spec("aiko", name="Aiko", role="weaver", knows_people=["kenji", "ashi"]))
    sim.add_citizen(make_spec("ashi", name="Ashi", role="lord of nothing", knows_people=["aiko"]))
    profiles = {brain.profile.citizen_id: brain.profile for brain in citizen_brains(sim, 1).brains.values()}
    assert profiles["aiko"].titled == (("Kenji", "samurai"),)
    assert profiles["kenji"].titles == ("samurai",) and profiles["aiko"].titles == ()
    assert profiles["aiko"].bows_to("Kenji") and not profiles["kenji"].bows_to("Aiko")


# --- the routines on built perceptions ---


class Recorder:
    """A world api that notes what the brain asked of it; instant actions are done, durative ones handed back."""

    def __init__(self, notes: dict[str, JsonValue] | None = None, refuse: str = "") -> None:
        self.notes: dict[str, JsonValue] = notes if notes is not None else {}
        self.calls: list[tuple[Any, ...]] = []
        self.refuse = refuse  # an action the world refuses

    def handle(self, _number: int) -> Any:
        """Every action asked about ran to its end."""
        return SimpleNamespace(result=ActionResult(action="work", outcome="done", text=""))

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any) -> Any:
            self.calls.append((name, *args))
            outcome = "failed" if name == self.refuse else "done"
            return ActionResult(action="wait", outcome=outcome, text="")

        return call


LORD = known_titles([("Masanori", ["lord"])])
STALL_RICE = PriceSeen(item="rice", price="four coins for two measures; it pays three coins", word="fair")


def _look(
    *,
    place: str = "at the market, in The castle town",
    when: TimeOfDay = "mid-morning",
    carrying: tuple[str, ...] = ("seven coins",),
    market: tuple[PriceSeen, ...] | None = None,
    day: str = "the third day of the week",
    people: tuple[Seen, ...] = (),
    heard: tuple[HeardWords, ...] = (),
) -> Perception:
    you = SelfView(feeling=[], carrying=list(carrying), doing="You are standing still.")
    return Perception(
        you=you, place=place, time="It is the day.", time_of_day=when, people=list(people), animals=[], things=[],
        heard=list(heard), day_of_week=day, market=MarketView(items=list(market)) if market is not None else None,
    )  # fmt: skip


def _ctx(
    look: Perception, profile: BrainProfile, api: Recorder | None = None, hunger: int = 0, phase: Phase = "day"
) -> tuple[Context, Recorder]:
    recorder = api or Recorder()
    ctx = Context(cast(WorldApi, recorder), profile, look, Needs(hunger, 0, 0), phase, lambda _p: False, lambda _n: 0)
    return ctx, recorder


def _profile(name: str, role: str, **fields: Any) -> BrainProfile:
    return BrainProfile(name.lower(), name, role, "town", "The castle town", titled=LORD, **fields)


GENZO = _profile("Genzo", "rice farmer", household=3, paddies=4, dues=12)
TOKUJI = _profile("Tokuji", "elder rice farmer", household=1, paddies=2, dues=12)
GORO = _profile("Goro", "ashigaru of the night watch", titles=("ashigaru",), dues=5)
MASANORI = BrainProfile("masanori", "Masanori", "lord of the castle", "town", "The castle town", titles=("lord",))


def _beside(name: str) -> Seen:
    return Seen(label=name, where="right beside you to the north", nearness="right beside you")


def test_the_words_for_coins_and_days_are_read_at_their_least() -> None:
    assert [town.purse(_look(carrying=(words,))) for words in ("a coin", "seven coins", "twelve coins")] == [1, 7, 12]
    words = ("a short string of coins", "a string of coins", "three strings of coins", "a little rice")
    assert [town.purse(_look(carrying=(w,))) for w in words] == [13, 100, 300, 0]
    assert town.purse(_look(carrying=("a little rice",))) == 0
    assert town.weekday(_look(day="the seventh day of the week, court day")) == 7
    assert town.court_day(_look(day="the seventh day of the week, court day"))
    assert not town.court_day(_look(day="the first day of the week, market day"))
    look = _look(carrying=("a few reeds", "some iron sand", "plenty of rice", "a reed basket", "a length of cloth"))
    assert [town.carrying(look, item) for item in ("reeds", "iron sand", "rice", "cloth", "hide")] == [2, 4, 13, 1, 0]


def test_a_farm_household_spares_what_its_paddies_give_past_the_tax_and_its_mouths() -> None:
    """10 §1.4: Genzo's household keeps 48 a day, Tokuji 24; at 11 a mouth (D180) Genzo's spares 15, Tokuji 13."""
    assert town._surplus(GENZO) == pytest.approx(15 / 48)  # reckoning 11 a mouth (D180)
    assert town._surplus(TOKUJI) == pytest.approx(13 / 24)
    assert town._surplus(GORO) == 0.0


@pytest.mark.parametrize(("word", "sold"), [("dear", 14), ("fair", 9), ("cheap", 5)])
def test_farmers_sell_their_spare_rice_by_the_price_rule(word: PriceWord, sold: int) -> None:
    """Fifty harvested: 30 kept after the tax, 9.4 of them spare for Genzo's household; ×1.5 dear, ×0.5 cheap (with a
    great deal of rice put by at home)."""
    price = STALL_RICE.model_copy(update={"word": word})
    notes: dict[str, JsonValue] = {"taxed": True, "harvested": 50, "chest rice": town.A_GREAT_DEAL}
    ctx, api = _ctx(_look(market=(price,), carrying=("plenty of rice",)), GENZO, Recorder(notes))
    [option] = town._farm(ctx)
    assert option.name == "sell rice"
    option.start()
    assert ("sell", "rice", sold) in api.calls and notes["harvested"] == 0


def test_a_household_with_little_rice_put_by_keeps_its_own_first() -> None:
    """The chest seen at home: plenty in it, no more than the spare share however dear; less than plenty, none sold."""
    dear = (STALL_RICE.model_copy(update={"word": "dear"}),)
    home = _look(place="at your home, in The castle town", carrying=("plenty of rice",))
    seen = home.model_copy(update={"chest": ChestView(holds=["plenty of rice"])})
    notes: dict[str, JsonValue] = {"taxed": True, "harvested": 50}
    town._farm(_ctx(seen, GENZO, Recorder(notes))[0])
    assert notes["chest rice"] == town.PLENTY
    ctx, api = _ctx(_look(market=dear, carrying=("plenty of rice",)), GENZO, Recorder(notes))
    town._farm(ctx)[0].start()
    assert ("sell", "rice", 9) in api.calls
    notes |= {"harvested": 50, "chest rice": 4}
    [option] = town._farm(_ctx(_look(market=dear, carrying=("plenty of rice",)), GENZO, Recorder(notes))[0])
    assert option.name == "go home" and notes["harvested"] == 0


def test_a_farmer_takes_the_rice_home_when_the_stall_is_shut_for_the_day() -> None:
    notes: dict[str, JsonValue] = {"taxed": True, "harvested": 40}
    ctx, _ = _ctx(_look(place="at your home", carrying=("plenty of rice",), when="sunset"), GENZO, Recorder(notes))
    [option] = town._farm(ctx)
    assert option.name == "stash rice" and notes["harvested"] == 0


def test_food_buyers_buy_a_day_of_rice_when_it_runs_low_and_first_of_all_when_hungry() -> None:
    open_stall = (STALL_RICE,)
    ctx, api = _ctx(_look(market=open_stall, carrying=("seven coins", "a little rice")), GORO)
    [option] = town._buy_rice(ctx)
    assert option.name == "buy rice" and option.score == WORK + 8
    option.start()
    assert ("buy", "rice", town.BUY_RICE) in api.calls
    assert town._buy_rice(_ctx(_look(market=open_stall, carrying=("seven coins", "some rice")), GORO)[0]) == []
    late = _look(market=open_stall, carrying=("seven coins", "some rice"), when="late afternoon")
    assert [o.name for o in town._buy_rice(_ctx(late, GORO)[0])] == ["buy rice"]  # enough for the night
    hungry = town._buy_rice(_ctx(_look(market=open_stall), GORO, hunger=2)[0])
    assert [(o.score, o.driver) for o in hungry] == [(86.0, "hunger")]
    assert town._buy_rice(_ctx(_look(market=open_stall, carrying=()), GORO)[0]) == []  # no coins
    assert town._buy_rice(_ctx(_look(market=open_stall, when="dusk"), GORO)[0]) == []  # the stall is shut


def test_a_shut_stall_is_waited_for_a_few_times_a_day_then_given_up() -> None:
    notes: dict[str, JsonValue] = {"arrived": "go to the market"}
    for _ in range(town.STALL_WAITS):
        ctx, _ = _ctx(_look(carrying=("seven coins",)), GORO, Recorder(notes))
        [option] = town._buy_rice(ctx)
        assert option.name == "wait for the stall"
        option.start()
    assert town._buy_rice(_ctx(_look(carrying=("seven coins",)), GORO, Recorder(notes))[0]) == []
    away, _ = _ctx(_look(place="at the well, in The castle town"), GORO, Recorder({}))
    assert [o.name for o in town._buy_rice(away)] == ["go to the market"]


def test_dues_fall_due_each_new_day_and_are_paid_to_the_lord_on_court_day() -> None:
    notes: dict[str, JsonValue] = {}
    for day in ("first", "second", "second", "third"):
        ctx, _ = _ctx(_look(day=f"the {day} day of the week"), GORO, Recorder(notes))
        assert town._pay_dues(ctx) == []
    assert notes["owed"] == 2 * GORO.dues  # the run's first day is free
    court = "the seventh day of the week, court day"
    ctx, api = _ctx(_look(day=court, people=(_beside("Masanori"),)), GORO, Recorder(notes))
    [pay] = town._pay_dues(ctx)
    pay.start()
    assert ("give", "15 coins", "Masanori") in api.calls and notes["owed"] == 0  # a day more fell due on court day
    far = Seen(label="Masanori", where="close by to the west", nearness="close by")
    ctx, _ = _ctx(_look(day=court, people=(far,)), GORO, Recorder({"owed": 5, "day": court}))
    assert [o.name for o in town._pay_dues(ctx)] == ["go up to Masanori"]
    ctx, _ = _ctx(_look(day=court, place="at the well, in The castle town"), GORO, Recorder({"owed": 5, "day": court}))
    assert [o.name for o in town._pay_dues(ctx)] == ["go to the castle"]


LORD_OF_TOWN = BrainProfile(
    "masanori",
    "Masanori",
    "lord of the castle",
    "town",
    "The castle town",
    titled=known_titles([("Goro", ["ashigaru"])]),
    titles=("lord",),
)


def _asks(who: str, words: str) -> tuple[HeardWords, ...]:
    return (HeardWords(who=who, words=words, volume="normal"),)


def test_the_lord_pays_the_watchman_his_wage_once_a_day_and_nobody_else() -> None:
    notes: dict[str, JsonValue] = {}
    wage = "Good evening, my lord. I've come for my wage."
    look = _look(people=(_beside("Goro"),), heard=_asks("Goro", wage))
    ctx, api = _ctx(look, LORD_OF_TOWN, Recorder(notes), phase="dusk")
    [pay] = town.lord(ctx)
    pay.start()
    assert ("give", "25 coins", "Goro") in api.calls and ("say", "Here is your wage, Goro.") in api.calls
    again, _ = _ctx(look, LORD_OF_TOWN, Recorder(notes), phase="dusk")
    assert town._payments(again) == []  # paid today already
    stranger = _look(people=(_beside("Tetsu"),), heard=_asks("Tetsu", wage))
    assert town._payments(_ctx(stranger, LORD_OF_TOWN, Recorder({}), phase="dusk")[0]) == []  # holds no watch
    refused: dict[str, JsonValue] = {}
    ctx, api = _ctx(look, LORD_OF_TOWN, Recorder(refused, refuse="give"), phase="dusk")
    town._payments(ctx)[0].start()
    assert not [call for call in api.calls if call[0] == "say"]  # the coins didn't change hands: no thanks
    assert town._payments(_ctx(look, LORD_OF_TOWN, Recorder(refused), phase="dusk")[0])  # he'll pay when asked again


def test_the_lord_pays_for_an_order_only_when_he_was_handed_the_tool() -> None:
    order = _asks("Tetsu", "Your sickle, my lord, as you ordered.")
    notes: dict[str, JsonValue] = {}
    town._payments(_ctx(_look(carrying=("a short string of coins",)), LORD_OF_TOWN, Recorder(notes))[0])
    empty_handed = _look(people=(_beside("Tetsu"),), heard=order, carrying=("a short string of coins",))
    assert town._payments(_ctx(empty_handed, LORD_OF_TOWN, Recorder(notes))[0]) == []  # no tool came
    handed = _look(people=(_beside("Tetsu"),), heard=order, carrying=("a short string of coins", "a sickle"))
    ctx, api = _ctx(handed, LORD_OF_TOWN, Recorder(notes))
    town._payments(ctx)[0].start()
    assert ("give", "60 coins", "Tetsu") in api.calls
    assert town._payments(_ctx(handed, LORD_OF_TOWN, Recorder(notes))[0]) == []  # said again: no new tool
    away = Seen(label="Tetsu", where="a few paces to the west", nearness="a few paces")
    notes["tools"] = {}
    look = _look(people=(away,), heard=order, carrying=("a sickle",))
    assert [o.name for o in town._payments(_ctx(look, LORD_OF_TOWN, Recorder(notes))[0])] == ["go up to Tetsu"]
    assert town._payments(_ctx(_look(), LORD_OF_TOWN, Recorder(notes))[0]) == []  # gone before he paid


@pytest.mark.parametrize(
    ("word", "day", "fetch"),
    [("dear", "third", 40), ("fair", "fourth", 26), ("fair", "third", 0), ("cheap", "fourth", 0)],
)
def test_the_lord_sells_granary_rice_only_while_rice_is_dear_or_fair(word: PriceWord, day: str, fetch: int) -> None:
    """Dear: every day; fair: every second day; cheap: the rice stays in the granary (10 §1.4)."""
    price = STALL_RICE.model_copy(update={"word": word})
    notes: dict[str, JsonValue] = {}
    look = _look(market=(price,), when="early afternoon", day=f"the {day} day of the week", carrying=())
    ctx, _ = _ctx(look, MASANORI, Recorder(notes))
    options = town._market_round(ctx)
    assert notes.get("fetch rice", 0) == fetch
    assert [o.name for o in options] == (["go to the storehouses"] if fetch else [])


def test_the_watchman_keeps_the_west_gate_and_the_racks_in_turn_through_the_night() -> None:
    notes: dict[str, JsonValue] = {"arrived": "go to the west gate"}
    at_gate = _look(place="at the west gate, in The castle town", when="night")
    ctx, api = _ctx(at_gate, GORO, Recorder(notes), phase="night")
    [watch] = town.night_watch(ctx)
    assert (watch.name, watch.score) == ("guard", town.WATCH) and town.WATCH > 70  # over sleep
    watch.start()
    assert ("work", "guard") in api.calls and notes["beat"] == "racks"
    ctx, _ = _ctx(at_gate, GORO, Recorder(notes), phase="night")
    assert [o.name for o in town.night_watch(ctx)] == ["go to the rice fields"]
    morning = _look(place="at the west gate", when="early morning")
    assert [(o.name, o.score) for o in town.night_watch(_ctx(morning, GORO, Recorder(notes), phase="morning")[0])] == [
        ("go home", town.WATCH)
    ]  # the night on watch is slept off in the morning, however rested he feels
    home = _look(place="at your home, in The castle town", when="mid-morning")
    town.night_watch(_ctx(home, GORO, Recorder(notes))[0])[0].start()
    assert not notes["kept watch"]
    rested = [o.name for o in town.night_watch(_ctx(home, GORO, Recorder(notes))[0])]
    assert rested and "sleep" not in rested
    worn = _ctx(at_gate, GORO, Recorder(notes), phase="night")[0]
    worn.needs = Needs(0, 0, 3)
    assert [(o.name, o.score) for o in town.night_watch(worn)] == [("go home", town.EXHAUSTED)]  # not on the stand


def test_the_smith_buys_his_supplies_forges_and_brings_every_second_tool_to_the_lord() -> None:
    smith = _profile("Tetsu", "smith", dues=5)
    notes: dict[str, JsonValue] = {"arrived": "go to the market"}
    stall = (STALL_RICE,)
    ctx, api = _ctx(_look(market=stall, carrying=("a short string of coins", "some rice")), smith, Recorder(notes))
    town.smith(ctx)[0].start()
    assert ("buy", "wood", 4) in api.calls  # wood first, then the iron sand
    supplied = ("a short string of coins", "some rice", "some wood", "a little iron sand")
    ctx, api = _ctx(_look(market=stall, carrying=supplied), smith, Recorder(notes))
    town.smith(ctx)[0].start()
    assert ("buy", "iron sand", 3) in api.calls
    ready = ("a short string of coins", "some rice", "some wood", "some iron sand")
    notes["arrived"] = "go to the forge"
    at_forge = _look(place="at the forge, in The castle town", carrying=ready, when="midday")
    ctx, api = _ctx(at_forge, smith, Recorder(notes))
    town.smith(ctx)[0].start()
    assert ("craft", "iron axe") in api.calls
    early = _look(place="at the forge, in The castle town", carrying=ready, when="mid-morning")
    assert [o.name for o in town.smith(_ctx(early, smith, Recorder(notes))[0])] != ["forge"]  # forging from midday
    notes["order"] = "iron axe"
    with_axe = (*ready, "an iron axe")
    ctx, api = _ctx(_look(carrying=with_axe, people=(_beside("Masanori"),)), smith, Recorder(notes))
    [hand] = town.smith(ctx)
    hand.start()
    assert ("give", "iron axe", "Masanori") in api.calls
    assert ("say", "Your iron axe, my lord, as you ordered.") in api.calls


# --- the rice shock (10 §1.4; plan BR1 and the critic checklist) ---

SHOCK_DAYS = 4
SEED = 20261028
RICE_LOT = stall_lot("rice")


def test_a_day_without_the_farmers_selling_makes_rice_dear_and_the_price_rule_brings_it_back(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The town alone, its stall at its target: the farmers sell nothing on the first day, the buyers empty the
    stall until the price factor is ≥ 1.2, then the price rule (farmers ×1.5 while dear, the lord's granary rice
    every day while dear) has rice fair again within 3 days."""
    sim = new_sim(seed=SEED)
    cast = load_citizens(CITIZENS)
    sim.add_cast(cast.model_copy(update={"citizens": [c for c in cast.citizens if c.region == "town"]}))
    brains = citizen_brains(sim, SEED)
    sim.drain()
    selling = town._sell_rice
    monkeypatch.setattr(town, "_sell_rice", lambda ctx, score: None if sim.tick < DAY_MINUTES else selling(ctx, score))
    stall, target = stalls(sim.core)[0], RICE_LOT.target if RICE_LOT is not None else 0
    peak, peak_tick, fair_again = 0.0, 0, None
    for _ in range(SHOCK_DAYS * DAY_MINUTES):
        brains(sim)
        sim.step()
        sim.drain()
        stock = stock_of(sim.core, stall, "rice")
        if factor(stock, target) > peak:
            peak, peak_tick = factor(stock, target), sim.tick
        if peak >= 1.2 and fair_again is None and price_word("rice", stock) == "fair":
            fair_again = sim.tick
    assert peak >= 1.2
    assert fair_again is not None and fair_again - peak_tick <= 3 * DAY_MINUTES


def test_a_hotspot_is_a_place_known_by_name_only_to_those_who_know_it(new_sim: Callable[..., Simulation]) -> None:
    """The digger knows the South marsh (the cast's knowledge) and walks there by name; someone standing in it who
    was never told its name doesn't learn it from the land."""
    sim = new_sim()
    marsh = sim.world.places["south_marsh"]
    assert (marsh.kind, marsh.name) == ("hotspot", "the South marsh")
    sim.add_citizen(make_spec("daisuke", knows_places=["town", "south_marsh"]))
    walk = WorldApi(sim, "daisuke").walk_to_place("the South marsh")
    assert walk.result is None or walk.result.outcome != "failed"
    stranger = sim.add_citizen(make_spec("stranger"))
    sim.core.place_at(stranger, marsh.centre)
    sim.step()
    assert "south_marsh" not in sim.citizen("stranger").places
    assert "south_marsh" in sim.citizen("daisuke").places


def test_every_second_tool_the_smith_makes_is_the_lord_s_order() -> None:
    smith = _profile("Tetsu", "smith", dues=5)
    notes: dict[str, JsonValue] = {"last": "forge", "chosen": 1}
    town.smith(_ctx(_look(when="early afternoon"), smith, Recorder(notes))[0])
    assert notes["forged"] == 1 and notes["order"] == "iron axe"  # the first tool made
    notes |= {"last": "forge", "chosen": 2}
    notes.pop("order")
    town.smith(_ctx(_look(when="early afternoon"), smith, Recorder(notes))[0])
    assert notes["forged"] == 2 and "order" not in notes  # the second goes to the stall


def test_a_good_cheap_at_the_stall_is_kept_for_another_day() -> None:
    digger = _profile("Daisuke", "iron-sand digger", dues=5)
    sand = PriceSeen(item="iron sand", price="three coins each; it pays two coins", word="cheap")
    ctx, _ = _ctx(_look(market=(sand,), carrying=("seven coins", "some iron sand")), digger)
    assert town._sell(ctx, "iron sand", "Sell my iron sand") == []
    fair = sand.model_copy(update={"word": "fair"})
    ctx, api = _ctx(_look(market=(fair,), carrying=("seven coins", "some iron sand")), digger)
    town._sell(ctx, "iron sand", "Sell my iron sand")[0].start()
    assert ("sell", "iron sand", 99) in api.calls


def test_the_weaver_fetches_reeds_on_reed_days_and_makes_a_pack_from_two_hides() -> None:
    aiko = _profile("Aiko", "weaver, the farmer's wife", household=3, paddies=4, dues=12)
    home = "at your home, in The castle town"
    reed_day = _look(place=home, when="early morning", day="the fourth day of the week")
    assert [o.name for o in town.weaver(_ctx(reed_day, aiko)[0])] == ["go to the South marsh"]
    other_day = _look(place=home, when="early morning", day="the fifth day of the week")
    notes: dict[str, JsonValue] = {"arrived": "go home"}
    assert [o.name for o in town.weaver(_ctx(other_day, aiko, Recorder(notes))[0])] == ["weave"]
    hides = _look(
        place=home, when="early morning", day="the fifth day of the week", carrying=("a few hides", "a few reeds")
    )
    ctx, api = _ctx(hides, aiko, Recorder(notes))
    town.weaver(ctx)[0].start()
    assert ("craft", "pack") in api.calls


def test_a_child_tagging_along_stops_when_the_one_followed_lies_down_to_sleep(
    new_sim: Callable[..., Simulation],
) -> None:
    """Regression (seed 7: Hana followed the watchman home and stood at his door 6 h while he slept)."""
    sim = new_sim()
    sim.add_citizen(make_spec("hana", name="Hana", knows_people=["goro"]))
    goro = sim.add_citizen(make_spec("goro", name="Goro", knows_people=["hana"], at=(-20.0, 60.0)))
    follow = WorldApi(sim, "hana").follow("Goro")
    goro.body.asleep = True
    sim.step()
    assert follow.result is not None and follow.result.text == "Goro lies down to sleep."


# --- the law ---

KENJI = _profile("Kenji", "samurai retainer", titles=("samurai",))
ENNEN = _profile("Ennen", "monk of the temple", skills=("healing",))


def _kaz(nearness: Nearness = "right beside you", doing: str | None = None) -> Seen:
    return Seen(
        label="Kaz",
        where=f"{nearness} to the west",
        nearness=nearness,
        doing=doing,
        regard="who stole rice from the racks",
    )


def test_an_officer_seizes_someone_known_for_a_wrong_leads_them_to_the_gaol_and_tells_the_lord() -> None:
    notes: dict[str, JsonValue] = {}
    far = _ctx(_look(people=(_kaz("close by"),)), KENJI, Recorder(notes))[0]
    assert [(o.name, o.score) for o in town.samurai(far)] == [("go up to Kaz", town.LAW)]
    ctx, api = _ctx(_look(people=(_kaz(),)), KENJI, Recorder(notes))
    town.samurai(ctx)[0].start()
    assert ("seize", "Kaz") in api.calls
    notes |= {"last": "seize", "chosen": 7}
    held = _look(place="at the market, in The castle town", people=(_kaz(doing="held by a man in armour"),))
    assert [o.name for o in town.samurai(_ctx(held, KENJI, Recorder(notes))[0])] == ["go to the gaol"]
    notes |= {"last": "go to the gaol", "arrived": "go to the gaol"}
    confined = _look(place="at the gaol, in The castle town", people=(_kaz(doing="confined in the gaol"),))
    assert [o.name for o in town.samurai(_ctx(confined, KENJI, Recorder(notes))[0])] == ["go to the castle"]
    with_lord = _look(people=(_kaz(doing="confined in the gaol"), _beside("Masanori")))
    ctx, api = _ctx(with_lord, KENJI, Recorder(notes))
    town.samurai(ctx)[0].start()
    assert ("accuse", "Kaz", "Masanori") in api.calls and "to tell" not in notes
    assert [o.name for o in town.samurai(_ctx(_look(people=(_kaz(),)), KENJI, Recorder(notes))[0])] != ["seize"]


def test_the_lord_judges_by_his_table_and_confines_whoever_can_t_pay_the_fine() -> None:
    notes: dict[str, JsonValue] = {}
    confined = _look(people=(_kaz(doing="confined in the gaol"),), place="at the gaol, in The castle town")
    ctx, api = _ctx(confined, MASANORI, Recorder(notes))
    town.lord(ctx)[0].start()
    assert ("judge", "Kaz", Fine(mon=20)) in api.calls  # theft: twice a few measures' worth
    ctx, api = _ctx(confined, MASANORI, Recorder(notes))
    town.lord(ctx)[0].start()
    assert ("judge", "Kaz", Confinement(hours=6)) in api.calls  # still held: the fine wasn't paid
    assert town._judge(_ctx(confined, MASANORI, Recorder(notes))[0]) == []  # judged
    free = _look(people=(_kaz(),))
    assert town._judge(_ctx(free, MASANORI, Recorder({}))[0]) == []  # only the held or confined


def test_the_monk_tends_whoever_looks_hurt() -> None:
    hurt = Seen(label="Lia", where="close by to the east", nearness="close by", doing="walking, looking hurt")
    assert [o.name for o in town.monk(_ctx(_look(people=(hurt,)), ENNEN)[0])] == ["go up to Lia"]
    beside = hurt.model_copy(update={"nearness": "right beside you"})
    ctx, api = _ctx(_look(people=(beside,)), ENNEN)
    [tend] = town.monk(ctx)
    tend.start()
    assert (tend.score, ("tend", "Lia") in api.calls) == (town.TEND, True)
    well = beside.model_copy(update={"doing": "walking"})
    assert [o.name for o in town.monk(_ctx(_look(people=(well,)), ENNEN)[0])] != ["tend"]


def test_a_fine_paid_leaves_a_clean_slate_and_a_second_wrong_gets_its_own_sentence() -> None:
    notes: dict[str, JsonValue] = {}
    confined = _look(people=(_kaz(doing="confined in the gaol"),))
    town._judge(_ctx(confined, MASANORI, Recorder(notes))[0])[0].start()
    assert notes["fined"] == ["Kaz"]
    town._judge(_ctx(_look(people=(_kaz(),)), MASANORI, Recorder(notes))[0])  # seen free: the fine was paid
    assert notes["fined"] == []
    again = _kaz(doing="confined in the gaol").model_copy(
        update={"regard": "who stole rice from the racks and struck you"}
    )
    ctx, api = _ctx(_look(people=(again,)), MASANORI, Recorder(notes))
    town._judge(ctx)[0].start()
    assert ("judge", "Kaz", Confinement(hours=12)) in api.calls  # the blow, not the 6 h of a fine unpaid
    assert notes["fined"] == []


def test_the_monk_leaves_someone_hurt_far_away_be() -> None:
    far = Seen(label="Lia", where="far away to the east", nearness="far away", doing="walking, looking hurt")
    assert town._tend(_ctx(_look(people=(far,)), ENNEN)[0]) == []


def test_a_household_s_dues_are_shared_by_its_adults_the_first_paying_what_doesn_t_divide(
    new_sim: Callable[..., Simulation],
) -> None:
    """farmhouse-2 owes 12 a day (two paddies): five adults pay 2 each, the first in the cast's order 2 more."""
    sim = new_sim()
    for who, age in (("ann", 30), ("bo", 40), ("cy", 50), ("dee", 35), ("eve", 60), ("kid", 8)):
        sim.add_citizen(make_spec(who, home="farmhouse-2", age=age))
    facts = town_households(sim.core.citizens(), ["cy", "ann", "bo", "dee", "eve", "kid"])
    assert {who: facts[who].dues for who in facts} == {"cy": 4, "ann": 2, "bo": 2, "dee": 2, "eve": 2, "kid": 0}
    assert {facts[who].mouths for who in facts} == {6} and {facts[who].paddies for who in facts} == {2}
