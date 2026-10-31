"""What a citizen's body is doing, for spectators (10-world-v1 §4.5): one `motion` and one `posture` per citizen, so
the client maps them through one table to clips, procedural poses and props and never parses labels.

Derived, never stored: from what the sim knows of a citizen at a tick's end (alive, asleep, the action and its
arguments, how they moved this tick, what they carry), which replay rebuilds from the events alone, so `/entities`
and the live feed tell the same motion at every tick as the sim had.

    dead / asleep / collapsed ─▶ lie            moved this tick ─▶ walk | carry_walk | jog | run | stalk (by gait)
    otherwise by action:  rest ─▶ sit_ground   gather ─▶ gather_low | gather_high | mine | pan (by what)
                          work ─▶ farm | craft | trade | pick_up | ring_bell | pray | talk | idle (by task) ...
    asleep in a house ─▶ inside                 still on a slot ─▶ its posture and facing (rest on a seat ─▶ sit)
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from app.observability.events import JsonScalar
from app.sim.items import ITEMS
from app.sim.locomotion import Gait
from app.sim.state import AGE_GROUPS, AgeGroup

Motion = Literal[
    "idle",
    "walk",
    "jog",
    "run",
    "carry_walk",
    "stalk",
    "sit",
    "sit_ground",
    "lie",
    "inside",
    "gather_low",
    "gather_high",
    "pick_up",
    "chop",
    "mine",
    "pan",
    "farm",
    "fish",
    "craft",
    "eat",
    "drink",
    "talk",
    "trade",
    "gesture",
    "attack",
    "tend",
    "pray",
    "ring_bell",
]
# standing; crouching (low gathering, panning, tending); sitting on a seat (hips at its height) or on the ground;
# lying (asleep outside, collapsed, dead); inside (asleep at home: the body is hidden after the door)
Posture = Literal["standing", "crouching", "sitting", "sitting_ground", "lying", "inside"]

CARRY_WALK_LOAD = 0.5  # a walker carrying at least this share of what they can carry walks loaded (§4.1)

POSTURES: dict[Motion, Posture] = {
    "sit": "sitting",
    "sit_ground": "sitting_ground",
    "lie": "lying",
    "inside": "inside",
    "gather_low": "crouching",
    "pan": "crouching",
    "tend": "crouching",
    "craft": "crouching",
    "pray": "sitting_ground",
}  # every other motion stands

_GAITS: dict[Gait, Motion] = {"walk": "walk", "jog": "jog", "run": "run", "stalk": "stalk"}
_GATHERED: dict[str, Motion] = {
    "berries": "gather_high",
    "nuts": "gather_high",
    "flint": "mine",
    "obsidian": "mine",
    "iron sand": "mine",
    "gold": "pan",
}  # roots, reeds, rice, deadwood: low
_TASKS: dict[str, Motion] = {
    "farm": "farm",
    "weave": "craft",
    "trade": "trade",
    "store food": "pick_up",
    "guard": "idle",
    "govern": "talk",
    "ring bell": "ring_bell",
    "pray": "pray",
}
_ACTIONS: dict[str, Motion] = {
    "rest": "sit_ground",
    "fish": "fish",
    "hunt": "stalk",
    "attack": "attack",
    "seize": "attack",
    "eat": "eat",
    "drink": "drink",
    "make_fire": "tend",
    "feed_fire": "pick_up",
    "pick_up": "pick_up",
    "drop": "pick_up",
    "give": "pick_up",
    "stash": "pick_up",
    "craft": "craft",
    "buy": "trade",
    "sell": "trade",
    "tend": "tend",
    "judge": "talk",
    "accuse": "talk",
    "say": "talk",
    "gesture": "gesture",
}  # walk_to, follow, flee standing still, wait and the rest: idle


@dataclass(frozen=True)
class BodyMotion:
    motion: Motion
    posture: Posture
    slot_heading: float | None = None  # the seat's, mat's or work slot's facing while on it (S1)
    slot_height_m: float | None = None  # how high the seat they sit on is (S1)


def load_share(inventory: Mapping[str, int], age_group: AgeGroup) -> float:
    """What they carry as a share of what they can carry."""
    carried = sum(ITEMS[item].weight_kg * count for item, count in inventory.items())
    return carried / AGE_GROUPS[age_group].carry_kg


def body_motion(
    *,
    alive: bool,
    asleep: bool,
    action: str | None,
    args: Mapping[str, JsonScalar],
    gait: Gait | None,
    load: float,
    talking: bool,
) -> BodyMotion:
    """`gait` is how they moved this tick (None when they didn't); `talking` that they spoke just now (shown while
    their body is otherwise idle). An action done at a slot (S1: its args carry the slot's `posture`, `facing` and
    `seat_m`) rests the body the slot's way once they stand still on it: inside a house, on a seat, a mat or at a work
    slot, facing the way it faces."""
    motion = _motion(alive, asleep, action, args, gait, load, talking)
    posture = POSTURES.get(motion, "standing")
    slot_posture, facing, seat_m = args.get("posture"), args.get("facing"), args.get("seat_m")
    if not alive or not isinstance(slot_posture, str) or not isinstance(facing, float | int):
        return BodyMotion(motion=motion, posture=posture)
    if slot_posture == "inside":
        return BodyMotion(motion="inside", posture="inside")
    if gait is not None:  # still stepping onto it
        return BodyMotion(motion=motion, posture=posture)
    if motion == "sit_ground" and slot_posture == "sitting":
        motion = "sit"
    if slot_posture != "standing":
        posture = cast(Posture, slot_posture)
    height = float(seat_m) if posture == "sitting" and isinstance(seat_m, float | int) else None
    return BodyMotion(motion, posture, float(facing), height)


def _motion(
    alive: bool,
    asleep: bool,
    action: str | None,
    args: Mapping[str, JsonScalar],
    gait: Gait | None,
    load: float,
    talking: bool,
) -> Motion:
    if not alive or asleep:
        return "lie"
    if gait is not None:
        walk = _GAITS[gait]
        return "carry_walk" if walk == "walk" and load >= CARRY_WALK_LOAD else walk
    if action == "gather":
        if args.get("node_kind") == "tree":  # N1: felling a standing tree (gather wood with an axe)
            return "chop"
        return _GATHERED.get(str(args.get("resource")), "gather_low")
    if action == "work":
        return _TASKS.get(str(args.get("task")), "idle")
    if action in _ACTIONS:
        return _ACTIONS[action]
    return "talk" if talking else "idle"
