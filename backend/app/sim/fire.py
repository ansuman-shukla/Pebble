"""Fire (02-simulation "Fire"): hearths and campfires burn their fuel down and go out unless fed. A lit fire gives
light (night sight ~30 m, 03), cooks food eaten beside it, and keeps animals away (predators don't attack near it).

Fuel is counted in minutes: each piece of wood burns an hour. Spectators and perception see a coarse level (out,
embers, low, burning); every change of level, lighting or feeding is one `fire_changed` event.
"""

from app.observability.events import FireChanged
from app.sim.core import SimCore
from app.sim.state import Fire, WorldState
from app.sim.vec import Vec3
from app.sim.world import SimWorld

WOOD_MINUTES = 60  # one piece of wood burns this long
MAX_FUEL = 12 * 60  # a fire holds at most this much wood's worth (a full fire lasts the night)
KINDLING_WOOD = 2  # make_fire burns up to this many pieces to get going
CAMP_START_FUEL = 6 * 60  # camps begin with their fire burning (one band starts the run at night)
LEVELS = (0, 30, 120)  # fuel above these: embers, low, burning
SAFE_M = 15.0  # predators don't attack people this close to a lit fire
FEAR_M = 25.0  # animals keep this far from a lit fire
REACH_M = 4.0  # tending, lighting or cooking at a fire


def fuel_level(fuel: int) -> int:
    return sum(fuel > threshold for threshold in LEVELS)


def strength(level: int) -> float:
    """0 (out) .. 1 (burning), for spectators."""
    return round(level / 3, 3)


def hearth_fires(world: SimWorld) -> dict[str, Fire]:
    """The world's hearths as fires at the start of a run: camp fire pits burning, town baskets cold."""
    fires: dict[str, Fire] = {}
    for hearth_id, hearth in world.hearths.items():
        cell = world.nearest_cell(hearth.centre)
        fuel = CAMP_START_FUEL if hearth.kind == "pit" else 0
        fires[hearth_id] = Fire(
            id=hearth_id,
            kind=hearth.kind,
            position=hearth.centre,
            cell=cell,
            height_m=world.ground_height(hearth.centre, cell),
            fuel=fuel,
            lit=fuel > 0,
            level=fuel_level(fuel),
        )
    return fires


def lit_fires(state: WorldState) -> list[Fire]:
    return [state.fires[fire_id] for fire_id in sorted(state.fires) if state.fires[fire_id].lit]


def nearest_fire(core: SimCore, position: Vec3, within_m: float, lit: bool | None = None) -> Fire | None:
    """The nearest fire (lit or cold, or either when `lit` is None) within the distance."""
    best: tuple[float, str] | None = None
    for fire in core.state.fires.values():
        if lit is not None and fire.lit != lit:
            continue
        distance = core.distance_m(position, fire.position)
        if distance <= within_m and (best is None or (distance, fire.id) < best):
            best = (distance, fire.id)
    return core.state.fires[best[1]] if best is not None else None


def near_lit_fire(core: SimCore, position: Vec3, within_m: float) -> bool:
    return nearest_fire(core, position, within_m, lit=True) is not None


def changed(core: SimCore, fire: Fire, cause_seq: int | None = None) -> int:
    """One `fire_changed` event with the fire's state now."""
    return core.emit(
        "fire_changed",
        FireChanged(
            id=fire.id,
            kind=fire.kind,
            lit=fire.lit,
            strength=strength(fire.level),
            position=fire.position,
            height_m=fire.height_m,
            cell=fire.cell,
        ),
        cause_seq=cause_seq,
    )


def add_fuel(fire: Fire, minutes: int) -> None:
    fire.fuel = min(MAX_FUEL, fire.fuel + minutes)
    fire.lit = fire.fuel > 0
    fire.level = fuel_level(fire.fuel)


def burn(core: SimCore) -> None:
    """One minute of burning for every lit fire; an event when a fire's level drops or it goes out."""
    for fire in lit_fires(core.state):
        fire.fuel -= 1
        level = fuel_level(fire.fuel)
        if fire.fuel <= 0:
            fire.fuel, fire.lit, fire.level = 0, False, 0
            changed(core, fire)
        elif level != fire.level:
            fire.level = level
            changed(core, fire)


def label(fire: Fire) -> str:
    """What a fire is to someone nearby (a pit's fire is told as the fire pit itself)."""
    return {"pit": "the fire pit", "basket": "a fire basket", "campfire": "a campfire"}[fire.kind]


def state_words(fire: Fire) -> str:
    """How it burns, told as what it is doing ("the fire pit … (burning low)")."""
    return ("cold", "glowing embers", "burning low", "burning")[fire.level]


KEYWORDS = frozenset({"fire", "campfire", "embers", "basket", "flames", "hearth"})
