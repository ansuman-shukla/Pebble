"""The system registry and the tick hooks: the seam later systems plug into without touching the tick loop.

A system registers its `System` (name, state, snapshot block and version) in `REGISTRY.systems` and its per-tick work
in the hook lists. Each tick, after bodies and ecology and before perception and interrupts, the simulation runs
`every_tick` hooks, then `at_dawn` hooks, then `at_midnight` hooks, each list in its order here; `at_tick_end` hooks
run last, after interrupts and before the tick's summary (where bodies end the tick). Dawn and midnight
are local: a dawn or midnight hook gets a test `now(unit)` that says whether it is that moment at a spot this tick
(sunrise there; local midnight by its longitude), so each system checks its own holders (citizens, stores, camps).
An `on_event` hook is told each event as it is emitted (inside the emitting call; every hook hears every event in
emission order, those emitted by a hook queued behind the one it hears), for a system that learns from what the others
do. It sees the emitter's state at the `emit` call, possibly half-updated (`SimCore._tell`).
Append rows; keep every row another stream added.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.sim import (
    animals,
    justice,
    market,
    movement,
    nodes,
    ownership,
    paddies,
    senses,
    slots,
    society,
    tax,
    territory,
    wear,
)
from app.sim.clock import local_minute, sun_altitude_deg, sun_direction
from app.sim.core import EventListener, SimCore
from app.sim.state import System
from app.sim.vec import Vec3, lat_lon_deg

TickHook = Callable[[SimCore], None]
LocalTest = Callable[[Vec3], bool]  # is it the hook's moment (dawn, midnight) at this spot this tick?
LocalHook = Callable[[SimCore, LocalTest], None]


@dataclass(frozen=True)
class Registry:
    systems: tuple[System[Any], ...] = ()
    every_tick: tuple[TickHook, ...] = ()
    at_dawn: tuple[LocalHook, ...] = ()
    at_midnight: tuple[LocalHook, ...] = ()
    at_tick_end: tuple[TickHook, ...] = ()
    on_event: tuple[EventListener, ...] = ()

    def __post_init__(self) -> None:
        names = [system.name for system in self.systems]
        if len(set(names)) != len(names):
            raise ValueError(f"two systems share a name: {sorted(names)}")


REGISTRY = Registry(
    systems=(
        movement.RUNNING,
        wear.WEAR,
        slots.SLOTS,
        nodes.NODES,
        society.SOCIETY,
        ownership.OWNERSHIP,
        tax.TAX,
        animals.WILDLIFE,
        market.MARKET,
        territory.TERRITORY,
        senses.SENSES,
        justice.JUSTICE,
    ),
    every_tick=(
        movement.catch_breath,
        wear.watch_sun,
        nodes.grow,
        society.keep_night,
        territory.keep_the_law,
        territory.learn_dens,
        justice.keep_custody,
    ),
    at_dawn=(
        wear.spoil_at_dawn,
        wear.wear_packs_at_dawn,
        society.society_at_dawn,
    ),
    at_midnight=(
        tax.ledger_at_midnight,
        tax.settle_at_midnight,
        paddies.lose_at_midnight,
    ),
    at_tick_end=(slots.settle, market.watch_prices, movement.lead_held, justice.lock_up),
    on_event=(
        society.on_event,
        tax.count_coins,
        territory.on_event,
        senses.on_event,
        justice.on_event,
    ),
)


def dawn_at(core: SimCore, unit: Vec3) -> bool:
    """The sun rose at this spot during this tick (the moment sleepers wake to "it is morning")."""
    before = sun_altitude_deg(unit, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    return before <= 0 < core.altitude(unit)


def midnight_at(core: SimCore, unit: Vec3) -> bool:
    """Local midnight (by the spot's longitude) passed during this tick."""
    _, lon = lat_lon_deg(unit)
    town_lon = core.world.town_lon_deg
    return local_minute(core.state.tick, town_lon, lon) < local_minute(core.state.tick - 1, town_lon, lon)


def run_tick_end(core: SimCore, registry: Registry) -> None:
    for hook in registry.at_tick_end:
        hook(core)


def run_hooks(core: SimCore, registry: Registry) -> None:
    for hook in registry.every_tick:
        hook(core)
    for local in registry.at_dawn:
        local(core, lambda unit: dawn_at(core, unit))
    for local in registry.at_midnight:
        local(core, lambda unit: midnight_at(core, unit))
