"""The goods table (10-world-v1 §2.2; `data/economy.yaml`).

One table of values in mon per unit (the town's and the bands'), where each good comes from and goes, and how the
market stall sells it. Every item kind has one row, so a new item can't enter the world without a value, a source and
a sink.
"""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import WORLD_DATA_DIR
from app.sim.items import ITEMS
from app.sim.state import Region

ECONOMY = WORLD_DATA_DIR / "economy.yaml"
Use = Literal["hunt", "fell", "harvest", "carry", "craft"]  # what wears a tool out (the `tool_broke` payload's)


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StallLot(_Spec):
    lot: int = Field(ge=1)  # units per lot bought or sold
    target: int = Field(ge=1)  # the stock the stall's price is fair at


class Good(_Spec):
    town: float | None = Field(ge=0)  # mon per unit to town folk; None = worth nothing to them
    band: float | None = Field(ge=0)  # ... to the bands
    source: str = Field(min_length=1)
    sink: str = Field(min_length=1)
    stall: StallLot | None  # None = not sold at the stall


class Breakage(_Spec):
    use: Use
    chance: float = Field(gt=0, lt=1)


class EconomySpec(_Spec):
    money_supply: int = Field(gt=0)
    goods: dict[str, Good]
    spoilage: dict[str, float]  # item -> share lost at each local dawn (rounded up)
    breakage: dict[str, Breakage]  # item -> chance it breaks per use

    @model_validator(mode="after")
    def _check_items(self) -> "EconomySpec":
        missing, unknown = set(ITEMS) - set(self.goods), set(self.goods) - set(ITEMS)
        if missing or unknown:
            raise ValueError(f"goods must list every item kind: missing {sorted(missing)}, unknown {sorted(unknown)}")
        for name, table in (("spoilage", self.spoilage), ("breakage", self.breakage)):
            if not set(table) <= set(ITEMS):
                raise ValueError(f"{name} names unknown items: {sorted(set(table) - set(ITEMS))}")
        if any(not 0 < share <= 1 for share in self.spoilage.values()):
            raise ValueError("a spoilage share is above 0 and at most 1")
        tools = {name for name, kind in ITEMS.items() if kind.tool}
        if not tools <= set(self.breakage):
            raise ValueError(f"every tool breaks with use: {sorted(tools - set(self.breakage))} don't")
        sold = {name for name, good in self.goods.items() if good.stall is not None}
        if worthless := sorted(name for name in sold if not self.goods[name].town):
            raise ValueError(f"the stall sells only goods with a town value: {worthless}")
        return self


@cache
def load_economy(path: Path = ECONOMY) -> EconomySpec:
    return EconomySpec.model_validate(yaml.safe_load(path.read_text()))


def value_of(item: str, region: Region) -> float:
    """What one unit is worth in mon to someone of this group: town folk by the town's column, bands by their own."""
    good = load_economy().goods[item]
    value = good.town if region == "town" else good.band
    return value or 0.0
