"""The route in every tick summary: how a mover is drawn over the next tick. It starts where they stood when the tick
began (where spectators drew them), passes through where they are now (timed in game seconds from the tick's start)
and carries on along their plan, so the whole move is drawn as walking and the next tick picks up where it ended."""

import math
from collections.abc import Callable

import pytest

from app.observability.events import Moved, RoutePoint, TickSummary
from app.sim import wild
from app.sim.clock import SECONDS_PER_TICK
from app.sim.core import WALK_AHEAD_TICKS
from app.sim.feed_citizens import streamed_route
from app.sim.navigation import Route
from app.sim.simulation import Simulation
from app.sim.vec import Vec3, step_towards
from app.world_api.facade import WorldApi
from tests.sim_helpers import add_animal, drawn_on, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

STEP_M = 0.1
FLAT_WALK_MPS = 1.4  # an adult walking on flat open ground by day (bodies.yaml)
WALK_M_PER_TICK = FLAT_WALK_MPS * SECONDS_PER_TICK
DRAWN_M = 0.01  # how close the drawn spot must be to the simulated one


def _moved(sim: Simulation, citizen_id: str) -> Moved | None:
    summaries = [event.payload for event in sim.drain() if event.type == "tick_summary"]
    assert len(summaries) == 1 and isinstance(summaries[0], TickSummary)
    return summaries[0].moved.get(citizen_id)


def _seconds(route: list[RoutePoint]) -> list[float]:
    times = [point.t_s for point in route]
    assert all(t is not None for t in times)
    return [float(t) for t in times if t is not None]


def _speeds(sim: Simulation, route: list[RoutePoint]) -> list[float]:
    """Ground speed on each leg (metres per game second)."""
    times = _seconds(route)
    return [
        sim.world.distance_m(a.unit, b.unit) / (tb - ta)
        for a, b, ta, tb in zip(route, route[1:], times, times[1:], strict=False)
    ]


def _walkable_segment(sim: Simulation, a: Vec3, b: Vec3) -> bool:
    (ax, az), (bx, bz) = sim.world.town.to_local(a), sim.world.town.to_local(b)
    steps = max(1, math.ceil(math.hypot(bx - ax, bz - az) / STEP_M))
    return all(
        sim.world.town.walk.is_walkable(ax + (bx - ax) * i / steps, az + (bz - az) * i / steps)
        for i in range(steps + 1)
    )


def _starts_where_they_stood(sim: Simulation, moved: Moved, before: Vec3) -> None:
    first = moved.route[0]
    assert first.unit == before and first.t_s == 0.0
    cell = sim.world.nearest_cell(before)
    assert first.height_m == pytest.approx(sim.world.ground_height(before, cell))


@pytest.mark.parametrize(("age", "pace"), [(25, 1.0), (63, 0.6)])
def test_a_town_walker_streams_each_step_from_where_they_stood_and_the_walkable_path_ahead(
    new_sim: Callable[..., Simulation], age: int, pace: float
) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(age=age, knows_places=["town", "main-gate", "training-ground"]))
    WorldApi(sim, citizen.id).walk_to_place("the training ground")
    sim.drain()
    goal = sim.world.places["training-ground"].stand
    walking_ticks = 0
    while citizen.action is not None:
        before = citizen.position
        sim.step()
        moved = _moved(sim, citizen.id)
        assert moved is not None  # a walker always moves
        route, times = moved.route, _seconds(moved.route)
        _starts_where_they_stood(sim, moved, before)
        assert all(sim.world.town_point(point.unit) is not None for point in route)
        assert all(point.height_m == sim.world.town.height_m for point in route)
        assert all(_walkable_segment(sim, a.unit, b.unit) for a, b in zip(route, route[1:], strict=False))
        assert all(a.unit != b.unit for a, b in zip(route, route[1:], strict=False))  # every leg has a direction
        assert all(a < b for a, b in zip(times, times[1:], strict=False))
        assert _speeds(sim, route) == pytest.approx([FLAT_WALK_MPS * pace] * (len(route) - 1))
        assert moved.speed_mps == pytest.approx(FLAT_WALK_MPS * pace)
        if citizen.action is None:  # arrived during the step: drawn walking up to the goal, nothing beyond
            assert route[-1].unit == goal == citizen.position and times[-1] <= SECONDS_PER_TICK
            break
        walking_ticks += 1
        # the step ends where they are a tick after it began; the plan goes on for WALK_AHEAD_TICKS
        assert sim.world.distance_m(drawn_on(route, SECONDS_PER_TICK), citizen.position) < DRAWN_M
        assert any(point.unit == citizen.position and point.t_s == pytest.approx(SECONDS_PER_TICK) for point in route)
        if route[-1].unit != goal:
            assert times[-1] == pytest.approx((1 + WALK_AHEAD_TICKS) * SECONDS_PER_TICK)
    assert walking_ticks >= 2


def test_a_walk_shorter_than_a_tick_is_drawn_walking_all_the_way(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec())
    WorldApi(sim, citizen.id).walk_towards("south", "a few steps")
    walk = citizen.action
    assert walk is not None and walk.goal is not None
    goal, before = walk.goal, citizen.position
    sim.drain()
    sim.step()
    moved = _moved(sim, citizen.id)
    assert citizen.action is None and citizen.position == goal  # there within the tick
    assert moved is not None
    _starts_where_they_stood(sim, moved, before)
    times = _seconds(moved.route)
    assert moved.route[-1].unit == goal
    length = sum(sim.world.distance_m(a.unit, b.unit) for a, b in zip(moved.route, moved.route[1:], strict=False))
    assert length > 10.0
    assert times[-1] == pytest.approx(length / FLAT_WALK_MPS)  # at walking pace, then standing for the rest
    assert moved.speed_mps == pytest.approx(FLAT_WALK_MPS)


def test_a_walker_who_collapses_mid_walk_is_streamed_only_up_to_where_they_fell(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(knows_places=["town", "main-gate", "training-ground"]))
    WorldApi(sim, citizen.id).walk_to_place("the training ground")
    sim.step()
    sim.drain()
    citizen.body.energy = 0.0
    before = citizen.position
    sim.step()
    moved = _moved(sim, citizen.id)
    assert citizen.action is not None and citizen.action.collapsed  # asleep where the step ended
    assert moved is not None
    _starts_where_they_stood(sim, moved, before)
    assert moved.route[-1].unit == citizen.position
    assert _seconds(moved.route)[-1] == pytest.approx(SECONDS_PER_TICK)  # nothing of the walk's plan beyond


def test_a_hair_of_a_move_is_one_spot(new_sim: Callable[..., Simulation]) -> None:
    """A walk that stopped a few nanometres short of a corner (float rounding) goes on from there: no leg of a few
    nanometres (drawn as a sprint for a frame), and a walk that ends with such a hair is drawn standing."""
    sim = without_animals(new_sim())
    citizen = sim.add_citizen(make_spec(home=None))
    put_in_the_wild(sim, citizen.id, wild_cell(sim))
    skip_to(sim, citizen.position, night=False)  # walking at the day pace
    radius = sim.world.radius_m
    WorldApi(sim, citizen.id).walk_towards("north", "a long walk")
    walk = citizen.action
    assert walk is not None
    corner = step_towards(citizen.position, 0.0, 30.0, radius)
    end = step_towards(corner, 90.0, 200.0, radius)
    walk.route, walk.leg, walk.along_m = Route(points=(citizen.position, corner, end), costs=(1.0, 1.0)), 0, 0.0
    walk.along_m = sim.world.distance_m(citizen.position, corner) - 1e-9
    sim.core.place_at(citizen, step_towards(corner, 180.0, 1e-9, radius))
    before = citizen.position
    sim.drain()
    sim.step()
    moved = _moved(sim, citizen.id)
    assert moved is not None
    _starts_where_they_stood(sim, moved, before)
    assert all(
        sim.world.distance_m(a.unit, b.unit) >= 0.001 for a, b in zip(moved.route, moved.route[1:], strict=False)
    )
    assert _speeds(sim, moved.route) == pytest.approx([FLAT_WALK_MPS] * (len(moved.route) - 1))
    assert moved.speed_mps == pytest.approx(FLAT_WALK_MPS)
    # the last hair of a walk
    walk.route, walk.leg = Route(points=(citizen.position, corner), costs=(1.0,)), 0
    walk.along_m = sim.world.distance_m(citizen.position, corner) - 1e-9
    sim.core.place_at(citizen, step_towards(corner, 180.0, 1e-9, radius))
    sim.drain()
    sim.step()
    moved = _moved(sim, citizen.id)
    assert citizen.action is None and citizen.position == corner
    assert moved is not None and moved.route == [] and moved.speed_mps == 0.0


def test_nobody_standing_still_is_streamed(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec())
    sim.step()
    assert _moved(sim, citizen.id) is None
    WorldApi(sim, citizen.id).walk_towards("south", "a few steps")
    sim.step()
    assert _moved(sim, citizen.id) is not None
    WorldApi(sim, citizen.id).rest(30)
    sim.step()
    assert _moved(sim, citizen.id) is None
    with pytest.raises(ValueError, match="moved without a stride"):  # last tick's walk is no move of this one
        streamed_route(sim.core, citizen)


def test_the_times_follow_each_legs_walking_cost(new_sim: Callable[..., Simulation]) -> None:
    """Grass then forest: the drawn walker slows down where the sim does and is where the sim says a tick later."""
    sim = without_animals(new_sim())
    citizen = sim.add_citizen(make_spec(home=None))
    put_in_the_wild(sim, citizen.id, wild_cell(sim))
    skip_to(sim, citizen.position, night=False)  # walking at the day pace
    WorldApi(sim, citizen.id).walk_towards("north", "a long walk")
    walk = citizen.action
    assert walk is not None
    radius = sim.world.radius_m
    corner = step_towards(citizen.position, 0.0, 30.0, radius)
    end = step_towards(corner, 0.0, 60.0, radius)
    walk.route, walk.leg, walk.along_m = Route(points=(citizen.position, corner, end), costs=(1.0, 2.0)), 0, 0.0
    sim.drain()
    sim.step()
    moved = _moved(sim, citizen.id)
    assert moved is not None
    seconds_per_cost = SECONDS_PER_TICK / WALK_M_PER_TICK
    at_corner = next(point for point in moved.route if point.unit == corner)
    assert at_corner.t_s == pytest.approx(30.0 * seconds_per_cost)
    assert _speeds(sim, moved.route)[0] == pytest.approx(FLAT_WALK_MPS)
    assert _speeds(sim, moved.route)[-1] == pytest.approx(FLAT_WALK_MPS / 2)
    assert moved.speed_mps == pytest.approx(FLAT_WALK_MPS)  # where the route starts: on the grass
    assert sim.world.distance_m(drawn_on(moved.route, SECONDS_PER_TICK), citizen.position) < DRAWN_M
    # the rest of the forest leg (60 m at cost 2, less what the step walked) and nothing past the route's end
    walked_m = 30.0 + (WALK_M_PER_TICK - 30.0) / 2.0
    assert moved.route[-1].unit == end
    assert moved.route[-1].t_s == pytest.approx(SECONDS_PER_TICK + (90.0 - walked_m) * 2.0 * seconds_per_cost)


def _hunter(new_sim: Callable[..., Simulation], deer_m: float, age: int = 25) -> tuple[Simulation, WorldApi, Vec3]:
    sim = without_animals(new_sim())
    spec = make_spec("hunter", age=age, home=None, skills=["hunting"], inventory={"spear": 1})
    citizen = sim.add_citizen(spec)
    put_in_the_wild(sim, citizen.id, wild_cell(sim))
    skip_to(sim, citizen.position, night=False)
    deer = step_towards(citizen.position, 90.0, deer_m, sim.world.radius_m)
    add_animal(sim, "deer", deer, activity="grazing", until=10**9)
    sim.drain()
    return sim, WorldApi(sim, citizen.id), deer


@pytest.mark.parametrize(("age", "pace"), [(25, 1.0), (63, 0.6)])
def test_a_hunter_creeping_up_is_streamed_at_the_stalking_pace(
    new_sim: Callable[..., Simulation], age: int, pace: float
) -> None:
    sim, api, deer = _hunter(new_sim, 140.0, age)
    hunter = sim.citizen("hunter")
    api.hunt("the deer")
    before = hunter.position
    sim.step()
    moved = _moved(sim, "hunter")
    assert moved is not None and hunter.action is not None
    _starts_where_they_stood(sim, moved, before)
    stalk_mps = wild.STALK_PACE_M * pace / SECONDS_PER_TICK
    # (the sim creeps along the chord towards the deer: a few cm short of the arc's length)
    assert moved.speed_mps == pytest.approx(stalk_mps, rel=1e-3)
    assert _speeds(sim, moved.route) == pytest.approx([stalk_mps] * (len(moved.route) - 1), rel=1e-3)
    assert moved.route[1].unit == hunter.position
    assert moved.route[1].t_s == SECONDS_PER_TICK
    # on towards the deer for two more minutes, stopping short of where they'd strike from
    left = sim.world.distance_m(moved.route[-1].unit, deer)
    assert left == pytest.approx(max(wild.HUNT_STRIKE_M * 0.8, 140.0 - 3 * wild.STALK_PACE_M * pace), abs=0.1)
    assert sim.world.distance_m(drawn_on(moved.route, SECONDS_PER_TICK), hunter.position) < DRAWN_M


def test_a_hunter_who_strikes_is_streamed_only_up_to_the_strike(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 62 m off: a minute's creep (48 m) brings the deer within the strike (15 m), short of the usual 12 m stop
    sim, api, _ = _hunter(new_sim, 62.0)
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 1.0)
    hunter = sim.citizen("hunter")
    api.hunt("the deer")
    before = hunter.position
    sim.step()
    moved = _moved(sim, "hunter")
    assert moved is not None and hunter.action is None  # struck this tick: no plan left to draw
    assert [point.unit for point in moved.route] == [before, hunter.position]
    assert _seconds(moved.route) == [0.0, SECONDS_PER_TICK]


def test_a_short_creep_into_the_strike_is_timed_at_the_stalking_pace(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 40 m off: 28 m of creeping (to 12 m off) brings the deer within the strike in a little over half a minute
    sim, api, _ = _hunter(new_sim, 40.0)
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 1.0)
    hunter = sim.citizen("hunter")
    api.hunt("the deer")
    before = hunter.position
    sim.step()
    moved = _moved(sim, "hunter")
    assert moved is not None and hunter.action is None
    assert [point.unit for point in moved.route] == [before, hunter.position]
    creep_m = 40.0 - wild.HUNT_STRIKE_M * 0.8
    assert _seconds(moved.route) == pytest.approx([0.0, creep_m / wild.STALK_PACE_M * SECONDS_PER_TICK])
    assert moved.speed_mps == pytest.approx(wild.STALK_PACE_M / SECONDS_PER_TICK, rel=1e-3)
