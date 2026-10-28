"""Citizen specs: who someone is and where they start. The real 15 arrive with M7; `data/citizens/dev.yaml` is a
small cast for running the engine during development.
"""

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import WORLD_DATA_DIR
from app.world.geometry import Point

CITIZENS_DATA_DIR = WORLD_DATA_DIR / "citizens"
DEV_CITIZENS = CITIZENS_DATA_DIR / "dev.yaml"


class CitizenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    look: str  # frontend look id (citizen-looks.ts)
    appearance: str  # how strangers see them
    age: int = Field(ge=5, le=100)
    site: str = "town"  # local metres below are around this site's anchor (the town uses its chart)
    at: Point
    home: str | None = None  # a house placement id in the town
    knows_places: list[str] = []
    knows_people: list[str] = []


class CitizensSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citizens: list[CitizenSpec]


@cache
def load_citizens(path: Path = DEV_CITIZENS) -> CitizensSpec:
    return CitizensSpec.model_validate(yaml.safe_load(path.read_text()))
