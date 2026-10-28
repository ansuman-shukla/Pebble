"""World stats for spectators, now or at a past tick: population, deaths, food stocks, wild resources and how busy
each game day was."""

import base64
from typing import Literal

import numpy as np
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.db.models import Event, Snapshot
from app.services.citizens import PersonRef, roster
from app.services.entities import world_at
from app.services.places import PlaceIndex
from app.sim.clock import DAY_MINUTES, town_clock
from app.sim.items import ITEMS, RESOURCES
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
    now: int  # pieces in the wild, all cells together
    start: int  # at the run's first snapshot
    emptied_cells: int  # cells that had some at the start and have none now


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


def _start_resources(session: Session, run_id: str) -> np.ndarray | None:
    statement = (
        select(col(Snapshot.state)["resources"].astext, col(Snapshot.state)["resource_columns"].as_integer())
        .where(Snapshot.run_id == run_id)
        .order_by(col(Snapshot.tick))
        .limit(1)
    )
    first = session.exec(statement).first()
    if first is None:
        return None
    encoded, columns = first
    return np.frombuffer(base64.b64decode(encoded), dtype=np.uint8).reshape(-1, columns)


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
        select(Event).where(Event.run_id == run.id, Event.type == "died", Event.tick <= tick).order_by(col(Event.seq))
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

    start = _start_resources(session, run.id)
    resources = []
    for column, resource in enumerate(RESOURCES):
        now_counts = state.resources[:, column].astype(np.int64)
        start_counts = start[:, column].astype(np.int64) if start is not None else now_counts
        resources.append(
            ResourceStock(
                resource=resource,
                now=int(now_counts.sum()),
                start=int(start_counts.sum()),
                emptied_cells=int(((start_counts > 0) & (now_counts == 0)).sum()),
            )
        )

    day_of = (col(Event.game_time) // DAY_MINUTES).label("day")
    counted = session.exec(
        select(day_of, Event.type, func.count())
        .where(Event.run_id == run.id, Event.tick <= tick)
        .group_by(day_of, Event.type)
    ).all()
    days: dict[int, DayCount] = {}
    for day_number, kind, count in counted:
        entry = days.setdefault(day_number, DayCount(day=day_number, events=0, said=0, actions=0, deaths=0))
        entry.events += count
        if kind == "said":
            entry.said += count
        elif kind == "action_started":
            entry.actions += count
        elif kind == "died":
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
