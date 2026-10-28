"""Who a brain is living as: the identity a mind would get in its prompt (name, role, region, home ground)."""

from dataclasses import dataclass
from typing import Literal

Routine = Literal[
    "lord",
    "samurai",
    "merchant",
    "farmer",
    "weaver",
    "town_child",
    "townsperson",
    "band_leader",
    "healer",
    "hunter",
    "gatherer",
    "band_child",
]
ROLE_ROUTINES: tuple[tuple[str, Routine], ...] = (  # first keyword found in the role picks the routine
    ("lord", "lord"),
    ("samurai", "samurai"),
    ("merchant", "merchant"),
    ("weaver", "weaver"),
    ("farmer's child", "town_child"),
    ("farmer", "farmer"),
    ("leader", "band_leader"),
    ("healer", "healer"),
    ("hunter", "hunter"),
)


@dataclass(frozen=True)
class BrainProfile:
    citizen_id: str
    name: str
    role: str
    region: Literal["town", "band_a", "band_b"]
    home_area: str  # the name of their home ground as they know it ("The castle town", "Band A camp")

    @property
    def routine(self) -> Routine:
        role = self.role.lower()
        found = next((routine for word, routine in ROLE_ROUTINES if word in role), None)
        if found is not None:
            return found
        if self.region == "town":
            return "town_child" if "child" in role else "townsperson"
        return "band_child" if "child" in role else "gatherer"
