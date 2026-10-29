"""How fast a citizen covers flat open ground (10-world-v1 §4.1): the gait × age × load × health × energy × night
(`locomotion.py`), for walks (`movement.py`) and for the few steps people take to their spots (`slots.py`)."""

from app.sim.core import SimCore
from app.sim.fire import near_lit_fire
from app.sim.locomotion import Gait, body_factor, gait_mps, load_bodies, night_factor
from app.sim.state import Citizen


def load_share(core: SimCore, citizen: Citizen) -> float:
    return core.carried_kg(citizen) / citizen.traits.carry_kg


def ground_mps(core: SimCore, citizen: Citizen, gait: Gait) -> float:
    """Metres a second on flat open ground: the gait × age × load × health × energy × night (outside the town in
    the dark with no lit fire close)."""
    position = citizen.position
    dark_outside = (
        core.is_night_at(position)
        and core.world.town_point(position) is None
        and not near_lit_fire(core, position, load_bodies().night.fire_m)
    )
    return gait_mps(gait) * body_factor(citizen, load_share(core, citizen)) * night_factor(dark_outside)
