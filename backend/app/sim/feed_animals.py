"""The animals' part of each `tick_summary`: the pose of every animal that moved, turned or changed what it does,
with the path it walked this tick and its plan ahead (10-world-v1 §4.2, the same rule as a citizen's `Moved`), how
fast and at what gait, and what it is after."""

from app.observability.events import AnimalPose, RoutePoint
from app.sim.animals import WILDLIFE, Walk, aim
from app.sim.core import SimCore
from app.sim.fauna import terrain
from app.sim.state import Animal, AnimalActivity
from app.sim.vec import Vec3

Pose = tuple[Vec3, float, AnimalActivity]  # position, heading, activity


def poses(core: SimCore) -> dict[str, Pose]:
    """Every animal's pose (taken as the tick begins, to compare with at its end)."""
    return {a.id: (a.position, a.heading_deg, a.activity) for a in core.state.animals.values()}


def changed(core: SimCore, before: dict[str, Pose]) -> dict[str, AnimalPose]:
    """Animals whose pose differs from `before` or who walked this tick, by id."""
    if not core.state.animals:
        return {}
    walks = WILDLIFE.of(core.state).walks
    return {
        animal.id: _pose(core, animal, walks.get(animal.id))
        for animal in (core.state.animals[animal_id] for animal_id in sorted(core.state.animals))
        if animal.id in walks or (animal.position, animal.heading_deg, animal.activity) != before.get(animal.id)
    }


def _pose(core: SimCore, animal: Animal, walk: Walk | None) -> AnimalPose:
    goal, target = aim(core, animal)
    return AnimalPose(
        position=animal.position,
        height_m=animal.height_m,
        cell=animal.cell,
        heading_deg=animal.heading_deg,
        activity=animal.activity,
        route=_route(core, animal, walk) if walk is not None else [],
        speed_mps=walk.speed_mps if walk is not None else 0.0,
        gait=walk.gait if walk is not None else "walk",
        goal=goal,
        target=target,
    )


def _route(core: SimCore, animal: Animal, walk: Walk) -> list[RoutePoint]:
    surface = terrain(core.world).surface_m
    cell = animal.cell
    route: list[RoutePoint] = []
    for unit, seconds in walk.points:
        cell = core.world.nearest_cell(unit, cell)
        route.append(RoutePoint(unit=unit, height_m=float(surface[cell]), t_s=round(seconds, 3)))
    return route
