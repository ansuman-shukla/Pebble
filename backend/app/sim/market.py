"""The market stall (10-world-v1 §2.5): prices that follow the stock, `buy` and `sell`, and the merchant's `trade`.

The drawn stall is a store (its stock in `state.stores` under the stall's id), open while someone works `trade` at it
(the merchant behind the counter, within `OPEN_M`); `buy` and `sell` answer "The stall is shut." otherwise. The till
is the keeper's purse: buyers pay into it and the stall pays sellers out of it, never more than it holds (D159).

Each good the stall trades (`data/economy.yaml`: a lot and a target stock) has a price factor from its stock, and
prices per lot from that:

    factor = clamp(√((target + 1) / (stock + 1)), 0.5, 2.0)      1 at the target stock: prices open at the values
    sells for ⌈value × factor × lot⌉      pays max(1, ⌊0.75 × sells for⌋)
    word: dear above the price at the target, fair at it, cheap below

A purchase prices each lot at the stock it takes from, a sale to the stall at the stock it makes, so the price walks
the curve as the stock moves and the stall always pays less for a lot than it asks for that same lot back (no round
trip pays). The stall buys only goods it sells and holds at most twice their target. A good whose word changes tells
`prices_changed` (after the sale that moved it, or at the tick's end for any other cause: a stash, a theft).
"""

import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import JsonValue, TypeAdapter

from app.observability.events import ItemLocation, PricesChanged, Traded
from app.sim.acting import capital, item_name, refuse
from app.sim.coins import number_words
from app.sim.core import SimCore
from app.sim.crafting import Station, count_words, stations
from app.sim.economy import StallLot, load_economy, value_of
from app.sim.items import ITEMS
from app.sim.state import ActionState, Citizen, System
from app.world_api.models import ActionResult, Buy, MarketView, PriceSeen, PriceWord, Sell

STALL_KIND = "market_stall"
OPEN_M = 6.0  # the keeper works `trade` within this of the stall; buyers and sellers stand within it too
FACTOR_RANGE = (0.5, 2.0)
BUY_SHARE = 0.75  # the stall pays this share of what it sells a lot for
HOLD_TARGETS = 2  # the stall buys a good up to this many times its target stock
_EPSILON = 1e-9  # a price that is a whole number of coins stays that number despite float error


# --- prices ---


def factor(stock: int, target: int) -> float:
    low, high = FACTOR_RANGE
    return min(high, max(low, math.sqrt((target + 1) / (stock + 1))))


def sell_price(item: str, stock: int) -> int:
    """What the stall asks for one lot of the good at this stock."""
    lot = _lot(item)
    return math.ceil(value_of(item, "town") * factor(stock, lot.target) * lot.lot - _EPSILON)


def buy_price(item: str, stock: int) -> int:
    """Three quarters of what the stall asks for one lot at this stock (at least a coin)."""
    return max(1, math.floor(BUY_SHARE * sell_price(item, stock) + _EPSILON))


def pays_for(item: str, stock: int) -> int:
    """What the stall pays for the next lot sold to it while it holds `stock`: priced at the stock that lot makes,
    so selling a lot and buying it back never gains a coin."""
    return buy_price(item, stock + _lot(item).lot)


def price_word(item: str, stock: int) -> PriceWord:
    """Dear, fair or cheap: the lot's price against its price at the target stock (the good's value)."""
    lot = _lot(item)
    price, fair = sell_price(item, stock), math.ceil(value_of(item, "town") * lot.lot - _EPSILON)
    return "dear" if price > fair else "cheap" if price < fair else "fair"


def stall_lot(item: str) -> StallLot | None:
    """How the stall trades a good (its lot and target), or None when it doesn't."""
    good = load_economy().goods.get(item)
    return good.stall if good is not None else None


def stall_goods() -> tuple[str, ...]:
    return tuple(sorted(item for item, good in load_economy().goods.items() if good.stall is not None))


def _lot(item: str) -> StallLot:
    lot = stall_lot(item)
    if lot is None:
        raise ValueError(f"the stall doesn't trade {item}")
    return lot


# --- the stall's state: the price words last told, and each trading session's sales ---


@dataclass
class MarketState:
    words: dict[str, dict[str, PriceWord]] = field(default_factory=dict)  # stall -> item -> word last told
    sales: dict[str, int] = field(default_factory=dict)  # "<keeper>#<trade action number>" -> sales made in it
    stalls: tuple[Station, ...] | None = field(default=None, compare=False, repr=False)  # found on first use


def _dump(state: MarketState) -> JsonValue:
    return {
        "words": {stall: dict[str, JsonValue](sorted(words.items())) for stall, words in sorted(state.words.items())},
        "sales": dict[str, JsonValue](sorted(state.sales.items())),
    }


def _load(data: JsonValue) -> MarketState:
    if not isinstance(data, dict) or set(data) != {"words", "sales"}:
        raise ValueError("a market block holds {words: {stall: {item: word}}, sales: {session: count}}")
    return MarketState(words=_WORDS.validate_python(data["words"]), sales=_SALES.validate_python(data["sales"]))


_WORDS = TypeAdapter(dict[str, dict[str, PriceWord]])
_SALES = TypeAdapter(dict[str, int])
MARKET = System[MarketState]("market", 1, new=lambda _world: MarketState(), dump=_dump, load=_load)


# --- where the stall is and whether it is open ---


def stalls(core: SimCore) -> tuple[Station, ...]:
    """The drawn stalls (found once a run: the tick-end hook asks every tick)."""
    state = MARKET.of(core.state)
    if state.stalls is None:
        state.stalls = tuple(stations(core.world, STALL_KIND))
    return state.stalls


def stall_in_reach(core: SimCore, citizen: Citizen) -> Station | None:
    near = [(core.distance_m(citizen.position, s.centre), s.id, s) for s in stalls(core)]
    within = [option for option in near if option[0] <= OPEN_M]
    return min(within)[2] if within else None


def keeper(core: SimCore, stall: Station) -> Citizen | None:
    """Who keeps the stall open: someone awake working `trade` within `OPEN_M` of it (the merchant)."""
    return next(
        (
            citizen
            for citizen in core.living()
            if citizen.action is not None
            and citizen.action.kind == "work"
            and citizen.action.item == "trade"
            and not citizen.body.asleep
            and core.distance_m(citizen.position, stall.centre) <= OPEN_M
        ),
        None,
    )


def stock_of(core: SimCore, stall: Station, item: str) -> int:
    return core.state.stores.get(stall.id, {}).get(item, 0)


# --- buying and selling ---


def buy(core: SimCore, citizen: Citizen, action: Buy) -> ActionResult:
    """Buy whole lots of a good from an open stall within reach, as many as asked that it has, you can pay for and
    carry, lot by lot at the stock each one leaves."""
    opened = _open_stall(core, citizen, "buy")
    if isinstance(opened, ActionResult):
        return opened
    stall, merchant = opened
    item = item_name(action.item)
    lot = stall_lot(item) if item is not None else None
    if item is None or lot is None:
        return refuse(core, citizen, "buy", f"The stall doesn't sell {action.item}.")
    if action.amount < lot.lot:
        return refuse(core, citizen, "buy", f"{capital(item)} is sold {_lot_words(item, lot.lot)} at a time.")
    remember_prices(core, stall)
    stock, coins, room = stock_of(core, stall, item), citizen.inventory.get("coins", 0), core.room_for(citizen, item)
    deal, paid, stopped = 0, 0, ""
    while deal < action.amount // lot.lot:
        price = sell_price(item, stock)
        if stock < lot.lot:
            stopped = f"The stall has no more {ITEMS[item].plural or item}."
        elif coins - paid < price:
            stopped = "You can't pay for more."
        elif room < (deal + 1) * lot.lot:
            stopped = "You can't carry any more."
        if stopped:
            break
        deal, paid, stock = deal + 1, paid + price, stock - lot.lot
    if deal == 0:
        return refuse(core, citizen, "buy", stopped)
    count = deal * lot.lot
    seq = core.emit(
        "bought",
        Traded(item=item, count=count, lots=deal, coins=paid, stall=stall.id, merchant=merchant.id),
        actor=citizen,
    )
    _move_store(core, citizen, item, -count, stall, seq)
    _pay(core, citizen, merchant, paid, seq)
    _tally(core, merchant)
    note_prices(core, stall, seq)
    bought = f"You buy {count_words(item, count)} for {_coins(paid)}."
    return ActionResult(action="buy", outcome="done", text=f"{bought} {stopped}".strip())


def sell(core: SimCore, citizen: Citizen, action: Sell) -> ActionResult:
    """Sell whole lots of a good you carry to an open stall within reach, as many as asked and carried that it wants
    (up to twice its target) and can pay for, lot by lot at the stock each one makes."""
    opened = _open_stall(core, citizen, "sell")
    if isinstance(opened, ActionResult):
        return opened
    stall, merchant = opened
    item = item_name(action.item)
    lot = stall_lot(item) if item is not None else None
    if item is None or lot is None:
        return refuse(core, citizen, "sell", f"The stall doesn't buy {action.item}.")
    carried = citizen.inventory.get(item, 0)
    if carried < lot.lot:
        return refuse(core, citizen, "sell", f"You don't have {count_words(item, lot.lot)} to sell.")
    if action.amount < lot.lot:
        return refuse(core, citizen, "sell", f"{capital(item)} is bought {_lot_words(item, lot.lot)} at a time.")
    remember_prices(core, stall)
    stock, till = stock_of(core, stall, item), merchant.inventory.get("coins", 0)
    deal, paid, stopped = 0, 0, ""
    while deal < min(action.amount, carried) // lot.lot:
        price = pays_for(item, stock)
        if stock + lot.lot > HOLD_TARGETS * lot.target:
            stopped = f"The stall has all the {ITEMS[item].plural or item} it wants."
        elif till - paid < price:
            stopped = "The stall can't pay for more."
        if stopped:
            break
        deal, paid, stock = deal + 1, paid + price, stock + lot.lot
    if deal == 0:
        return refuse(core, citizen, "sell", stopped)
    count = deal * lot.lot
    seq = core.emit(
        "sold",
        Traded(item=item, count=count, lots=deal, coins=paid, stall=stall.id, merchant=merchant.id),
        actor=citizen,
    )
    _move_store(core, citizen, item, count, stall, seq)
    _pay(core, merchant, citizen, paid, seq)
    _tally(core, merchant)
    note_prices(core, stall, seq)
    sold = f"You sell {count_words(item, count)} for {_coins(paid)}."
    return ActionResult(action="sell", outcome="done", text=f"{sold} {stopped}".strip())


def _open_stall(
    core: SimCore, citizen: Citizen, action: Literal["buy", "sell"]
) -> tuple[Station, Citizen] | ActionResult:
    stall = stall_in_reach(core, citizen)
    if stall is None:
        return refuse(core, citizen, action, "There's no stall here.")
    merchant = keeper(core, stall)
    if merchant is None:
        return refuse(core, citizen, action, "The stall is shut.")
    if merchant is citizen:
        return refuse(core, citizen, action, "You keep this stall; you can't trade with yourself.")
    return stall, merchant


def _move_store(core: SimCore, citizen: Citizen, item: str, into_stall: int, stall: Station, seq: int) -> None:
    """Move goods between the citizen and the stall's stock (positive: into the stall)."""
    store = core.state.stores.setdefault(stall.id, {})
    store[item] = store.get(item, 0) + into_stall
    citizen.inventory[item] = citizen.inventory.get(item, 0) - into_stall
    for stock in (store, citizen.inventory):
        if stock[item] == 0:
            del stock[item]
    hand, shelf = ItemLocation(kind="inventory", id=citizen.id), ItemLocation(kind="store", id=stall.id)
    source, destination = (hand, shelf) if into_stall > 0 else (shelf, hand)
    core.item_moved(citizen, item, abs(into_stall), source, destination, cause_seq=seq)


def _pay(core: SimCore, payer: Citizen, payee: Citizen, coins: int, seq: int) -> None:
    payer.inventory["coins"] -= coins
    if payer.inventory["coins"] == 0:
        del payer.inventory["coins"]
    payee.inventory["coins"] = payee.inventory.get("coins", 0) + coins
    core.item_moved(
        payer,
        "coins",
        coins,
        ItemLocation(kind="inventory", id=payer.id),
        ItemLocation(kind="inventory", id=payee.id),
        cause_seq=seq,
    )


def _tally(core: SimCore, merchant: Citizen) -> None:
    if merchant.action is None:
        raise ValueError(f"{merchant.id} keeps the stall without working at it")
    sales = MARKET.of(core.state).sales
    session = f"{merchant.id}#{merchant.action.number}"
    sales[session] = sales.get(session, 0) + 1


def _coins(count: int) -> str:
    return "a coin" if count == 1 else f"{number_words(count)} coins"


def _lot_words(item: str, lot: int) -> str:
    """A lot as a buyer counts it: "a hide", "two measures", "four pieces"."""
    kind = ITEMS[item]
    if lot == 1:
        return kind.one
    unit = kind.one.partition(" ")[2].partition(" of ")[0] if kind.mass else (kind.plural or kind.name)
    return f"{number_words(lot)} {unit}s" if kind.mass else f"{number_words(lot)} {unit}"


# --- price words and what someone at the stall sees ---


def remember_prices(core: SimCore, stall: Station) -> None:
    """Note the word of each good not noted yet, without telling it (the stall's opening prices)."""
    words = MARKET.of(core.state).words.setdefault(stall.id, {})
    for item in stall_goods():
        words.setdefault(item, price_word(item, stock_of(core, stall, item)))


def note_prices(core: SimCore, stall: Station, cause_seq: int | None = None) -> None:
    """Tell `prices_changed` for each good whose word moved since it was last told."""
    words = MARKET.of(core.state).words.setdefault(stall.id, {})
    for item in stall_goods():
        stock = stock_of(core, stall, item)
        word = price_word(item, stock)
        before = words.setdefault(item, word)
        if word == before:
            continue
        words[item] = word
        lot = _lot(item).lot
        payload = PricesChanged(
            stall=stall.id,
            item=item,
            word=word,
            before=before,
            lot=lot,
            sell=sell_price(item, stock),
            buy=pays_for(item, stock),
        )
        core.emit("prices_changed", payload, cause_seq=cause_seq)


def watch_prices(core: SimCore) -> None:
    """Tick-end hook: words moved by anything but a sale (a stash, a theft), and sessions no longer running let go."""
    for stall in stalls(core):
        note_prices(core, stall)
    sales = MARKET.of(core.state).sales
    running = {f"{citizen.id}#{citizen.action.number}" for citizen in core.citizens() if citizen.action is not None}
    for session in sorted(set(sales) - running):
        del sales[session]


def market_view(core: SimCore, citizen: Citizen) -> MarketView | None:
    """What an open stall within reach sells, each good's price in words and whether it is dear, fair or cheap."""
    stall = stall_in_reach(core, citizen)
    if stall is None or citizen.body.asleep or keeper(core, stall) is None:
        return None
    seen: list[PriceSeen] = []
    for item in stall_goods():
        stock, lot = stock_of(core, stall, item), _lot(item).lot
        each = "each" if lot == 1 else f"for {_lot_words(item, lot)}"
        sells = f"{_coins(sell_price(item, stock))} {each}" if stock >= lot else "none left"
        seen.append(
            PriceSeen(
                item=item, price=f"{sells}; it pays {_coins(pays_for(item, stock))}", word=price_word(item, stock)
            )
        )
    return MarketView(items=seen)


# --- the merchant's trading session (`work("trade")`) ---


def trade(core: SimCore, citizen: Citizen, action: ActionState) -> str:
    """`work("trade")`'s finisher: what a session behind the stall came to."""
    sales = MARKET.of(core.state).sales.pop(f"{citizen.id}#{action.number}", 0)
    if sales == 0:
        return "You keep the stall a while; nobody comes to trade."
    made = "a sale" if sales == 1 else f"{number_words(sales)} sales"
    return f"You keep the stall a while and make {made}."
