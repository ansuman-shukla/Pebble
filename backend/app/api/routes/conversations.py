from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import PlaceIndexDep, SessionDep
from app.services.conversations import MAX_THREADS, ConversationsPage, list_conversations

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationsPage)
def read_conversations(
    session: SessionDep,
    places: PlaceIndexDep,
    run_id: str | None = None,
    from_tick: Annotated[int | None, Query(ge=0)] = None,
    to_tick: Annotated[int | None, Query(ge=0)] = None,
    place: Annotated[str | None, Query(description="only threads at this place or area id")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_THREADS)] = 50,
) -> ConversationsPage:
    """Threads of speech by place and time (the last game day by default), newest first, with who heard them."""
    page = list_conversations(
        session, places, run_id=run_id, from_tick=from_tick, to_tick=to_tick, place=place, limit=limit
    )
    if page is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return page
