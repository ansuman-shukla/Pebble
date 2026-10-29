"""The citizens' part of each `tick_summary`: how every citizen who moved is drawn, and every living body."""

from app.observability.events import Moved, RoutePoint
from app.sim.core import SimCore
from app.sim.state import Citizen
from app.sim.vec import Vec3

BodyNumbers = tuple[float, float, float, float]  # hunger, thirst, energy, health


def moves(core: SimCore, before: dict[str, Vec3]) -> dict[str, Moved]:
    """Citizens alive when the tick began who stand somewhere else now (`before`: where they stood then)."""
    moved: dict[str, Moved] = {}
    for citizen in core.citizens():
        if citizen.id in before and citizen.position != before[citizen.id]:
            route, speed_mps = streamed_route(core, citizen)
            moved[citizen.id] = Moved(
                position=citizen.position,
                height_m=citizen.height_m,
                cell=citizen.cell,
                heading_deg=citizen.heading_deg,
                route=route,
                speed_mps=speed_mps,
                gait=core.strides[citizen.id].gait,
            )
    return moved


def bodies(core: SimCore) -> dict[str, BodyNumbers]:
    return {
        citizen.id: (citizen.body.hunger, citizen.body.thirst, citizen.body.energy, citizen.body.health)
        for citizen in core.living()
    }


def streamed_route(core: SimCore, citizen: Citizen) -> tuple[list[RoutePoint], float]:
    """How a citizen who moved this tick is drawn: the path from where they stood when the tick began, through
    where they are now, on along their plan while they keep at it, timed in game seconds from the tick's start;
    and their ground speed where it starts (metres per game second)."""
    stride = core.strides.get(citizen.id)
    if stride is None:
        raise ValueError(f"{citizen.id} moved without a stride")
    if len(stride.walked) < 2:  # moved less than a millimetre: drawn standing
        return [], 0.0
    going_on = citizen.action is not None and citizen.action.number == stride.action
    world, cell = core.world, citizen.cell
    points: list[RoutePoint] = []
    for unit, seconds in (*stride.walked, *(stride.ahead if going_on else ())):
        cell = world.nearest_cell(unit, cell)
        points.append(RoutePoint(unit=unit, height_m=world.ground_height(unit, cell), t_s=seconds))
    (start, began), (then, reached) = stride.walked[0], stride.walked[1]
    return points, world.distance_m(start, then) / (reached - began)
