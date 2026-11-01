"""Role routines: what each kind of citizen does with an ordinary day once needs and night are taken care of.

Every routine returns scored options (needs and night outscore them; see `brain.py`). Bands forage around camp in
outings and come back; the town's routines live in `town.py`, built on the helpers here.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import get_args

from pydantic import JsonValue

from app.brains.profile import BrainProfile, Routine
from app.brains.senses import (
    DISTANCE,
    Needs,
    Phase,
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
    near,
    prowler,
    resources_in_view,
    wood_at_hand,
)
from app.world_api.facade import ActionHandle, WorldApi
from app.world_api.models import Compass, Driver, Pace, Perception, RoughDistance

WORK = 30.0  # the score of an ordinary day's routine
FOODS = ("roots", "nuts", "berries")  # wild food, most filling first
OUTING_FOOD = 150.0  # bands head back to camp carrying about this much (a day and a half of food)
COMPASS: tuple[Compass, ...] = get_args(Compass)
HUNT_TRIES = 3  # hunts (and as many searches for game) a hunter tries a day
TRIP_TIMES = frozenset({"dawn", "early morning", "mid-morning", "midday", "early afternoon"})  # time to be back
TRIP_LEGS = 4  # short walks on past where a forage trip's long walk ended, while no food shows (fewer near a den)
FISH_CHANCE = 0.3  # a forager standing at a river or lake fishes instead of gathering this often
FIRE = "the fire pit"
HUNT = "Hunt game for the band"
LYING_FOOD = ("meat on the ground", "fish on the ground")  # fresh: not "dried meat" (someone's store, not remains)
# a forager with enough food (or no room) rests, looks about camp and heads back: one aim, so goals don't flip
AT_EASE: tuple[str, Driver] = ("Take it easy about camp", "rest")
SCAVENGE = WORK + 6  # over a hunt: the meat is there already
KEEP_FIRE = "Keep the camp fire going"


@dataclass(frozen=True)
class Option:
    """A scored choice; `start` runs only if it is chosen (any notes it keeps are written then). `aim` is the goal it
    serves as spectators read it, with why (`driver`): the steps of one aim share it ("go to the rice fields", then
    "farm": "Tend the rice fields"); an option without an aim leaves the goal as it was."""

    score: float
    name: str
    start: Callable[[], ActionHandle]
    aim: str = ""
    driver: Driver = "duty"


def _then(note: Callable[[], None], start: Callable[[], ActionHandle]) -> Callable[[], ActionHandle]:
    def run() -> ActionHandle:
        note()
        return start()

    return run


@dataclass
class Context:
    """What a routine sees and can do at one decision point."""

    api: WorldApi
    profile: BrainProfile
    perception: Perception
    needs: Needs
    phase: Phase
    chance: Callable[[float], bool]
    pick: Callable[[int], int]
    pace: Pace = "walk"  # how walks home go: run when desperate or a predator prowls in view

    @property
    def notes(self) -> dict[str, JsonValue]:
        return self.api.notes

    def counter(self, key: str) -> int:
        value = self.notes.get(key, 0)
        return value if isinstance(value, int) else 0

    def done_today(self, chore: str) -> bool:
        chores = self.notes.get("chores", [])
        return isinstance(chores, list) and chore in chores

    def finished(self, name: str) -> bool:
        """The option chosen last was this one and its action ran to its end, not cut short (`chosen`: its number)."""
        number = self.notes.get("chosen")
        result = self.api.handle(number).result if isinstance(number, int) else None
        return self.notes.get("last") == name and result is not None and result.outcome == "done"

    def mark_done(self, chore: str) -> None:
        chores = self.notes.setdefault("chores", [])
        if isinstance(chores, list):
            chores.append(chore)


def _set(ctx: Context, key: str, value: JsonValue) -> None:
    ctx.notes[key] = value


def _go(ctx: Context, place: str, score: float = WORK, aim: str = "", driver: Driver = "duty") -> Option:
    return Option(score, f"go to {place}", lambda: ctx.api.walk_to_place(place), aim, driver)


def _on_spot(ctx: Context, walk: str) -> bool:
    """Still standing where this walk ended (`arrived`, kept by the brain): on the work slot it claimed (D118).
    Anywhere else in the place (a walk cut short, a rest on a bench, an errand there) the walk comes first: it lands
    on the slot, or says you are already there (issue #89: no long walks to a slot at the tick's end)."""
    return ctx.notes.get("arrived") == walk


def _work_at(
    ctx: Context, place: str, task: str, score: float = WORK, aim: str = "", driver: Driver = "duty"
) -> Option:
    if at(ctx.perception, place) and _on_spot(ctx, f"go to {place}"):
        return Option(score, task, lambda: ctx.api.work(task), aim, driver)
    return _go(ctx, place, score, aim, driver)


def _daytime(ctx: Context) -> bool:
    return ctx.phase in ("morning", "day")


# --- the bands ---


@dataclass(frozen=True)
class Forager:
    outing: int  # gathers before heading back to camp
    chore: str | None  # wood or reeds, gathered once a day for the camp
    rests: int  # minutes of rest at camp between outings


def _forage(ctx: Context, style: Forager) -> list[Option]:
    p, api = ctx.perception, ctx.api
    if style.chore is not None and ctx.finished(f"gather {style.chore}"):  # gathered to the end, not cut short
        ctx.mark_done(style.chore)
    home_area = ctx.profile.home_area
    food = carried_food(p.you)
    hungry_empty = ctx.needs.hunger >= 2 and not food
    if ctx.phase == "dusk":
        return _evening_chores(ctx) + _keep_fire(ctx, 48.0)
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
    if wanted and fishing_here(p) and ctx.chance(FISH_CHANCE):
        return [Option(score, "fish", api.fish, aim, why)]
    if not wanted:
        rested = ctx.notes.get("last") == "rest at camp"  # one rest at a time: then a look around
        if near(p, home_area) and (rested or ctx.chance(0.6)):
            direction = COMPASS[ctx.pick(len(COMPASS))]
            stroll = lambda: api.walk_towards(direction, "a short walk")  # noqa: E731  # a tiny closure reads best inline
            return [Option(score, "stroll", stroll, *AT_EASE)]
        if not (at_home(p) or at(p, home_area)):
            return [Option(score, "go home", lambda: api.walk_to_place("home", ctx.pace), *AT_EASE)]
        return [Option(score, "rest at camp", lambda: api.rest(style.rests), *AT_EASE)]
    seen = resources_in_view(p)
    food_wanted = [kind for kind in wanted if kind in FOODS]
    if food_wanted and not any(r.plenty for r in seen if r.kind in food_wanted):  # only scraps about: out farther
        trip = _forage_trip(ctx, score, aim, why)
        if trip:
            return trip
    here = [r for r in seen if r.distance == "here" and r.kind in wanted]
    if here:
        resource = min(here, key=lambda r: (wanted.index(r.kind), not r.plenty))

        def gathered() -> None:
            _set(ctx, "outing", gathers + 1)

        start = _then(gathered, lambda: api.gather(resource.kind))
        return [Option(score, f"gather {resource.kind}", start, _aim(aim, resource.kind, style), why)]
    visible = [r for r in seen if r.kind in wanted]
    if visible:
        target = min(visible, key=lambda r: (_reach(r), not r.plenty, wanted.index(r.kind)))
        start = lambda: api.walk_to_thing(target.label)  # noqa: E731  # a tiny closure reads best inline
        return [Option(score, f"go to {target.kind}", start, _aim(aim, target.kind, style), why)]
    trip = _forage_trip(ctx, score, aim, why)
    if trip:
        return trip
    if near(p, home_area):
        direction = COMPASS[ctx.pick(len(COMPASS))]
        return [Option(score, "search", lambda: api.walk_towards(direction, "a short walk"), aim, why)]
    return [Option(score, "go home", _then(lambda: _end_trip(ctx), _home(ctx)), "Head back to camp")]


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
    """No food left in view about camp (the home ring runs thin by day 3-4, 10 §1.2): walk out a long way towards
    the band's food grounds (`BrainProfile.grounds`, a different one each trip), then on a few short walks the same
    way until food shows; trips start early enough in the day to be back by dusk. The usual gathering takes over as
    soon as food is in view, and the outing's gathers bring them home."""
    p, api = ctx.perception, ctx.api
    way = compass_word(ctx.notes.get("trip"))
    if way is None:
        grounds = ctx.profile.grounds
        if not grounds or not near(p, ctx.profile.home_area) or p.time_of_day not in TRIP_TIMES:
            return []
        trips = ctx.counter("trips")
        way = grounds[trips % len(grounds)].way

        def set_out(way: Compass = way) -> None:
            _set(ctx, "trip", way)
            _set(ctx, "trip_legs", 0)
            _set(ctx, "trips", trips + 1)

        out = _then(set_out, lambda: api.walk_towards(way, "a long walk"))
        return [Option(score, "forage trip", out, f"Forage out to the {way}", why)]
    if p.time_of_day not in TRIP_TIMES:
        return []
    if _cut_short(ctx, "forage trip"):  # game came into view on the way out: on out
        return [
            Option(score, "forage trip", lambda: api.walk_towards(way, "a long walk"), f"Forage out to the {way}", why)
        ]
    legs = ctx.counter("trip_legs")
    if _cut_short(ctx, "search further"):
        legs -= 1  # the leg cut short doesn't count
    if legs >= next((ground.legs for ground in ctx.profile.grounds if ground.way == way), 0):
        return []  # as far as the way stays clear of dens
    on = _then(lambda: _set(ctx, "trip_legs", legs + 1), lambda: api.walk_towards(way, "a short walk"))
    return [Option(score, "search further", on, aim, why)]


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
    """Hunters hunt by day: game in view is stalked (hunters setting out together go for the same herd); else they
    search around camp a few times; meat goes home to the fire."""
    p, api = ctx.perception, ctx.api
    if "hunting" not in ctx.profile.skills or not _daytime(ctx):
        return []
    sharing = _share_meat(ctx)
    if sharing or ctx.done_today("hunt"):
        return sharing
    if carried_food(p.you).get("meat"):
        ctx.mark_done("hunt")
        home = Option(WORK + 5, "bring the meat home", lambda: api.walk_to_place("home"), "Bring the meat home")
        return [] if at_home(p) else [home]
    tries = _count_today(ctx, "hunt-try")
    if tries >= HUNT_TRIES:
        return []
    seen = game(p)
    if seen:
        name = seen[0][0]
        hunt = _then(lambda: ctx.mark_done("hunt-try"), lambda: api.hunt(name))
        return [Option(WORK + 5, f"hunt {name}", hunt, HUNT)]
    searches = _count_today(ctx, "game-search")
    if near(p, ctx.profile.home_area) and searches < HUNT_TRIES:
        direction = COMPASS[ctx.pick(len(COMPASS))]
        distance: RoughDistance = "a short walk" if searches == 0 else "a long walk"
        search = _then(lambda: ctx.mark_done("game-search"), lambda: api.walk_towards(direction, distance))
        return [Option(WORK + 4, "look for game", search, HUNT)]
    return []


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


def _count_today(ctx: Context, chore: str) -> int:
    chores = ctx.notes.get("chores", [])
    return chores.count(chore) if isinstance(chores, list) else 0


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


ROUTINES: dict[Routine, Callable[[Context], list[Option]]] = {
    **{routine: _forager(routine) for routine in FORAGERS},
}
