"""Expressing yourself without words (contract v1, 10 §6.1): gestures and goals, both instant.

A gesture is seen, never heard: everyone awake who has the gesturer in sight sees it (`gestured`, its `seen_by`), and
it may be made to a person in view. A goal is what a citizen says to itself it is after and why (`goal_set`): it
takes no time, and only spectators learn it; nobody in the world perceives it.
"""

from app.observability.events import Gestured, GoalSet
from app.sim.acting import refuse
from app.sim.core import SimCore
from app.sim.perception import match_person, person_label
from app.sim.state import Citizen
from app.world_api.models import ActionResult, Gesture, GestureKind, SetGoal

# how a gesture is said to the one making it: alone, and made to someone (laughing and jumping aren't aimed)
GESTURE_WORDS: dict[GestureKind, tuple[str, str]] = {
    "wave": ("wave", "wave to"),
    "bow": ("bow", "bow to"),
    "nod": ("nod", "nod to"),
    "shake_head": ("shake your head", "shake your head at"),
    "point": ("point", "point at"),
    "laugh": ("laugh", ""),
    "jump": ("jump", ""),
}


def gesture(core: SimCore, citizen: Citizen, action: Gesture) -> ActionResult:
    person = match_person(core, citizen, action.to) if action.to is not None else None
    if action.to is not None and person is None:
        return refuse(core, citizen, "gesture", "You don't see anyone like that.")
    seen_by = [
        other.id
        for other in core.living()
        if other.id != citizen.id
        and not other.body.asleep
        and core.distance_m(other.position, citizen.position) <= core.sight_range(other)
    ]
    core.emit(
        "gestured",
        Gestured(kind=action.kind, to=person.id if person is not None else None, seen_by=seen_by),
        actor=citizen,
    )
    alone, aimed = GESTURE_WORDS[action.kind]
    said = f"{aimed} {person_label(citizen, person)}" if person is not None and aimed else alone
    return ActionResult(action="gesture", outcome="done", text=f"You {said}.")


def set_goal(core: SimCore, citizen: Citizen, action: SetGoal) -> ActionResult:
    core.emit("goal_set", GoalSet(text=action.text, driver=action.driver), actor=citizen, visibility="private")
    return ActionResult(action="set_goal", outcome="done", text="You set your mind on it.")
