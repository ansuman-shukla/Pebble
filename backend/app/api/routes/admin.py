from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.db.schemas import ClockChange
from app.services.clock import ClockCommandAccepted, request_clock_change

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/clock", response_model=ClockCommandAccepted, status_code=status.HTTP_202_ACCEPTED)
def change_clock(change: ClockChange, session: SessionDep, run_id: str | None = None) -> ClockCommandAccepted:
    """Pause, resume or change speed; the engine applies it on its next loop."""
    accepted = request_clock_change(session, change, run_id)
    if accepted is None:
        raise HTTPException(status_code=404, detail="no simulation run yet")
    return accepted
