"""Who is in custody (10-world-v1 §3.4): held by a seizer, confined in the gaol, or tied at a band's fire.

The state only, and what other systems read of it (perception tells it, territory and movement follow it); justice
(`app.sim.justice`) puts people in custody and lets them go. A custody runs on one clock of CUSTODY_HOURS from the
seizure (D174).
"""

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import JsonValue, TypeAdapter

from app.sim.clock import TICKS_PER_HOUR
from app.sim.core import SimCore
from app.sim.state import System

CUSTODY_HOURS = 12  # the gaol has water but no food
CustodyPlace = Literal["held", "gaol", "fire"]


@dataclass
class Custody:
    since: int  # the tick they were seized: custody ends CUSTODY_HOURS on at the latest
    keeper: str | None  # who holds them while held; None once confined
    place: CustodyPlace = "held"
    until: int | None = None  # a confinement sentence's last tick
    judgement: int | None = None  # the `judged` seq of the confinement being served


_BLOCK = TypeAdapter(dict[str, Custody])


def _dump(custody: dict[str, Custody]) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(dict(sorted(custody.items())), mode="json"))


def _load(data: JsonValue) -> dict[str, Custody]:
    return _BLOCK.validate_python(data)


CUSTODY = System[dict[str, Custody]]("custody", 1, new=lambda _world: {}, dump=_dump, load=_load)  # by citizen


def custody_of(core: SimCore, citizen_id: str) -> Custody | None:
    return CUSTODY.of(core.state).get(citizen_id)


def in_custody(core: SimCore, citizen_id: str) -> bool:
    return citizen_id in CUSTODY.of(core.state)


def held_pairs(core: SimCore) -> list[tuple[str, str]]:
    """(held, seizer) for everyone held (not confined), by id."""
    return [
        (person, custody.keeper)
        for person, custody in sorted(CUSTODY.of(core.state).items())
        if custody.keeper is not None
    ]


def leading(core: SimCore, keeper_id: str) -> str | None:
    """The person this citizen holds, if any."""
    return next((person for person, keeper in held_pairs(core) if keeper == keeper_id), None)


def custody_ends(custody: Custody) -> int:
    """The last tick of a custody: its 12 h from the seizure, sooner if a confinement sentence ends before."""
    cap = custody.since + CUSTODY_HOURS * TICKS_PER_HOUR
    return cap if custody.until is None else min(cap, custody.until)
