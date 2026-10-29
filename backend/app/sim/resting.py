"""Resting, waiting and sleeping (03), and collapsing from exhaustion: a sleeper wakes at sunrise or once rested."""

from app.sim.acting import begin, settled
from app.sim.bodies import COLLAPSE_WAKE_ENERGY
from app.sim.clock import sun_altitude_deg, sun_direction
from app.sim.core import SimCore
from app.sim.doing import apply_partial
from app.sim.state import ActionState, Citizen
from app.world_api.models import Rest, Sleep, Wait

SLEEPY_ENERGY = 80.0  # above this nobody falls asleep by day


def start_rest(core: SimCore, citizen: Citizen, action: Rest | Wait) -> int:
    begin(core, citizen, action.action, "", {"minutes": action.minutes}).until_tick = core.state.tick + action.minutes
    return citizen.next_action - 1


def start_sleep(core: SimCore, citizen: Citizen, _action: Sleep) -> int:
    if citizen.body.energy > SLEEPY_ENERGY and not core.is_night_at(citizen.position):
        return settled(core, citizen, "sleep", "failed", "You aren't tired enough to sleep.")
    citizen.body.asleep = True
    begin(core, citizen, "sleep", "", {})
    return citizen.next_action - 1


def advance_sleep(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    if action.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY:
        return
    now = core.altitude(citizen.position)
    before = sun_altitude_deg(citizen.position, sun_direction(core.state.tick - 1, core.world.town_lon_deg))
    if before <= 0 < now:
        core.end_action(citizen, "done", "You wake up; it is morning.")
    elif now > 0 and citizen.body.energy >= 100:
        core.end_action(citizen, "done", "You wake up rested.")


def finish_rest(core: SimCore, citizen: Citizen, _action: ActionState) -> None:
    core.end_action(citizen, "done", "You rest a while.")


def finish_wait(core: SimCore, citizen: Citizen, _action: ActionState) -> None:
    core.end_action(citizen, "done", "You wait a while.")


def collapse(core: SimCore, citizen: Citizen) -> None:
    if citizen.action is not None:
        apply_partial(core, citizen, citizen.action)
        core.end_action(citizen, "interrupted", "Your legs give way; you collapse, exhausted.")
    citizen.body.asleep = True
    begin(core, citizen, "sleep", "", {"collapsed": True}).collapsed = True
