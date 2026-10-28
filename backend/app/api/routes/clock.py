from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.services.clock import ClockView, read_clock

router = APIRouter(prefix="/clock", tags=["clock"])


@router.get("", response_model=ClockView)
def read_game_clock(session: SessionDep, run_id: str | None = None) -> ClockView:
    """Game time, speed and pause state of the latest run (or the given one)."""
    clock = read_clock(session, run_id)
    if clock is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return clock
