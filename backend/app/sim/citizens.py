"""Citizen specs: who someone is and where they start. `data/citizens/citizens.yaml` is the v0 cast of 15 (the
engine starts new runs with it); `data/citizens/dev.yaml` is a small cast for tests and development.
"""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import WORLD_DATA_DIR
from app.sim.state import Region
from app.world.geometry import Point

CITIZENS_DATA_DIR = WORLD_DATA_DIR / "citizens"
DEV_CITIZENS = CITIZENS_DATA_DIR / "dev.yaml"
CITIZENS = CITIZENS_DATA_DIR / "citizens.yaml"


class CitizenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    look: str  # frontend look id (citizen-looks.ts)
    appearance: str  # how strangers see them
    age: int = Field(ge=5, le=100)
    site: str = "town"  # local metres below are around this site's anchor (the town uses its chart)
    at: Point
    home: str | None = None  # a town house placement id, or "<camp site>:<lean-to placement id>"
    knows_places: list[str] = []
    knows_people: list[str] = []
    role: str = ""
    region: Region = "town"
    sex: Literal["female", "male"] | None = None
    skills: list[str] = []
    inventory: dict[str, int] = {}  # what they start out carrying
    personality: str = ""  # one line, for the minds of phase B and for spectators


class CitizensSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citizens: list[CitizenSpec]
    stores: dict[str, dict[str, int]] = {}  # storehouse id -> starting stock


@cache
def load_citizens(path: Path = DEV_CITIZENS) -> CitizensSpec:
    return CitizensSpec.model_validate(yaml.safe_load(path.read_text()))
