from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import PlaceIndexDep, SessionDep
from app.services.entities import TickNotReached
from app.services.scoreboard import ScoreboardView, scoreboard_at

router = APIRouter(prefix="/scoreboard", tags=["scoreboard"])


@router.get("", response_model=ScoreboardView)
def read_scoreboard(
    session: SessionDep,
    places: PlaceIndexDep,
    run_id: str | None = None,
    at: Annotated[int | None, Query(ge=0, description="replay this tick instead of now")] = None,
) -> ScoreboardView:
    """The spectator scoreboard, now or at a past tick: every citizen's wealth, flow, health, duty, status, ambition,
    ties and skills, each group's spread of wealth and deeds, the money supply check and the stall's stocks and
    prices. For spectators only: minds are never shown it."""
    try:
        view = scoreboard_at(session, places, run_id, at)
    except TickNotReached as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if view is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return view
