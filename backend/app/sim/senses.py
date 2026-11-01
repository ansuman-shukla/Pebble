"""What a citizen notices between two looks around (10-world-v1 §6.2), told once by the next look (`perception`).

- **Gestures** (`gestured`): everyone in its `seen_by` sees who made it, and to whom.
- **The temple bell** (`bell_rang`): everyone awake within the bell's hearing (`laws.yaml` bell `heard_m`) hears it.
- **Spoiling** (`spoiled` of what someone carries): its holder finds some of their food gone off at their dawn.
- **A pack wearing out** (`tool_broke` of a pack, at dawn): its carrier. Tools that break in use are told in the
  result of the action that broke them.

The system `senses` keeps each citizen's notices until they look around, only the latest few.
"""

from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import JsonValue, TypeAdapter

from app.observability.events import BellRang, EventDraft, Gestured, Spoiled, ToolBroke
from app.sim import society
from app.sim.core import SimCore
from app.sim.state import System
from app.world_api.models import GestureKind

KEPT = 8  # notices kept per citizen until they look (the oldest go first)
WORN_USE = "carry"  # a tool broken by this use broke outside any action (a pack at dawn)


@dataclass(frozen=True)
class Notice:
    kind: Literal["gesture", "bell", "spoiled", "worn"]
    who: str | None = None  # the gesturer
    gesture: GestureKind | None = None
    to: str | None = None  # whom the gesture was made to
    items: tuple[str, ...] = ()  # what spoiled, what wore out


@dataclass
class Senses:
    noticed: dict[str, list[Notice]] = field(default_factory=dict)  # citizen -> notices since their last look


_BLOCK = TypeAdapter(Senses)


def _dump(senses: Senses) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(senses, mode="json"))


def _load(data: JsonValue) -> Senses:
    return _BLOCK.validate_python(data)


SENSES = System[Senses]("senses", 1, new=lambda _world: Senses(), dump=_dump, load=_load)


def on_event(core: SimCore, event: EventDraft) -> None:
    """Event hook: who notices this event, and what."""
    payload, actor = event.payload, event.actor_id
    if isinstance(payload, Gestured) and actor is not None:
        notice = Notice("gesture", who=actor, gesture=payload.kind, to=payload.to)
        for seer in payload.seen_by:
            _note(core, seer, notice)
    elif isinstance(payload, BellRang) and actor in core.state.citizens:
        ringer = core.state.citizens[actor].position
        heard_m = society.load_laws().bell.heard_m
        for hearer in core.living():
            if hearer.id != actor and not hearer.body.asleep and core.distance_m(hearer.position, ringer) <= heard_m:
                _note(core, hearer.id, Notice("bell"))
    elif isinstance(payload, Spoiled) and payload.holder_kind == "inventory":
        _note(core, payload.holder, Notice("spoiled", items=tuple(sorted(payload.items))))
    elif isinstance(payload, ToolBroke) and payload.use == WORN_USE and actor is not None:
        _note(core, actor, Notice("worn", items=(payload.item,)))


def _note(core: SimCore, citizen_id: str, notice: Notice) -> None:
    noticed = SENSES.of(core.state).noticed.setdefault(citizen_id, [])
    noticed.append(notice)
    del noticed[:-KEPT]


def take(core: SimCore, citizen_id: str) -> list[Notice]:
    """What the citizen noticed since their last look, oldest first; told now, so forgotten here."""
    return SENSES.of(core.state).noticed.pop(citizen_id, [])
