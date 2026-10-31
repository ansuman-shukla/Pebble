"""World stats for spectators, now or at a past tick: population, deaths, food stocks, wild resources (what the nodes
hold) and how busy each game day was."""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.db.models import Event, Snapshot
from app.services.citizens import PersonRef, roster
from app.services.entities import world_at
from app.services.places import PlaceIndex
from app.sim.clock import DAY_MINUTES, town_clock
from app.sim.items import ITEMS
from app.sim.nodes import NodeView, node_views
from app.sim.state import Region

REGION_NAMES: dict[Region, str] = {"town": "the castle town", "band_a": "Band A", "band_b": "Band B"}


class Population(BaseModel):
    alive: int
    dead: int


class Death(BaseModel):
    citizen: PersonRef
    cause: str
    tick: int
    day: int
    time: str


class FoodStock(BaseModel):
    id: str  # store id, or the region whose people carry it
    name: str
    kind: Literal["storehouse", "field", "carried"]
    items: dict[str, int]
    hunger: float  # how much hunger it all removes (a meal is ~30)


class ResourceStock(BaseModel):
    resource: str
    now: int  # pieces in the wild, all nodes together
    start: int  # at the run's first snapshot
    emptied_nodes: int  # nodes that had some at the start and have none now


class DayCount(BaseModel):
    day: int
    events: int
    said: int
    actions: int  # actions started
    deaths: int


class StatsView(BaseModel):
    run_id: str
    tick: int
    day: int
    time: str
    population: Population
    deaths_by_cause: dict[str, int]
    deaths: list[Death]
    food: list[FoodStock]
    resources: list[ResourceStock]
    days: list[DayCount]


def _hunger(items: dict[str, int]) -> float:
    return sum(ITEMS[item].food * count for item, count in items.items() if item in ITEMS)


def _food(items: dict[str, int]) -> dict[str, int]:
    return {item: count for item, count in sorted(items.items()) if item in ITEMS and ITEMS[item].food > 0}


def _start_nodes(session: Session, run_id: str) -> dict[str, NodeView] | None:
    """The nodes that differed from full at the run's first snapshot."""
    statement = (
        select(col(Snapshot.state)["systems"]["nodes"]["data"])
        .where(Snapshot.run_id == run_id)
        .order_by(col(Snapshot.tick))
        .limit(1)
    )
    first = session.exec(statement).first()
    return None if first is None else node_views(first)


def _short(nodes: dict[str, NodeView], item: str) -> int:
    """How far the nodes of an item are below their caps, together."""
    return sum(view.cap - view.stock for view in nodes.values() if view.item == item)


def world_stats(
    session: Session, places: PlaceIndex, run_id: str | None = None, at: int | None = None
) -> StatsView | None:
    """None when there is no run; raises TickNotReached for a tick the run hasn't simulated yet."""
    world = world_at(session, run_id, at)
    if world is None:
        return None
    run, tick, state = world.run, world.tick, world.state
    people = roster(session, run.id)

    died = session.exec(
        select(Event)
        .where(Event.run_id == run.id, Event.type == "died", Event.actor_kind == "citizen", Event.tick <= tick)
        .order_by(col(Event.seq))
    ).all()
    deaths = []
    for row in died:
        day, time = town_clock(row.tick)
        person = people.get(row.actor_id or "", PersonRef(id=row.actor_id or "?", name=row.actor_id or "?", role=""))
        deaths.append(Death(citizen=person, cause=row.payload["cause"], tick=row.tick, day=day, time=time))
    by_cause: dict[str, int] = {}
    for death in deaths:
        by_cause[death.cause] = by_cause.get(death.cause, 0) + 1

    food = [
        FoodStock(
            id=store_id,
            name=places.store_name(store_id) if places.is_storehouse(store_id) else places.place_name(store_id),
            kind="storehouse" if places.is_storehouse(store_id) else "field",
            items=_food(items),
            hunger=_hunger(items),
        )
        for store_id, items in sorted(state.stores.items())
    ]
    for region, name in REGION_NAMES.items():
        carried: dict[str, int] = {}
        for citizen in state.citizens.values():
            if citizen.region == region:  # the dead keep what they held
                for item, count in citizen.inventory.items():
                    carried[item] = carried.get(item, 0) + count
        if any(c.region == region for c in state.citizens.values()):
            food.append(
                FoodStock(
                    id=region, name=f"carried by {name}", kind="carried", items=_food(carried), hunger=_hunger(carried)
                )
            )

    start = _start_nodes(session, run.id)
    now = state.nodes
    if start is None:
        start = now
    full = places.world.nodes.full_stock()
    resources = [
        ResourceStock(
            resource=item,
            now=total - _short(now, item),
            start=total - _short(start, item),
            emptied_nodes=sum(
                1
                for node_id, view in now.items()
                if view.item == item and view.stock == 0 and (node_id not in start or start[node_id].stock > 0)
            ),
        )
        for item, total in full.items()
    ]

    day_of = (col(Event.game_time) // DAY_MINUTES).label("day")
    counted = session.exec(
        select(day_of, Event.type, Event.actor_kind, func.count())
        .where(Event.run_id == run.id, Event.tick <= tick)
        .group_by(day_of, Event.type, Event.actor_kind)
    ).all()
    days: dict[int, DayCount] = {}
    for day_number, kind, actor_kind, count in counted:
        entry = days.setdefault(day_number, DayCount(day=day_number, events=0, said=0, actions=0, deaths=0))
        entry.events += count
        if kind == "said":
            entry.said += count
        elif kind == "action_started":
            entry.actions += count
        elif kind == "died" and actor_kind == "citizen":  # animals die too; deaths count people
            entry.deaths += count

    alive = sum(citizen.alive for citizen in state.citizens.values())
    day, time = town_clock(tick)
    return StatsView(
        run_id=run.id,
        tick=tick,
        day=day,
        time=time,
        population=Population(alive=alive, dead=len(state.citizens) - alive),
        deaths_by_cause=by_cause,
        deaths=deaths,
        food=food,
        resources=resources,
        days=[days[d] for d in sorted(days)],
    )
