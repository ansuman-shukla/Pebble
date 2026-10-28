from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.observability.events import EventType
from app.services.events import MAX_LIMIT, EventsPage, list_events

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventsPage)
def read_events(
    session: SessionDep,
    run_id: str | None = None,
    actor: str | None = None,
    type: Annotated[list[EventType] | None, Query()] = None,
    since_tick: Annotated[int | None, Query(ge=0)] = None,
    until_tick: Annotated[int | None, Query(ge=0)] = None,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
) -> EventsPage:
    """Events in order, filtered by actor, type and tick range; page with `after_seq`."""
    page = list_events(
        session,
        run_id=run_id,
        actor=actor,
        types=type,
        since_tick=since_tick,
        until_tick=until_tick,
        after_seq=after_seq,
        limit=limit,
    )
    if page is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return page
