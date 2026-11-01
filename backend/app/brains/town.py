"""Town routines (10-world-v1 §3.1, §2): what each of the castle town's citizens does with an ordinary day once needs
and night are taken care of: the fields, the stall, the gates, the castle, the temple, the loom, the forge and the
iron-sand bar.

Every routine returns scored options (needs and night outscore them; see `brain.py`), built from the shared helpers of
`routines.py`. The town's coins go round through the stall and the lord (§2.7):

```
 farmers ──rice──▶ stall ──rice──▶ watchman, smith, digger (each buys a day's rice at a time)
 granary ──rice (lord, while dear or fair)──▶ stall
 digger ──iron sand, wood, gold──▶ stall ──iron sand, wood──▶ smith ──tools──▶ stall / the lord's orders
 weaver ──cloth──▶ stall ──gold, cloth──▶ lord ──wages, orders──▶ watchman, smith
 households ──dues on court day──▶ lord
```
"""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from app.brains.profile import BrainProfile, Routine
from app.brains.routines import (
    COMPASS,
    WORK,
    Context,
    Option,
    _count_today,
    _daytime,
    _go,
    _on_spot,
    _set,
    _then,
    _work_at,
)
from app.brains.senses import (
    DISTANCE,
    Resource,
    afternoon,
    at,
    at_home,
    beside,
    carried_food,
    carries,
    resources_in_view,
)
from app.world_api.facade import ActionHandle
from app.world_api.models import (
    ActionResult,
    Driver,
    Perception,
    PriceSeen,
    PriceWord,
    RecipeName,
    Seen,
    TimeOfDay,
)

FIELDS = "the rice fields"
STOREHOUSES = "the storehouses"
WELL = "the well"
MARKET = "the market"
CASTLE = "the castle"
TEMPLE = "the temple"
FORGE = "the forge"
WEST_GATE = "the west gate"
SOUTH_MARSH = "the South marsh"  # reed beds, and the iron-sand bar by the Mill river
NORTH_WOODS = "the North woods"
FALLS_POOL = "the Falls pool"
POSTS = ("the main gate", "the west gate", "the castle", "the training ground")  # the samurai's rounds
BASKETS = "the main gate"  # where the guard lights the fire baskets at dusk
BELL_TOWER = "the bell tower"
BELL = 88.0  # the bell can't wait: above hungry (85) and thirsty (80), below starving, parched, exhausted (90), danger
# when to go: the words of the sun where the monk stands (a bell's moment is the town's clock, see `sim/society.py`)
BELLS: dict[TimeOfDay, str] = {"dawn": "dawn bell", "midday": "noon bell", "sunset": "dusk bell", "dusk": "dusk bell"}

RICE = "rice"
COINS = "coins"
# the stall is kept while the merchant trades, from early morning to late afternoon (10 §3.1: 8-12 and 13-17)
STALL_TIMES: frozenset[TimeOfDay] = frozenset(
    {"early morning", "mid-morning", "midday", "early afternoon", "late afternoon"}
)
STALL_WAITS = 3  # times a day someone waits at a shut stall before giving up on it
LOW_RICE = 4  # a buyer's rice runs low at "a little" (2-3 measures) or none: a day's buying then
NIGHT_RICE = 13  # and in the late afternoon below "plenty", so the night is covered
BUY_RICE = 12  # measures bought at a time: a day's eating (a person eats 10 a day, 10 §1.4) and a little over
HUNGRY_BUY = {2: 86.0, 3: 106.0}  # buying rice when hungry with none carried: above going home to an empty chest
# the price rule (10 §1.4): farmers sell their surplus ×1.5 while rice is dear at the stall, ×0.5 while cheap
SELL_FACTOR: dict[PriceWord, float] = {"dear": 1.5, "fair": 1.0, "cheap": 0.5}
# a farmer's reckoning of the household's rice (10 §1.4): a paddy gives 60 measures every 3 days, 40 % goes in tax,
# everyone eats 10 a day; what is left over is sold at the stall
PADDY_RICE = 60
PADDY_DAYS = 3
RICE_TAX = 0.4
EATS = 10
HARVEST = 10  # measures a harvest session takes from a ripe paddy (15 with a sickle, counted as 10)
PLENTY = 13  # "plenty of rice" in the chest at the least: a household with less sells none of its own
A_GREAT_DEAL = 41  # "a great deal of rice": only then a dear price draws out more than the spare share
SICKLE = "sickle"
SICKLE_PURSE = 120  # a farmer buys a sickle once the purse holds this much (the dues come first)
DUES = WORK + 12  # paying the household's dues on court day comes before the day's work
WAGE = 25  # the watchman's wage, paid at dusk (10 §2.7)
ORDER = 60  # what the lord pays for an iron tool for his armoury, one every 2 days (10 §2.7)
WAGE_WORDS = "my wage"
ORDER_WORDS = "as you ordered"
PAY = 48.0  # the lord pays what he owes before his evening at home (40) and his work
PAY_WAITS = 3  # waits for the lord to pay (or to be seen at the castle) before giving up for the day
GRANARY_SALE: dict[PriceWord, int] = {"dear": 40, "fair": 26}  # the lord sells granary rice while dear or fair
PURSE_LOW = 100  # the lord takes coins from the treasury when his purse holds less
PURSE_TOP_UP = 150
PURSE_HEAVY = 300  # and puts what is over the day's needs into it when his purse holds this much
GOLD = "gold"
GOLD_TREASURY = 1800  # the lord buys gold for his hoard while the treasury holds more than this (10 §2.2)
CLOTH = "cloth"
CLOTH_DAYS = (1, 5)  # week days the lord buys a length of cloth for the keep (≈ one every 4 days)
GOLD_DAYS = (2, 6)  # week days the digger pans gold at the Falls pool (10 §3.1)
GOLD_LOAD = 4  # grains ("some") he pans before heading back: two hours' luck at the pool
DIG_LOAD = 4  # measures of iron sand ("some") the digger brings in a day: about what the forge burns
DIG_TIMES: frozenset[TimeOfDay] = frozenset({"dawn", "early morning", "mid-morning", "midday"})  # 7-11, at the bar
WOOD_TIMES: frozenset[TimeOfDay] = frozenset({"late afternoon", "sunset"})  # back from the woods at dusk
IRON_SAND = "iron sand"
TRIES = {"gold": 6}  # sessions in a day that may find nothing before giving up (gold: half of them do, 10 §2.2)
LOTS = {"wood": 4, "rice": 2}  # what the stall trades by more than one at a time (10 §2.2)
WOOD = "wood"
REEDS = "reeds"
DAY_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh")
TOOLS: tuple[RecipeName, ...] = ("iron axe", "sickle", "iron spear")  # what the smith forges, in turn
# what each tool needs bought for it: iron sand, and wood for the tool and the forge's 2 a round (10 §2.3)
SUPPLIES: dict[str, tuple[int, int]] = {"iron axe": (3, 4), "sickle": (3, 3), "iron spear": (2, 3)}
UNSOLD_TOOLS = 2  # the smith forges no more while he carries this many tools nobody took
# the smith starts the day's tool from 11 (at the anvil at noon) to 15.30 (done by 17); mornings go to the stall
FORGE_TIMES: frozenset[TimeOfDay] = frozenset({"midday", "early afternoon"})
_ONES = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen"
_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
NUMBERS = {word: n for n, word in enumerate(f"{_ONES} eighteen nineteen".split(), 1)} | {
    f"{tens}-{one}" if one else tens: 10 * t + n
    for t, tens in enumerate(_TENS, 2)
    for n, one in enumerate(["", *_ONES.split()[:9]])
}  # 1-99 in words, as counts are said
# what the words for an amount carried mean at the least (`items.amount_words`); anything else is one
LEAST = (("a great", 41), ("plenty of", 13), ("a handful of", 4), ("some", 4), ("a few", 2), ("a little", 2))
WATCH = 72.0  # the night watch outscores sleep (70) for the watchman
STORE_RICE = "Bring the rice into the storehouse"
TAKE_RICE_HOME = "Take the rice home to the chest"
SELL_RICE = "Sell our spare rice at the stall"


# --- reading what is perceived ---


def _result(ctx: Context) -> ActionResult | None:
    number = ctx.notes.get("chosen")
    return ctx.api.handle(number).result if isinstance(number, int) else None


def _refused(ctx: Context, name: str) -> bool:
    """The option chosen last was this one and the world refused it at once."""
    result = _result(ctx)
    return ctx.notes.get("last") == name and result is not None and result.outcome == "failed"


def weekday(p: Perception) -> int | None:
    """The day of the week (1-7) as the town counts it, from the words ("the seventh day of the week, court day")."""
    words = p.day_of_week or ""
    return next((n for n, word in enumerate(DAY_WORDS, 1) if words.startswith(f"the {word} day")), None)


def court_day(p: Perception) -> bool:
    return "court day" in (p.day_of_week or "")


def purse(p: Perception) -> int:
    """The least the words for your coins can mean ("a short string of coins": 13, "two strings of coins": 200)."""
    you = p.you
    return coins_in([*([you.purse] if you.purse else []), *you.carrying])


def coins_in(lines: list[str]) -> int:
    """The least the words for coins among amount words can mean."""
    for line in lines:
        if not line.endswith(("coin", "coins")):
            continue
        head = line.split()[0]
        if line == "a coin":
            return 1
        if "short string" in line:
            return 13
        if "string" in line:
            return 100 if head == "a" else 100 * NUMBERS.get(head, 1)
        return NUMBERS.get(head, 0)
    return 0


def _price(p: Perception, item: str) -> PriceSeen | None:
    """The stall at hand's price of a good, if it is open and trades it."""
    return next((seen for seen in p.market.items if seen.item == item), None) if p.market is not None else None


def _on_sale(p: Perception, item: str) -> bool:
    seen = _price(p, item)
    return seen is not None and not seen.price.startswith("none left")


def _person(p: Perception, name: str | None) -> Seen | None:
    return next((person for person in p.people if person.label == name), None) if name else None


def _lord(profile: BrainProfile) -> str | None:
    return next((name for name, title in profile.titled if title == "lord"), None)


def _heard(p: Perception, who: str | None, words: str) -> bool:
    return who is not None and any(heard.who == who and words in heard.words for heard in p.heard)


def carrying(p: Perception, item: str) -> int:
    """The least the words for what you carry can mean of an item ("a few reeds": 2, "some iron sand": 4)."""
    return least(p.you.carrying, item)


def least(lines: list[str], item: str) -> int:
    """The least a list of amount words ("plenty of rice", "a reed") can mean of an item."""
    for line in lines:
        if line.endswith((f" {item}", f" {item}s", f" {item}es")) or line.endswith(item):
            return next((count for words, count in LEAST if line.startswith(words)), 1)
    return 0


def _nearest(resources: list[Resource]) -> Resource:
    return min(resources, key=lambda r: (("here", "near", "close", "off", "far").index(r.distance), not r.plenty))


# --- the stall ---


def _at_stall(
    ctx: Context, score: float, name: str, aim: str, deal: Callable[[], ActionResult], driver: Driver = "duty"
) -> Option | None:
    """At the open stall: make the deal and stand by it a moment (a deal refused is not tried again that day: `failed
    <name>`). Else on the way there (`_to_stall`)."""
    if ctx.perception.market is None:
        return _to_stall(ctx, score, aim, driver)

    def run() -> ActionHandle:
        if deal().outcome == "failed":
            ctx.mark_done(f"failed {name}")
        return ctx.api.wait(3)

    return Option(score, name, run, aim, driver)


def _to_stall(ctx: Context, score: float, aim: str, driver: Driver = "duty") -> Option | None:
    """Walk to the market (onto a buyer's spot); a shut stall is waited for a few times a day before giving up on it
    (None)."""
    if at(ctx.perception, MARKET) and _on_spot(ctx, f"go to {MARKET}"):
        if _count_today(ctx, "waited at the stall") >= STALL_WAITS:
            return None
        wait = _then(lambda: ctx.mark_done("waited at the stall"), lambda: ctx.api.wait(10))
        return Option(score, "wait for the stall", wait, aim, driver)
    return _go(ctx, MARKET, score, aim, driver)


def _buy_rice(ctx: Context) -> list[Option]:
    """Households the granary doesn't feed and that farm no rice buy theirs at the stall (10 §2.6): a day's rice while
    the stall is kept and theirs runs low; hungry with nothing to eat, before anything else."""
    p = ctx.perception
    food = carried_food(p.you)
    low = NIGHT_RICE if p.time_of_day == "late afternoon" else LOW_RICE  # before the stall shuts: enough for the night
    if carrying(p, RICE) >= low or p.time_of_day not in STALL_TIMES or not carries(p, COINS):
        return []
    if ctx.done_today("failed buy rice"):
        return []
    hungry = None if food else HUNGRY_BUY.get(ctx.needs.hunger)
    buy = partial(ctx.api.buy, RICE, BUY_RICE)
    option = _at_stall(
        ctx, hungry or WORK + 8, "buy rice", "Buy rice at the stall", buy, "hunger" if hungry else "duty"
    )
    return [option] if option is not None else []


# --- dues, wages and the lord's orders ---


def _count_dues(ctx: Context) -> None:
    """The household's dues fall due with each new day of the week told (the run's first day is free, 10 §2.7)."""
    day = ctx.perception.day_of_week
    if day is None or not ctx.profile.dues:
        return
    seen = ctx.notes.get("day")
    ctx.notes["day"] = day
    if seen is not None and seen != day:
        ctx.notes["owed"] = ctx.counter("owed") + ctx.profile.dues


def _pay_dues(ctx: Context) -> list[Option]:
    """On court day whoever settles the household's dues takes the week's to the lord, who holds court at the castle
    (10 §2.7, §3.6)."""
    _count_dues(ctx)
    owed, p = ctx.counter("owed"), ctx.perception
    if owed <= 0 or not court_day(p) or not _daytime(ctx) or not carries(p, COINS):
        return []
    lord = _lord(ctx.profile)

    def pay() -> ActionHandle:
        if lord is not None and ctx.api.give(f"{owed} coins", lord).outcome == "done":
            ctx.notes["owed"] = 0  # what the purse couldn't cover stays owed in the lord's books (arrears)
        return ctx.api.wait(3)

    return _to_the_lord(ctx, DUES, "pay dues", "Pay my household's dues to the lord", pay)


def _to_the_lord(ctx: Context, score: float, name: str, aim: str, act: Callable[[], ActionHandle]) -> list[Option]:
    """Right beside the lord: do it; with him in view: walk up to him; else go to the castle and wait for him there a
    few times a day."""
    p, lord = ctx.perception, _lord(ctx.profile)
    seen = _person(p, lord)
    if lord is None:
        return []
    if seen is not None and seen.nearness == "right beside you":
        return [Option(score, name, act, aim)]
    if seen is not None:
        return [Option(score, f"go up to {lord}", partial(ctx.api.walk_to_person, lord), aim)]
    if at(p, CASTLE) and _on_spot(ctx, f"go to {CASTLE}"):
        if _count_today(ctx, "waited for the lord") >= PAY_WAITS:
            return []
        wait = _then(lambda: ctx.mark_done("waited for the lord"), lambda: ctx.api.wait(10))
        return [Option(score, "wait for the lord", wait, aim)]
    return [_go(ctx, CASTLE, score, aim)]


def _paid_by_lord(ctx: Context, chore: str, words: str, aim: str, score: float) -> list[Option] | None:
    """After asking the lord for coins (`chore` asked today): heard him pay (`words` said by him) or waited long
    enough: done (None); else wait by him a little longer."""
    if not ctx.done_today(f"asked: {chore}") or ctx.done_today(chore):
        return None
    if _heard(ctx.perception, _lord(ctx.profile), words) or _count_today(ctx, f"waited: {chore}") >= PAY_WAITS:
        ctx.mark_done(chore)
        return []
    wait = _then(lambda: ctx.mark_done(f"waited: {chore}"), lambda: ctx.api.wait(5))
    return [Option(score, "wait to be paid", wait, aim)]


def _payments(ctx: Context) -> list[Option]:
    """The lord pays what he is asked for by those he owes: the watchman's wage at dusk, the smith's order when the
    tool is handed over (heard: "my wage", "as you ordered"); someone who has gone before he pays asks again."""
    p = ctx.perception
    owing = ctx.notes.setdefault("to pay", [])
    if not isinstance(owing, list):
        raise TypeError("to pay must be a list")
    for heard in p.heard:
        for words in (WAGE_WORDS, ORDER_WORDS):
            if words in heard.words and _person(p, heard.who) is not None and [heard.who, words] not in owing:
                owing.append([heard.who, words])
    owing[:] = [entry for entry in owing if isinstance(entry, list) and _person(p, str(entry[0])) is not None]
    first = owing[0] if owing else None
    if not isinstance(first, list):
        return []
    who, why = str(first[0]), str(first[1])
    seen = _person(p, who)
    aim = f"Pay {who}"
    if seen is None or seen.nearness != "right beside you":
        return [Option(PAY, f"go up to {who}", partial(ctx.api.walk_to_person, who), aim)]

    def pay() -> ActionHandle:
        owing.pop(0)
        if why == WAGE_WORDS:
            ctx.api.give(f"{WAGE} coins", who)
            ctx.api.say(f"Here is your wage, {who}.")
        else:
            ctx.api.give(f"{ORDER} coins", who)
            ctx.api.say(f"Sixty coins for it, {who}. Good work.")
        return ctx.api.wait(2)

    return [Option(PAY, "pay", pay, aim)]


def _collect_wage(ctx: Context) -> list[Option]:
    """Before the night watch (late afternoon or dusk) the watchman goes to the lord for his day's wage (10 §2.7)."""
    aim = "Collect my wage from the lord"
    waiting = _paid_by_lord(ctx, "wage", "wage", aim, 45.0)
    if waiting is not None or ctx.done_today("wage"):
        return waiting or []

    def ask() -> ActionHandle:
        ctx.mark_done("asked: wage")
        ctx.api.say(f"Good evening, my lord. I've come for {WAGE_WORDS}.")
        return ctx.api.wait(5)

    return _to_the_lord(ctx, 45.0, "ask for my wage", aim, ask)


# --- the fields ---


def _surplus(profile: BrainProfile) -> float:
    """The share of the rice a farm household brings home that it can spare for the stall: what its paddies give
    after the tax, less what its mouths eat (10 §1.4: Genzo's household 18 of 48 a day, Tokuji 14 of 24)."""
    kept = profile.paddies * PADDY_RICE / PADDY_DAYS * (1 - RICE_TAX)
    return max(0.0, 1 - profile.household * EATS / kept) if kept else 0.0


def _store_rice(ctx: Context, score: float = WORK + 1) -> Option:
    """Pay the rice tax on the harvest at the granary ("store food"), sell the household's spare rice at the stall
    while it is kept, then take the rest home to the chest."""
    if ctx.notes.get("taxed") is False:
        return _work_at(ctx, STOREHOUSES, "store food", score, STORE_RICE)
    selling = _sell_rice(ctx, score)
    if selling is not None:
        return selling
    if at_home(ctx.perception):
        return Option(score, "stash rice", partial(_stash_rice, ctx), TAKE_RICE_HOME)
    return Option(score, "go home", lambda: ctx.api.walk_to_place("home"), TAKE_RICE_HOME)


def _sell_rice(ctx: Context, score: float) -> Option | None:
    """The spare share of what was harvested since the last sale, by the price rule: ×1.5 while rice is dear at the
    stall, ×0.5 while it is cheap (10 §1.4); as the household chest was last seen: ×1.5 only while it holds a great
    deal of rice, nothing while it holds less than plenty. Nothing to sell, or the stall shut for the day: None."""
    p = ctx.perception
    harvested, chest = ctx.counter("harvested"), ctx.notes.get("chest rice", PLENTY)
    spare = harvested * (1 - RICE_TAX) * _surplus(ctx.profile)
    low = isinstance(chest, int) and chest < PLENTY  # the household's own rice comes first
    if spare < 1 or low or p.time_of_day not in STALL_TIMES or ctx.done_today("failed sell rice"):
        ctx.notes["harvested"] = 0
        return None
    price = _price(p, RICE)
    rule = SELL_FACTOR[price.word] if price is not None else 0.0
    if isinstance(chest, int) and chest < A_GREAT_DEAL:
        rule = min(rule, 1.0)  # more only while the chest holds a great deal
    amount = round(spare * rule)

    def sell() -> ActionResult:
        ctx.notes["harvested"] = 0
        return ctx.api.sell(RICE, amount)

    option = _at_stall(ctx, score, "sell rice", SELL_RICE, sell)
    if option is None:
        ctx.notes["harvested"] = 0
    return option


def _stash_rice(ctx: Context) -> ActionHandle:
    """Put the carried rice in the household chest (as much as they reckon they carry), then rest a moment at home."""
    ctx.api.stash(RICE, max(1, carried_food(ctx.perception.you).get(RICE, 0)))
    return ctx.api.rest(10)


def _buy_sickle(ctx: Context) -> list[Option]:
    """At the stall with a full enough purse and no sickle, a farmer buys one (15 measures a harvest, not 10)."""
    p = ctx.perception
    if p.market is None or carrying(p, SICKLE) or purse(p) < SICKLE_PURSE or not _on_sale(p, SICKLE):
        return []
    option = _at_stall(ctx, WORK + 2, "buy a sickle", "Buy a sickle", partial(ctx.api.buy, SICKLE, 1))
    return [option] if option is not None and not ctx.done_today("failed buy a sickle") else []


def _farm(ctx: Context) -> list[Option]:
    p = ctx.perception
    rice = carried_food(p.you).get(RICE, 0)
    if p.chest is not None:  # at the chest: how much rice the household has put by
        ctx.notes["chest rice"] = least(p.chest.holds, RICE)
    if ctx.notes.get("last") == "store food" and ctx.notes.get("failed") != "store food":  # the tax is paid
        ctx.notes["taxed"] = True
    result = _result(ctx)
    if ctx.finished("farm") and result is not None and result.text.startswith("You harvest"):
        ctx.notes["harvested"] = ctx.counter("harvested") + HARVEST
    dues = _pay_dues(ctx)
    if dues:
        return dues
    if ctx.notes.get("chest empty") is True:  # nothing left at home: buy a day's rice back at the stall
        food = _buy_rice(ctx)
        if food:
            return food
    if ctx.phase == "dusk" and rice:
        return [_store_rice(ctx, 46)]  # bring the day's harvest in before supper
    if not _daytime(ctx):
        return []
    if rice >= 25 or (rice and p.time_of_day == "late afternoon"):  # and in before the dusk bell and the stall shuts
        return [_store_rice(ctx)]
    sickle = _buy_sickle(ctx)
    if sickle:
        return sickle
    if _refused(ctx, "farm"):  # another paddy needs them more (N1): walk over to it
        return [_go(ctx, FIELDS, aim="Tend the rice fields")]
    farm = _work_at(ctx, FIELDS, "farm", aim="Tend the rice fields")
    if farm.name == "farm":  # each harvest is taxed: the rice goes to the granary before it goes home
        farm = replace(farm, start=_then(lambda: _set(ctx, "taxed", False), farm.start))
    return [farm]


def farmer(ctx: Context) -> list[Option]:
    return _farm(ctx)


# --- the loom ---

WEAVE = "Weave cloth at the loom"
HIDE = "hide"
PACK = "pack"
REED_DAYS = (1, 4)  # week days the weaver fetches reeds (market day too: a pack takes two)


def _gather_at(ctx: Context, place: str, resource: str, aim: str, score: float = WORK) -> list[Option]:
    """Fetch a wild thing from where it is found: walk to the place, up to the nearest in view there, and gather it.
    Nothing (left) there: given up for the day (`no <resource>`)."""
    p = ctx.perception
    if _refused(ctx, f"gather {resource}"):  # none left there, the load full, or (gold) a session that found none
        ctx.mark_done(f"missed {resource}")
        if _count_today(ctx, f"missed {resource}") >= TRIES.get(resource, 1):
            ctx.mark_done(f"no {resource}")
    if ctx.done_today(f"no {resource}"):
        return []
    seen = [r for r in resources_in_view(p) if r.kind == resource] if at(p, place) else []
    if any(r.distance == "here" for r in seen):
        return [Option(score, f"gather {resource}", partial(ctx.api.gather, resource), aim)]
    if seen:
        return [Option(score, f"go to the {resource}", partial(ctx.api.walk_to_thing, _nearest(seen).label), aim)]
    if at(p, place):
        ctx.mark_done(f"no {resource}")
        return []
    return [_go(ctx, place, score, aim)]


def _sell(ctx: Context, item: str, aim: str, score: float = WORK + 1) -> list[Option]:
    """Sell what you carry of a good at the stall (as much as it takes, in its lots) while it is kept; while it is
    cheap there (the stall holds more than it wants) it is kept for another day."""
    p = ctx.perception
    lot, price = LOTS.get(item, 1), _price(p, item)
    if price is not None and price.word == "cheap":
        ctx.mark_done(f"failed sell {item}")
    if carrying(p, item) < lot or p.time_of_day not in STALL_TIMES or ctx.done_today(f"failed sell {item}"):
        return []
    option = _at_stall(ctx, score, f"sell {item}", aim, partial(ctx.api.sell, item, 99))
    return [option] if option is not None else []


def weaver(ctx: Context) -> list[Option]:
    """Weaves at home in the morning (at the loom: the walk home ends there) from reeds she fetches from the South
    marsh twice a week (the loom is mended on the other mornings), sells the cloth and helps in the fields in the
    afternoon; on market day she buys hides for a pack."""
    p = ctx.perception
    dues = _pay_dues(ctx)
    if dues:
        return dues
    if not (_daytime(ctx) and not afternoon(p)):
        return _sell(ctx, CLOTH, "Sell my cloth at the stall") or _farm(ctx)
    if ctx.finished(f"gather {REEDS}"):
        ctx.mark_done(REEDS)  # one trip a reed day: a reed bed gives five to eight, two to four lengths of cloth
    if weekday(p) in REED_DAYS and carrying(p, REEDS) < 2 and not ctx.done_today(REEDS):
        fetching = _gather_at(ctx, SOUTH_MARSH, REEDS, "Fetch reeds for the loom")
        if fetching:
            return fetching
    hides = _buy_hides(ctx)
    if hides:
        return hides
    if not (at_home(p) and _on_spot(ctx, "go home")):
        return [Option(WORK, "go home", lambda: ctx.api.walk_to_place("home"), WEAVE)]
    if carrying(p, HIDE) >= 2 and carrying(p, REEDS) >= 2:
        return [Option(WORK, "make a pack", partial(ctx.api.craft, PACK), "Make a pack at the loom")]
    return [Option(WORK, "weave", lambda: ctx.api.work("weave"), WEAVE)]


def _buy_hides(ctx: Context) -> list[Option]:
    """On market day, with no pack and coins enough, two hides for one (10 §2.3: 2 hides + 2 reeds at the loom)."""
    p = ctx.perception
    if weekday(p) != 1 or carrying(p, PACK) or carrying(p, HIDE) >= 2 or purse(p) < 13:
        return []
    if ctx.done_today("failed buy hides") or p.time_of_day not in STALL_TIMES:
        return []
    option = _at_stall(ctx, WORK + 1, "buy hides", "Buy hides for a pack", partial(ctx.api.buy, HIDE, 2))
    return [option] if option is not None else []


# --- the stall's keeper ---


def merchant(ctx: Context) -> list[Option]:
    """Keeps the stall (her purse is her ambition), eats from its rice (her own stock) and takes a day's home in the
    late afternoon, and strolls about now and then."""
    dues = _pay_dues(ctx)
    if dues:
        return dues
    if not _daytime(ctx):
        return []
    p = ctx.perception
    aim = "Trade at the market"
    at_stall = at(p, MARKET) and _on_spot(ctx, f"go to {MARKET}")
    meal = _stall_meal(ctx, at_stall)
    if meal:
        return meal
    sessions = ctx.counter("sessions")
    if not at_stall:
        return [_go(ctx, MARKET, aim=aim, driver="ambition")]
    if sessions >= 4:  # stretch the legs now and then
        stroll = (WELL, "the temple", STOREHOUSES)[ctx.pick(3)]
        start = _then(lambda: _set(ctx, "sessions", 0), _go(ctx, stroll).start)
        return [Option(WORK, f"go to {stroll}", start, f"Stretch my legs to {stroll}", "social")]
    trade = _then(lambda: _set(ctx, "sessions", sessions + 1), lambda: ctx.api.work("trade"))
    return [Option(WORK, "trade", trade, aim, "ambition")]


def _stall_meal(ctx: Context, at_stall: bool) -> list[Option]:
    p = ctx.perception
    food = carried_food(p.you)
    hunger = ctx.needs.hunger
    if hunger and not food:
        score = {1: 46.0, 2: 86.0, 3: 106.0}[hunger]
        aim = "Eat from the stall's rice"
        if at_stall:
            return [Option(score, "eat", partial(ctx.api.eat, RICE), aim, "hunger")]
        return [_go(ctx, MARKET, score, aim, "hunger")]
    if at_stall and p.time_of_day == "late afternoon" and carrying(p, RICE) < LOW_RICE:
        if ctx.done_today("took rice home"):
            return []

        def take() -> ActionHandle:
            ctx.mark_done("took rice home")
            ctx.api.pick_up(f"{BUY_RICE} rice")
            return ctx.api.wait(2)

        return [Option(WORK + 1, "take rice for supper", take, "Take a day's rice home from the stall")]
    return []


# --- the guards ---


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


def night_watch(ctx: Context) -> list[Option]:
    """The ashigaru keeps the night watch (10 §3.1): his wage from the lord at dusk, then the west gate and the field
    racks in turn till dawn; he sleeps the morning away at home and buys his rice in the afternoon."""
    p = ctx.perception
    if ctx.phase == "night":
        ctx.notes["kept watch"] = True
        return _watch(ctx, WATCH)
    if ctx.phase == "dusk" or p.time_of_day == "late afternoon":
        wage = _collect_wage(ctx)
        if wage or ctx.phase == "dusk":
            return wage or _watch(ctx, 45.0)
    if not afternoon(p) and ctx.notes.get("kept watch"):  # a night on watch: the morning in bed
        aim = "Sleep after the night watch"
        if at_home(p):
            return [Option(WATCH, "sleep", _then(lambda: _set(ctx, "kept watch", False), ctx.api.sleep), aim, "rest")]
        return [Option(WATCH, "go home", lambda: ctx.api.walk_to_place("home"), aim, "rest")]
    return _pay_dues(ctx) or _buy_rice(ctx) or _watch(ctx, WORK)


def _watch(ctx: Context, score: float) -> list[Option]:
    """A watch at the west gate (on its guard stand), then a look over the racks in the rice fields, and back."""
    p, beat = ctx.perception, ctx.notes.get("beat", "gate")
    aim = "Keep watch over the west gate and the racks"
    if beat == "gate":
        if not (at(p, WEST_GATE) and _on_spot(ctx, f"go to {WEST_GATE}")):
            return [_go(ctx, WEST_GATE, score, aim)]
        watch = _then(lambda: _set(ctx, "beat", "racks"), lambda: ctx.api.work("guard"))
        return [Option(score, "guard", watch, aim)]
    if not (at(p, FIELDS) and _on_spot(ctx, f"go to {FIELDS}")):
        return [_go(ctx, FIELDS, score, aim)]
    look = _then(lambda: _set(ctx, "beat", "gate"), lambda: ctx.api.wait(15))
    return [Option(score, "look over the racks", look, aim)]


# --- the castle ---


def lord(ctx: Context) -> list[Option]:
    """Holds court at the castle in the morning (on his seat: the walk there ends on it); in the afternoon walks the
    market (gold, cloth, the price of rice) and the granary, selling its rice while rice is dear or fair; pays the
    watchman's wage at dusk and the smith for each tool he orders (10 §3.1, §2.7)."""
    paying = _payments(ctx)
    if paying:
        return paying
    p = ctx.perception
    if p.chest is not None:  # at the treasury: how many coins it holds
        ctx.notes["treasury"] = coins_in(p.chest.holds)
    if ctx.phase == "dusk":
        return _keep_goods(ctx)
    if not _daytime(ctx):
        return []
    purse_ = _top_up(ctx)
    if purse_:
        return purse_
    if afternoon(p):
        market = _market_round(ctx)
        if market:
            return market
    aim = "Hold court at the castle"
    if at(p, CASTLE) and _on_spot(ctx, f"go to {CASTLE}"):
        return [Option(WORK, "govern", lambda: ctx.api.work("govern"), aim)]
    return [_go(ctx, CASTLE, aim=aim)]


def _top_up(ctx: Context) -> list[Option]:
    """At home in the morning, the purse set to what a day needs: coins from the treasury (the keep's chest) for
    wages, orders and the market when it is light, the dues collected into it when it is heavy."""
    p = ctx.perception
    held = purse(p)
    if not at_home(p) or ctx.done_today("purse") or PURSE_LOW <= held < PURSE_HEAVY:
        return []

    def settle() -> ActionHandle:
        ctx.mark_done("purse")
        if held < PURSE_LOW:
            ctx.api.pick_up(f"{PURSE_TOP_UP} coins")
        else:
            ctx.api.stash(COINS, held - PURSE_TOP_UP)
        return ctx.api.wait(2)

    return [Option(WORK + 2, "settle the purse", settle, "Keep the treasury")]


def _keep_goods(ctx: Context) -> list[Option]:
    """Back at the keep at dusk, the gold and cloth bought go into the treasury."""
    p = ctx.perception
    goods = [item for item in (GOLD, CLOTH) if carrying(p, item)]
    if not goods or not at_home(p):
        return []

    def stash() -> ActionHandle:
        for item in goods:
            ctx.api.stash(item, 99)
        return ctx.api.rest(10)

    return [Option(41, "put away the goods", stash, "Put the gold and cloth in the treasury", "night")]


def _market_round(ctx: Context) -> list[Option]:
    """The afternoon round: at the stall buy gold (the lord's hoard) and on cloth days a length of cloth; while rice
    is dear (every day) or fair (every second day) fetch rice from the granary and sell it (10 §1.4, §2.7)."""
    p = ctx.perception
    if ctx.done_today("market round"):
        return []
    aim = "Walk the market and the granary"
    fetch = ctx.counter("fetch rice")
    if fetch:
        if not (at(p, STOREHOUSES) and _on_spot(ctx, f"go to {STOREHOUSES}")):
            return [_go(ctx, STOREHOUSES, aim=aim)]

        def take() -> ActionHandle:
            _set(ctx, "fetch rice", 0)
            ctx.api.pick_up(f"{fetch} rice")
            return ctx.api.wait(2)

        return [Option(WORK, "take granary rice", take, aim)]
    price = _price(p, RICE)
    deals: list[tuple[str, Callable[[], ActionResult]]] = []
    if carried_food(p.you).get(RICE) and price is not None and price.word in GRANARY_SALE:
        deals.append(("sell granary rice", partial(ctx.api.sell, RICE, 99)))
    chest = ctx.notes.get("treasury")
    treasury = purse(p) + (chest if isinstance(chest, int) else GOLD_TREASURY)  # his purse is the treasury's too
    if _on_sale(p, GOLD) and purse(p) >= PURSE_LOW and treasury > GOLD_TREASURY:
        deals.append(("buy gold", partial(ctx.api.buy, GOLD, 1)))
    if weekday(p) in CLOTH_DAYS and _on_sale(p, CLOTH) and purse(p) >= PURSE_LOW:
        deals.append(("buy cloth", partial(ctx.api.buy, CLOTH, 1)))
    for name, deal in deals:
        if not ctx.done_today(name) and not ctx.done_today(f"failed {name}"):
            return [Option(WORK, name, partial(_once, ctx, name, deal), aim)]
    if price is not None and price.word in GRANARY_SALE and not ctx.done_today("granary rice"):
        due = price.word == "dear" or (weekday(p) or 0) % 2 == 0
        ctx.mark_done("granary rice")
        if due:
            _set(ctx, "fetch rice", GRANARY_SALE[price.word])
            return [_go(ctx, STOREHOUSES, aim=aim)]
    if p.market is None:  # not at the open stall yet
        option = _to_stall(ctx, WORK, aim)
        if option is not None:
            return [option]
    ctx.mark_done("market round")
    return []


def _once(ctx: Context, name: str, deal: Callable[[], ActionResult]) -> ActionHandle:
    """A deal at the stall done once a day, then a moment stood by it."""
    ctx.mark_done(name)
    deal()
    return ctx.api.wait(3)


# --- the forge and the iron-sand bar ---


def smith(ctx: Context) -> list[Option]:
    """Forges an iron tool a day at the forge from midday (10 §3.1): an axe, a sickle and a spear in turn, from
    iron sand and wood bought at the stall (each iron craft burns 2 wood besides); every second tool goes to the lord's
    armoury (he pays for it), the rest to the stall; while two tools go unsold he forges no more."""
    dues = _pay_dues(ctx)
    if dues:
        return dues
    food = _buy_rice(ctx)
    if food or not _daytime(ctx):
        return food
    p = ctx.perception
    if ctx.finished("forge"):
        ctx.mark_done("forge")  # a tool a day: an axe or a sickle is two hours at the anvil
        made = ctx.counter("forged")
        ctx.notes["forged"] = made + 1
        if made % 2 == 0:
            ctx.notes["order"] = TOOLS[made % len(TOOLS)]
    order = _deliver_order(ctx)
    if order:
        return order
    for tool in TOOLS:
        if tool != ctx.notes.get("order"):
            sale = _sell(ctx, tool, "Sell my tools at the stall")
            if sale:
                return sale
    tool = TOOLS[ctx.counter("forged") % len(TOOLS)]
    unsold = sum(carrying(p, made) for made in TOOLS)
    if unsold >= UNSOLD_TOOLS or ctx.done_today("forge") or ctx.done_today("failed forge"):
        return townsperson(ctx)
    sand, wood = SUPPLIES[tool]
    aim = "Forge iron tools at the forge"
    for item, need, lot in ((WOOD, wood, 4), (IRON_SAND, sand, sand)):
        if carrying(p, item) < need:
            if ctx.done_today(f"failed buy {item}") or p.time_of_day not in STALL_TIMES:
                return townsperson(ctx)
            option = _at_stall(ctx, WORK, f"buy {item}", f"Buy {item} for the forge", partial(ctx.api.buy, item, lot))
            return [option] if option is not None else townsperson(ctx)
    if p.time_of_day not in FORGE_TIMES:
        return townsperson(ctx)
    if _refused(ctx, "forge"):
        ctx.mark_done("failed forge")
    if at(p, FORGE) and _on_spot(ctx, f"go to {FORGE}"):
        return [Option(WORK, "forge", partial(ctx.api.craft, tool), aim)]
    return [_go(ctx, FORGE, aim=aim)]


def _deliver_order(ctx: Context) -> list[Option]:
    """A tool made for the lord's armoury is brought to him; he pays for it once he has it (10 §2.7)."""
    order = ctx.notes.get("order")
    if not isinstance(order, str):
        return []
    aim = f"Bring the {order} to the lord"
    waiting = _paid_by_lord(ctx, order, "coins for it", aim, WORK + 6)
    if waiting is not None:
        return waiting
    if ctx.done_today(order) or not carrying(ctx.perception, order):
        ctx.notes.pop("order")
        return []
    lord = _lord(ctx.profile)

    def hand() -> ActionHandle:
        if lord is not None and ctx.api.give(order, lord).outcome == "done":
            ctx.mark_done(f"asked: {order}")
            ctx.api.say(f"Your {order}, my lord, {ORDER_WORDS}.")
        return ctx.api.wait(3)

    return _to_the_lord(ctx, WORK + 6, f"give the {order}", aim, hand)


def digger(ctx: Context) -> list[Option]:
    """Digs iron sand at the South marsh's bar in the morning, pans gold at the Falls pool on week days 2 and 6, sells
    what he brings at the stall in the afternoon and on every second day fetches wood from the North woods in the late
    afternoon, back at dusk (10 §3.1, §1.6: the walk home comes when the wolves are about)."""
    dues = _pay_dues(ctx)
    if dues:
        return dues
    food = _buy_rice(ctx)
    if food or not _daytime(ctx):
        return food
    p = ctx.perception
    now, day = p.time_of_day, weekday(p) or 1
    if now in DIG_TIMES:
        if day in GOLD_DAYS and carrying(p, GOLD) < GOLD_LOAD:
            panning = _gather_at(ctx, FALLS_POOL, GOLD, "Pan gold at the Falls pool")
            if panning:
                return panning
        if carrying(p, IRON_SAND) < DIG_LOAD:
            digging = _gather_at(ctx, SOUTH_MARSH, IRON_SAND, "Dig iron sand at the bar")
            if digging:
                return digging
    for item, aim in ((IRON_SAND, "Sell my iron sand"), (GOLD, "Sell my gold"), (WOOD, "Sell my wood")):
        sale = _sell(ctx, item, aim)
        if sale:
            return sale
    if day % 2 == 0 and now in WOOD_TIMES and carrying(p, WOOD) < 4:
        fetching = _gather_at(ctx, NORTH_WOODS, WOOD, "Fetch wood from the North woods")
        if fetching:
            return fetching
    return townsperson(ctx)


# --- everyone else ---


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
    """Errands between the well and the market, lingering a while at each (one wait, however short talk cuts it)."""
    if not _daytime(ctx):
        return []
    aim = "Run errands about town"
    here = next((place for place in (WELL, MARKET) if _on_spot(ctx, f"go to {place}")), None)
    if here is not None and at(ctx.perception, here) and ctx.notes.get("last") != "look around":
        return [Option(WORK, "look around", lambda: ctx.api.wait(15 + 5 * ctx.pick(3)), aim)]
    return [_go(ctx, MARKET if here == WELL else WELL, aim=aim)]


TOWN_ROUTINES: dict[Routine, Callable[[Context], list[Option]]] = {
    "lord": lord,
    "samurai": samurai,
    "merchant": merchant,
    "farmer": farmer,
    "weaver": weaver,
    "town_child": town_child,
    "townsperson": townsperson,
    "monk": monk,
    "night_watch": night_watch,
    "smith": smith,
    "digger": digger,
}
