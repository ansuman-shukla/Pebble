from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.services.entities import EntitiesView, TickNotReached, entities_at

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("", response_model=EntitiesView)
def read_entities(
    session: SessionDep,
    run_id: str | None = None,
    at: Annotated[int | None, Query(ge=0, description="replay this tick instead of now")] = None,
) -> EntitiesView:
    """Citizens now or at a past tick: position, cell, current action and coarse state."""
    try:
        view = entities_at(session, run_id, at)
    except TickNotReached as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if view is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return view
