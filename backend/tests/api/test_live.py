"""The live feed over a real WebSocket: a snapshot on connect, then event and tick messages as the engine commits.

NOTIFY only reaches listeners on commit, so this test commits its own run for real (back-dated so no one takes it for
the latest run) and deletes it afterwards.
"""

import queue
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import Session, col
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.db import engine
from app.db.models import EngineCommand, Event, Run, Snapshot
from app.engine import Clock, EngineLoop, open_loop
from app.observability.store import queue_command
from app.services.live import LiveEvent, LiveState
from app.sim.citizens import CITIZENS
from app.sim.world import SimWorld
from app.world.store import WorldKey
from app.world_api.facade import WorldApi

API = settings.API_V1_STR
KEY = WorldKey(seed=20261028, generator_version="test-live", spec_hash="2" * 64)
RECEIVE_TIMEOUT_S = 15.0


@pytest.fixture
def committed_run(sim_world: SimWorld) -> Iterator[EngineLoop]:
    session = Session(engine)
    loop = open_loop(session, sim_world, KEY, new_run=True, citizens=CITIZENS, clock=Clock(), brains=False)
    run_id = loop.run.id
    loop.run.created_at = datetime(2000, 1, 1, tzinfo=UTC)
    session.add(loop.run)
    session.commit()
    try:
        yield loop
    finally:
        session.rollback()
        for table in (Event, Snapshot, EngineCommand):
            session.execute(delete(table).where(col(table.run_id) == run_id))
        session.execute(delete(Run).where(col(Run.id) == run_id))
        session.commit()
        session.close()


def _receive(ws: WebSocketTestSession) -> dict[str, Any]:
    """The next message, or a failure after RECEIVE_TIMEOUT_S (a daemon thread waits, so a silent feed can't hang
    the test run)."""
    box: queue.Queue[dict[str, Any]] = queue.Queue()
    threading.Thread(target=lambda: box.put(ws.receive_json()), daemon=True).start()
    try:
        return box.get(timeout=RECEIVE_TIMEOUT_S)
    except queue.Empty:
        raise AssertionError(f"no live message within {RECEIVE_TIMEOUT_S} s") from None


def _until_tick(ws: WebSocketTestSession, tick: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    while not messages or messages[-1]["type"] != "tick" or messages[-1]["tick"] < tick:
        messages.append(_receive(ws))
    return messages


def test_the_live_feed_streams_snapshot_events_and_ticks(client: TestClient, committed_run: EngineLoop) -> None:
    loop = committed_run
    with client.websocket_connect(f"{API}/live?run_id={loop.run.id}") as ws:
        snapshot = LiveState.model_validate(_receive(ws))
        assert (snapshot.type, snapshot.run_id, snapshot.tick, snapshot.time) == ("snapshot", loop.run.id, 0, "08:00")
        assert len(snapshot.citizens) == 15
        assert {c.region for c in snapshot.citizens} == {"town", "band_a", "band_b"}
        genzo = next(c for c in snapshot.citizens if c.id == "genzo")
        assert (genzo.role, genzo.activity) == ("rice farmer", "idle")

        WorldApi(loop.sim, "genzo").say("Good morning, Aiko!")
        WorldApi(loop.sim, "hana").walk_to_place("the storehouses")  # over 100 m: still walking at tick 1
        loop.run_ticks(3, headless=True)
        messages = _until_tick(ws, 3)
        ticks = [LiveState.model_validate(m) for m in messages if m["type"] == "tick"]
        assert [t.tick for t in ticks] == [1, 2, 3]
        events = [LiveEvent.model_validate(m) for m in messages if m["type"] == "event"]
        said = [e for e in events if e.event.type == "said"]
        assert len(said) == 1 and said[0].event.actor_id == "genzo"
        assert said[0].event.payload["words"] == "Good morning, Aiko!"
        kinds = [m["event"]["type"] if m["type"] == "event" else m["type"] for m in messages]
        assert kinds.index("said") < kinds.index("tick")  # events come before the tick they belong to
        assert any(e.event.type == "action_started" and e.event.actor_id == "hana" for e in events)
        assert {e.event.type for e in events} <= {"said", "died", "action_started", "action_finished"}
        hana = next(c for c in ticks[0].citizens if c.id == "hana")
        start = next(c for c in snapshot.citizens if c.id == "hana")
        assert hana.activity == "walking" and hana.position.unit != start.position.unit
        talker = next(c for c in ticks[0].citizens if c.id == "genzo")
        assert talker.activity == "talking"

        queue_command(loop.store.session, loop.run.id, "clock", {"speed": 7})
        loop.apply_commands()  # commits the new speed without a tick: the feed notices within a second
        changed = LiveState.model_validate(_receive(ws))
        assert (changed.type, changed.tick, changed.speed, changed.paused) == ("tick", 3, 7.0, False)


def test_unknown_runs_close_the_socket_and_the_schema_route_answers(
    client: TestClient, committed_run: EngineLoop
) -> None:
    with client.websocket_connect(f"{API}/live?run_id=nope") as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    assert closed.value.code == 4404
    body = client.get(f"{API}/live/schema", params={"run_id": committed_run.run.id}).json()
    assert body["type"] == "snapshot" and len(body["citizens"]) == 15
    assert client.get(f"{API}/live/schema", params={"run_id": "nope"}).status_code == 404
    schema = client.get(f"{API}/openapi.json").json()["components"]["schemas"]
    assert {"LiveState", "LiveEvent", "LiveEventDetail", "CitizenEntity"} <= set(schema)
    assert {"heading_deg", "activity", "role", "region"} <= set(schema["CitizenEntity"]["properties"])
