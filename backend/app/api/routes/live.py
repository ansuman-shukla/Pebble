"""The live feed: a WebSocket of citizens and public events as the engine ticks (`app.services.live`)."""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.api.deps import EngineDep, SessionDep
from app.db.models import Run
from app.observability.store import latest_run
from app.services.live import LiveMessage, LiveState, Queue, live_hub, load_feed

router = APIRouter(prefix="/live", tags=["live"])
NO_RUN = 4404  # close code: there is no such run (yet)
RESYNC = 1012  # close code: a newer run started or the run's history was rewritten; reconnect for a fresh snapshot


@router.websocket("")
async def live(websocket: WebSocket, db_engine: EngineDep, run_id: str | None = None) -> None:
    """`snapshot` on connect, then `event` messages and one `tick` message per engine tick (see `LiveMessage`)."""
    await websocket.accept()
    queue: Queue = asyncio.Queue()
    hub = live_hub(db_engine)
    subscription = await run_in_threadpool(hub.subscribe, run_id, asyncio.get_running_loop(), queue)
    if subscription is None:
        await websocket.close(code=NO_RUN, reason="no simulation run yet")
        return
    subscriber, snapshot = subscription
    closed = asyncio.create_task(_until_closed(websocket))
    try:
        await websocket.send_text(snapshot)
        while True:
            message = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({message, closed}, return_when=asyncio.FIRST_COMPLETED)
            if closed in done:
                message.cancel()
                return
            text = message.result()
            if text is None:
                await websocket.close(code=RESYNC, reason="reconnect for a fresh snapshot")
                return
            await websocket.send_text(text)
    except WebSocketDisconnect:
        return
    finally:
        closed.cancel()
        hub.unsubscribe(subscriber)


async def _until_closed(websocket: WebSocket) -> None:
    """Spectators don't send anything; this only notices when they leave."""
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return


@router.get("/schema", response_model=LiveMessage)
def live_schema(session: SessionDep, run_id: str | None = None) -> LiveState:
    """The live feed's message types for clients (this answers with the current `snapshot` message)."""
    run = session.get(Run, run_id) if run_id is not None else latest_run(session)
    if run is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    try:
        return load_feed(session, run).message("snapshot")
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
