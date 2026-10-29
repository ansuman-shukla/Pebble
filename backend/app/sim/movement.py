"""Moving about (03): walk_to, follow and flee start here and advance each tick along their planned route, at the
walker's pace; each step leaves a stride (where they went and where they go next) for spectators to draw.
"""

from app.observability.events import RoutePoint
from app.sim.acting import VERB, begin, settled
from app.sim.clock import SECONDS_PER_TICK
from app.sim.core import WALK_AHEAD_TICKS, SimCore, Stride, TimedPoint
from app.sim.destinations import beside, resolve
from app.sim.fauna import SPECIES
from app.sim.navigation import WalkProgress, walk_along
from app.sim.perception import match_person, nearest_danger, person_label
from app.sim.state import ActionState, Citizen
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.world_api.models import Flee, Follow, WalkTo

WALK_M_PER_TICK = 5000 / 60  # 5 km/h on flat ground
EXHAUSTED_PACE = 0.5
ARRIVE_M = 2.0  # close enough to a person
SAME_SPOT_M = 0.001  # spots on a streamed route closer than this are one spot
FOLLOW_REPLAN_M = 3.0
FLEE_M = 150.0  # flee() runs this far from the danger
FLEE_PACE = 1.6  # running
FLEE_TURNS = (0.0, 45.0, -45.0, 90.0, -90.0, 135.0, -135.0)


def start_walk(core: SimCore, citizen: Citizen, action: WalkTo) -> int:
    target = action.target
    resolved = resolve(core, citizen, target)
    if isinstance(resolved, str):
        return settled(core, citizen, "walk_to", "failed", resolved)
    if resolved.person_id is None and core.distance_m(citizen.position, resolved.goal) < 1.0:
        return settled(core, citizen, "walk_to", "done", "You are already there.")
    if resolved.person_id is not None and core.distance_m(citizen.position, resolved.goal) <= ARRIVE_M:
        return settled(core, citizen, "walk_to", "done", f"You are already beside {resolved.words}.")
    route = core.planner.plan(citizen.position, resolved.goal, citizen.cell)
    if route is None:
        return settled(core, citizen, "walk_to", "failed", "You can't find a way there.")
    walk = begin(
        core,
        citizen,
        "walk_to",
        resolved.shown,
        {"target": target.kind, "arrive": resolved.arrive},
        destination=resolved.words,
    )
    walk.route, walk.goal, walk.target_id = route, resolved.goal, resolved.person_id
    return walk.number


def start_follow(core: SimCore, citizen: Citizen, action: Follow) -> int:
    """Walk after someone in view until they stop (03 follow); the route is planned as they go."""
    person = match_person(core, citizen, action.person)
    if person is None:
        return settled(core, citizen, "follow", "failed", "You don't see anyone like that.")
    follow = begin(
        core, citizen, "follow", person.name, {"target": "person"}, destination=person_label(citizen, person)
    )
    follow.target_id = person.id
    return follow.number


def start_flee(core: SimCore, citizen: Citizen, _action: Flee) -> int:
    """Run away from the nearest danger in view (03 flee), turning aside if water or walls are in the way."""
    danger = nearest_danger(core, citizen)
    if danger is None:
        return settled(core, citizen, "flee", "failed", "You see nothing to run from.")
    animal, _ = danger
    away = bearing_deg(animal.position, citizen.position)
    for turn in FLEE_TURNS:
        goal = step_towards(citizen.position, (away + turn) % 360.0, FLEE_M, core.world.radius_m)
        town = core.world.town_point(goal)
        walkable = (
            core.world.town.walk.is_walkable(*town)
            if town is not None
            else core.planner.outer.allowed[core.world.nearest_cell(goal, citizen.cell)]
        )
        route = core.planner.plan(citizen.position, goal, citizen.cell) if walkable else None
        if route is not None:
            label = f"away from {SPECIES[animal.kind].one}"
            flee = begin(core, citizen, "flee", label, {"arrive": "You run until you feel safer."}, destination=label)
            flee.route, flee.goal = route, goal
            return flee.number
    return settled(core, citizen, "flee", "failed", "There's nowhere to run.")


def advance_walk(core: SimCore, citizen: Citizen, walk: ActionState) -> None:
    if walk.target_id is not None:
        person = core.state.citizens[walk.target_id]
        distance = core.distance_m(citizen.position, person.position)
        if not person.body.alive or distance > core.sight_range(citizen):
            text = f"You stop {VERB[walk.kind]}: you lose sight of {walk.destination}."
            core.end_action(citizen, "interrupted", text)
            return
        if distance <= ARRIVE_M:
            beside(core, citizen, walk, person)
            return
        if walk.goal is None or core.distance_m(person.position, walk.goal) > FOLLOW_REPLAN_M:
            route = core.planner.plan(citizen.position, person.position, citizen.cell)
            if route is None:
                core.end_action(
                    citizen, "interrupted", f"You stop walking: you can't find a way to {walk.destination}."
                )
                return
            walk.route, walk.goal, walk.leg, walk.along_m = route, person.position, 0, 0.0
    if walk.route is None:
        raise ValueError(f"walk {walk.number} of {citizen.id} has no route")
    budget = WALK_M_PER_TICK * walk_pace(citizen)
    progress = walk_along(walk.route, walk.leg, walk.along_m, budget, core.world.radius_m)
    core.strides[citizen.id] = _walk_stride(core, citizen, walk, progress, budget)
    walk.leg, walk.along_m = progress.leg, progress.along_m
    core.place_at(citizen, progress.position)
    if not progress.arrived:
        return
    if walk.target_id is not None:
        person = core.state.citizens[walk.target_id]
        if core.distance_m(citizen.position, person.position) <= ARRIVE_M:
            beside(core, citizen, walk, person)
        else:
            walk.goal = None  # they moved on: plan again next tick
        return
    arrive = str(walk.args["arrive"])
    if arrive.startswith("rough:"):
        place = core.world.places[arrive.removeprefix("rough:")]
        if core.distance_m(citizen.position, place.centre) <= place.radius_m:
            arrive = f"You arrive at {place.name}."
        else:
            arrive = f"You reach about where {place.name} should be, but you don't find it."
    core.end_action(citizen, "done", arrive)


def walk_pace(citizen: Citizen) -> float:
    """Walking cost budget per tick as a share of WALK_M_PER_TICK (age, halved when exhausted, ×1.6 fleeing)."""
    fleeing = citizen.action is not None and citizen.action.kind == "flee"
    return (
        citizen.traits.speed * (EXHAUSTED_PACE if citizen.body.energy <= 10 else 1.0) * (FLEE_PACE if fleeing else 1.0)
    )


def _walk_stride(core: SimCore, citizen: Citizen, walk: ActionState, step: WalkProgress, budget: float) -> Stride:
    """This tick's step along the route (from where the walker stands to `step`) and the next WALK_AHEAD_TICKS of
    it, timed by the cost spent: the route's own corners, so the path between them is as walkable as the route (in
    town: grid corners, no corner cutting)."""
    if walk.route is None:
        raise ValueError(f"walk {walk.number} of {citizen.id} has no route")
    seconds = SECONDS_PER_TICK / budget  # game seconds per unit of walking cost
    walked = [(citizen.position, 0.0), *((unit, cost * seconds) for unit, cost in step.corners)]
    walked.append((step.position, step.cost_spent * seconds))
    on = walk_along(walk.route, step.leg, step.along_m, WALK_AHEAD_TICKS * budget, core.world.radius_m)
    ahead = [(unit, SECONDS_PER_TICK + cost * seconds) for unit, cost in on.corners]
    ahead.append((on.position, SECONDS_PER_TICK + on.cost_spent * seconds))
    return Stride(walk.number, _distinct(core, walked), _distinct(core, ahead, after=step.position))


def _distinct(core: SimCore, points: list[TimedPoint], after: Vec3 | None = None) -> tuple[TimedPoint, ...]:
    """The points without repeats of the spot just before (every leg drawn has a direction): a walk that stopped a
    hair short of a corner (float rounding) goes on from there, not on a leg of a few nanometres."""
    kept: list[TimedPoint] = []
    for point in points:
        last = kept[-1][0] if kept else after
        if last is None or core.distance_m(point[0], last) >= SAME_SPOT_M:
            kept.append(point)
    return tuple(kept)


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
