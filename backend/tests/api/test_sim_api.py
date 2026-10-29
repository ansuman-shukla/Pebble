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
from app.observability.replay import from_snapshot
from app.observability.store import latest_snapshot
from app.services.clock import read_clock
from app.services.entities import world_at
from app.sim.actions import streamed_route
from app.sim.citizens import DEV_CITIZENS
from app.sim.snapshot import SimSnapshot
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
    assert client.post(f"{API}/admin/clock", json={"speed": 601}).status_code == 422
    assert client.post(f"{API}/admin/clock", json={"speed": 0}).status_code == 422
    assert client.post(f"{API}/admin/clock", json={"speed": 600}).status_code == 202  # ×600 time-lapse is the top


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

    animals = {a["id"]: a for a in body["animals"]}
    assert set(animals) == set(loop.sim.state.animals) and 150 < len(animals) < 400
    for animal_id, entity in animals.items():
        animal = loop.sim.state.animals[animal_id]
        assert (entity["kind"], entity["group"], entity["activity"]) == (animal.kind, animal.group, animal.activity)
        assert tuple(entity["position"]["unit"]) == pytest.approx(animal.position, abs=1e-12)
        assert entity["position"]["height_m"] == pytest.approx(animal.height_m)
        assert entity["heading_deg"] == pytest.approx(animal.heading_deg)
    fires = {f["id"]: f for f in body["fires"]}
    assert set(fires) == set(loop.sim.state.fires) >= {"band_a_camp:fire-pit", "main-gate-fire-w"}
    pit = fires["band_a_camp:fire-pit"]
    assert (pit["kind"], pit["lit"], pit["strength"]) == ("pit", True, 1.0)  # camps start with their fire burning
    assert (fires["main-gate-fire-w"]["kind"], fires["main-gate-fire-w"]["lit"]) == ("basket", False)


def test_entities_carry_the_streamed_route_even_at_a_snapshot_tick(
    client: TestClient, api_session: Session, sim_world: SimWorld
) -> None:
    loop = open_loop(api_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock(), brains=False)
    loop.run_ticks(59, headless=True)
    WorldApi(loop.sim, "dev-aiko").walk_to_place("the west gate")  # ~90 m: still walking after tick 60
    loop.run_ticks(1, headless=True)  # tick 60 is snapshotted; its summary has the route, the snapshot doesn't
    expected, speed_mps = streamed_route(loop.sim.core, loop.sim.citizen("dev-aiko"))
    assert len(expected) >= 3  # where she stood, where she is, and on
    before = next(
        c for c in client.get(f"{API}/entities", params={"at": 59}).json()["citizens"] if c["id"] == "dev-aiko"
    )
    assert (before["route"], before["speed_mps"]) == ([], 0.0)  # she has just set off
    for params in ({}, {"at": 60}):
        aiko = next(c for c in client.get(f"{API}/entities", params=params).json()["citizens"] if c["id"] == "dev-aiko")
        assert aiko["activity"] == "walking"
        assert aiko["route"] == [point.model_dump(mode="json") for point in expected]
        assert aiko["route"][0]["unit"] == before["position"]["unit"]
        assert aiko["speed_mps"] == pytest.approx(speed_mps)

    loop.run_ticks(1, headless=True)
    WorldApi(loop.sim, "dev-aiko").walk_to_place("the main gate")
    loop.run_ticks(1, headless=True)  # tick 62: on her way again
    walking = next(c for c in client.get(f"{API}/entities").json()["citizens"] if c["id"] == "dev-aiko")
    assert walking["route"]
    WorldApi(loop.sim, "dev-aiko").rest(10)  # stops the walk between ticks: she doesn't move in tick 63
    loop.run_ticks(1, headless=True)
    after = next(c for c in client.get(f"{API}/entities").json()["citizens"] if c["id"] == "dev-aiko")
    assert (after["activity"], after["route"], after["speed_mps"]) == ("resting", [], 0.0)


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


def test_replaying_from_the_snapshot_before_a_tick_rebuilds_the_snapshotted_world(
    api_session: Session, loop: EngineLoop
) -> None:
    """Spectator endpoints share `world_at`, which starts from the snapshot before the asked tick: at a snapshot
    tick its replay (knowledge, inventories, bodies, positions) must equal that snapshot."""
    snapshot_row = latest_snapshot(api_session, loop.run.id, at_or_before=60)
    assert snapshot_row is not None and snapshot_row.tick == 60
    world = world_at(api_session, loop.run.id, at=60)
    assert world is not None and world.tick == 60
    assert world.state.same_as(from_snapshot(SimSnapshot.model_validate(snapshot_row.state)))
