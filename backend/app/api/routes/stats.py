from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import PlaceIndexDep, SessionDep
from app.services.entities import TickNotReached
from app.services.stats import StatsView, world_stats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsView)
def read_stats(
    session: SessionDep,
    places: PlaceIndexDep,
    run_id: str | None = None,
    at: Annotated[int | None, Query(ge=0, description="replay this tick instead of now")] = None,
) -> StatsView:
    """Population, deaths by cause, food stocks, wild resources and events per game day, now or at a past tick."""
    try:
        view = world_stats(session, places, run_id, at)
    except TickNotReached as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if view is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return view
