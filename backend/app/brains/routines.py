"""Role routines: what each kind of citizen does with an ordinary day once needs and night are taken care of.

Every routine returns scored options (needs and night outscore them; see `brain.py`). The town's routines live in
`town.py` and the bands' in `bands.py`, both built on the helpers here.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import get_args

from pydantic import JsonValue

from app.brains.profile import BrainProfile
from app.brains.senses import (
    Needs,
    Phase,
    at,
)
from app.world_api.facade import ActionHandle, WorldApi
from app.world_api.models import Compass, Driver, Pace, Perception

WORK = 30.0  # the score of an ordinary day's routine
COMPASS: tuple[Compass, ...] = get_args(Compass)


@dataclass(frozen=True)
class Option:
    """A scored choice; `start` runs only if it is chosen (any notes it keeps are written then). `aim` is the goal it
    serves as spectators read it, with why (`driver`): the steps of one aim share it ("go to the rice fields", then
    "farm": "Tend the rice fields"); an option without an aim leaves the goal as it was."""

    score: float
    name: str
    start: Callable[[], ActionHandle]
    aim: str = ""
    driver: Driver = "duty"


def _then(note: Callable[[], None], start: Callable[[], ActionHandle]) -> Callable[[], ActionHandle]:
    def run() -> ActionHandle:
        note()
        return start()

    return run


@dataclass
class Context:
    """What a routine sees and can do at one decision point."""

    api: WorldApi
    profile: BrainProfile
    perception: Perception
    needs: Needs
    phase: Phase
    chance: Callable[[float], bool]
    pick: Callable[[int], int]
    pace: Pace = "walk"  # how walks home go: run when desperate or a predator prowls in view
    seed: int = 0  # the world's seed, for the rolls a group makes alike (a band's choice at the fire)

    @property
    def notes(self) -> dict[str, JsonValue]:
        return self.api.notes

    def counter(self, key: str) -> int:
        value = self.notes.get(key, 0)
        return value if isinstance(value, int) else 0

    def done_today(self, chore: str) -> bool:
        chores = self.notes.get("chores", [])
        return isinstance(chores, list) and chore in chores

    def finished(self, name: str) -> bool:
        """The option chosen last was this one and its action ran to its end, not cut short (`chosen`: its number)."""
        number = self.notes.get("chosen")
        result = self.api.handle(number).result if isinstance(number, int) else None
        return self.notes.get("last") == name and result is not None and result.outcome == "done"

    def mark_done(self, chore: str) -> None:
        chores = self.notes.setdefault("chores", [])
        if isinstance(chores, list):
            chores.append(chore)


def _set(ctx: Context, key: str, value: JsonValue) -> None:
    ctx.notes[key] = value


def _go(ctx: Context, place: str, score: float = WORK, aim: str = "", driver: Driver = "duty") -> Option:
    return Option(score, f"go to {place}", lambda: ctx.api.walk_to_place(place), aim, driver)


def _on_spot(ctx: Context, walk: str) -> bool:
    """Still standing where this walk ended (`arrived`, kept by the brain): on the work slot it claimed (D118).
    Anywhere else in the place (a walk cut short, a rest on a bench, an errand there) the walk comes first: it lands
    on the slot, or says you are already there (issue #89: no long walks to a slot at the tick's end)."""
    return ctx.notes.get("arrived") == walk


def _work_at(
    ctx: Context, place: str, task: str, score: float = WORK, aim: str = "", driver: Driver = "duty"
) -> Option:
    if at(ctx.perception, place) and _on_spot(ctx, f"go to {place}"):
        return Option(score, task, lambda: ctx.api.work(task), aim, driver)
    return _go(ctx, place, score, aim, driver)


def _daytime(ctx: Context) -> bool:
    return ctx.phase in ("morning", "day")


# --- the bands ---


def _refused(ctx: Context, name: str) -> bool:
    """The option chosen last was this one and the world refused it at once."""
    number = ctx.notes.get("chosen")
    result = ctx.api.handle(number).result if isinstance(number, int) else None
    return ctx.notes.get("last") == name and result is not None and result.outcome == "failed"


def _count_today(ctx: Context, chore: str) -> int:
    chores = ctx.notes.get("chores", [])
    return chores.count(chore) if isinstance(chores, list) else 0
