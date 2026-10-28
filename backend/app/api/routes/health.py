from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import EngineDep
from app.core.db import database_is_up

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok"]
    database: Literal["up", "down"]


@router.get("", response_model=HealthStatus)
def read_health(engine: EngineDep) -> HealthStatus:
    return HealthStatus(status="ok", database="up" if database_is_up(engine) else "down")
