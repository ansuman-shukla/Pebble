from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import PlaceIndexDep, SessionDep
from app.observability.events import EventType
from app.services.citizens import (
    MAX_TIMELINE,
    CitizenNotFound,
    CitizenProfile,
    CitizensView,
    NeedsSeries,
    Order,
    TimelinePage,
    citizen_needs,
    citizen_profile,
    citizen_timeline,
    list_citizens,
)
from app.services.entities import TickNotReached

router = APIRouter(prefix="/citizens", tags=["citizens"])

NO_RUN = "no simulation run yet"
AtQuery = Annotated[int | None, Query(ge=0, description="replay this tick instead of now")]
TickQuery = Annotated[int | None, Query(ge=0)]


@router.get("", response_model=CitizensView)
def read_citizens(
    session: SessionDep, places: PlaceIndexDep, run_id: str | None = None, at: AtQuery = None
) -> CitizensView:
    """Everyone at a glance, now or at a past tick: role, region, age, look, alive, what they are doing and where."""
    try:
        view = list_citizens(session, places, run_id, at)
    except TickNotReached as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if view is None:
        raise HTTPException(status_code=404, detail=NO_RUN)
    return view


@router.get("/{citizen_id}", response_model=CitizenProfile)
def read_citizen(
    citizen_id: str, session: SessionDep, places: PlaceIndexDep, run_id: str | None = None, at: AtQuery = None
) -> CitizenProfile:
    """One citizen now or at a past tick: who they are, their body in words and numbers, what they carry and know,
    and their latest doings."""
    try:
        profile = citizen_profile(session, places, citizen_id, run_id, at)
    except (TickNotReached, CitizenNotFound) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if profile is None:
        raise HTTPException(status_code=404, detail=NO_RUN)
    return profile


@router.get("/{citizen_id}/timeline", response_model=TimelinePage)
def read_citizen_timeline(
    citizen_id: str,
    session: SessionDep,
    places: PlaceIndexDep,
    run_id: str | None = None,
    from_tick: TickQuery = None,
    to_tick: TickQuery = None,
    type: Annotated[
        list[EventType] | None, Query(description="default: everything but tick summaries and looking around")
    ] = None,
    order: Order = "asc",
    cursor: Annotated[int | None, Query(ge=0, description="the previous page's next_cursor")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_TIMELINE)] = 100,
) -> TimelinePage:
    """The citizen's life in order: their actions, speech (said and heard), needs, knowledge, items: one line each."""
    try:
        page = citizen_timeline(
            session,
            places,
            citizen_id,
            run_id=run_id,
            from_tick=from_tick,
            to_tick=to_tick,
            types=type,
            order=order,
            cursor=cursor,
            limit=limit,
        )
    except CitizenNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if page is None:
        raise HTTPException(status_code=404, detail=NO_RUN)
    return page


@router.get("/{citizen_id}/needs", response_model=NeedsSeries)
def read_citizen_needs(
    citizen_id: str,
    session: SessionDep,
    run_id: str | None = None,
    from_tick: TickQuery = None,
    to_tick: TickQuery = None,
    step: Annotated[int | None, Query(ge=1, description="ticks between points (default: ~288 points)")] = None,
) -> NeedsSeries:
    """Hunger, thirst, energy and health over time (the last game day by default)."""
    try:
        series = citizen_needs(session, citizen_id, run_id=run_id, from_tick=from_tick, to_tick=to_tick, step=step)
    except CitizenNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if series is None:
        raise HTTPException(status_code=404, detail=NO_RUN)
    return series
