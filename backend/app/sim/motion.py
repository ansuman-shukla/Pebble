"""What a citizen's body is doing, for spectators (10-world-v1 §4.5): one `motion` and one `posture` per citizen, so
the client maps them through one table to clips, procedural poses and props and never parses labels.
"""

from typing import Literal

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
