"""Ecology, once per tick: fires burn down, animals live (`app.sim.animals`), wild plants and fish grow back.

Regrowth (02-simulation: berries ~3 days, roots ~5, nuts ~7): a gathered or fished cell grows one piece back every
`REGROW_DAYS × day / cap` ticks until it is full again, each piece one `resource_changed` event, so a bare berry cell
is full three game days later. Cells nobody touches keep their starting stock.
"""

from app.observability.events import ResourceChanged
from app.sim import animals, fire
from app.sim.clock import DAY_MINUTES
from app.sim.core import SimCore
from app.sim.items import REGROW_DAYS, RESOURCE_INDEX


def regrow_key(cell: int, resource: str) -> str:
    return f"{cell}:{resource}"


def regrow_interval(cap: int, resource: str) -> int:
    """Ticks between two pieces growing back on a cell holding at most `cap`."""
    return max(1, round(REGROW_DAYS[resource] * DAY_MINUTES / cap))


def schedule_regrowth(core: SimCore, cell: int, resource: str) -> None:
    """After gathering: the cell starts growing back (if it isn't already)."""
    key = regrow_key(cell, resource)
    cap = int(core.world.resource_caps[cell, RESOURCE_INDEX[resource]])
    if key not in core.state.regrow and cap > 0:
        core.state.regrow[key] = core.state.tick + regrow_interval(cap, resource)


def step(core: SimCore) -> None:
    """Advance the ecology by one tick."""
    fire.burn(core)
    animals.step(core)
    _regrow(core)


def _regrow(core: SimCore) -> None:
    state = core.state
    due = sorted(key for key, tick in state.regrow.items() if tick <= state.tick)
    for key in due:
        cell_text, resource = key.split(":", 1)
        cell, column = int(cell_text), RESOURCE_INDEX[resource]
        cap = int(core.world.resource_caps[cell, column])
        before = int(state.resources[cell, column])
        if before < cap:
            state.resources[cell, column] = before + 1
            core.emit(
                "resource_changed", ResourceChanged(cell=cell, resource=resource, before=before, after=before + 1)
            )
        if before + 1 < cap:
            state.regrow[key] += regrow_interval(cap, resource)
        else:
            del state.regrow[key]
