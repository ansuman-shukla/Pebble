"""World stats: population, deaths, food, wild resources and events per game day, now and replayed."""

import base64
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.db.models import Event, Snapshot
from app.engine import EngineLoop
from app.sim.clock import DAY_MINUTES
from app.sim.items import RESOURCES
from app.sim.world import SimWorld
from tests.api.spectator import API, dev_run


@pytest.mark.usefixtures("spectator_session")
def test_no_run_yet_is_a_404(client: TestClient) -> None:
    assert client.get(f"{API}/stats").status_code == 404


def test_stats_count_people_food_resources_and_days(
    client: TestClient, cast: EngineLoop, spectator_session: Session
) -> None:
    stats = client.get(f"{API}/stats").json()
    state = cast.sim.state
    assert stats["tick"] == 70 and stats["population"] == {"alive": 15, "dead": 0}
    food = {f["id"]: f for f in stats["food"]}
    assert food["store-2"]["kind"] == "storehouse" and food["store-2"]["name"] == "the storehouse"
    assert food["store-2"]["items"] == {"rice": state.stores["store-2"]["rice"]}
    assert food["store-2"]["hunger"] == pytest.approx(10.0 * state.stores["store-2"]["rice"])
    for region in ("town", "band_a", "band_b"):
        carried: dict[str, int] = {}
        for citizen in state.citizens.values():
            if citizen.region == region:
                for item, count in citizen.inventory.items():
                    if item not in ("wood", "reeds") and count:
                        carried[item] = carried.get(item, 0) + count
        assert food[region]["kind"] == "carried" and food[region]["items"] == dict(sorted(carried.items()))
    assert food["band_a"]["name"] == "carried by Band A" and food["band_a"]["hunger"] > 0
    first = client.get(f"{API}/stats", params={"at": 0}).json()
    assert {f["id"]: f["items"] for f in first["food"]}["store-2"] == {"rice": 400}
    for column, resource in enumerate(RESOURCES):
        row = next(r for r in stats["resources"] if r["resource"] == resource)
        assert row["now"] == int(state.resources[:, column].astype(np.int64).sum())
        assert row["start"] == next(r for r in first["resources"] if r["resource"] == resource)["now"]
    assert sum(r["start"] - r["now"] for r in stats["resources"]) > 0  # the bands have gathered
    start_state = spectator_session.exec(
        select(Snapshot.state).where(Snapshot.run_id == cast.run.id).order_by(col(Snapshot.tick))
    ).first()
    assert start_state is not None
    start = np.frombuffer(base64.b64decode(start_state["resources"]), dtype=np.uint8).reshape(state.resources.shape)
    emptied = [int(((start[:, c] > 0) & (state.resources[:, c] == 0)).sum()) for c in range(len(RESOURCES))]
    assert [r["emptied_cells"] for r in stats["resources"]] == emptied
    counted = spectator_session.exec(
        select(func.count()).select_from(Event).where(Event.run_id == cast.run.id, Event.tick <= 70)
    ).one()
    said = spectator_session.exec(
        select(func.count()).select_from(Event).where(Event.run_id == cast.run.id, Event.type == "said")
    ).one()
    assert stats["days"] == [
        {"day": 0, "events": counted, "said": said, "actions": stats["days"][0]["actions"], "deaths": 0}
    ]
    started = spectator_session.exec(
        select(func.count()).select_from(Event).where(Event.run_id == cast.run.id, col(Event.type) == "action_started")
    ).one()
    assert stats["days"][0]["actions"] == started > 0


@pytest.mark.usefixtures("story")
def test_stats_record_deaths_by_cause(client: TestClient) -> None:
    stats = client.get(f"{API}/stats").json()
    assert stats["population"] == {"alive": 2, "dead": 1}
    assert stats["deaths_by_cause"] == {"dehydration": 1}
    (death,) = stats["deaths"]
    assert death["citizen"]["id"] == "dev-genzo" and death["cause"] == "dehydration" and 66 <= death["tick"] < 75
    assert stats["days"][0]["deaths"] == 1
    before = client.get(f"{API}/stats", params={"at": 65}).json()
    assert before["population"] == {"alive": 3, "dead": 0} and before["deaths"] == []
    assert before["days"][0]["events"] < stats["days"][0]["events"]
    assert client.get(f"{API}/stats", params={"at": 76}).status_code == 404


def test_days_split_at_town_midnight(client: TestClient, spectator_session: Session, sim_world: SimWorld) -> None:
    loop = dev_run(spectator_session, sim_world)
    loop.run_ticks(DAY_MINUTES - 8 * 60 + 10, headless=True)  # 08:00 on day 0 to 00:10 on day 1
    days = client.get(f"{API}/stats").json()["days"]
    midnight = DAY_MINUTES - 8 * 60  # the first tick of day 1

    def count(*where: Any) -> int:
        return spectator_session.exec(
            select(func.count()).select_from(Event).where(Event.run_id == loop.run.id, *where)
        ).one()

    assert [d["day"] for d in days] == [0, 1]
    assert [d["events"] for d in days] == [count(Event.tick < midnight), count(Event.tick >= midnight)]
    assert days[1]["events"] >= 11  # at least the tick summaries of 00:00 to 00:10
