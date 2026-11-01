"""Moving about (03): walk_to, follow and flee start here and advance each tick along their planned route, at the
walker's ground speed (`locomotion.py`: gait × age × load × health × energy × night, over legs that cost at least 1
per metre); each step leaves a stride (where they went, where they go next and the gait) for spectators to draw.

A walk goes at its `pace` (walk, or run), a flee always runs. Running lasts while the run endurance does (the
`running` system: seconds of run left per citizen, a minute spent by each minute of running, held while jogging,
coming back at half speed otherwise), then the runner jogs; children, elders and heavy loads jog at most.

Someone held (`custody`) is led along their seizer's steps to a free spot about a metre behind them, and a seizer
leading someone walks at 0.8× their pace.
"""

from typing import cast

from pydantic import JsonValue

from app.sim import custody, slots
from app.sim.acting import VERB, begin, capital, settled
from app.sim.clock import SECONDS_PER_TICK
from app.sim.core import WALK_AHEAD_TICKS, SimCore, Stride, TimedPoint
from app.sim.destinations import beside, resolve
from app.sim.fauna import SPECIES
from app.sim.ground_speed import ground_mps, load_share
from app.sim.locomotion import Gait, gait_for, load_bodies, top_gait
from app.sim.navigation import WalkProgress, walk_along
from app.sim.perception import match_person, nearest_danger, person_label
from app.sim.state import ActionState, Citizen, System
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.world_api.models import Flee, Follow, Pace, WalkTo

ARRIVE_M = 2.0  # close enough to a person
SAME_SPOT_M = 0.001  # spots on a streamed route closer than this are one spot
FOLLOW_REPLAN_M = 3.0
FLEE_M = 150.0  # flee() runs this far from the danger
FLEE_TURNS = (0.0, 45.0, -45.0, 90.0, -90.0, 135.0, -135.0)
LEAD_PACE = 0.8  # a seizer leading someone walks at this share of their pace (10 §3.4)
LEAD_RADII_M = (1.0, 1.5, 2.0, 2.5)  # the held walk this far behind their seizer, the first free one
LEAD_CLOSE_M = 1.5  # a held person this close to a seizer standing still stays where they are


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
        {"target": target.kind, "arrive": resolved.arrive, "pace": action.pace},
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
        core,
        citizen,
        "follow",
        person.name,
        {"target": "person", "pace": action.pace},
        destination=person_label(citizen, person),
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
            arrive = "You run until you feel safer."
            flee = begin(core, citizen, "flee", label, {"arrive": arrive, "pace": "run"}, destination=label)
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
        if walk.kind == "follow" and person.body.asleep:  # stopped for good, maybe behind a door: no waiting there
            core.end_action(citizen, "done", f"{capital(walk.destination)} lies down to sleep.")
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
    gait = walk_gait(core, citizen, walk)
    budget = ground_mps(core, citizen, gait) * SECONDS_PER_TICK  # metres of flat ground this minute
    if custody.leading(core, citizen.id) is not None:
        budget *= LEAD_PACE
    progress = walk_along(walk.route, walk.leg, walk.along_m, budget, core.world.radius_m)
    core.strides[citizen.id] = _walk_stride(core, citizen, walk, progress, budget, gait)
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


def walk_gait(core: SimCore, citizen: Citizen, walk: ActionState) -> Gait:
    """How the walker goes this minute: at its pace, a run turning to a jog once the endurance is spent."""
    pace = cast(Pace, walk.args.get("pace", "walk"))
    return gait_for(pace, top_gait(citizen, load_share(core, citizen)), run_left_s(core, citizen))


def lead_held(core: SimCore) -> None:
    """Tick-end hook (after slots settle): everyone held follows their seizer's step this minute to the first free spot
    of LEAD_RADII_M behind them (right behind, a metre off, when none is free: never left out of reach), drawn
    walking at the seizer's times; next to a seizer standing still they stay put. The spot is claimed (a ring spot),
    so nobody is stepped aside onto it."""
    for person_id, keeper_id in custody.held_pairs(core):
        held, keeper = core.state.citizens[person_id], core.state.citizens[keeper_id]
        stride = core.strides.get(keeper.id)
        walked = stride.walked if stride is not None else ()
        if len(walked) < 2 and core.distance_m(held.position, keeper.position) <= LEAD_CLOSE_M:
            continue
        behind = walked[-2][0] if len(walked) >= 2 else held.position
        bearing = bearing_deg(keeper.position, behind)
        spot = next(
            (s for r in LEAD_RADII_M if (s := slots.free_round(core, held, keeper.position, r, bearing)) is not None),
            step_towards(keeper.position, bearing, LEAD_RADII_M[0], core.world.radius_m),  # crowded: right behind
        )
        if core.distance_m(held.position, spot) < SAME_SPOT_M:
            continue
        end_s = (
            walked[-1][1] if len(walked) >= 2 else core.distance_m(held.position, spot) / ground_mps(core, held, "walk")
        )
        path = [(held.position, 0.0), *walked[1:-1], (spot, max(end_s, slots.MIN_STEP_S))]
        number = held.action.number if held.action is not None else 0
        core.strides[held.id] = Stride(number, _distinct(core, path))
        core.place_at(held, spot)
        slots.claim(core, held, None, spot)


def _dump_running(left: dict[str, float]) -> JsonValue:
    return dict(sorted(left.items()))


def _load_running(data: JsonValue) -> dict[str, float]:
    if not isinstance(data, dict):
        raise ValueError("the running block is a map of citizen ids to seconds")
    return {citizen: float(cast(float, seconds)) for citizen, seconds in data.items()}


# Seconds of running each citizen has left (absent: rested, the full endurance).
RUNNING: System[dict[str, float]] = System(
    name="running", version=1, new=lambda _world: {}, dump=_dump_running, load=_load_running
)


def run_left_s(core: SimCore, citizen: Citizen) -> float:
    return RUNNING.of(core.state).get(citizen.id, load_bodies().run.endurance_s)


def catch_breath(core: SimCore) -> None:
    """Every tick: a minute of running spends a minute of the run endurance, a minute of jogging keeps it as it is,
    any other minute (walking, standing, sleeping...) brings some back."""
    spec = load_bodies().run
    left = RUNNING.of(core.state)
    for citizen in core.citizens():
        stride = core.strides.get(citizen.id)
        gait = stride.gait if stride is not None else None
        now = left.get(citizen.id, spec.endurance_s)
        if gait == "run":
            now = max(0.0, now - SECONDS_PER_TICK)
        elif gait != "jog":
            now = min(spec.endurance_s, now + spec.recover_s_per_s * SECONDS_PER_TICK)
        if now < spec.endurance_s and citizen.body.alive:
            left[citizen.id] = now
        else:
            left.pop(citizen.id, None)


def ran(core: SimCore, citizen: Citizen) -> bool:
    """The citizen ran this minute (running costs energy and makes thirsty faster)."""
    stride = core.strides.get(citizen.id)
    return stride is not None and stride.gait == "run"


def _walk_stride(
    core: SimCore, citizen: Citizen, walk: ActionState, step: WalkProgress, budget: float, gait: Gait
) -> Stride:
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
    return Stride(walk.number, _distinct(core, walked), _distinct(core, ahead, after=step.position), gait)


def _distinct(core: SimCore, points: list[TimedPoint], after: Vec3 | None = None) -> tuple[TimedPoint, ...]:
    """The points without repeats of the spot just before (every leg drawn has a direction): a walk that stopped a
    hair short of a corner (float rounding) goes on from there, not on a leg of a few nanometres."""
    kept: list[TimedPoint] = []
    for point in points:
        last = kept[-1][0] if kept else after
        if last is None or core.distance_m(point[0], last) >= SAME_SPOT_M:
            kept.append(point)
    return tuple(kept)
