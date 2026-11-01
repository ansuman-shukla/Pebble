"""The spectator scoreboard (10-world-v1 §7, D95): each citizen's wealth, flow, health, duty, status, ambition, ties
and skills as numbers, each group's spread of wealth and deeds, the money supply check and the market stall's stocks
and prices, now or at a past tick. For spectators and research only: no mind is ever shown it as a score.

Derived per request (D62): the world replayed at the tick (purses, goods, chests, bodies, standing, rank, knowledge),
the run's events up to it (coins moved, sales, tax, deeds, judgements, crafts, actions) and the tick summaries of the
last day (bodies, sampled). Bonds are society's as of the snapshot the replay starts from (they have no event of their
own, D186), so they lag the tick by up to a game hour.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Integer, and_, or_
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from app.db.models import Event
from app.observability.events import BodyValues, EventDraft
from app.observability.replay import ReplayCitizen, ReplayState
from app.services.ambitions import AmbitionProgress, Facts, Record, action_spans, ambition_progress, cast_ambitions
from app.services.entities import WorldAt, world_at
from app.services.places import PlaceIndex
from app.sim.clock import DAY_MINUTES, town_clock
from app.sim.crafting import load_recipes, stations
from app.sim.economy import load_economy
from app.sim.market import STALL_KIND, pays_for, price_word, sell_price, stall_goods, stall_lot
from app.sim.ownership import CHEST, owner_of, owns
from app.sim.society import GROUPS, SOCIETY, standing_word
from app.sim.state import Region
from app.sim.tax import chest_share, wealth_mon
from app.sim.work import work_task
from app.sim.world import SimWorld

WEEK = 7  # days the `_7d` fields look back
BODY_SAMPLE_TICKS = 10  # wellbeing reads every tenth tick summary of the last day
WELL = {"hunger": 60.0, "thirst": 60.0, "energy": 20.0}  # below, below, above: a well minute (10 §7)
TOP_BONDS = 3
GROUP_NAMES: dict[Region, str] = {"town": "the castle town", "band_a": "Band A", "band_b": "Band B"}
SKILLED = ("gather", "hunt", "make_fire", "feed_fire", "tend", "work", "craft")  # actions practising a skill
SKILL_OF: dict[str, str] = {
    "gather": "gathering",
    "hunt": "hunting",
    "make_fire": "fire",
    "feed_fire": "fire",
    "tend": "healing",
}  # work and craft practise their task's or recipe's skill
COIN_FLOW = ("item_moved",)
READ = (  # the event types the scoreboard and the ambition checks read over the whole run
    "bought",
    "sold",
    "tax_assessed",
    "tax_paid",
    "tax_overdue",
    "stole",
    "trespassed",
    "injured",
    "died",
    "seized",
    "judged",
    "tended",
    "crafted",
    "need_changed",
)
ACTION_EVENTS = ("action_started", "action_finished", "action_interrupted")
TAX_EVENTS = ("tax_assessed", "tax_paid", "tax_overdue")


class Owed(BaseModel):
    rice: int
    coins: int


class BondView(BaseModel):
    id: str
    name: str
    value: int  # -100..100


class CitizenScore(BaseModel):
    id: str
    name: str
    role: str
    region: Region
    alive: bool
    # wealth and flow
    coins: int
    wealth_mon: int  # coins + town value of what they carry + an equal share of the household chest (the ledger's)
    income_24h: int  # coins in over the last game day (not from their own household's stores)
    spent_24h: int  # coins out over the last game day (not into their own household's stores)
    # health
    health: float
    wellbeing_24h: int | None  # % of the last day with hunger < 60, thirst < 60, energy > 20 (None: no sample)
    # duty: their household's account
    tax_owed: Owed
    tax_paid_7d: Owed
    # status
    rank: int | None  # 1 child .. 5 lord
    titles: list[str]
    standing: int | None  # with their own group, -100..100
    standing_word: str
    # ambition
    ambition: AmbitionProgress | None  # None: the cast gives them none
    # ties
    trade_partners_7d: int  # distinct people they bought from or sold to at a stall, or who traded at theirs
    people_known: int
    places_known: int
    bonds_top3: list[BondView]  # their warmest bonds (as of the snapshot before the tick)
    # skill
    skill_hours: dict[str, float]  # hours practised per skill over the run


class GroupScore(BaseModel):
    group: Region
    name: str
    alive: int
    wealth_mon: int  # the living members' together
    gini_wealth: float  # 0 everyone alike .. 1 one holds it all
    deeds_7d: int  # deeds its members did
    caught_7d: int  # judgements of its members


class StallGood(BaseModel):
    item: str
    stock: int
    lot: int
    sell: int  # mon a lot the stall asks
    buy: int  # mon it pays for the next lot sold to it
    word: str  # dear, fair or cheap


class StallView(BaseModel):
    id: str
    keeper: str | None  # the keeper's name
    trading: bool  # the keeper is working the stall
    goods: list[StallGood]


class ScoreboardView(BaseModel):
    run_id: str
    tick: int
    day: int
    time: str
    citizens: list[CitizenScore]
    groups: list[GroupScore]
    money_supply: int  # coins carried, stored and on the ground
    money_supply_ok: bool  # the closed supply holds (10 §2.1)
    stalls: list[StallView]


@dataclass(frozen=True)
class Board:
    citizens: list[CitizenScore]
    groups: list[GroupScore]
    money_supply: int
    money_supply_ok: bool
    stalls: list[StallView]


def score_board(
    facts: Facts, bodies: Sequence[Mapping[str, BodyValues]], bonds: Mapping[str, int], world: SimWorld
) -> Board:
    """The board from the replayed world, the run's events (`READ`, coin moves of the last day, gifts and the
    `SKILLED` actions) and the bodies of the last day's sampled tick summaries."""
    state = facts.state
    shares = _chest_shares(state)
    wealth = {c.id: wealth_mon(c.inventory, c.region, _share(c, shares)) for c in state.citizens.values()}
    income, spent = _coin_flow(facts, world)
    partners = _partners(facts)
    owed, paid = _accounts(facts)
    skills = _skill_hours(facts)
    ambitions = cast_ambitions()
    citizens = [
        CitizenScore(
            id=c.id,
            name=c.name,
            role=c.role,
            region=c.region,
            alive=c.alive,
            coins=c.inventory.get("coins", 0),
            wealth_mon=wealth[c.id],
            income_24h=income.get(c.id, 0),
            spent_24h=spent.get(c.id, 0),
            health=c.body[3],
            wellbeing_24h=_wellbeing(c.id, bodies),
            tax_owed=owed.get(c.home or "", Owed(rice=0, coins=0)),
            tax_paid_7d=paid.get(c.home or "", Owed(rice=0, coins=0)),
            rank=c.member.rank if c.member is not None else None,
            titles=list(c.member.titles) if c.member is not None else [],
            standing=c.standing.get(c.region),
            standing_word=standing_word(c.standing[c.region]) if c.region in c.standing else "",
            ambition=ambition_progress(facts, c, ambitions[c.id]) if c.id in ambitions else None,
            trade_partners_7d=len(partners.get(c.id, set())),
            people_known=len(c.people),
            places_known=len(c.places),
            bonds_top3=_bonds(c, state, bonds),
            skill_hours=skills.get(c.id, {}),
        )
        for _, c in sorted(state.citizens.items())
    ]
    money = _money(state)
    return Board(
        citizens=citizens,
        groups=_groups(facts, wealth),
        money_supply=money,
        money_supply_ok=money == load_economy().money_supply,
        stalls=_stalls(state, world),
    )


def _chest_shares(state: ReplayState) -> dict[str, float]:
    """Household -> each living resident's share of its chest (the ledger's rule)."""
    residents: dict[str, int] = {}
    for citizen in state.citizens.values():
        if citizen.alive and citizen.home is not None:
            residents[citizen.home] = residents.get(citizen.home, 0) + 1
    return {home: chest_share(state.stores.get(home + CHEST, {}), count) for home, count in residents.items()}


def _share(citizen: ReplayCitizen, shares: Mapping[str, float]) -> float:
    """Their share of the household chest: the living residents share it, the dead hold none (the ledger's rule)."""
    return shares.get(citizen.home or "", 0.0) if citizen.alive else 0.0


def _coin_flow(facts: Facts, world: SimWorld) -> tuple[dict[str, int], dict[str, int]]:
    """Citizen -> coins in, coins out over the last day; coins put in or taken from their own household's (or
    band's) store stay theirs (the tax books' rule)."""
    income: dict[str, int] = {}
    spent: dict[str, int] = {}
    for record in facts.since(1, "item_moved"):
        moved = record.payload
        if moved["item"] != "coins":
            continue
        source, destination = moved["source"], moved["destination"]
        for tally, side, other in ((spent, source, destination), (income, destination, source)):
            holder = facts.state.citizens.get(side.get("id") or "") if side["kind"] == "inventory" else None
            if holder is None or (other["kind"] == "store" and owns(world, holder, str(other.get("id")))):
                continue
            tally[holder.id] = tally.get(holder.id, 0) + int(moved["count"])
    return income, spent


def _partners(facts: Facts) -> dict[str, set[str]]:
    """Citizen -> the people they traded with at a stall in the last week (both sides of each sale)."""
    partners: dict[str, set[str]] = {}
    for record in facts.since(WEEK, "bought", "sold"):
        trader, merchant = record.actor, str(record.payload["merchant"])
        if trader is None or trader == merchant:
            continue
        partners.setdefault(trader, set()).add(merchant)
        partners.setdefault(merchant, set()).add(trader)
    return partners


def _accounts(facts: Facts) -> tuple[dict[str, Owed], dict[str, Owed]]:
    """Household -> what it owes (its latest tax change tells), and what it paid over the last week."""
    owed = {
        str(r.payload["household"]): Owed(rice=int(r.payload["owed_rice"]), coins=int(r.payload["owed_coins"]))
        for r in facts.of(*TAX_EVENTS)
    }
    paid: dict[str, Owed] = {}
    for record in facts.since(WEEK, "tax_paid"):
        household = str(record.payload["household"])
        before = paid.get(household, Owed(rice=0, coins=0))
        paid[household] = Owed(
            rice=before.rice + int(record.payload["rice"]), coins=before.coins + int(record.payload["coins"])
        )
    return owed, paid


def _skill_hours(facts: Facts) -> dict[str, dict[str, float]]:
    """Citizen -> skill -> hours spent at actions practising it (a work task's or a recipe's skill)."""
    hours: dict[str, dict[str, float]] = {}
    recipes = load_recipes().recipes
    for span in action_spans(facts, SKILLED):
        skill = SKILL_OF.get(span.action)
        if span.action == "work":
            task = work_task(str(span.args.get("task", "")))
            skill = task.skill if task is not None else None
        elif span.action == "craft":
            recipe = recipes.get(str(span.args.get("recipe", "")))
            skill = recipe.skill if recipe is not None else None
        if skill is None or span.end <= span.start:
            continue
        mine = hours.setdefault(span.actor, {})
        mine[skill] = round(mine.get(skill, 0.0) + (span.end - span.start) / 60, 2)
    return {actor: dict(sorted(skills.items())) for actor, skills in hours.items()}


def _wellbeing(citizen_id: str, bodies: Sequence[Mapping[str, BodyValues]]) -> int | None:
    seen = [body for sample in bodies if (body := sample.get(citizen_id)) is not None]
    if not seen:
        return None
    well = sum(h < WELL["hunger"] and t < WELL["thirst"] and e > WELL["energy"] for h, t, e, _ in seen)
    return round(100 * well / len(seen))


def _bonds(citizen: ReplayCitizen, state: ReplayState, bonds: Mapping[str, int]) -> list[BondView]:
    mine = []
    for pair, value in bonds.items():
        a, _, b = pair.partition("|")
        other = b if a == citizen.id else a if b == citizen.id else None
        if other is not None and value > 0 and other in state.citizens:
            mine.append(BondView(id=other, name=state.citizens[other].name, value=value))
    return sorted(mine, key=lambda bond: (-bond.value, bond.id))[:TOP_BONDS]


def _groups(facts: Facts, wealth: Mapping[str, int]) -> list[GroupScore]:
    citizens = facts.state.citizens
    deeds = [deed for deed in facts.deeds if deed.tick > facts.tick - WEEK * DAY_MINUTES]
    judged = [str(r.payload["person"]) for r in facts.since(WEEK, "judged")]
    groups = []
    for group in GROUPS:
        living = [wealth[c.id] for c in citizens.values() if c.region == group and c.alive]
        groups.append(
            GroupScore(
                group=group,
                name=GROUP_NAMES[group],
                alive=len(living),
                wealth_mon=sum(living),
                gini_wealth=gini(living),
                deeds_7d=sum(citizens[d.doer].region == group for d in deeds if d.doer in citizens),
                caught_7d=sum(citizens[p].region == group for p in judged if p in citizens),
            )
        )
    return groups


def gini(values: Sequence[int]) -> float:
    """0 when everyone holds the same, towards 1 when one holds it all (mean absolute difference / twice the mean)."""
    total = sum(values)
    if not values or total <= 0:
        return 0.0
    spread = sum(abs(a - b) for a in values for b in values)
    return round(spread / (2 * len(values) * total), 3)


def _money(state: ReplayState) -> int:
    carried = sum(citizen.inventory.get("coins", 0) for citizen in state.citizens.values())
    stored = sum(items.get("coins", 0) for items in state.stores.values())
    return carried + stored + sum(stack.count for stack in state.ground.values() if stack.item == "coins")


def _stalls(state: ReplayState, world: SimWorld) -> list[StallView]:
    views = []
    for stall in stations(world, STALL_KIND):
        stock = state.stores.get(stall.id, {})
        owner = owner_of(world, stall.id)
        keepers = [c for _, c in sorted(state.citizens.items()) if c.alive and owner is not None and c.home == owner]
        keeper = next((c for c in keepers if "trade" in c.skills), keepers[0] if keepers else None)
        goods = []
        for item in stall_goods():
            lot = stall_lot(item)
            if lot is None:
                continue
            count = stock.get(item, 0)
            sell, buy = sell_price(item, count), pays_for(item, count)
            goods.append(
                StallGood(item=item, stock=count, lot=lot.lot, sell=sell, buy=buy, word=price_word(item, count))
            )
        views.append(
            StallView(
                id=stall.id,
                keeper=keeper.name if keeper is not None else None,
                trading=keeper is not None and _trading(keeper),
                goods=goods,
            )
        )
    return views


def _trading(citizen: ReplayCitizen) -> bool:
    task = work_task(str(citizen.action_args.get("task", ""))) if citizen.action == "work" else None
    return task is not None and task.name == "trade"


def record_of(event: EventDraft) -> Record:
    """An event as the board reads it, straight from a simulation (headless runs, tests): as the store keeps it."""
    return Record(event.seq, event.tick, event.type, event.actor_id, event.payload.model_dump(mode="json"))


# --- from the event store ---


def scoreboard_at(
    session: Session, places: PlaceIndex, run_id: str | None = None, at: int | None = None
) -> ScoreboardView | None:
    """None when there is no run; raises TickNotReached for a tick the run hasn't simulated yet."""
    world = world_at(session, run_id, at)
    if world is None:
        return None
    board = board_at(session, places, world)
    day, time = town_clock(world.tick)
    return ScoreboardView(
        run_id=world.run.id,
        tick=world.tick,
        day=day,
        time=time,
        citizens=board.citizens,
        groups=board.groups,
        money_supply=board.money_supply,
        money_supply_ok=board.money_supply_ok,
        stalls=board.stalls,
    )


def board_at(session: Session, places: PlaceIndex, world: WorldAt) -> Board:
    """The board of a replayed world (`world_at`)."""
    facts = Facts(tick=world.tick, state=world.state, events=_records(session, world.run.id, world.tick))
    bonds = SOCIETY.load(world.snapshot.systems["society"].data).bonds
    return score_board(facts, _bodies(session, world.run.id, world.tick), bonds, places.world)


def _records(session: Session, run_id: str, tick: int) -> list[Record]:
    """The events the board reads up to the tick, oldest first: `READ` (hunger crossings only), the last day's coin
    moves, every hand-to-hand move (gifts), and the starts and ends of the `SKILLED` actions and follows."""
    payload = col(Event.payload)
    read = and_(col(Event.type).in_(READ), or_(col(Event.type) != "need_changed", payload["need"].astext == "hunger"))
    moved = and_(
        col(Event.type) == "item_moved",
        or_(
            and_(payload["item"].astext == "coins", col(Event.tick) > tick - DAY_MINUTES),
            and_(payload["source"]["kind"].astext == "inventory", payload["destination"]["kind"].astext == "inventory"),
        ),
    )
    whole = sa_select(col(Event.seq), col(Event.tick), col(Event.type), col(Event.actor_id), payload).where(
        col(Event.run_id) == run_id, col(Event.tick) <= tick, or_(read, moved)
    )
    records = [Record(*row) for row in session.execute(whole).all()]
    # actions come by the thousand: only the fields spans read, as plain columns (no JSON to decode)
    actions = sa_select(
        col(Event.seq),
        col(Event.tick),
        col(Event.type),
        col(Event.actor_id),
        payload["number"].astext.cast(Integer),
        payload["action"].astext,
        payload["args"]["task"].astext,
        payload["args"]["recipe"].astext,
        payload["target"]["id"].astext,
    ).where(
        col(Event.run_id) == run_id,
        col(Event.tick) <= tick,
        col(Event.type).in_(ACTION_EVENTS),
        payload["action"].astext.in_((*SKILLED, "follow")),
    )
    for seq, at, kind, actor, number, action, task, recipe, target in session.execute(actions).all():
        args = {name: value for name, value in (("task", task), ("recipe", recipe)) if value is not None}
        span = {"number": number, "action": action, "args": args, "target": {"id": target} if target else None}
        records.append(Record(seq, at, kind, actor, span))
    return sorted(records, key=lambda record: record.seq)


def _bodies(session: Session, run_id: str, tick: int) -> list[dict[str, BodyValues]]:
    """Every living citizen's body at every `BODY_SAMPLE_TICKS`-th tick of the last day."""
    bodies = col(Event.payload)["bodies"]
    statement = select(bodies).where(
        Event.run_id == run_id,
        Event.type == "tick_summary",
        col(Event.tick) > tick - DAY_MINUTES,
        col(Event.tick) <= tick,
        col(Event.tick) % BODY_SAMPLE_TICKS == 0,
    )
    return [_body_values(sample) for sample in session.exec(statement).all()]


def _body_values(sample: Any) -> dict[str, BodyValues]:
    return {citizen_id: (v[0], v[1], v[2], v[3]) for citizen_id, v in sample.items()}
