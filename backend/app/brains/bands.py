"""Band routines (10-world-v1 §1.2, §2.3, §3.6): what the Stone Age bands do with an ordinary day once needs and night
are taken care of: forage around camp in outings and come back, hunt, scavenge, keep the camp fire going, dry meat
on the camp's rack, knap spears and axes, fell trees, and take the band's goods to the town's stall.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial

from app.brains.healing import tend_the_hurt
from app.brains.justice import known_deed
from app.brains.profile import Routine, Spot
from app.brains.routines import COMPASS, WORK, Context, Option, _count_today, _daytime, _refused, _set, _then
from app.brains.senses import (
    DISTANCE,
    FOOD_VALUE,
    GAME_WORDS,
    HURT,
    NIGHT_HUNGER,
    Resource,
    at,
    at_home,
    beside,
    carried_food,
    carries,
    compass_word,
    fire_here,
    fire_in_view,
    fishing_here,
    food_value,
    full_load,
    game,
    harmful_by_morning,
    is_name,
    near,
    prowler,
    resources_in_view,
    wood_at_hand,
)
from app.core.rng import Rng
from app.world_api.facade import ActionHandle
from app.world_api.models import ActionResult, Compass, Driver, Fine, Perception, RoughDistance, Seen

FOODS = ("roots", "nuts", "berries")  # wild food, most filling first
OUTING_FOOD = 150.0  # bands head back to camp carrying about this much (a day and a half of food)
HUNT_TRIES = 3  # hunts (and as many searches for game) a hunter tries a day
KILL_CALL = "We took game at "  # a hunter back with meat calls where across camp: the band spares that ground
SPARE_DAYS = 2  # band days a ground is left alone after a kill there (a herd's dead are replaced in about two)
TRIP_TIMES = frozenset({"dawn", "early morning", "mid-morning", "midday", "early afternoon"})  # time to be back
TRIP_LEGS = 4  # short walks on past where a forage trip's long walk ended, while no food shows (fewer near a den)
FISH_TRIES = 4  # casts a fisher makes a day at the band's fishing spot (each lands fish 35 % of the time, D70)
HOME_RING_M = 400.0  # a spot this near camp is in the home ring (10 §1.2)
RING_FOOD = 40  # wild food (pieces when full) a home-ring spot holds to be worth a walk there
FOOD_SPOT = 150  # and a spot farther out, to be worth an outing (B wood holds ~360)
RING_SEARCHES = 12  # short walks about camp a day looking over the home ring before an outing farther out
RING_LEGS = 3  # of them out each way, one after the other
SPOT_SEARCHES = 2  # short walks about a spot reached with nothing in view before heading home
FARTHER = "outing farther"  # the day's chore note of an outing past the home ring
SCRAPS_REACH = frozenset({"here", "near", "close"})  # how far a forager in the home ring walks for scraps
SCRAPS_FED = 40.0  # and the food carried first (about a day's): short of it, out to where there's plenty
RING_FIND = "ring find"  # and of plenty of food found in the home ring
RING_FINDS = 1  # finds in a day that tell the home ring still feeds the band
FEED = 60.0  # a bandmate looking starved is fed first: over a day's work and the evening, under one's own needs
FIRST_LIGHT = 52.0  # hunters set out at first light: over a morning drink or bite (50, 45), under real thirst (80)
FIRE = "the fire pit"
HUNT = "Hunt game for the band"
LYING_FOOD = ("meat on the ground", "fish on the ground")  # fresh: not "dried meat" (someone's store, not remains)
# a forager with enough food (or no room) rests, looks about camp and heads back: one aim, so goals don't flip
AT_EASE: tuple[str, Driver] = ("Take it easy about camp", "rest")
SCAVENGE = WORK + 6  # over a hunt: the meat is there already
KEEP_FIRE = "Keep the camp fire going"
# one outing a day to the band's fishing spot (10 §3.1: Suna forages, fishes; Nim at B shore, near her camp)
FISHERS = frozenset({"suna", "nim"})
FISHING = "fishing spot"  # what a fisher walks up to ("a good fishing spot, fish jumping")
RACK = "the drying rack"  # the camp's rack: meat dries there, and the band keeps its strips and hides on it
KEEP_STRIPS = 4  # strips of dried meat one keeps on them; the rest go on the rack
MARKET = "the market"
ERRAND = WORK + 8  # a trading trip or a trek: over the day's foraging (30) and a hunt (35), under needs
# who does what beyond foraging (10 §3.1 roster): band A's trading trip (the leader and the toolmaker), Nim's obsidian
TRADERS = frozenset({"ama", "bo"})
TRADE_EVERY, TRADE_DAY = 4, 2  # band A trades on its 2nd day, then every 4th (6th, 10th, 14th)
TRADE_TIMES = frozenset({"early afternoon"})  # band A sets out then: the town's morning, when the stall is open
TREKKERS = frozenset({"nim"})
TREK_EVERY, TREK_DAY = 5, 3  # Nim's obsidian trek: band B's 3rd day, then every 5th (8th, 13th)
TREK_TIMES = frozenset({"dawn", "early morning", "mid-morning"})  # band B's morning is the town's (3 h behind)
TREK_SHARDS = 4  # shards she mines (one each) before taking them to the stall
STALL_WAITS = 6  # quarter hours a trader waits at a shut stall before heading home
STALL_LATE = frozenset({"late afternoon", "sunset", "dusk", "night", "pre-dawn"})  # too late to wait for the stall
GOLD_RICE = 6  # measures each panner buys with the gold
RICE_BOUGHT = 10  # measures each trader buys a trip (10 §2.7: band A ~24 mon of rice every 4 days, band B ~8 a day)
TOOLMAKERS = frozenset({"bo"})  # knaps a stone axe too, and fells trees with it
TOOL_ENDS = ("spear", "spears", "axe", "axes", "sickle", "sickles")
SPEAR_STONES = ("obsidian", "flint")  # what a spear is knapped from, the best first
POACHERS = frozenset({"kaz"})  # hunts in the Lord's woods when band B's grass is empty (10 §3.6)
POACH_AFTER = 2  # searches of the band's own ground without game before he is tempted
FLINT_TRIES = 3  # flint mined (one nodule each) before knapping
# band B's hunger choice (10 §3.6): two lean days running (the camp's food short), then a raid or gold, as the leader
# tells it at the fire
LEAN_FOOD = 60.0
LEAN_DAYS = 2
RAIDERS = frozenset({"barro", "kaz", "nim"})
PANNERS = frozenset({"barro", "nim"})
CALLS = {  # what band B's leader tells the band at the fire, by the choice
    "raid": "Tonight we take rice from the town's racks.",
    "gold": "Tomorrow we pan gold at the falls pool for rice.",
}
RAID_CHANCE = 0.75  # Barro's boldness and temper (10 §3.1; 0.6 before Q1, D190: too few raids for the watch to judge)
COUNSEL = 0.3  # Vesa counsels against raids (10 §3.1: −0.3)
RAID = 75.0  # the night's raid: over sleep (70), under danger and real need
FIELDS = "the rice fields"
RICE_RACK = "a rice rack"  # the town's hasa racks by the paddies, where the day's rice dries overnight
LADEN = "hung with rice"  # a rice rack with the day's rice drying on it
LADEN_RACK = f"{RICE_RACK} {LADEN}"
RACK_SEARCHES = 4  # short walks about the rice fields at night looking for the racks before going home
BUNDLE_MINUTES = 5  # tying the rice taken off a rack into a bundle before heading home
NIGHT_SHARE = "take the night's strip"
PANS = 3  # pans at the falls pool a trip (each finds a grain half the time)
JUDGE = 60.0  # a leader's justice at the fire: over the day's work
JUDGE_TRIES = 4  # seizing and judging tries a day
BAND_FINE = 5  # mon a band leader fines a wrong


@dataclass(frozen=True)
class Forager:
    outing: int  # gathers before heading back to camp
    chore: str | None  # wood or reeds, gathered once a day for the camp
    rests: int  # minutes of rest at camp between outings


def _today(ctx: Context) -> int:
    """The band's day count by the camp's sun (the first day is 1): the first daytime look after a night starts the
    next. Only deep night counts as one (going to sleep is a night choice), not the edges of the dark: the words of
    the sun flicker there as someone walks east or west."""
    if ctx.perception.time_of_day == "night":
        ctx.notes["night"] = True
    elif _daytime(ctx) and ctx.notes.get("night") is not False:
        ctx.notes["days"] = ctx.counter("days") + 1
        ctx.notes["night"] = False
    return ctx.counter("days")


def _about_camp(ctx: Context) -> bool:
    """At camp or in the home ring about it: not far from camp, or at one of its home-ring spots."""
    p = ctx.perception
    return near(p, ctx.profile.home_area) or any(
        at(p, spot.name) for spot in ctx.profile.spots if spot.metres <= HOME_RING_M
    )


def _forage(ctx: Context, style: Forager) -> list[Option]:
    p, api = ctx.perception, ctx.api
    _today(ctx)
    _hear_kills(ctx)
    if style.chore is not None and ctx.finished(f"gather {style.chore}"):  # gathered to the end, not cut short
        ctx.mark_done(style.chore)
    home_area = ctx.profile.home_area
    food = carried_food(p.you)
    hungry_empty = ctx.needs.hunger >= 2 and not food
    supper = (  # band A's strips are trading stock it may yet eat at supper; band B takes its night strip anyway
        ctx.profile.region == "band_a"
        and ctx.phase in ("dusk", "night")
        and harmful_by_morning(ctx.needs.hunger, NIGHT_HUNGER)
        and not food
    )
    feeding = (  # at supper a strip rather than sleep hungry, but no search in the dark for a little hunger
        _feed_the_starving(ctx, food)
        or (_eat_at_rack(ctx) if hungry_empty or supper else [])
        or tend_the_hurt(ctx, strangers=False)
    )
    if feeding:
        return feeding
    _reckon_lean(ctx, food)
    _hear_the_choice(ctx)
    hunger_choice = _choose_at_fire(ctx) or _raid(ctx) or _judge_at_fire(ctx)
    if hunger_choice:
        return hunger_choice
    if ctx.phase == "dusk":
        return _night_share(ctx) + _evening_chores(ctx) + _keep_fire(ctx, 48.0)
    if not _daytime(ctx) and not hungry_empty:
        return _keep_fire(ctx, 72.0, only_failing=True)
    score = 90.0 if hungry_empty else WORK
    aim = "Find something to eat" if hungry_empty else "Gather food for the camp"
    why: Driver = "hunger" if hungry_empty else "duty"
    gathers = ctx.counter("outing")
    if (at_home(p) or at(p, home_area)) and ctx.notes.get("returning") and not hungry_empty:

        def back() -> None:
            _set(ctx, "returning", False)
            _set(ctx, "outing", 0)
            _end_trip(ctx)

        return [Option(WORK, "rest at camp", _then(back, lambda: api.rest(style.rests)), *AT_EASE)]
    scavenging = _scavenge(ctx)
    if scavenging:
        return scavenging
    if not hungry_empty:
        for errand in (_trade, _trek, _gold_trip, _tell_kill, _share_meat, _dry_meat, _knap, _logs):
            options = errand(ctx)
            if options:
                return options
    fresh = food_value({name: count for name, count in food.items() if name in FOODS})
    if not hungry_empty and gathers >= style.outing:
        head_back = _then(lambda: _set(ctx, "returning", True), lambda: api.walk_to_place("home", ctx.pace))
        return [Option(score, "go home", head_back, "Bring the food back to camp")]
    full = full_load(p, ctx.notes.get("full"))  # told there is no room for more
    wanted = [] if fresh >= OUTING_FOOD or full else list(FOODS)  # enough (or no room): chores, a look around, a rest
    if style.chore is not None and not ctx.done_today(style.chore) and food and not full:  # the chore once there's room
        wanted.insert(0, style.chore)
    if not hungry_empty:
        hunting = _hunt(ctx)
        if hunting:
            return hunting
    if wanted and ctx.profile.citizen_id in FISHERS and not hungry_empty:
        fishing = _fishing(ctx, gathers)
        if fishing:
            return fishing
    if not wanted:
        rested = ctx.notes.get("last") == "rest at camp"  # one rest at a time: then a look around
        if _about_camp(ctx) and (rested or ctx.chance(0.6)):
            direction = COMPASS[ctx.pick(len(COMPASS))]
            stroll = lambda: api.walk_towards(direction, "a short walk")  # noqa: E731  # a tiny closure reads best inline
            return [Option(score, "stroll", stroll, *AT_EASE)]
        if not (at_home(p) or at(p, home_area)):
            return [Option(score, "go home", lambda: api.walk_to_place("home", ctx.pace), *AT_EASE)]
        return [Option(score, "rest at camp", lambda: api.rest(style.rests), *AT_EASE)]
    seen = resources_in_view(p)
    food_wanted = [kind for kind in wanted if kind in FOODS]
    chore_here = any(r.distance == "here" and r.kind == style.chore for r in seen if r.kind in wanted)
    # in the home ring what's left is worth taking (it is all that grows back there) unless hunger presses; farther
    # out only plenty
    scraps = ctx.needs.hunger < 2 and fresh >= SCRAPS_FED and _about_camp(ctx)
    scraps = scraps and any(r.distance in SCRAPS_REACH for r in seen if r.kind in food_wanted)
    plenty = any(r.plenty for r in seen if r.kind in food_wanted)
    if food_wanted and not chore_here and not plenty and not scraps:
        trip = _forage_trip(ctx, score, aim, why)
        if trip:
            return trip
    here = [r for r in seen if r.distance == "here" and r.kind in wanted]
    if here:
        resource = min(here, key=lambda r: (wanted.index(r.kind), not r.plenty))

        def gathered() -> None:
            _set(ctx, "outing", gathers + 1)
            if resource.kind in FOODS and resource.plenty and ctx.notes.get("trip") is None and _about_camp(ctx):
                ctx.mark_done(RING_FIND)

        start = _then(gathered, lambda: api.gather(resource.kind))
        return [Option(score, f"gather {resource.kind}", start, _aim(aim, resource.kind, style), why)]
    visible = [r for r in seen if r.kind in wanted]
    if visible:
        target = min(visible, key=lambda r: (_reach(r), not r.plenty, wanted.index(r.kind)))
        start = lambda: api.walk_to_thing(target.label)  # noqa: E731  # a tiny closure reads best inline
        return [Option(score, f"go to {target.kind}", start, _aim(aim, target.kind, style), why)]
    if food_wanted or isinstance(ctx.notes.get("trip"), str):  # no outing for the day's wood alone
        trip = _forage_trip(ctx, score, aim, why)
        if trip:
            return trip
    if _about_camp(ctx):
        direction = COMPASS[ctx.pick(len(COMPASS))]
        return [Option(score, "search", lambda: api.walk_towards(direction, "a short walk"), aim, why)]
    return [Option(score, "go home", _then(lambda: _end_trip(ctx), _home(ctx)), "Head back to camp")]


def _feed_the_starving(ctx: Context, food: dict[str, int]) -> list[Option]:
    """A bandmate in view looking starved gets half of what you carry most of, if you carry about a day's food:
    walk up to them and hand it over (once a day for each; a band feeds its weak, 10 §3.5 shared food)."""
    p, api = ctx.perception, ctx.api
    if ctx.needs.hunger >= 2 or food_value(food) < SCRAPS_FED:
        return []
    starving = [
        person
        for person in p.people
        if is_name(person.label)
        and "looking starved" in (person.doing or "")
        and DISTANCE[person.nearness] in ("here", "near", "close")
        and not ctx.done_today(f"fed {person.label}")
    ]
    if not starving:
        return []
    who = starving[0].label
    aim = f"Give {who} something to eat"
    if not beside(starving[0]):
        return [Option(FEED, f"take food to {who}", partial(api.walk_to_person, who), aim, "social")]
    item = max(food, key=lambda name: (food[name] * FOOD_VALUE.get(name, 0.0), name))

    def give() -> ActionHandle:
        ctx.mark_done(f"fed {who}")
        api.give(f"half the {item}", who)
        return api.wait(2)

    return [Option(FEED, f"give {who} food", give, aim, "social")]


def _cut_short(ctx: Context, name: str) -> bool:
    """The option chosen last was this one and something cut its action short (not a refusal: that ends the trip)."""
    number = ctx.notes.get("chosen")
    result = ctx.api.handle(number).result if isinstance(number, int) else None
    return ctx.notes.get("last") == name and result is not None and result.outcome == "interrupted"


def _home(ctx: Context) -> Callable[[], ActionHandle]:
    return lambda: ctx.api.walk_to_place("home", ctx.pace)


def _end_trip(ctx: Context) -> None:
    ctx.notes.pop("trip", None)
    ctx.notes.pop("trip_legs", None)


def _forage_trip(ctx: Context, score: float, aim: str, why: Driver) -> list[Option]:
    """No food left in view: out farther, ring by ring (10 §1.2), early enough in the day to be back by dusk. First
    the home ring: its food spots by name, then short walks about camp; once it is picked over, an outing to a food
    spot farther out (a different one each time), or where no spot holds the food, a long walk out towards the band's
    food grounds (`BrainProfile.grounds`) and on a few short walks the same way. The usual gathering takes over as
    soon as food is in view, and the outing's gathers bring them home."""
    p = ctx.perception
    trip = ctx.notes.get("trip")
    if not isinstance(trip, str):
        return _set_out(ctx, score, aim, why)
    if p.time_of_day not in TRIP_TIMES:
        return []
    way = compass_word(trip)
    if way is None:
        return _at_spot(ctx, trip, score, aim, why)
    if _cut_short(ctx, "forage trip"):  # game came into view on the way out: on out
        out = lambda: ctx.api.walk_towards(way, "a long walk")  # noqa: E731  # a tiny closure reads best inline
        return [Option(score, "forage trip", out, f"Forage out to the {way}", why)]
    legs = ctx.counter("trip_legs")
    if _cut_short(ctx, "search further"):
        legs -= 1  # the leg cut short doesn't count
    if legs >= next((ground.legs for ground in ctx.profile.grounds if ground.way == way), 0):
        return []  # as far as the way stays clear of dens
    on = _then(lambda: _set(ctx, "trip_legs", legs + 1), lambda: ctx.api.walk_towards(way, "a short walk"))
    return [Option(score, "search further", on, aim, why)]


def _set_out(ctx: Context, score: float, aim: str, why: Driver) -> list[Option]:
    p, api = ctx.perception, ctx.api
    if not _about_camp(ctx) or p.time_of_day not in TRIP_TIMES:
        return []
    spots = ctx.profile.spots
    ring = [s for s in spots if s.metres <= HOME_RING_M and s.food >= RING_FOOD and not ctx.done_today(s.name)]
    ring = [s for s in ring if _ours(ctx, s)]
    if ring and not at(p, ring[0].name):
        return [_outing(ctx, ring[0].name, score, why)]
    searched = _count_today(ctx, "ring search")
    if searched < RING_SEARCHES:  # short walks out each way (the ring's food lies a few hundred paces out)
        turn = ctx.counter("ring way")  # kept from day to day, so the ways go round
        ways = ctx.profile.ring_ways
        way = ways[turn % len(ways)] if ways else COMPASS[turn * 3 % len(COMPASS)]

        def search() -> ActionHandle:
            ctx.mark_done("ring search")
            if searched % RING_LEGS == RING_LEGS - 1:
                _set(ctx, "ring way", turn + 1)
            return api.walk_towards(way, "a short walk")

        return [Option(score, "search", search, aim, why)]
    trips = ctx.counter("trips")
    farther = [s for s in spots if s.metres > HOME_RING_M and s.food >= FOOD_SPOT and _ours(ctx, s)]
    if farther:
        # a rich spot draws them from the ring: one outing to it a day while the ring feeds them (as many once it's
        # thin, or when hungry); a long walk out the food ways is no easier than the ring, so it isn't held back
        if ctx.done_today(FARTHER) and _count_today(ctx, RING_FIND) >= RING_FINDS and ctx.needs.hunger < 2:
            return []
        return [_outing(ctx, farther[trips % len(farther)].name, score, why, counted=True)]
    grounds = ctx.profile.grounds
    if not grounds:
        return []
    way = grounds[trips % len(grounds)].way

    def set_out(way: Compass = way) -> None:
        _set(ctx, "trip", way)
        _set(ctx, "trip_legs", 0)
        _set(ctx, "trips", trips + 1)

    out = _then(set_out, lambda: api.walk_towards(way, "a long walk"))
    return [Option(score, "forage trip", out, f"Forage out to the {way}", why)]


def _ours(ctx: Context, spot: Spot) -> bool:
    """Free to take from: nobody's, or the band's own claimed spot (not another group's: that's poaching)."""
    return spot.claim in (None, ctx.profile.region)


def _outing(ctx: Context, spot: str, score: float, why: Driver, counted: bool = False) -> Option:
    """Walk out to a named spot to forage there (`trip`: its name; `counted`: an outing past the home ring, so the
    next goes to the next spot)."""
    trips = ctx.counter("trips")

    def set_out() -> None:
        _set(ctx, "trip", spot)
        _set(ctx, "trip_legs", 0)
        ctx.mark_done(spot)
        if counted:
            _set(ctx, "trips", trips + 1)
            ctx.mark_done(FARTHER)

    return Option(score, f"go to {spot}", _then(set_out, _walk_to(ctx, spot)), f"Forage at {spot}", why)


def _walk_to(ctx: Context, place: str) -> Callable[[], ActionHandle]:
    return lambda: ctx.api.walk_to_place(place, ctx.pace)


def _at_spot(ctx: Context, spot: str, score: float, aim: str, why: Driver) -> list[Option]:
    """Out on an outing to a named spot with no food in view: on to it (a walk cut short, or refused), then a few short
    walks about it, then home."""
    p = ctx.perception
    legs = ctx.counter("trip_legs")
    if not at(p, spot) and legs == 0:
        if _refused(ctx, f"go to {spot}"):
            return []
        return [Option(score, f"go to {spot}", _walk_to(ctx, spot), f"Forage at {spot}", why)]
    if legs >= SPOT_SEARCHES:
        return []
    direction = COMPASS[ctx.pick(len(COMPASS))]
    on = _then(lambda: _set(ctx, "trip_legs", legs + 1), lambda: ctx.api.walk_towards(direction, "a short walk"))
    return [Option(score, "search further", on, aim, why)]


def _fishing(ctx: Context, gathers: int) -> list[Option]:
    """A fisher's first outing of the day: to the band's fishing spot by name, up to a fishing spot there, and a few
    casts (each counts as a gather towards heading home)."""
    p, api = ctx.perception, ctx.api
    if ctx.done_today("fished"):
        return []
    spot = next((s.name for s in ctx.profile.spots if "fish" in s.goods), None)
    if spot is None:
        return []
    aim = f"Fish at {spot}"
    if fishing_here(p) or ctx.finished("go to the fishing spot") or ctx.finished("fish"):
        if _count_today(ctx, "cast") >= FISH_TRIES:
            ctx.mark_done("fished")
            return []

        def cast() -> ActionHandle:
            ctx.mark_done("cast")
            _set(ctx, "outing", gathers + 1)
            return api.fish()

        return [Option(WORK, "fish", cast, aim)]
    if at(p, spot):
        if _refused(ctx, "go to the fishing spot") or _refused(ctx, "fish"):  # taken, or too far: forage here instead
            ctx.mark_done("fished")
            return []
        return [Option(WORK, "go to the fishing spot", lambda: api.walk_to_thing(FISHING), aim)]
    if not _about_camp(ctx) or p.time_of_day not in TRIP_TIMES:
        return []
    return [replace(_outing(ctx, spot, WORK, "duty"), aim=aim)]


def _scavenge(ctx: Context) -> list[Option]:
    """Meat or fish lying about (what a predator left of its kill, 10 §4.6) is food for the taking while no predator
    prowls in view: walk up to it, pick it up and bring it home."""
    p, api = ctx.perception, ctx.api
    if prowler(p) is not None or full_load(p, ctx.notes.get("full")):
        return []
    food = next(
        (
            t
            for t in p.things
            if t.label.endswith(LYING_FOOD) and "dried meat" not in t.label and DISTANCE[t.nearness] != "far"
        ),
        None,
    )
    if food is None:
        return []
    item = "fish" if food.label.endswith("fish on the ground") else "meat"
    aim = f"Take the {item} lying there home"
    if food.nearness != "right beside you":
        return [Option(SCAVENGE, f"go to the {item}", partial(api.walk_to_thing, food.label), aim)]

    def take() -> ActionHandle:
        api.pick_up(item)
        return api.walk_to_place("home")

    return [Option(SCAVENGE, f"pick up the {item}", take, aim)]


def _aim(aim: str, kind: str, style: Forager) -> str:
    """The camp's daily wood or reeds are a chore of their own, not food."""
    return f"Gather {kind} for the camp fire" if kind == style.chore else aim


def _hunt(ctx: Context) -> list[Option]:
    """Hunters hunt by day. Those who know hunting grounds set out at first light to the day's one (each hunter of the
    band starts at a different ground and moves on to the next each day, so the herds are spread over) and look
    about it; the rest search around camp. Game in view is stalked unless only one or two of a herd are left in
    sight (spare the herd); meat goes home to the fire."""
    p, api = ctx.perception, ctx.api
    if "hunting" not in ctx.profile.skills or not _daytime(ctx):
        return []
    sharing = _share_meat(ctx)
    if sharing or ctx.done_today("hunt"):
        return sharing
    tries = _count_today(ctx, "hunt-try")
    if carried_food(p.you).get("meat") and tries:  # today's kill (yesterday's meat is dried at camp, the hunt goes on)
        ctx.mark_done("hunt")
        for ground_name in ctx.profile.hunting_grounds:
            if at(p, ground_name):
                ctx.notes["kill ground"] = [ground_name, _today(ctx)]
                _spare(ctx, ground_name)
        home = Option(WORK + 5, "bring the meat home", lambda: api.walk_to_place("home"), "Bring the meat home")
        return [] if at_home(p) else [home]
    if tries >= HUNT_TRIES:
        return []
    grounds = ctx.profile.hunting_grounds
    day = _today(ctx)
    turn, of = ctx.profile.hunt_turn
    if not grounds and day % of != turn:
        return []  # another hunter's day on the grass round camp
    rotation = [grounds[(day - 1 + k) % len(grounds)] for k in range(len(grounds))]
    ground = next((name for name in rotation if not _spared(ctx, name)), None)  # the day's ground, or the next
    if grounds and ground is None:
        return []  # every ground the band hunts lost a beast lately: their herds are left to recover
    poach = _poach_spot(ctx)
    where_allowed = ground is None or at(p, ground) or _about_camp(ctx)  # the day's ground, or about camp
    where_allowed = where_allowed or (poach is not None and at(p, poach))
    hunted = {
        name for word, name in GAME_WORDS for a in p.animals if a.label.startswith("the remains") and word in a.label
    }
    seen = [(name, animal) for name, animal in game(p) if not _thin(animal.label) and name not in hunted]
    seen = seen if where_allowed else []  # a herd one of them was taken from lately (its remains lie about) is spared
    if seen:
        name = seen[0][0]
        hunt = _then(lambda: ctx.mark_done("hunt-try"), lambda: api.hunt(name))
        return [Option(WORK + 5, f"hunt {name}", hunt, HUNT)]
    searches = _count_today(ctx, "game-search")
    if poach is not None and searches >= POACH_AFTER and _tempted(ctx):
        if not at(p, poach) and not _refused(ctx, f"go to {poach}") and p.time_of_day in TRIP_TIMES:
            return [Option(WORK + 4, f"go to {poach}", _walk_to(ctx, poach), f"Hunt in {poach}")]
    if searches >= HUNT_TRIES:
        return []
    if ground is not None:
        aim = f"Hunt at {ground}"
        if not at(p, ground) and searches == 0:
            if _refused(ctx, f"go to {ground}"):
                return []
            score = FIRST_LIGHT if p.time_of_day == "dawn" else WORK + 4
            return [Option(score, f"go to {ground}", _walk_to(ctx, ground), aim)]
        direction = COMPASS[ctx.pick(len(COMPASS))]
        search = _then(lambda: ctx.mark_done("game-search"), lambda: api.walk_towards(direction, "a short walk"))
        return [Option(WORK + 4, "look for game", search, aim)]
    if near(p, ctx.profile.home_area):
        direction = COMPASS[ctx.pick(len(COMPASS))]
        distance: RoughDistance = "a short walk" if searches == 0 else "a long walk"
        search = _then(lambda: ctx.mark_done("game-search"), lambda: api.walk_towards(direction, distance))
        return [Option(WORK + 4, "look for game", search, HUNT)]
    return []


def _poach_spot(ctx: Context) -> str | None:
    """Kaz's poaching ground (10 §3.6): the game spot he knows on another group's claim (the Lord's woods)."""
    if ctx.profile.citizen_id not in POACHERS:
        return None
    return next((s.name for s in ctx.profile.spots if s.game and not _ours(ctx, s)), None)


def _tempted(ctx: Context) -> bool:
    """No game on the band's ground after the day's searches: tempted to poach with p = 1 - honesty, rolled once a
    day."""
    if not ctx.done_today("poach roll"):
        ctx.mark_done("poach roll")
        if ctx.chance(1.0 - ctx.profile.honesty):
            ctx.mark_done("poach")
    return ctx.done_today("poach")


def _thin(label: str) -> bool:
    """One or two of a herd in sight ("a deer", "two goats"): spared, so hunting never takes a herd down to nothing."""
    words = label.split()
    return words[0] == "two" or (words[0] in ("a", "an") and len(words) == 2)


def _spare(ctx: Context, ground: str) -> None:
    spared = ctx.notes.setdefault("spared", {})
    if not isinstance(spared, dict):
        raise TypeError("spared must be a dict")
    spared[ground] = _today(ctx)


def _spared(ctx: Context, ground: str) -> bool:
    """A beast was taken at this ground (by you or, as heard at camp, a bandmate) within the last `SPARE_DAYS` band
    days: its herd is left to recover (issue #130: hunters in turn took four of one herd in two days)."""
    spared = ctx.notes.get("spared")
    day = spared.get(ground) if isinstance(spared, dict) else None
    return isinstance(day, int) and _today(ctx) - day < SPARE_DAYS


def _hear_kills(ctx: Context) -> None:
    """A hunter back at camp calls out where the game was taken; every bandmate who hears it spares that ground."""
    for heard in ctx.perception.heard:
        if heard.words.startswith(KILL_CALL):
            _spare(ctx, heard.words.removeprefix(KILL_CALL).removesuffix("."))


def _tell_kill(ctx: Context) -> list[Option]:
    """Back at camp after a kill at a hunting ground, tell the band where (once): the herd there is spared a while."""
    p, kill = ctx.perception, ctx.notes.get("kill ground")
    if not isinstance(kill, list) or kill[1] != _today(ctx) or ctx.done_today("told kill"):
        return []
    if not (at_home(p) or at(p, ctx.profile.home_area)):
        return []

    def tell() -> ActionResult:
        ctx.mark_done("told kill")
        return ctx.api.say(f"{KILL_CALL}{kill[0]}.", "shout")  # across the camp

    aim = "Tell the band where the game was taken"
    return [Option(WORK + 6, "tell the band of the kill", lambda: _instant(ctx, tell), aim, "social")]


def _share_meat(ctx: Context) -> list[Option]:
    """Back at camp with meat, a hunter hands half of it to the nearest one close by (walking up to them first), once
    a day."""
    p, api = ctx.perception, ctx.api
    if ctx.done_today("shared meat") or carried_food(p.you).get("meat", 0) < 2:
        return []
    if not (at_home(p) or at(p, ctx.profile.home_area)):
        return []
    close = [person for person in p.people if DISTANCE[person.nearness] in ("here", "near", "close")]
    if not close:
        return []
    who = close[0].label
    aim = f"Share meat with {who}"
    if not beside(close[0]):
        return [Option(WORK + 5, f"take meat to {who}", partial(api.walk_to_person, who), aim, "social")]

    def share() -> ActionHandle:
        ctx.mark_done("shared meat")
        api.give("half the meat", who)
        return api.rest(20)

    return [Option(WORK + 5, "share the meat", share, aim, "social")]


def _carrying(p: Perception, *words: str) -> bool:
    """Carrying something these words name ("two flint nodules": flint), not a tool made of it ("a flint spear")."""
    return any(set(words) & set(line.split()) and not line.endswith(TOOL_ENDS) for line in p.you.carrying)


def _by_rack(ctx: Context) -> Seen | None:
    """The camp's rack when at camp with it in view."""
    p = ctx.perception
    if not (at_home(p) or at(p, ctx.profile.home_area)):
        return None
    return next((thing for thing in p.things if thing.label == RACK), None)


def _at_rack(ctx: Context, rack: Seen) -> bool:
    return rack.nearness == "right beside you" or ctx.finished(f"go to {RACK}") or ctx.finished("dry meat")


def _eat_at_rack(ctx: Context) -> list[Option]:
    """Hungry at camp with nothing carried: eat from the band's strips on the rack (the camp's food store, 10 §2.6)
    until it runs out for the day."""
    rack = _by_rack(ctx)
    if rack is None or ctx.done_today("rack bare"):
        return []
    trading_soon = _today(ctx) % TRADE_EVERY in ((TRADE_DAY - 1) % TRADE_EVERY, TRADE_DAY % TRADE_EVERY)
    bedtime = ctx.phase in ("dusk", "night")  # going to sleep hungry with nothing: urgent, the stock may go
    if ctx.profile.region == "band_a" and trading_soon and ctx.needs.hunger < 3 and not bedtime:
        return []  # band A's strips are its trading stock (10 §2.7): kept for the trip the day before and on the day
    if _refused(ctx, "eat at the rack"):
        ctx.mark_done("rack bare")
        return []
    aim = "Eat from the band's store"
    if _at_rack(ctx, rack) or ctx.finished("eat at the rack"):
        return [Option(91.0, "eat at the rack", lambda: ctx.api.eat("dried meat"), aim, "hunger")]
    return [Option(91.0, f"go to {RACK}", partial(ctx.api.walk_to_thing, RACK), aim, "hunger")]


def _dry_meat(ctx: Context) -> list[Option]:
    """Back at camp with raw meat (it spoils by half each dawn), dry it on the camp's rack (1-5 pieces a go, 30 min,
    10 §2.3); then leave the strips beyond a few, and any hides, on the rack for the band and its trading trips."""
    p, api = ctx.perception, ctx.api
    rack = _by_rack(ctx)
    if rack is None:
        return []
    food = carried_food(p.you)
    meat, strips = food.get("meat", 0), food.get("dried meat", 0)
    if meat and not _refused(ctx, "dry meat"):  # refused: the rack is taken (eat it, or dry it later)
        aim = "Dry the meat on the rack"
        if _at_rack(ctx, rack):
            return [Option(WORK + 5, "dry meat", lambda: api.craft("dried meat"), aim)]
        return [Option(WORK + 5, f"go to {RACK}", partial(api.walk_to_thing, RACK), aim)]
    hides = _carrying(p, "hide", "hides")
    if not (hides or strips > KEEP_STRIPS) or not _at_rack(ctx, rack):
        return []

    def store() -> ActionHandle:
        if hides:
            api.stash("hide", 9)
        if strips > KEEP_STRIPS:
            api.stash("dried meat", strips - KEEP_STRIPS)
        return api.rest(5)

    return [Option(WORK + 5, "put the goods on the rack", store, "Keep the band's goods on the rack")]


def _trade(ctx: Context) -> list[Option]:
    """Band A's trading trip (10 §2.7, §3.6), every 4th day by the camp's count: the leader and the toolmaker take the
    band's hides and strips from the rack to the stall in their early afternoon (the town's morning), sell them, buy
    rice (the toolmaker an obsidian shard first, for spears) and head home; a shut stall is waited for until late
    afternoon."""
    p, api = ctx.perception, ctx.api
    day = _today(ctx)
    if ctx.profile.citizen_id not in TRADERS or day % TRADE_EVERY != TRADE_DAY % TRADE_EVERY:
        return []
    if ctx.done_today("traded"):
        return _back_from_town(ctx)
    aim = "Trade the band's hides and meat in town"
    going = ctx.notes.get("trading") is True
    if p.time_of_day in STALL_LATE or not (going or p.time_of_day in TRADE_TIMES):
        if going:
            _done_trading(ctx)
        return []
    if at(p, MARKET):
        return [_at_stall(ctx, aim, (("hide", 99), ("dried meat", 2 * KEEP_STRIPS)))]
    if going:
        return [Option(ERRAND, f"go to {MARKET}", _walk_to(ctx, MARKET), aim)]
    rack = _by_rack(ctx)
    if rack is not None and not _at_rack(ctx, rack):
        return [Option(ERRAND, f"go to {RACK}", partial(api.walk_to_thing, RACK), aim)]

    def take_goods() -> ActionHandle:
        if rack is not None:
            api.pick_up("2 hides")
            api.pick_up(f"{2 * KEEP_STRIPS} dried meat")
        carrying = api.check_self().carrying
        if not any(_goods_word(line) for line in carrying):  # nothing the stall buys: no trip this time
            _done_trading(ctx)
            return api.rest(10)
        ctx.notes["trading"] = True
        return api.walk_to_place(MARKET, ctx.pace)

    return [Option(ERRAND, "take the goods to town", take_goods, aim)]


def _at_stall(ctx: Context, aim: str, goods: tuple[tuple[str, int], ...]) -> Option:
    """At the market: sell the goods (up to so many of each, as many as carried and the stall takes) and buy rice at
    the open stall, then home; wait while it is shut."""
    api = ctx.api
    if ctx.perception.market is None:
        if _count_today(ctx, "stall wait") >= STALL_WAITS:  # the town's sun, not the camp's: give up by the count

            def give_up() -> ActionHandle:
                _done_trading(ctx)
                return api.walk_to_place("home", ctx.pace)

            return Option(ERRAND, "go home", give_up, "Head back to camp")
        return Option(
            ERRAND, "wait for the stall", _then(lambda: ctx.mark_done("stall wait"), lambda: api.wait(15)), aim
        )

    gold = any(item == "gold" for item, _ in goods)  # a gold trip buys less: band B mustn't empty the stall

    def deal() -> ActionHandle:
        for item, most in goods:
            api.sell(item, most)
        if ctx.profile.citizen_id in TOOLMAKERS:
            api.buy("obsidian", 1)
        api.buy("rice", GOLD_RICE if gold else RICE_BOUGHT)  # or as much as the coins pay for
        _done_trading(ctx)
        return api.walk_to_place("home", ctx.pace)

    return Option(ERRAND, "trade at the stall", deal, aim, "ambition")


def _goods_word(line: str) -> bool:
    """A carried line the stall buys from band A: hides, or strips of dried meat."""
    return line.endswith(("hide", "hides", "dried meat"))


def _back_from_town(ctx: Context) -> list[Option]:
    """Traded: straight back to camp (nothing is taken from the town's ground on the way)."""
    if _about_camp(ctx) or at_home(ctx.perception):
        return []
    return [Option(ERRAND, "go home", _home(ctx), "Head back to camp")]


def _done_trading(ctx: Context) -> None:
    ctx.mark_done("traded")
    ctx.notes.pop("trading", None)


def _trek(ctx: Context) -> list[Option]:
    """Nim's obsidian trek (10 §3.6), every 6th day by band B's count: at first light to the Obsidian field, mine four
    shards, take them to the stall on the way back (band B's morning is the stall's hours), buy rice and come home."""
    p, api = ctx.perception, ctx.api
    day = _today(ctx)
    if ctx.profile.citizen_id not in TREKKERS or day % TREK_EVERY != TREK_DAY % TREK_EVERY:
        ctx.notes.pop("trekking", None)
        return []
    if ctx.done_today("traded"):
        return _back_from_town(ctx)
    field = next((s.name for s in ctx.profile.spots if "obsidian" in s.goods), None)
    aim = "Fetch obsidian to sell in town"
    going = ctx.notes.get("trading") is True
    if at(p, MARKET):
        return [_at_stall(ctx, aim, (("obsidian", 99), ("hide", 99)))]
    if p.time_of_day in STALL_LATE:
        if going or ctx.done_today("trek"):
            _done_trading(ctx)
        return []
    if going:
        return [Option(ERRAND, f"go to {MARKET}", _walk_to(ctx, MARKET), aim)]
    if field is None or _count_today(ctx, "shard") >= TREK_SHARDS:
        ctx.notes["trading"] = True
        return [Option(ERRAND, f"go to {MARKET}", _walk_to(ctx, MARKET), aim)]
    if not at(p, field):  # on the way (the long walk is offered again each look till she gets there)
        walking = ctx.notes.get("trekking") is True
        if ctx.done_today("trek") or _refused(ctx, f"go to {field}") or not (walking or p.time_of_day in TREK_TIMES):
            ctx.notes.pop("trekking", None)
            return []  # left the field (or too late to go, or no way there): the trek's mining is over
        set_out = _then(lambda: ctx.notes.__setitem__("trekking", True), _walk_to(ctx, field))
        return [Option(ERRAND, f"go to {field}", set_out, aim)]
    if not ctx.done_today("trek"):
        ctx.mark_done("trek")
    ctx.notes.pop("trekking", None)
    seen = [r for r in resources_in_view(p) if r.kind == "obsidian"]
    here = [r for r in seen if r.distance == "here"]
    if here:
        mine = _then(lambda: ctx.mark_done("shard"), lambda: api.gather("obsidian"))
        return [Option(ERRAND, "mine obsidian", mine, aim)]
    if seen and not _refused(ctx, "go to the obsidian"):
        return [Option(ERRAND, "go to the obsidian", partial(api.walk_to_thing, seen[0].label), aim)]
    ctx.notes["trading"] = True  # none left to mine: off to the stall with what there is
    return [Option(ERRAND, f"go to {MARKET}", _walk_to(ctx, MARKET), aim)]


def _leads(ctx: Context) -> bool:
    return "leader" in ctx.profile.role.lower()


def _reckon_lean(ctx: Context, food: dict[str, int]) -> None:
    """At dusk band B's leader reckons the band's day (10 §3.6: the camp's food short): the camp's rack bare at the
    night's share, the leader hungry at some point of it, or carrying less than a day's food make it a lean one
    (`lean`: lean days running)."""
    if ctx.profile.region != "band_b" or not _leads(ctx):
        return
    if ctx.needs.hunger >= 2 and not ctx.done_today("went hungry"):
        ctx.mark_done("went hungry")
    if ctx.phase not in ("dusk", "night") or ctx.done_today("reckoned"):
        return
    if ctx.phase == "dusk" and not ctx.done_today(NIGHT_SHARE):
        return  # the night's share from the rack first: a bare rack is a lean day
    ctx.mark_done("reckoned")
    lean = ctx.done_today("went hungry") or food_value(food) < LEAN_FOOD or ctx.done_today("rack bare")
    _set(ctx, "lean", ctx.counter("lean") + 1 if lean else 0)


def _choose_at_fire(ctx: Context) -> list[Option]:
    """After two lean days running band B's leader chooses at the fire (10 §3.6): a raid on the town's racks that
    night, or a gold trip next morning to buy rice (one roll a band day from the world's seed: p of a raid =
    `RAID_CHANCE` less Vesa's counsel), and tells the band; whoever hears it goes along."""
    if ctx.profile.region != "band_b" or not _leads(ctx) or ctx.counter("lean") < LEAN_DAYS:
        return []
    if ctx.done_today("chose") or ctx.phase not in ("dusk", "night") or not at_home(ctx.perception):
        return []
    roll = Rng.for_subsystem(ctx.seed, f"brains.band_hunger:{ctx.profile.region}:{_today(ctx)}").random()
    choice = "raid" if roll < RAID_CHANCE - COUNSEL else "gold"

    def tell() -> ActionResult:
        ctx.mark_done("chose")
        _note_choice(ctx, choice)
        return ctx.api.say(CALLS[choice], "shout")  # across the camp: whoever is about hears it

    return [
        Option(RAID + 1, "tell the band", lambda: _instant(ctx, tell), "Tell the band what we do for food", "hunger")
    ]


def _hear_the_choice(ctx: Context) -> None:
    """A band B member who hears the leader's choice at the fire notes it for the night or the morning after."""
    if ctx.profile.region != "band_b":
        return
    for heard in ctx.perception.heard:
        for choice, words in CALLS.items():
            if words in heard.words:
                _note_choice(ctx, choice)


def _note_choice(ctx: Context, choice: str) -> None:
    """`hunger choice`: [choice, the band day it is for] (a raid tonight, a gold trip tomorrow)."""
    ctx.notes["hunger choice"] = [choice, _today(ctx) + (1 if choice == "gold" else 0)]


def _hungry_choice(ctx: Context) -> str | None:
    """Band B's hunger choice for today as its leader told it at the fire (10 §3.6), or None."""
    told = ctx.notes.get("hunger choice")
    return str(told[0]) if isinstance(told, list) and told[1] == _today(ctx) else None


def _night_share(ctx: Context) -> list[Option]:
    """At dusk a band B member takes a strip from the camp's rack for the night; a bare rack tells the camp's food ran
    short (a lean day, 10 §3.6)."""
    if ctx.profile.region != "band_b" or ctx.phase != "dusk" or ctx.done_today(NIGHT_SHARE):
        return []
    rack = _by_rack(ctx)
    if rack is None:
        return []
    if _refused(ctx, NIGHT_SHARE):
        ctx.mark_done("rack bare")
        ctx.mark_done(NIGHT_SHARE)
        return []
    aim = "Take a strip from the rack for the night"
    if not _at_rack(ctx, rack):
        return [Option(47.0, f"go to {RACK}", partial(ctx.api.walk_to_thing, RACK), aim)]

    def take() -> ActionResult:
        result = ctx.api.pick_up("1 dried meat")
        if result.outcome == "failed":
            ctx.mark_done("rack bare")
        ctx.mark_done(NIGHT_SHARE)
        return result

    return [Option(47.0, NIGHT_SHARE, lambda: _instant(ctx, take), aim)]


def _instant(ctx: Context, act: Callable[[], ActionResult]) -> ActionHandle:
    """An instant action, then a moment's rest (an option starts something that runs)."""
    act()
    return ctx.api.rest(5)


def _raid(ctx: Context) -> list[Option]:
    """The raiders go to the rice fields in band B's evening (the town's night) and take rice from a rack hung with it,
    then home (a theft, and a night trespass inside the walls: Goro's watch may catch them). With no rack in sight
    hung with rice they walk up to the racks to look them over, or a few steps each way round the fields when no rack
    is in sight at all (night sight is short), then go home with nothing. Bundling the rice takes a few minutes at
    the rack (the watch may catch them at it). A raid over (or given up, or the night nearly gone) with the raider
    still away from camp, home is all that is left (issue #131: never asleep inside the walls)."""
    p, api = ctx.perception, ctx.api
    if ctx.profile.citizen_id not in RAIDERS:
        return []
    if ctx.phase not in ("dusk", "night") or at_home(p) or _about_camp(ctx):  # by day no law keeps them out of town
        ctx.notes.pop("raiding", None)
        if ctx.phase not in ("dusk", "night"):
            return []
    raiding = _hungry_choice(ctx) == "raid" and not ctx.done_today("raided") and p.time_of_day != "pre-dawn"
    if not raiding:
        if ctx.notes.get("raiding") is not True:
            return []
        return [Option(RAID, "go home", _home(ctx), "Get home from the raid", "hunger")]
    if any(word in p.you.feeling for word in HURT):  # badly hurt on the way: no raid tonight, home
        ctx.mark_done("raided")
        return _raid(ctx)
    ctx.notes["raiding"] = True
    aim = "Take rice from the town's racks"
    racks = [t for t in p.things if RICE_RACK.removeprefix("a ") in t.label and DISTANCE[t.nearness] != "far"]
    laden = next((t for t in racks if t.doing == LADEN), None)
    if laden is not None and (laden.nearness == "right beside you" or ctx.finished(f"go to {LADEN_RACK}")):

        def take() -> ActionHandle:
            ctx.mark_done("raided")
            api.pick_up("5 rice")
            return api.wait(BUNDLE_MINUTES)

        return [Option(RAID, "take rice from the racks", take, aim, "hunger")]
    if laden is not None and not _refused(ctx, f"go to {LADEN_RACK}"):
        return [Option(RAID, f"go to {LADEN_RACK}", partial(api.walk_to_thing, LADEN_RACK), aim, "hunger")]
    looked = ctx.finished(f"go to {RICE_RACK}") or _refused(ctx, f"go to {RICE_RACK}")
    if racks and not looked and not any(t.nearness == "right beside you" for t in racks):
        return [Option(RAID, f"go to {RICE_RACK}", partial(api.walk_to_thing, "rice rack"), aim, "hunger")]
    searches = _count_today(ctx, "rack search")
    there = ctx.finished(f"go to {FIELDS}") or _refused(ctx, f"go to {FIELDS}") or searches > 0
    if not racks and there and searches < RACK_SEARCHES:  # at the fields, the racks out of the night's sight
        way = COMPASS[2 * searches % len(COMPASS)]  # a few steps each way round
        search = _then(lambda: ctx.mark_done("rack search"), partial(api.walk_towards, way, "a few steps", ctx.pace))
        return [Option(RAID, "look for the racks", search, aim, "hunger")]
    if racks or there:
        home = _then(lambda: ctx.mark_done("raided"), partial(api.walk_to_place, "home", ctx.pace))
        return [Option(RAID, "go home with nothing", home, aim, "hunger")]  # nothing hangs on any rack in sight
    return [Option(RAID, f"go to {FIELDS}", _walk_to(ctx, FIELDS), aim, "hunger")]


def _gold_trip(ctx: Context) -> list[Option]:
    """The other way out of hunger (10 §3.6): Barro and Nim pan the falls pool in the morning and sell the gold at the
    stall for rice; once the pool is panned out, there's no gold to find and they come home."""
    p, api = ctx.perception, ctx.api
    if ctx.profile.citizen_id not in PANNERS or _hungry_choice(ctx) != "gold" or ctx.done_today("traded"):
        return _back_from_town(ctx) if ctx.done_today("traded") and ctx.profile.citizen_id in PANNERS else []
    pool = next((s.name for s in ctx.profile.spots if "gold" in s.goods), None)
    aim = "Pan gold to buy rice"
    going = ctx.notes.get("trading") is True
    if at(p, MARKET):
        return [_at_stall(ctx, aim, (("gold", 99),))]
    if going:
        return [Option(ERRAND, f"go to {MARKET}", _walk_to(ctx, MARKET), aim)]
    if pool is None:
        return []
    if not at(p, pool):  # on the way (a walk cut short goes on), unless refused or the pans are done
        if _count_today(ctx, "pan") or _refused(ctx, f"go to {pool}") or p.time_of_day not in TRIP_TIMES:
            return []
        return [Option(ERRAND, f"go to {pool}", _walk_to(ctx, pool), aim)]
    seen = [r for r in resources_in_view(p) if r.kind == "gold"]
    if _count_today(ctx, "pan") < PANS and seen:
        if seen[0].distance == "here":
            return [Option(ERRAND, "pan gold", _then(lambda: ctx.mark_done("pan"), lambda: api.gather("gold")), aim)]
        if not _refused(ctx, "go to the gold"):
            return [Option(ERRAND, "go to the gold", partial(api.walk_to_thing, seen[0].label), aim)]
    ctx.notes["trading"] = True  # panned (or nothing left to pan): to the stall with what there is
    return [Option(ERRAND, f"go to {MARKET}", _walk_to(ctx, MARKET), aim)]


def _judge_at_fire(ctx: Context) -> list[Option]:
    """A band leader seizes someone at camp known for a wrong and judges them at the fire (10 §3.4: a fine; in a
    band it goes to the one wronged)."""
    p, api = ctx.perception, ctx.api
    if not _leads(ctx) or not (at_home(p) or at(p, ctx.profile.home_area)):
        return []
    if _count_today(ctx, "judging") >= JUDGE_TRIES:
        return []
    for person in p.people:
        deed = known_deed(person)
        if deed is None or not is_name(person.label) or DISTANCE[person.nearness] == "far":
            continue
        aim = f"Judge {person.label} at the fire for what they did"
        held = (person.doing or "").startswith("held by")  # seized (as the town's law reads it too)
        if not beside(person):
            return [Option(JUDGE, f"go up to {person.label}", partial(api.walk_to_person, person.label), aim)]
        if not held:
            seize = _then(lambda: ctx.mark_done("judging"), partial(api.seize, person.label))
            return [Option(JUDGE, f"seize {person.label}", seize, aim, "duty")]
        judge = _then(lambda: ctx.mark_done("judging"), partial(api.judge, person.label, Fine(mon=BAND_FINE)))
        return [Option(JUDGE, f"judge {person.label}", judge, aim, "duty")]
    return []


def _knap(ctx: Context) -> list[Option]:
    """A hunter whose spear broke knaps another at the camp fire from a piece of wood and a stone (obsidian if they
    have any, else flint), fetching flint from the band's flint spot first; the toolmaker also knaps a stone axe
    (2 flint) when he has none (10 §2.3)."""
    p, api = ctx.perception, ctx.api
    skills = ctx.profile.skills
    if "hunting" in skills and not carries(p, "spear"):
        stone = next((s for s in SPEAR_STONES if _carrying(p, s)), None)
        recipe = f"{stone or 'flint'} spear"
    elif ctx.profile.citizen_id in TOOLMAKERS and "gathering" in skills and not carries(p, "axe"):
        stone, recipe = ("flint" if _carrying(p, "flint") else None), "stone axe"
    else:
        return []
    aim = f"Make a {recipe}"
    if _refused(ctx, "knap"):  # short of a stone (the axe takes two): fetch more; refused twice, try tomorrow
        ctx.mark_done("knap refused")
        ctx.notes["more flint"] = True
    if _count_today(ctx, "knap refused") >= 2:
        return []
    if stone is None or ctx.notes.get("more flint"):
        return _fetch_flint(ctx, aim)
    if not wood_at_hand(p):
        return []  # the day's wood chore brings some
    fire = fire_in_view(p)
    if fire is None or not (at_home(p) or at(p, ctx.profile.home_area)):
        return [Option(WORK + 3, "go home", _home(ctx), aim)] if _about_camp(ctx) else []
    if fire.nearness != "right beside you" and not ctx.finished("go to the fire"):  # the craft needs it within 4 m
        return [Option(WORK + 3, "go to the fire", lambda: api.walk_to_thing(FIRE), aim)]

    def knap() -> ActionHandle:
        if not carries(p, "wood"):
            api.pick_up("wood")  # from the fire's woodpile
        return api.craft(recipe)

    return [Option(WORK + 3, "knap", knap, aim)]


def _fetch_flint(ctx: Context, aim: str) -> list[Option]:
    """To the band's flint spot by name and mine a few nodules there."""
    p, api = ctx.perception, ctx.api
    spot = next((s.name for s in ctx.profile.spots if "flint" in s.goods and _ours(ctx, s)), None)
    if spot is None or _count_today(ctx, "flint") >= FLINT_TRIES:
        ctx.notes.pop("more flint", None)
        return []
    if not at(p, spot):
        if not _about_camp(ctx) or p.time_of_day not in TRIP_TIMES:
            return []
        return [Option(WORK + 3, f"go to {spot}", _walk_to(ctx, spot), aim)]
    seen = [r for r in resources_in_view(p) if r.kind == "flint"]
    here = [r for r in seen if r.distance == "here"]
    if here:

        def mine() -> ActionHandle:
            ctx.mark_done("flint")
            ctx.notes.pop("more flint", None)
            return api.gather("flint")

        return [Option(WORK + 3, "mine flint", mine, aim)]
    if seen and not _refused(ctx, "go to the flint"):
        return [Option(WORK + 3, "go to the flint", partial(api.walk_to_thing, seen[0].label), aim)]
    return []


def _logs(ctx: Context) -> list[Option]:
    """A tree just felled (the toolmaker's axe: his day's wood) leaves its logs by the stump: carry them home."""
    number = ctx.notes.get("chosen")
    result = ctx.api.handle(number).result if isinstance(number, int) else None
    if ctx.notes.get("last") != "gather wood" or result is None or not result.text.startswith("The tree falls"):
        return []

    def carry() -> ActionHandle:
        ctx.api.pick_up("wood")
        return ctx.api.walk_to_place("home", ctx.pace)

    return [Option(WORK + 3, "carry the logs home", carry, "Bring the felled tree's logs to the fire")]


def _keep_fire(ctx: Context, score: float, only_failing: bool = False) -> list[Option]:
    """Bands keep the camp fire going through the night: everyone feeds it once at dusk (so it burns till morning),
    and anyone awake at night tends a fire burning low; only those with the skill make one that went out."""
    p, api = ctx.perception, ctx.api
    state = fire_here(p)
    if ctx.finished("feed the fire"):  # fed to the end: talk or someone walking up cuts a feeding short
        ctx.mark_done("fed fire")
    if state is None or (state == "burning" and (only_failing or ctx.done_today("fed fire"))):
        return []
    if not wood_at_hand(p):
        return []
    at_hearth = any(t.nearness == "right beside you" and t.kind == "fire" for t in p.things)
    if not at_hearth:
        return [Option(score, "go to the fire", lambda: api.walk_to_thing(FIRE), KEEP_FIRE)]
    if state == "out":
        return [Option(score, "make a fire", api.make_fire, KEEP_FIRE)] if "fire" in ctx.profile.skills else []
    return [Option(score, "feed the fire", api.feed_fire, KEEP_FIRE)]


def _reach(resource: Resource) -> int:
    return ("here", "near", "close", "off", "far").index(resource.distance)


def _evening_chores(ctx: Context) -> list[Option]:
    """Put the day's wood and reeds down by the fire, then rest there (the rest itself is a common dusk option)."""
    p, api = ctx.perception, ctx.api
    fire = fire_in_view(p)
    by_fire = fire is not None and beside(fire)
    for item in ("wood", "reeds"):
        if carries(p, item) and by_fire:

            def put_down(item: str = item) -> ActionHandle:
                api.drop(item)
                return api.rest(30)

            return [Option(41, f"put down {item}", put_down, f"Put the day's {item} by the fire")]
    return []


FORAGERS: dict[Routine, Forager] = {
    "band_leader": Forager(outing=4, chore="wood", rests=30),
    "hunter": Forager(outing=5, chore="wood", rests=20),
    "healer": Forager(outing=3, chore="wood", rests=40),
    "gatherer": Forager(outing=5, chore="wood", rests=30),  # the camp fire burns about a dozen pieces a night
    "band_child": Forager(outing=2, chore=None, rests=45),
}


def _forager(routine: Routine) -> Callable[[Context], list[Option]]:
    style = FORAGERS[routine]
    return lambda ctx: _forage(ctx, style)


BAND_ROUTINES: dict[Routine, Callable[[Context], list[Option]]] = {routine: _forager(routine) for routine in FORAGERS}
