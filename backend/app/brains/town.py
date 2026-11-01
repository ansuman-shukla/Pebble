"""Town routines (10-world-v1 §3.1, §2): what each of the castle town's citizens does with an ordinary day once needs
and night are taken care of: the fields, the stall, the gates, the castle, the temple and the loom.

Every routine returns scored options (needs and night outscore them; see `brain.py`), built from the shared helpers of
`routines.py`.
"""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from app.brains.profile import Routine
from app.brains.routines import (
    COMPASS,
    WORK,
    Context,
    Option,
    _daytime,
    _go,
    _on_spot,
    _set,
    _then,
    _work_at,
)
from app.brains.senses import DISTANCE, afternoon, at, at_home, beside, carried_food
from app.world_api.facade import ActionHandle
from app.world_api.models import TimeOfDay

FIELDS = "the rice fields"
STOREHOUSES = "the storehouses"
WELL = "the well"
MARKET = "the market"
CASTLE = "the castle"
TEMPLE = "the temple"
POSTS = ("the main gate", "the west gate", "the castle", "the training ground")  # the samurai's rounds
BASKETS = "the main gate"  # where the guard lights the fire baskets at dusk
BELL_TOWER = "the bell tower"
BELL = 88.0  # the bell can't wait: above hungry (85) and thirsty (80), below starving, parched, exhausted (90), danger
# when to go: the words of the sun where the monk stands (a bell's moment is the town's clock, see `sim/society.py`)
BELLS: dict[TimeOfDay, str] = {"dawn": "dawn bell", "midday": "noon bell", "sunset": "dusk bell", "dusk": "dusk bell"}


STORE_RICE = "Bring the rice into the storehouse"
TAKE_RICE_HOME = "Take the rice home to the chest"


def _store_rice(ctx: Context, score: float = WORK + 1) -> Option:
    """Pay the rice tax on the harvest at the granary ("store food"), then take the rest home to the chest."""
    if ctx.notes.get("taxed") is False:
        return _work_at(ctx, STOREHOUSES, "store food", score, STORE_RICE)
    if at_home(ctx.perception):
        return Option(score, "stash rice", partial(_stash_rice, ctx), TAKE_RICE_HOME)
    return Option(score, "go home", lambda: ctx.api.walk_to_place("home"), TAKE_RICE_HOME)


def _stash_rice(ctx: Context) -> ActionHandle:
    """Put the carried rice in the household chest (as much as they reckon they carry), then rest a moment at home."""
    ctx.api.stash("rice", max(1, carried_food(ctx.perception.you).get("rice", 0)))
    return ctx.api.rest(10)


def _farm(ctx: Context) -> list[Option]:
    rice = carried_food(ctx.perception.you).get("rice", 0)
    if ctx.notes.get("last") == "store food" and ctx.notes.get("failed") != "store food":  # the tax is paid
        ctx.notes["taxed"] = True
    if ctx.phase == "dusk" and rice:
        return [_store_rice(ctx, 46)]  # bring the day's harvest in before supper
    if not _daytime(ctx):
        return []
    if rice >= 25:
        return [_store_rice(ctx)]
    if _refused(ctx, "farm"):  # another paddy needs them more (N1): walk over to it
        return [_go(ctx, FIELDS, aim="Tend the rice fields")]
    farm = _work_at(ctx, FIELDS, "farm", aim="Tend the rice fields")
    if farm.name == "farm":  # each harvest is taxed: the rice goes to the granary before it goes home
        farm = replace(farm, start=_then(lambda: _set(ctx, "taxed", False), farm.start))
    return [farm]


def _refused(ctx: Context, name: str) -> bool:
    """The option chosen last was this one and the world refused it at once."""
    number = ctx.notes.get("chosen")
    result = ctx.api.handle(number).result if isinstance(number, int) else None
    return ctx.notes.get("last") == name and result is not None and result.outcome == "failed"


def farmer(ctx: Context) -> list[Option]:
    return _farm(ctx)


def weaver(ctx: Context) -> list[Option]:
    """Weaves at home in the morning (at the loom: the walk home ends there), helps in the fields in the afternoon."""
    aim = "Weave cloth at the loom"
    if _daytime(ctx) and not afternoon(ctx.perception):
        if at_home(ctx.perception) and _on_spot(ctx, "go home"):
            return [Option(WORK, "weave", lambda: ctx.api.work("weave"), aim)]
        return [Option(WORK, "go home", lambda: ctx.api.walk_to_place("home"), aim)]
    return _farm(ctx)


def merchant(ctx: Context) -> list[Option]:
    """Keeps the stall (her purse is her ambition) and strolls about now and then."""
    if not _daytime(ctx):
        return []
    aim = "Trade at the market"
    sessions = ctx.counter("sessions")
    if not (at(ctx.perception, MARKET) and _on_spot(ctx, f"go to {MARKET}")):
        return [_go(ctx, MARKET, aim=aim, driver="ambition")]
    if sessions >= 3:  # stretch the legs now and then
        stroll = (WELL, "the temple", STOREHOUSES)[ctx.pick(3)]
        start = _then(lambda: _set(ctx, "sessions", 0), _go(ctx, stroll).start)
        return [Option(WORK, f"go to {stroll}", start, f"Stretch my legs to {stroll}", "social")]
    trade = _then(lambda: _set(ctx, "sessions", sessions + 1), lambda: ctx.api.work("trade"))
    return [Option(WORK, "trade", trade, aim, "ambition")]


def samurai(ctx: Context) -> list[Option]:
    """Rounds of the gates, the castle and the training ground, keeping watch at each (on its guard stand: the walk
    there ends on it); fire baskets lit at dusk."""
    if ctx.phase == "dusk":
        return _light_baskets(ctx)
    if not _daytime(ctx):
        return []
    aim = "Keep watch on my rounds"
    post = ctx.counter("post") % len(POSTS)
    if not (at(ctx.perception, POSTS[post]) and _on_spot(ctx, f"go to {POSTS[post]}")):
        return [_go(ctx, POSTS[post], aim=aim)]
    if ctx.notes.get("watched") == post:  # watched here already: on to the next post
        following = (post + 1) % len(POSTS)
        note = lambda: _set(ctx, "post", following)  # noqa: E731  # a tiny closure reads best inline
        return [Option(WORK, f"go to {POSTS[following]}", _then(note, _go(ctx, POSTS[following]).start), aim)]
    return [Option(WORK, "guard", _then(lambda: _set(ctx, "watched", post), lambda: ctx.api.work("guard")), aim)]


def _light_baskets(ctx: Context) -> list[Option]:
    """At dusk the guard fetches wood from the storehouse and lights the fire baskets at the main gate."""
    p, api = ctx.perception, ctx.api
    if "fire" not in ctx.profile.skills or ctx.done_today("baskets"):
        return []
    score = 45.0  # before going home for the night
    aim = "Light the fire baskets at the gate"
    if not ctx.done_today("fetched wood"):  # topped up every evening: two full baskets burn two dozen pieces
        if at(p, STOREHOUSES):
            return [Option(score, "fetch wood", lambda: _fetch_wood(ctx), aim)]
        return [_go(ctx, STOREHOUSES, score, aim)]
    if not at(p, BASKETS):
        return [_go(ctx, BASKETS, score, aim)]
    here = [t for t in p.things if beside(t)]  # the gate's pair
    cold = [t for t in here if t.label == "a fire basket" and t.doing == "cold"]
    low = [t for t in here if t.label == "a fire basket" and t.doing in ("burning low", "glowing embers")]
    for things, action, name in ((cold, api.make_fire, "light a basket"), (low, api.feed_fire, "feed a basket")):
        if things and things[0].nearness == "right beside you":
            return [Option(score, name, action, aim)]
        if things:
            basket = f"the {things[0].doing} fire basket"  # the cold one, not the one already burning
            return [Option(score, f"go to {basket}", partial(api.walk_to_thing, basket), aim)]
    ctx.mark_done("baskets")
    return []


def _fetch_wood(ctx: Context) -> ActionHandle:
    """Take wood from the storehouse and head for the baskets; stopped short of its doors, walk up to them first."""
    if ctx.api.pick_up("wood").outcome == "done":
        ctx.mark_done("fetched wood")
        return ctx.api.walk_to_place(BASKETS)
    return ctx.api.walk_to_place(STOREHOUSES)


def lord(ctx: Context) -> list[Option]:
    """Holds court at the castle (on his seat: the walk there ends on it); now and then walks out to the temple or
    the market."""
    if not _daytime(ctx):
        return []
    aim = "Hold court at the castle"
    sessions = ctx.counter("sessions")
    if at(ctx.perception, CASTLE) and _on_spot(ctx, f"go to {CASTLE}"):
        if sessions >= 2:
            outing = ("the temple", MARKET)[ctx.pick(2)]
            start = _then(lambda: _set(ctx, "sessions", 0), _go(ctx, outing).start)
            return [Option(WORK, f"go to {outing}", start, f"Look over {outing}")]
        govern = _then(lambda: _set(ctx, "sessions", sessions + 1), lambda: ctx.api.work("govern"))
        return [Option(WORK, "govern", govern, aim)]
    if ctx.notes.get("last") in ("go to the temple", "go to the market"):
        return [Option(WORK, "look around", lambda: ctx.api.wait(20))]  # still on the outing: same aim
    return [_go(ctx, CASTLE, aim=aim)]


def town_child(ctx: Context) -> list[Option]:
    """Plays around the well; sometimes tags along after someone close by, or runs off to the market or the fields."""
    if not _daytime(ctx):
        return []
    p = ctx.perception
    aim = "Play about the town"
    if not (at(p, WELL) or at(p, MARKET) or at(p, FIELDS)):
        return [_go(ctx, WELL, aim=aim, driver="social")]
    roll = ctx.pick(10)
    close = [person.label for person in p.people if DISTANCE[person.nearness] in ("near", "close")]
    if roll < 1 and close:
        return [Option(WORK, f"tag along after {close[0]}", partial(ctx.api.follow, close[0]), aim, "social")]
    if roll < 4:
        direction = COMPASS[ctx.pick(len(COMPASS))]
        return [Option(WORK, "play", lambda: ctx.api.walk_towards(direction, "a few steps"), aim, "social")]
    if roll < 7:
        return [Option(WORK, "watch", lambda: ctx.api.wait(10 + 5 * ctx.pick(3)), aim, "social")]
    return [_go(ctx, (MARKET, WELL, FIELDS)[ctx.pick(3)], aim=aim, driver="social")]


def monk(ctx: Context) -> list[Option]:
    """Rings the bell at dawn, noon and dusk; prays at the temple by day (alms and tending come with their own
    systems)."""
    bell = BELLS.get(ctx.perception.time_of_day)
    if bell is not None and not ctx.done_today(bell) and _rang(ctx, bell):
        ctx.mark_done(bell)
    if bell is not None and not ctx.done_today(bell):
        return [_ring(ctx, bell)]
    if not _daytime(ctx):
        return []
    return [_work_at(ctx, TEMPLE, "pray", aim="Pray at the temple")]


def _ring(ctx: Context, bell: str) -> Option:
    if not at(ctx.perception, BELL_TOWER):
        return _go(ctx, BELL_TOWER, BELL, f"Ring the {bell}")

    def start() -> ActionHandle:
        handle = ctx.api.work("ring bell")
        ctx.notes["bell"] = [bell, handle.number]
        return handle

    return Option(BELL, "ring the bell", start, f"Ring the {bell}")


def _rang(ctx: Context, bell: str) -> bool:
    """The last try at this bell is over: it rang, or the world refused it (rung already, or its time gone by), so
    trying again won't ring it; only an interrupted try is tried again."""
    tried = ctx.notes.get("bell")
    if not isinstance(tried, list) or len(tried) != 2 or tried[0] != bell or not isinstance(tried[1], int):
        return False
    result = ctx.api.handle(tried[1]).result
    return result is not None and result.outcome in ("done", "failed")


def townsperson(ctx: Context) -> list[Option]:
    if not _daytime(ctx):
        return []
    return [_go(ctx, (WELL, MARKET)[ctx.pick(2)], aim="Run errands about town")]


TOWN_ROUTINES: dict[Routine, Callable[[Context], list[Option]]] = {
    "lord": lord,
    "samurai": samurai,
    "merchant": merchant,
    "farmer": farmer,
    "weaver": weaver,
    "town_child": town_child,
    "townsperson": townsperson,
    "monk": monk,
}
