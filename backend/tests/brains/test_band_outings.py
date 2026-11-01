"""Band outings (World v1 plan BR2, 10 §1.2): bands know their land's hotspots by name and walk to them; the home
ring first, then the spots farther out; hunters set out at first light to a hunting ground of their own and spare a
herd down to one or two; fishers fish at the band's fishing spot; a forager far from water makes for camp (#114)."""

from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

from pydantic import JsonValue

from app.brains.bands import (
    BAND_ROUTINES,
    FARTHER,
    FIRST_LIGHT,
    FISH_TRIES,
    RING_FIND,
    RING_FINDS,
    RING_LEGS,
    RING_SEARCHES,
    SPOT_SEARCHES,
    _thin,
    _today,
)
from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile, Spot
from app.brains.routines import Context, Option
from app.brains.senses import Needs, phase
from app.engine import citizen_brains
from app.sim import grounds
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from app.world_api.models import ActionResult, Perception, Seen, SelfView, TimeOfDay
from tests.sim_helpers import make_spec, without_animals

CAMP = "at your home, at Band A camp"
SAVANNA = Spot("the A savanna", 287, ("roots",), 64, ("antelope",))
MARSH = Spot("the River marsh", 409, ("reeds", "berries", "fish"), 80)
MEADOWS = Spot("the Bridge meadows", 634, ("wood",), 23, ("deer",))
WOOD = Spot("B wood", 622, ("berries", "nuts", "roots"), 364, (), "band_a")
LORDS = Spot("the Lord's woods", 853, ("berries",), 337, ("deer", "boar"), "town")


class FakeApi:
    """Records the actions an option starts; `results` says how earlier actions (by number) ended."""

    def __init__(self, notes: dict[str, JsonValue] | None = None) -> None:
        self.notes: dict[str, JsonValue] = notes if notes is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.results: dict[int, ActionResult] = {}
        self.carrying: list[str] = []  # what `check_self` tells is carried

    def check_self(self) -> SimpleNamespace:
        return SimpleNamespace(feeling=[], carrying=self.carrying)

    def handle(self, number: int) -> SimpleNamespace:
        return SimpleNamespace(number=number, result=self.results.get(number))

    def __getattr__(self, name: str) -> Callable[..., SimpleNamespace]:
        def act(*args: Any, **_kwargs: Any) -> SimpleNamespace:
            self.calls.append((name, args))
            return SimpleNamespace(number=len(self.calls), result=None)

        return act


def _look(place: str, when: TimeOfDay = "midday", carrying: tuple[str, ...] = (), **fields: Any) -> Perception:
    you = SelfView(feeling=[], carrying=list(carrying), doing="You are standing about.")
    seen: dict[str, Any] = {"people": [], "animals": [], "things": [], "heard": []} | fields
    return Perception(you=you, place=place, time="It is a time of day.", time_of_day=when, **seen)


def _profile(role: str = "gatherer", **fields: Any) -> BrainProfile:
    return BrainProfile("suna", "Suna", role, "band_a", "Band A camp", ("gathering", "fire"), **fields)


def _ctx(look: Perception, profile: BrainProfile, notes: dict[str, JsonValue] | FakeApi | None = None) -> Context:
    """A decision point; pass the same `FakeApi` to decisions that read how earlier actions ended."""
    api = notes if isinstance(notes, FakeApi) else FakeApi(notes)
    return Context(cast(WorldApi, api), profile, look, Needs(0, 0, 0), phase(look), lambda _p: False, lambda _n: 0)


def _choose(ctx: Context) -> Option:
    """The routine's best option (`nothing` when it has none)."""
    options = BAND_ROUTINES[ctx.profile.routine](ctx)
    return max(options, key=lambda option: option.score, default=Option(0, "nothing", lambda: ctx.api.wait(1)))


def _start(ctx: Context, option: Option) -> tuple[str, tuple[Any, ...]]:
    """Start the option as the brain does (`last`, `chosen`) and say what it did last."""
    api = cast(FakeApi, ctx.api)
    handle = option.start()
    api.notes["last"], api.notes["chosen"] = option.name, handle.number
    return api.calls[-1]


def _ended(ctx: Context, outcome: str, action: str = "walk_to") -> None:
    api = cast(FakeApi, ctx.api)
    number = api.notes["chosen"]
    assert isinstance(number, int)
    api.results[number] = ActionResult(action=action, outcome=outcome, text="")


# --- the day count ---


def test_the_day_count_moves_on_once_a_night_however_the_sun_words_flicker_at_its_edges() -> None:
    notes: dict[str, JsonValue] = {}
    profile = _profile()
    times: list[TimeOfDay] = ["early afternoon", "sunset", "late afternoon", "dusk", "night"]  # day 1, a night
    times += ["pre-dawn", "dawn", "pre-dawn", "dawn", "midday", "night", "dawn"]  # day 2 (flickering), day 3
    counts = [_today(_ctx(_look("at Band A camp", when), profile, notes)) for when in times]
    assert counts == [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3]


# --- hunters ---


def _hunter(**fields: Any) -> BrainProfile:
    grounds = ("the A savanna", "the Bridge meadows")
    return BrainProfile(
        "tek", "Tek", "hunter", "band_a", "Band A camp", ("gathering", "hunting"), hunting_grounds=grounds, **fields
    )


def test_a_hunter_sets_out_at_first_light_to_the_day_s_hunting_ground_and_the_next_one_next_day() -> None:
    notes: dict[str, JsonValue] = {"night": True, "days": 0}
    ctx = _ctx(_look(CAMP, "dawn"), _hunter(), notes)
    first = _choose(ctx)
    assert (first.name, first.score) == ("go to the A savanna", FIRST_LIGHT)
    assert FIRST_LIGHT > 50.0  # over a morning drink (thirst a little: 50) and a bite (45)
    assert _start(ctx, first) == ("walk_to_place", ("the A savanna", "walk"))
    notes.update(night=True, chores=[])  # the next morning
    assert _choose(_ctx(_look(CAMP, "dawn"), _hunter(), notes)).name == "go to the Bridge meadows"
    later = _choose(_ctx(_look(CAMP, "mid-morning"), _hunter(), {"night": True, "days": 0}))
    assert later.name == "go to the A savanna" and later.score < FIRST_LIGHT  # past first light: an ordinary choice


def test_at_its_hunting_ground_a_hunter_looks_about_it_a_few_times_then_gives_up() -> None:
    notes: dict[str, JsonValue] = {"night": False, "days": 1}
    picks = []
    for _ in range(4):
        ctx = _ctx(_look("at the A savanna"), _hunter(), notes)
        option = _choose(ctx)
        picks.append(option.name)
        _start(ctx, option)
    assert picks[:3] == ["look for game"] * 3 and picks[3] != "look for game"


def test_a_hunter_spares_a_herd_down_to_one_or_two_in_sight() -> None:
    assert _thin("two deer") and _thin("a deer") and _thin("an antelope")
    assert not _thin("a herd of deer") and not _thin("a few rabbits")
    notes: dict[str, JsonValue] = {"night": False, "days": 1}
    pair = Seen(label="two deer", where="close by to the north", nearness="close by", doing="grazing")
    herd = pair.model_copy(update={"label": "a herd of deer"})
    spared = _choose(_ctx(_look("at the A savanna", animals=[pair]), _hunter(), dict(notes)))
    hunted = _choose(_ctx(_look("at the A savanna", animals=[herd]), _hunter(), dict(notes)))
    assert spared.name == "look for game" and hunted.name == "hunt deer"


# --- foragers: ring by ring ---


def _gatherer() -> BrainProfile:
    return _profile("gatherer", spots=(SAVANNA, MARSH, WOOD, MEADOWS, LORDS))


def test_a_forager_works_the_home_ring_first_then_goes_to_a_food_spot_farther_out_never_another_group_s() -> None:
    notes: dict[str, JsonValue] = {"night": False, "days": 1, "chores": ["fished"]}
    profile = _gatherer()
    ctx = _ctx(_look(CAMP), profile, notes)
    first = _choose(ctx)
    assert first.name == "go to the A savanna"  # the home ring's food spot, by name
    assert _start(ctx, first) == ("walk_to_place", ("the A savanna", "walk"))
    notes.pop("trip")  # back from it, picked over
    walks = []
    for _ in range(RING_SEARCHES):
        ctx = _ctx(_look("not far from Band A camp"), profile, notes)
        option = _choose(ctx)
        assert option.name == "search"
        walks.append(_start(ctx, option))
    ways = [args[0] for _, args in walks]
    assert ways[:RING_LEGS] == [ways[0]] * RING_LEGS and ways[RING_LEGS] != ways[0]  # a few short walks out each way
    assert all(args[1] == "a short walk" for _, args in walks)
    ctx = _ctx(_look("not far from Band A camp"), profile, notes)
    farther = _choose(ctx)
    assert farther.name == "go to B wood"  # rich, and the band's own (not the Lord's woods: the town's)
    assert _start(ctx, farther) == ("walk_to_place", ("B wood", "walk"))
    assert notes["trip"] == "B wood" and notes["trips"] == 1


def test_at_a_spot_with_nothing_in_view_a_forager_looks_about_it_then_heads_home() -> None:
    notes: dict[str, JsonValue] = {"night": False, "days": 1, "chores": ["fished"], "trip": "B wood", "trip_legs": 0}
    profile = _gatherer()
    on_the_way = _ctx(_look("in open grassland"), profile, notes)
    assert _choose(on_the_way).name == "go to B wood"  # a walk cut short: on to it
    picks = []
    for _ in range(SPOT_SEARCHES + 1):
        ctx = _ctx(_look("at B wood"), profile, notes)
        option = _choose(ctx)
        picks.append(option.name)
        _start(ctx, option)
    assert picks == ["search further"] * SPOT_SEARCHES + ["go home"]


def test_no_outing_to_another_group_s_claimed_spot_however_rich() -> None:
    notes = _searched_today()
    profile = _profile("gatherer", spots=(MARSH, LORDS))
    picked = _choose(_ctx(_look("not far from Band A camp"), profile, notes))
    assert picked.name != "go to the Lord's woods" and "trip" not in notes


def test_a_refused_walk_to_a_spot_ends_the_outing() -> None:
    api = FakeApi({"night": False, "days": 1, "chores": ["fished"], "trip": "B wood", "trip_legs": 0})
    ctx = _ctx(_look("in open grassland"), _gatherer(), api)
    _start(ctx, _choose(ctx))
    _ended(ctx, "failed")
    assert _choose(_ctx(_look("in open grassland"), _gatherer(), api)).name == "go home"


# --- fishers ---


def test_a_fisher_s_first_outing_is_to_the_band_s_fishing_spot_where_it_casts_a_few_times() -> None:
    api = FakeApi({"night": False, "days": 1})
    profile = _gatherer()
    ctx = _ctx(_look(CAMP), profile, api)
    out = _choose(ctx)
    assert (out.name, out.aim) == ("go to the River marsh", "Fish at the River marsh")
    _start(ctx, out)
    there = _ctx(_look("at the River marsh"), profile, api)
    walk = _choose(there)
    assert walk.name == "go to the fishing spot"
    assert _start(there, walk) == ("walk_to_thing", ("fishing spot",))
    _ended(there, "done")
    casts = 0
    while True:
        ctx = _ctx(_look("at the River marsh"), profile, api)
        option = _choose(ctx)
        if option.name != "fish":
            break
        assert _start(ctx, option) == ("fish", ())
        _ended(ctx, "done", "fish")
        casts += 1
    assert casts == FISH_TRIES and "fished" in cast(list[str], api.notes["chores"])


# --- hotspots are places ---


def test_a_band_member_walks_to_a_hotspot_by_name_and_is_told_they_are_there(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = without_animals(new_sim())
    spec: dict[str, Any] = {
        "site": "band_a_camp",
        "at": (0.0, 6.0),
        "home": "band_a_camp:shelter-n",
        "region": "band_a",
    }
    suna = sim.add_citizen(make_spec("suna", knows_places=["band_a_camp", "river_marsh"], **spec))
    lia = sim.add_citizen(make_spec("lia", knows_places=["band_a_camp"], **spec))
    api, other = WorldApi(sim, suna.id), WorldApi(sim, lia.id)
    assert other.walk_to_place("the River marsh").result is not None  # refused at once: she doesn't know it
    walk = api.walk_to_place("the River marsh")
    while walk.result is None:
        sim.step()
    assert walk.result.outcome == "done"
    assert "at the River marsh" in api.look_around().place
    marsh = sim.world.places["river_marsh"]
    assert marsh.kind == "hotspot" and marsh.name == "the River marsh"
    sim.core.place_at(lia, suna.position)
    sim.step()  # standing in a hotspot doesn't tell its name (BR1's rule, D183): nobody reads it off the land
    assert "river_marsh" not in sim.citizen(lia.id).places


def test_the_engine_gives_each_band_hunter_a_different_first_hunting_ground_and_none_reserved(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim(seed=7)
    sim.add_cast(load_citizens(CITIZENS))
    profiles = {brain.profile.citizen_id: brain.profile for brain in citizen_brains(sim, 7).brains.values()}
    band_a = [profiles[who].hunting_grounds for who in ("ama", "bo", "tek")]
    assert len({grounds[0] for grounds in band_a}) == 3  # each starts at a different one
    assert all(sorted(grounds) == sorted(band_a[0]) for grounds in band_a)  # the same grounds, turned
    assert profiles["kaz"].hunting_grounds == ()  # the Lord's woods are the lord's and the samurai's
    assert profiles["oru"].hunting_grounds == ()  # no hunter
    spots = profiles["suna"].spots
    assert [spot.metres for spot in spots] == sorted(spot.metres for spot in spots)
    marsh = next(spot for spot in spots if spot.name == "the River marsh")
    assert "fish" in marsh.goods and marsh.food > 0
    lords = next(spot for spot in profiles["kaz"].spots if spot.name == "the Lord's woods")
    assert lords.claim == "town" and "deer" in lords.game
    assert profiles["masanori"].spots == ()


# --- #114: no water in view far from camp ---


def test_a_thirsty_forager_who_found_no_water_out_here_makes_for_camp_not_another_failing_go_drink() -> None:
    """Issue #114: Oru looped on a failing `go drink` (no water in view) far from camp for 24 ticks."""
    api = FakeApi({"water_way": "south-east", "failed": "go drink", "last": "go drink"})
    brain = UtilityBrain(cast(WorldApi, api), _profile("healer"), seed=1)
    look = _look("in open grassland", "midday")
    needs = Needs(hunger=0, thirst=2, tiredness=0)
    option = brain.thirst_option(look, needs, "day")
    assert option is not None and (option.name, option.score) == ("go home", 80.0)
    api.notes.update(failed=None, last="go home")  # the walk home cut short by something on the way
    again = brain.thirst_option(look, needs, "day")
    assert again is not None and again.name == "go home"  # still no water in view: on home, not "go drink"
    water = Seen(label="a river", where="close by to the east", nearness="close by", kind="water")
    seen = brain.thirst_option(look.model_copy(update={"things": [water]}), needs, "day")
    assert seen is not None and seen.name == "go drink" and "dry" not in api.notes
    api.notes.update(failed=None, last="go drink")  # the walk "to the water" reached the sea: no fresh water in view
    sea = brain.thirst_option(look, needs, "day")
    assert sea is not None and sea.name == "go home"
    api.notes.update(last="go home")  # cut short by ducks coming into view (Lia looped sea and home for an hour)
    again = brain.thirst_option(look, needs, "day")
    assert again is not None and again.name == "go home"


def test_the_home_ring_is_looked_over_the_ways_its_food_lies_first() -> None:
    notes: dict[str, JsonValue] = {"night": False, "days": 1, "chores": ["fished", "the A savanna"]}
    profile = replace(_gatherer(), ring_ways=("south", "east"))
    ways = []
    for _ in range(3 * RING_LEGS):
        ctx = _ctx(_look("not far from Band A camp"), profile, notes)
        ways.append(_start(ctx, _choose(ctx))[1][0])
    assert ways == ["south"] * RING_LEGS + ["east"] * RING_LEGS + ["south"] * RING_LEGS


def test_the_ring_ways_are_where_the_home_ring_s_food_lies_most_first(new_sim: Callable[..., Simulation]) -> None:
    world = new_sim().world
    camp = world.places["band_b_camp"].centre
    totals = world.nodes.food_by_bearing(world.grid, camp, *grounds.RING_M, grounds.GROUND_FOOD)
    ways = grounds.ring_ways(world, "band_b_camp")
    food = [totals[grounds.WAYS.index(way)] for way in ways]
    assert food == sorted(food, reverse=True) and all(food) and len(ways) == sum(1 for total in totals if total)


def _searched_today(*more: str) -> dict[str, JsonValue]:
    """The day's fishing done, the home ring's spot visited and its ways looked over, and `more` chores."""
    chores: list[JsonValue] = ["fished", "the A savanna", *(["ring search"] * RING_SEARCHES), *more]
    return {"night": False, "days": 1, "chores": chores}


def test_one_outing_farther_a_day_while_the_home_ring_still_feeds_them_as_many_once_hungry() -> None:
    fed = _searched_today(FARTHER, *([RING_FIND] * RING_FINDS))  # out once, and the ring gave plenty thrice
    assert _choose(_ctx(_look("not far from Band A camp"), _gatherer(), fed)).name != "go to B wood"
    thin = _searched_today(FARTHER, *([RING_FIND] * (RING_FINDS - 1)))
    assert _choose(_ctx(_look("not far from Band A camp"), _gatherer(), thin)).name == "go to B wood"
    hungry = _ctx(_look("not far from Band A camp"), _gatherer(), _searched_today(FARTHER, *([RING_FIND] * 3)))
    hungry.needs = Needs(hunger=2, thirst=0, tiredness=0)
    assert _choose(hungry).name == "go to B wood"


def test_in_the_home_ring_a_forager_takes_what_is_left_unless_hunger_presses() -> None:
    scraps = Seen(
        label="a berry bush with a few berries left", where="close by to the east", nearness="close by",
        kind="node", resource="berries",
    )  # fmt: skip
    carrying = ("a handful of roots", "a handful of nuts")  # about a day's food
    look = _look("not far from Band A camp", carrying=carrying, things=[scraps])
    content = _choose(_ctx(look, _gatherer(), _searched_today()))
    assert content.name == "go to berries"
    short = _choose(_ctx(look.model_copy(update={"you": _look("").you}), _gatherer(), _searched_today()))
    assert short.name == "go to B wood"  # little carried: out to where there's plenty
    hungry = _ctx(look, _gatherer(), _searched_today())
    hungry.needs = Needs(hunger=2, thirst=0, tiredness=0)
    assert _choose(hungry).name == "go to B wood"  # where there is plenty
    out = _choose(
        _ctx(look.model_copy(update={"place": "at B wood"}), _gatherer(), {**_searched_today(), "trip": "B wood"})
    )
    assert out.name == "search further"  # out farther, scraps aren't worth it


def test_a_bandmate_looking_starved_gets_half_of_what_you_carry_most_of() -> None:
    starved = Seen(label="Lia", where="close by to the east", nearness="close by", doing="resting, looking starved")
    look = _look(CAMP, "dusk", ("plenty of roots", "a few berries"), people=[starved])
    api = FakeApi({"night": False, "days": 1})
    walk = _choose(_ctx(look, _gatherer(), api))
    assert walk.name == "take food to Lia" and walk.score > 48.0  # before the evening's chores at the fire
    beside = look.model_copy(update={"people": [starved.model_copy(update={"nearness": "a few paces"})]})
    ctx = _ctx(beside, _gatherer(), api)
    give = _choose(ctx)
    assert give.name == "give Lia food"
    _start(ctx, give)
    assert api.calls[-2] == ("give", ("half the roots", "Lia"))
    assert _choose(_ctx(beside, _gatherer(), api)).name != "give Lia food"  # once a day
    fed = starved.model_copy(update={"doing": "resting"})
    assert _choose(_ctx(look.model_copy(update={"people": [fed]}), _gatherer(), FakeApi({}))).name != "take food to Lia"
    empty = look.model_copy(update={"you": _look("", carrying=("a few berries",)).you})
    assert _choose(_ctx(empty, _gatherer(), FakeApi({}))).name != "take food to Lia"  # too little to spare


def test_someone_on_a_shore_spot_whose_nearest_cell_is_water_is_told_where_they_are(
    new_sim: Callable[..., Simulation],
) -> None:
    """A walk to fallen wood by a lake ended on a spot whose nearest cell is the lake: looking around crashed
    (no words for a water biome) and stopped a 14-day run on seed 2."""
    sim = without_animals(new_sim())
    world = sim.world
    lake = next(
        cell
        for cell in range(world.cell_count)
        if world.biome(cell) == "lake" and any(not world.is_water(other) for other in world.neighbours[cell])
    )
    wader = sim.add_citizen(make_spec("wader", knows_places=["town"]))
    wader.position, wader.cell = world.unit(lake), lake
    assert "the shore of a lake" in WorldApi(sim, wader.id).look_around().place
