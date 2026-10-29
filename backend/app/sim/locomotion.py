"""How fast a citizen goes (10-world-v1 §4.1, `data/bodies.yaml`, D114/D115).

```
  ground speed = gait (walk 1.4 · jog 2.5 · run 3.5 · stalk 0.8 m/s)
               × age × load × health × energy × night
               ÷ the leg's cost per metre (biome × slope × road, never below 1: `navigation.py`)
```

Every factor is at most 1 and every leg costs at least 1 per metre, so nobody covers more than their gait's metres in a
tick (walk 84, jog 150, run 210). Roads, paths, bridges and gentle downhill cost less than 1 for the route planner (it
prefers them) but don't lift anyone past their gait. Running wants `pace: "run"` (or a flee) and lasts while the run
endurance does; children, elders and anyone carrying 90 % of what they can jog at most. Pure (no sim core): the
walking code feeds it the body, the load and whether it is dark outside the town.
"""

from functools import cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import WORLD_DATA_DIR
from app.sim.clock import SECONDS_PER_TICK
from app.sim.state import AgeGroup, Citizen

Gait = Literal["walk", "jog", "run", "stalk"]
Pace = Literal["walk", "run"]
BODIES_PATH = WORLD_DATA_DIR / "bodies.yaml"


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunSpec(_Spec):
    endurance_s: float = Field(gt=0)
    recover_s_per_s: float = Field(gt=0)
    energy_per_minute: float = Field(ge=0)
    thirst_rate: float = Field(ge=1)
    jog_only: frozenset[AgeGroup]


class LoadBand(_Spec):
    share: float = Field(gt=0)  # carried kg / carry kg at or above this...
    factor: float = Field(gt=0, le=1)  # ...goes this much slower
    no_run: bool = False


class LevelBand(_Spec):
    at: float  # a need at or below this...
    factor: float = Field(gt=0, le=1)  # ...goes this much slower


class NightSpec(_Spec):
    factor: float = Field(gt=0, le=1)
    fire_m: float = Field(ge=0)


class BodiesSpec(_Spec):
    gaits_mps: dict[Gait, float]
    run: RunSpec
    load: list[LoadBand]
    health: list[LevelBand]
    energy: list[LevelBand]
    night: NightSpec

    def model_post_init(self, _context: object) -> None:
        if set(self.gaits_mps) != {"walk", "jog", "run", "stalk"}:
            raise ValueError("bodies.yaml needs a speed for every gait")


@cache
def load_bodies() -> BodiesSpec:
    return BodiesSpec.model_validate(yaml.safe_load(BODIES_PATH.read_text()))


def _load_band(share: float) -> LoadBand | None:
    bands = [band for band in load_bodies().load if share >= band.share]
    return max(bands, key=lambda band: band.share) if bands else None


def _level_factor(bands: list[LevelBand], value: float) -> float:
    return min((band.factor for band in bands if value <= band.at), default=1.0)


def top_gait(citizen: Citizen, share: float) -> Gait:
    """The fastest gait the citizen has: run, or jog for children, elders and heavy loads (`share`: carried kg /
    carry kg)."""
    band = _load_band(share)
    if citizen.group in load_bodies().run.jog_only or (band is not None and band.no_run):
        return "jog"
    return "run"


def gait_for(pace: Pace, top: Gait, run_left_s: float) -> Gait:
    """The gait for a minute of walking at `pace`: walking, or running while a whole minute of run endurance is left
    (jogging past it, or when the body can't run)."""
    if pace == "walk":
        return "walk"
    return "run" if top == "run" and run_left_s >= SECONDS_PER_TICK else "jog"


def body_factor(citizen: Citizen, share: float) -> float:
    """age × load × health × energy (each at most 1)."""
    spec = load_bodies()
    band = _load_band(share)
    body = citizen.body
    return (
        citizen.traits.speed
        * (band.factor if band is not None else 1.0)
        * _level_factor(spec.health, body.health)
        * _level_factor(spec.energy, body.energy)
    )


def gait_mps(gait: Gait) -> float:
    return load_bodies().gaits_mps[gait]


def night_factor(dark_outside: bool) -> float:
    """Slower in the dark outside the town with no lit fire close (`dark_outside`)."""
    return load_bodies().night.factor if dark_outside else 1.0
