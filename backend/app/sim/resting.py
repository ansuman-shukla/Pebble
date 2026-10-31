"""Resting, waiting and sleeping (03), and collapsing from exhaustion: a sleeper wakes at sunrise or once rested.

Rest takes a free seat within a few steps, else sits on the ground; sleep goes inside at your house's door, onto
your mat at camp, else lies down where you are (10-world-v1 §4.3, `app.sim.slots`).
"""

from app.observability.events import JsonScalar
from app.sim import slots
from app.sim.acting import begin, settled
from app.sim.bodies import COLLAPSE_WAKE_ENERGY
from app.sim.core import SimCore
from app.sim.doing import apply_partial
from app.sim.state import ActionState, Citizen
from app.sim.systems import dawn_at
from app.world_api.models import Rest, Sleep, Wait

SLEEPY_ENERGY = 80.0  # above this nobody falls asleep by day
ON_THE_GROUND = "on the ground"


def start_rest(core: SimCore, citizen: Citizen, action: Rest | Wait) -> int:
    args: dict[str, JsonScalar] = {"minutes": action.minutes}
    if action.action == "rest":
        args |= _spot(slots.take_seat(core, citizen))
    begin(core, citizen, action.action, "", args).until_tick = core.state.tick + action.minutes
    return citizen.next_action - 1


def start_sleep(core: SimCore, citizen: Citizen, _action: Sleep) -> int:
    if citizen.body.energy > SLEEPY_ENERGY and not core.is_night_at(citizen.position):
        return settled(core, citizen, "sleep", "failed", "You aren't tired enough to sleep.")
    citizen.body.asleep = True
    bed = slots.take_bed(core, citizen)
    begin(core, citizen, "sleep", "", _spot(bed))
    return citizen.next_action - 1


def _spot(slot: slots.Slot | None) -> dict[str, JsonScalar]:
    """Where they rest or sleep, for spectators: the seat, mat or house taken (`inside` hides the body after the
    door), else on the ground where they are."""
    return slots.spot_args(slot) if slot is not None else {"slot": None, "where": ON_THE_GROUND}


def advance_sleep(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    if action.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY:
        return
    if dawn_at(core, citizen.position):
        core.end_action(citizen, "done", "You wake up; it is morning.")
    elif core.altitude(citizen.position) > 0 and citizen.body.energy >= 100:
        core.end_action(citizen, "done", "You wake up rested.")


def finish_rest(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    where = action.args.get("where")
    core.end_action(citizen, "done", f"You rest a while {where}." if where else "You rest a while.")


def finish_wait(core: SimCore, citizen: Citizen, _action: ActionState) -> None:
    core.end_action(citizen, "done", "You wait a while.")


def collapse(core: SimCore, citizen: Citizen) -> None:
    if citizen.action is not None:
        apply_partial(core, citizen, citizen.action)
        if citizen.body.alive:  # raw food eaten so far can kill, and dying has ended the action
            core.end_action(citizen, "interrupted", "Your legs give way; you collapse, exhausted.")
    if not citizen.body.alive:  # what they had eaten so far killed them
        return
    citizen.body.asleep = True
    begin(core, citizen, "sleep", "", {"collapsed": True}).collapsed = True
