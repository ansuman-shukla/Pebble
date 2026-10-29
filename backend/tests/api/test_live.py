"""The live feed over a real WebSocket: a snapshot on connect, then event and tick messages as the engine commits.

NOTIFY only reaches listeners on commit, so these tests commit for real (`committing_engine` empties the test
database afterwards).
"""

import queue
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.engine import Clock, EngineLoop, open_loop
from app.observability.events import GoalSet, Stole, Traded
from app.observability.store import queue_command
from app.services.live import LIVE_EVENT_TYPES, LiveEvent, LiveState
from app.sim.citizens import CITIZENS
from app.sim.world import SimWorld
from app.world.store import WorldKey
from app.world_api.facade import WorldApi

API = settings.API_V1_STR
KEY = WorldKey(seed=20261028, generator_version="test-live", spec_hash="2" * 64)
RECEIVE_TIMEOUT_S = 15.0


@pytest.fixture
def committed_run(committing_engine: Engine, sim_world: SimWorld) -> Iterator[EngineLoop]:
    with Session(committing_engine) as session:
        yield open_loop(session, sim_world, KEY, new_run=True, citizens=CITIZENS, clock=Clock(), brains=False)


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
        assert len(snapshot.citizens) == 22
        assert {c.region for c in snapshot.citizens} == {"town", "band_a", "band_b"}
        genzo = next(c for c in snapshot.citizens if c.id == "genzo")
        assert (genzo.role, genzo.activity) == ("rice farmer", "idle")
        assert {a.id for a in snapshot.animals} == set(loop.sim.state.animals)
        assert {a.kind for a in snapshot.animals} >= {"deer", "wolf", "fish", "duck"}
        assert {f.id for f in snapshot.fires} == set(loop.sim.state.fires)

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
        # actions and speech always come; anything else only when its line is worth telling
        assert all(e.event.type in LIVE_EVENT_TYPES or e.event.importance > 0 for e in events)
        assert said[0].event.line == "Genzo: “Good morning, Aiko!”" and said[0].event.importance == 1
        assert said[0].event.position is not None
        hana = next(c for c in ticks[0].citizens if c.id == "hana")
        start = next(c for c in snapshot.citizens if c.id == "hana")
        assert hana.activity == "walking" and hana.position.unit != start.position.unit
        # drawn walking from where she stood, through where she is now
        assert hana.route[0].unit == start.position.unit and hana.route[0].t_s == 0.0 and hana.speed_mps > 0
        assert any(point.unit == hana.position.unit for point in hana.route[1:])
        assert (start.route, start.speed_mps) == ([], 0.0)
        assert all(c.route == [] for c in ticks[0].citizens if c.activity != "walking")
        talker = next(c for c in ticks[0].citizens if c.id == "genzo")
        assert talker.activity == "talking"
        moved = {a.id: a for a in ticks[-1].animals}
        assert {a.id: (a.position.unit, a.activity) for a in ticks[-1].animals} == {
            a.id: (a.position, a.activity) for a in loop.sim.state.animals.values()
        }
        assert any(moved[a.id].position.unit != a.position.unit for a in snapshot.animals)  # animals move live

        queue_command(loop.store.session, loop.run.id, "clock", {"speed": 7})
        loop.apply_commands()  # commits the new speed without a tick: the feed notices within a second
        changed = LiveState.model_validate(_receive(ws))
        assert (changed.type, changed.tick, changed.speed, changed.paused) == ("tick", 3, 7.0, False)


def test_joining_at_a_snapshot_tick_still_shows_the_streamed_routes(
    client: TestClient, committed_run: EngineLoop
) -> None:
    loop = committed_run
    loop.run_ticks(59, headless=True)
    WorldApi(loop.sim, "hana").walk_to_place("the storehouses")
    loop.run_ticks(1, headless=True)  # tick 60: snapshotted, and hana is on her way
    with client.websocket_connect(f"{API}/live?run_id={loop.run.id}") as ws:
        snapshot = LiveState.model_validate(_receive(ws))
    hana = next(c for c in snapshot.citizens if c.id == "hana")
    assert snapshot.tick == 60 and hana.activity == "walking"
    assert hana.route[0].t_s == 0.0 and hana.speed_mps > 0
    assert any(point.unit == hana.position.unit for point in hana.route[1:])


def test_unknown_runs_close_the_socket_and_the_schema_route_answers(
    client: TestClient, committed_run: EngineLoop
) -> None:
    with client.websocket_connect(f"{API}/live?run_id=nope") as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    assert closed.value.code == 4404
    body = client.get(f"{API}/live/schema", params={"run_id": committed_run.run.id}).json()
    assert body["type"] == "snapshot" and len(body["citizens"]) == 22
    assert client.get(f"{API}/live/schema", params={"run_id": "nope"}).status_code == 404
    schema = client.get(f"{API}/openapi.json").json()["components"]["schemas"]
    assert {"LiveState", "LiveEvent", "LiveEventDetail", "CitizenEntity"} <= set(schema)
    assert {"heading_deg", "activity", "role", "region"} <= set(schema["CitizenEntity"]["properties"])


def test_a_death_reaches_the_feed_within_its_tick_with_its_line_and_place(
    client: TestClient, committed_run: EngineLoop
) -> None:
    loop = committed_run
    with client.websocket_connect(f"{API}/live?run_id={loop.run.id}") as ws:
        assert _receive(ws)["type"] == "snapshot"
        genzo = loop.sim.citizen("genzo")
        loop.sim.core.injure(genzo, 500.0, "violence", "Kaz strikes you", attacker="kaz")
        loop.run_ticks(1, headless=True)
        messages = _until_tick(ws, 1)
    events = [LiveEvent.model_validate(m).event for m in messages if m["type"] == "event"]
    died = next(e for e in events if e.type == "died")
    assert (died.actor_id, died.line, died.importance) == ("genzo", "Kaz kills Genzo", 3)
    assert died.payload == {"cause": "violence", "attacker": "kaz"}
    assert died.position is not None and died.position.unit == genzo.position
    struck = next(e for e in events if e.type == "injured")
    assert (struck.line, struck.importance) == ("Kaz strikes Genzo", 3)
    assert messages[-1]["type"] == "tick" and messages[-1]["tick"] == 1


def test_the_feed_sends_public_events_worth_telling_and_names_animals_and_households(
    client: TestClient, committed_run: EngineLoop
) -> None:
    loop = committed_run
    core = loop.sim.core
    genzo, kaz = loop.sim.citizen("genzo"), loop.sim.citizen("kaz")
    wolf = next(a for a in loop.sim.state.animals.values() if a.kind == "wolf")
    sale = {"item": "rice", "count": 4, "lots": 2, "coins": 8, "stall": "stall", "merchant": "fumiko"}
    with client.websocket_connect(f"{API}/live?run_id={loop.run.id}") as ws:
        assert _receive(ws)["type"] == "snapshot"
        core.emit("goal_set", GoalSet(text="sell rice", driver="ambition"), actor=genzo)  # public, importance 0
        core.emit("bought", Traded.model_validate(sale), actor=genzo)  # public, importance 2
        core.emit("sold", Traded.model_validate(sale), actor=genzo, visibility="private")
        core.emit("stole", Stole(owner="farmhouse-1", store="rack-1", item="rice", count=5), actor=kaz)
        core.injure(genzo, 5.0, "animal attack", "a wolf attacks you", attacker=wolf.id)
        loop.run_ticks(1, headless=True)
        messages = _until_tick(ws, 1)
    told = {e.type: e for e in (LiveEvent.model_validate(m).event for m in messages if m["type"] == "event")}
    assert "goal_set" not in told and "sold" not in told
    bought = told["bought"]
    assert (bought.actor_id, bought.line, bought.importance) == ("genzo", "Genzo buys 4 rice for 8 mon", 2)
    assert bought.position is not None and bought.position.unit == genzo.position
    assert (told["stole"].line, told["stole"].importance) == ("Kaz steals 5 rice from Genzo's house", 2)
    assert (told["injured"].line, told["injured"].importance) == ("A wolf attacks Genzo", 3)


def test_a_page_opened_mid_tick_learns_how_far_into_the_tick_the_world_is(
    client: TestClient, committed_run: EngineLoop
) -> None:
    loop = committed_run
    loop.store.clock = lambda: datetime.now(UTC) - timedelta(seconds=20)  # tick 1 was written 20 s ago (at ×1)
    loop.run_ticks(1, headless=True)
    with client.websocket_connect(f"{API}/live?run_id={loop.run.id}") as ws:
        snapshot = LiveState.model_validate(_receive(ws))
        assert snapshot.tick == 1 and 19.0 < snapshot.tick_elapsed_s < 30.0
        loop.store.clock = lambda: datetime.now(UTC)
        loop.run_ticks(1, headless=True)
        tick = LiveState.model_validate(_until_tick(ws, 2)[-1])
    assert tick.tick == 2 and tick.tick_elapsed_s < 5.0  # a tick as it happens: just begun
