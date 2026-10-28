"""Clock, admin, entities and events endpoints over a run the engine wrote (in a rolled-back transaction)."""

import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_session
from app.core.config import settings
from app.db.models import EngineCommand, Run
from app.engine import Clock, EngineLoop, open_loop
from app.main import app
from app.services.clock import read_clock
from app.sim.citizens import DEV_CITIZENS
from app.sim.vec import lat_lon_deg
from app.sim.world import SimWorld
from app.world.store import WorldKey
from app.world_api.facade import WorldApi

API = settings.API_V1_STR
KEY = WorldKey(seed=20261028, generator_version="test", spec_hash="1" * 64)


@pytest.fixture
def api_session(db_session: Session) -> Iterator[Session]:
    app.dependency_overrides[get_session] = lambda: db_session
    yield db_session


@pytest.fixture
def loop(api_session: Session, sim_world: SimWorld) -> EngineLoop:
    loop = open_loop(
        api_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock(speed=3), brains=False
    )
    WorldApi(loop.sim, "dev-aiko").walk_to_place("the main gate")  # scripted by the test, not by a brain
    loop.run_ticks(75, headless=True)
    return loop


@pytest.mark.usefixtures("api_session")
def test_no_run_yet_is_a_404(client: TestClient) -> None:
    for path in ("/clock", "/entities", "/events"):
        assert client.get(API + path).status_code == 404
    assert client.post(f"{API}/admin/clock", json={"paused": True}).status_code == 404


def test_clock_shows_the_runs_time_and_speed(client: TestClient, loop: EngineLoop) -> None:
    body = client.get(f"{API}/clock").json()
    assert body == {
        "run_id": loop.run.id,
        "status": "running",
        "engine_alive": True,
        "tick": 75,
        "game_time": 8 * 60 + 75,
        "day": 0,
        "time": "09:15",
        "speed": 3,
        "paused": False,
    }


def test_engine_alive_needs_a_recent_heartbeat(api_session: Session, loop: EngineLoop) -> None:
    later = datetime.now(UTC) + timedelta(seconds=30)
    clock = read_clock(api_session, loop.run.id, now=later)
    assert clock is not None and not clock.engine_alive


def test_admin_clock_queues_a_command_the_engine_applies(
    client: TestClient, api_session: Session, loop: EngineLoop
) -> None:
    response = client.post(f"{API}/admin/clock", json={"paused": True, "speed": 20})
    assert response.status_code == 202
    command = api_session.get(EngineCommand, response.json()["command_id"])
    assert command is not None and command.payload == {"paused": True, "speed": 20}
    assert command.applied_at is None
    loop.apply_commands()
    assert client.get(f"{API}/clock").json()["paused"] is True
    assert client.get(f"{API}/clock").json()["speed"] == 20
    assert client.post(f"{API}/admin/clock", json={}).status_code == 422
    assert client.post(f"{API}/admin/clock", json={"speed": 61}).status_code == 422


def test_entities_now_match_the_simulation(client: TestClient, loop: EngineLoop) -> None:
    body = client.get(f"{API}/entities").json()
    assert body["tick"] == 75 and body["time"] == "09:15"
    by_id = {c["id"]: c for c in body["citizens"]}
    assert set(by_id) == set(loop.sim.state.citizens)
    for citizen_id, entity in by_id.items():
        citizen = loop.sim.citizen(citizen_id)
        assert tuple(entity["position"]["unit"]) == pytest.approx(citizen.position, abs=1e-12)
        assert entity["cell"] == citizen.cell
        assert entity["position"]["height_m"] == pytest.approx(citizen.height_m)
        assert entity["action"] == (citizen.action.kind if citizen.action else None)
        assert entity["alive"] is True
        assert entity["heading_deg"] == pytest.approx(citizen.heading_deg)
        assert (entity["role"], entity["region"]) == (citizen.role, citizen.region)
        assert entity["activity"] == {"walk_to": "walking", "sleep": "sleeping"}.get(entity["action"], "idle")
    aiko = by_id["dev-aiko"]
    assert aiko["heading_deg"] != 0.0  # she walked to the gate and faces the way she went
    assert loop.sim.world.distance_m(tuple(aiko["position"]["unit"]), loop.sim.world.places["main-gate"].stand) < 1
    lat, lon = lat_lon_deg(loop.sim.citizen("dev-aiko").position)
    assert (aiko["position"]["lat"], aiko["position"]["lon"]) == pytest.approx((lat, lon))
    assert lat == pytest.approx(38 - 104 / (2000 * math.pi / 180), abs=0.05)  # ~104 m south of the town centre


@pytest.mark.usefixtures("loop")
def test_entities_replay_a_past_tick(client: TestClient, sim_world: SimWorld) -> None:
    start = client.get(f"{API}/entities", params={"at": 0}).json()
    aiko_start = next(c for c in start["citizens"] if c["id"] == "dev-aiko")
    assert sim_world.town.to_local(tuple(aiko_start["position"]["unit"])) == pytest.approx((-18, 54), abs=1e-6)
    assert start["tick"] == 0 and start["time"] == "08:00"
    early = next(c for c in client.get(f"{API}/entities", params={"at": 1}).json()["citizens"] if c["id"] == "dev-aiko")
    assert early["position"]["unit"] != aiko_start["position"]["unit"]
    mid = client.get(f"{API}/entities", params={"at": 61}).json()  # from the 60 snapshot plus one tick
    assert mid["tick"] == 61 and mid["time"] == "09:01"
    assert client.get(f"{API}/entities", params={"at": 76}).status_code == 404
    assert client.get(f"{API}/entities", params={"at": -1}).status_code == 422


@pytest.mark.usefixtures("loop")
def test_events_filter_by_actor_type_and_ticks(client: TestClient) -> None:
    everything = client.get(f"{API}/events", params={"limit": 1000}).json()["events"]
    assert [e["seq"] for e in everything] == list(range(1, len(everything) + 1))
    aiko = client.get(f"{API}/events", params={"actor": "dev-aiko", "limit": 1000}).json()["events"]
    assert aiko and all(e["actor_id"] == "dev-aiko" for e in aiko)
    assert {"citizen_spawned", "action_started", "action_finished"} <= {e["type"] for e in aiko}
    walks = client.get(f"{API}/events", params={"type": ["action_started", "action_finished"]}).json()["events"]
    assert {e["type"] for e in walks} == {"action_started", "action_finished"}
    window = client.get(f"{API}/events", params={"type": "tick_summary", "since_tick": 10, "until_tick": 19}).json()
    assert [e["tick"] for e in window["events"]] == list(range(10, 20))
    page = client.get(f"{API}/events", params={"after_seq": 5, "limit": 3}).json()["events"]
    assert [e["seq"] for e in page] == [6, 7, 8]
    assert client.get(f"{API}/events", params={"type": "nonsense"}).status_code == 422
    finished = next(e for e in aiko if e["type"] == "action_finished")
    assert finished["payload"]["text"] == "You arrive at the main gate."
    started = next(e for e in aiko if e["type"] == "action_started")
    assert finished["cause_id"] == started["id"]


def test_runs_are_listed_newest_first(api_session: Session, sim_world: SimWorld, client: TestClient) -> None:
    first = open_loop(api_session, sim_world, KEY, new_run=True, citizens=None, clock=Clock())
    second = open_loop(api_session, sim_world, KEY, new_run=True, citizens=None, clock=Clock())
    assert client.get(f"{API}/clock").json()["run_id"] == second.run.id
    assert client.get(f"{API}/clock", params={"run_id": first.run.id}).json()["run_id"] == first.run.id
    assert len(api_session.exec(select(Run)).all()) >= 2
