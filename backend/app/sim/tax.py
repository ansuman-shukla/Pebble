"""Tax, dues and the daily ledger (10-world-v1 §2.7).

- **Rice tax** (nengu): each rice harvest adds ⌈40 %⌉ of it to what the harvester's household owes (`tax_assessed`);
  `work("store food")` at the granary pays it down first from the rice they carry (`tax_paid`). Rice still owed at the
  household's local midnight is overdue (`tax_overdue`); it carries over.
- **Coin dues**: each local midnight a household starts a new day owing its dues: 5 mon for a household outside the
  fields, 6 mon a paddy for a farm household (the keep and the temple pay none). They are settled by handing coins to
  the lord (`give`), which pays them down (`tax_paid`, causing the coins' move). What is still owed when court day
  (week day 7) ends is in arrears, and stays overdue until paid.
- **Overdue**: one `tax_overdue` per household per local midnight while it owes overdue rice or coins, with the days
  running it has been in arrears (3 lets the lord fine them, §3.4); paying everything clears the count.
- **Ledger**: at each living citizen's local midnight, one `ledger`: coins carried, wealth (coins + the town value of
  what they carry + an equal share of their household chest), coins in and out since their last ledger, and what
  their household owes.

The system `tax` keeps each household's account and each citizen's coins in and out since their ledger, which it
counts from the `item_moved` events (its `on_event` hook).
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from pydantic import JsonValue, TypeAdapter

from app.observability.events import EventDraft, ItemLocation, ItemMoved, Ledger, TaxChange
from app.sim import ownership, society
from app.sim.clock import DAY_MINUTES, game_minute, local_minute
from app.sim.core import SimCore
from app.sim.economy import value_of
from app.sim.items import ITEMS, amount_words
from app.sim.ownership import CHEST, KEEP, is_granary, owns
from app.sim.state import ActionState, Citizen, Region, System
from app.sim.vec import Vec3, lat_lon_deg

LocalTest = Callable[[Vec3], bool]  # app.sim.systems' (which registers these hooks, so can't be imported here)
RICE_TAX = 0.4  # of each harvest
DUES = 5  # mon a day, a household outside the fields
FIELD_DUES = 6  # mon a day for each paddy a farm household farms
PADDIES: Mapping[str, int] = {"farmhouse-1": 4, "farmhouse-2": 2}  # farm household -> paddies (§1.4)
NO_DUES = frozenset({KEEP, "temple-hall"})
COURT_DAY = 7  # dues still owed when it ends (at the household's local midnight) are in arrears
LEDGER_GAP = DAY_MINUTES // 2  # ticks between one citizen's ledgers at the least


@dataclass
class Account:
    """What one household owes."""

    rice: int = 0  # rice tax owed
    coins: int = 0  # dues owed
    arrears: int = 0  # the part of `coins` that was owed when the last court day ended
    days: int = 0  # local midnights running it was overdue


@dataclass
class Books:
    accounts: dict[str, Account] = field(default_factory=dict)  # household -> account
    income: dict[str, int] = field(default_factory=dict)  # citizen -> coins received since their last ledger
    spent: dict[str, int] = field(default_factory=dict)  # citizen -> coins paid out since their last ledger
    ledgered: dict[str, int] = field(default_factory=dict)  # citizen -> tick of their last ledger


_BLOCK = TypeAdapter(Books)


def _dump(books: Books) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(books, mode="json"))


def _load(data: JsonValue) -> Books:
    return _BLOCK.validate_python(data)


TAX = System[Books]("tax", 1, new=lambda _world: Books(), dump=_dump, load=_load)


def dues_of(household: str) -> int:
    """Mon a day the household owes in dues."""
    if household in NO_DUES:
        return 0
    return FIELD_DUES * PADDIES[household] if household in PADDIES else DUES


def account(core: SimCore, household: str) -> Account:
    return TAX.of(core.state).accounts.setdefault(household, Account())


def assess_harvest(core: SimCore, citizen: Citizen, count: int, cause_seq: int | None = None) -> int | None:
    """The citizen harvested `count` rice: their household owes ⌈40 %⌉ of it more (`tax_assessed`, its seq, caused by
    `cause_seq`, the harvest's `item_moved`). The one seam whatever harvests rice calls (`paddies.harvest`, right after
    the rice moves from the paddy to the harvester)."""
    if citizen.home is None or count <= 0 or citizen.region != "town":
        return None
    owed = account(core, citizen.home)
    rice = math.ceil(RICE_TAX * count)
    owed.rice += rice
    return core.emit("tax_assessed", _change(citizen.home, owed, rice=rice), actor=citizen, cause_seq=cause_seq)


def store_food(core: SimCore, citizen: Citizen, action: ActionState) -> str:
    """`work("store food")` at a store: the rice tax the household owes is paid first from the rice carried (into the
    granary); a store of their own then takes the rest of their food, someone else's none of it."""
    store_id = str(action.store_id)
    store = core.state.stores.setdefault(store_id, {})
    told: list[str] = []
    noticed = ownership.notice(core, citizen, store_id).strip()  # the keep notices what others took from it
    owed = account(core, citizen.home) if citizen.home is not None else None
    if owed is not None and owed.rice and is_granary(core.world, store_id) and citizen.inventory.get("rice"):
        rice = min(owed.rice, citizen.inventory["rice"])
        owed.rice -= rice
        _clear_if_paid(owed)
        paid = core.emit("tax_paid", _change(str(citizen.home), owed, rice=rice), actor=citizen)
        _move(core, citizen, store, store_id, "rice", rice, paid)
        told.append(f"You pay {amount_words(rice, ITEMS['rice'])} as rice tax.")
        if owed.rice:
            told.append("Your household still owes more.")
    if owns(core.world, citizen, store_id):
        stored = [_move(core, citizen, store, store_id, item, citizen.inventory[item], None) for item in _food(citizen)]
        if stored:
            told.append(f"You put {' and '.join(stored)} in the storehouse.")
    if not told and owed is not None and owed.rice:
        told.append("You carry no rice for the tax.")
    if not told:
        told.append("You owe no rice tax, and the storehouse isn't yours to fill.")
    return " ".join([*told, noticed] if noticed else told)


def paid_dues(core: SimCore, giver: Citizen, receiver: Citizen, item: str, count: int) -> int | None:
    """`giver` hands `count` of `item` to `receiver`: coins to the lord pay down the dues the giver's household owes
    (`tax_paid`, its seq, which causes the coins' move). None if it pays nothing."""
    if item != "coins" or giver.home is None or "lord" not in society.titles(core, receiver.id):
        return None
    owed = account(core, giver.home)
    coins = min(count, owed.coins)
    if coins <= 0:
        return None
    owed.coins -= coins
    owed.arrears = max(0, owed.arrears - coins)
    _clear_if_paid(owed)
    return core.emit("tax_paid", _change(giver.home, owed, coins=coins), actor=giver)


def pay_by_fine(core: SimCore, payer: Citizen, household: str, mon: int, cause_seq: int) -> int | None:
    """A fine for overdue tax (justice, §3.4) settles what the household owes: its mon pay the dues in arrears first,
    then the rice owed at rice's town value (`tax_paid` by the one fined, caused by the judgement; its seq). None if
    it pays nothing."""
    owed = account(core, household)
    coins = min(mon, owed.arrears)
    rice = min(owed.rice, math.floor((mon - coins) / value_of("rice", "town")))
    if coins <= 0 and rice <= 0:
        return None
    owed.coins, owed.arrears, owed.rice = owed.coins - coins, owed.arrears - coins, owed.rice - rice
    _clear_if_paid(owed)
    return core.emit("tax_paid", _change(household, owed, rice=rice, coins=coins), actor=payer, cause_seq=cause_seq)


def households(core: SimCore) -> dict[str, Vec3]:
    """Every town household with a living resident -> where its local midnight is told (its home's door)."""
    homes: dict[str, Vec3] = {}
    for citizen in core.living():
        home = core.world.structures.get(citizen.home) if citizen.home is not None else None
        if citizen.region == "town" and home is not None:
            homes[home.id] = home.door
    return dict(sorted(homes.items()))


def settle_at_midnight(core: SimCore, now: LocalTest) -> None:
    """Midnight hook, per household whose local midnight it is: a court day ending puts what is owed in arrears;
    overdue rice or arrears are told (`tax_overdue`); then the new day's dues are owed."""
    for household, door in households(core).items():
        if not now(door):
            continue
        owed = account(core, household)
        if _local_day_ended(core, door) == COURT_DAY:
            owed.arrears = owed.coins
        if owed.rice or owed.arrears:
            owed.days += 1
            core.emit("tax_overdue", _change(household, owed, rice=owed.rice, coins=owed.arrears, days=owed.days))
        else:
            owed.days = 0
        if dues := dues_of(household):
            owed.coins += dues
            core.emit("tax_assessed", _change(household, owed, coins=dues))


def _local_day_ended(core: SimCore, unit: Vec3) -> int:
    """The week day that just ended at this spot's local midnight: its local clock runs 4 minutes a degree east of the
    town's, so a house west of the castle ends its day a few minutes after the town does."""
    before = core.state.tick - 1
    _, lon = lat_lon_deg(unit)
    ahead = local_minute(before, core.world.town_lon_deg, lon) - game_minute(before) % DAY_MINUTES
    ahead = (ahead + DAY_MINUTES / 2) % DAY_MINUTES - DAY_MINUTES / 2  # minutes the spot's clock is ahead of the town's
    return society.day_of_week(before + math.floor(ahead))


def _midnight_since(core: SimCore, unit: Vec3, tick: int) -> bool:
    """A local midnight at this spot fell after `tick` (by this tick)."""
    _, lon = lat_lon_deg(unit)
    ahead = (lon - core.world.town_lon_deg) * 4  # minutes the spot's clock is ahead of the town's
    return (game_minute(core.state.tick) + ahead) // DAY_MINUTES > (game_minute(tick) + ahead) // DAY_MINUTES


def ledger_at_midnight(core: SimCore, now: LocalTest) -> None:
    """Midnight hook: every living citizen whose local midnight it is gets their `ledger` for the day, once: someone
    walking west across their midnight (a few minutes a hundred metres) meets it again, and someone walking east
    across it steps past the tick it falls on, so after the first a ledger is due once a midnight has passed where
    they stand since the last."""
    books = TAX.of(core.state)
    chests = _chest_shares(core)
    for citizen in core.living():
        last = books.ledgered.get(citizen.id)
        if last is None:
            due = now(citizen.position)
        else:
            due = core.state.tick - last >= LEDGER_GAP and _midnight_since(core, citizen.position, last)
        if not due:
            continue
        books.ledgered[citizen.id] = core.state.tick
        owed = books.accounts.get(citizen.home or "", Account())
        payload = Ledger(
            coins=citizen.inventory.get("coins", 0),
            wealth_mon=wealth_mon(citizen.inventory, citizen.region, chests.get(citizen.home or "", 0.0)),
            income_24h=books.income.pop(citizen.id, 0),
            spent_24h=books.spent.pop(citizen.id, 0),
            owed_rice=owed.rice,
            owed_coins=owed.coins,
        )
        core.emit("ledger", payload, actor=citizen)


def wealth_mon(inventory: Mapping[str, int], region: Region, share: float) -> int:
    """The ledger's wealth: coins and the value of what someone carries (to their group) plus their share of the
    household chest, in whole mon (the scoreboard's too)."""
    return round(sum(value_of(item, region) * count for item, count in inventory.items()) + share)


def chest_share(chest: Mapping[str, int], residents: int) -> float:
    """Each living resident's equal share of the town value of their household chest."""
    return sum(value_of(item, "town") * count for item, count in chest.items()) / residents


def count_coins(core: SimCore, event: EventDraft) -> None:
    """Event hook: coins moving into or out of a citizen's inventory count as their income or spending (not when they
    come from or go to their own household's store)."""
    moved = event.payload
    if not isinstance(moved, ItemMoved) or moved.item != "coins":
        return
    books = TAX.of(core.state)
    source, destination = moved.source, moved.destination
    for tally, side, other in ((books.spent, source, destination), (books.income, destination, source)):
        holder = core.state.citizens.get(side.id or "") if side.kind == "inventory" else None
        if holder is None or (other.kind == "store" and owns(core.world, holder, str(other.id))):
            continue  # coins put in or taken from their own household's store stay theirs
        tally[holder.id] = tally.get(holder.id, 0) + moved.count


def _chest_shares(core: SimCore) -> dict[str, float]:
    """Household -> each living resident's equal share of the town value of its chest."""
    residents: dict[str, int] = {}
    for citizen in core.living():
        if citizen.home is not None:
            residents[citizen.home] = residents.get(citizen.home, 0) + 1
    return {home: chest_share(core.state.stores.get(home + CHEST, {}), count) for home, count in residents.items()}


def _food(citizen: Citizen) -> list[str]:
    return [item for item in sorted(citizen.inventory) if ITEMS[item].food > 0]


def _move(
    core: SimCore, citizen: Citizen, store: dict[str, int], store_id: str, item: str, count: int, cause: int | None
) -> str:
    citizen.inventory[item] -= count
    if citizen.inventory[item] == 0:
        del citizen.inventory[item]
    store[item] = store.get(item, 0) + count
    where = ItemLocation(kind="inventory", id=citizen.id)
    core.item_moved(citizen, item, count, where, ItemLocation(kind="store", id=store_id), cause_seq=cause)
    return amount_words(count, ITEMS[item])


def _clear_if_paid(owed: Account) -> None:
    if not owed.rice and not owed.arrears:
        owed.days = 0


def _change(household: str, owed: Account, *, rice: int = 0, coins: int = 0, days: int = 0) -> TaxChange:
    return TaxChange(household=household, rice=rice, coins=coins, owed_rice=owed.rice, owed_coins=owed.coins, days=days)
