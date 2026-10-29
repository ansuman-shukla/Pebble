"""The animals' part of each `tick_summary`: the pose of every animal that moved, turned or changed what it does."""

from app.observability.events import AnimalPose
from app.sim.core import SimCore
from app.sim.state import Animal, AnimalActivity
from app.sim.vec import Vec3

Pose = tuple[Vec3, float, AnimalActivity]  # position, heading, activity


def poses(core: SimCore) -> dict[str, Pose]:
    """Every living animal's pose (taken as the tick begins, to compare with at its end)."""
    return {a.id: (a.position, a.heading_deg, a.activity) for a in core.state.animals.values() if a.alive}


def changed(core: SimCore, before: dict[str, Pose]) -> dict[str, AnimalPose]:
    """Animals whose pose differs from `before`, by id."""
    return {
        animal.id: _pose(animal)
        for animal in (core.state.animals[animal_id] for animal_id in sorted(core.state.animals))
        if (animal.alive or animal.id in before)  # one that died this tick may have moved first
        and (animal.position, animal.heading_deg, animal.activity) != before.get(animal.id)
    }


def _pose(animal: Animal) -> AnimalPose:
    return AnimalPose(
        position=animal.position,
        height_m=animal.height_m,
        cell=animal.cell,
        heading_deg=animal.heading_deg,
        activity=animal.activity,
    )
