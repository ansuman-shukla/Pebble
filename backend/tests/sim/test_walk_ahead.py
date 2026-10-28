"""The walk ahead in every tick summary: the path a walker will follow next, so clients can draw smooth motion over
a tick that lasts a whole real minute at real-time speed."""

import math
from collections.abc import Callable

import pytest

from app.observability.events import Moved, RoutePoint, TickSummary
from app.sim.actions import WALK_AHEAD_TICKS, WALK_M_PER_TICK, walk_ahead
from app.sim.clock import SECONDS_PER_TICK
from app.sim.navigation import Route, walk_along
from app.sim.simulation import Simulation
from app.sim.vec import Vec3
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec

STEP_M = 0.1
FLAT_WALK_MPS = 5000 / 3600  # 5 km/h


def _moved(sim: Simulation, citizen_id: str) -> Moved | None:
    summaries = [event.payload for event in sim.drain() if event.type == "tick_summary"]
    assert len(summaries) == 1 and isinstance(summaries[0], TickSummary)
    return summaries[0].moved.get(citizen_id)


def _length_m(sim: Simulation, route: list[RoutePoint]) -> float:
    return sum(sim.world.distance_m(a.unit, b.unit) for a, b in zip(route, route[1:], strict=False))


def _along(sim: Simulation, route: list[RoutePoint], metres: float) -> Vec3:
    """Where walking `metres` along the streamed route ends (as a client drawing the walk would)."""
    flat = Route(points=tuple(point.unit for point in route), costs=(1.0,) * (len(route) - 1))
    return walk_along(flat, 0, 0.0, metres, sim.world.radius_m).position


def _walkable_segment(sim: Simulation, a: Vec3, b: Vec3) -> bool:
    (ax, az), (bx, bz) = sim.world.town.to_local(a), sim.world.town.to_local(b)
    steps = max(1, math.ceil(math.hypot(bx - ax, bz - az) / STEP_M))
    return all(
        sim.world.town.walk.is_walkable(ax + (bx - ax) * i / steps, az + (bz - az) * i / steps)
        for i in range(steps + 1)
    )


@pytest.mark.parametrize(("age", "pace"), [(25, 1.0), (63, 0.6)])
def test_a_town_walker_streams_the_walkable_path_ahead_and_follows_it(
    new_sim: Callable[..., Simulation], age: int, pace: float
) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(age=age, knows_places=["town", "main-gate", "training-ground"]))
    WorldApi(sim, citizen.id).walk_to_place("the training ground")
    sim.drain()
    predicted: Vec3 | None = None
    walking_ticks = 0
    while citizen.action is not None:
        sim.step()
        moved = _moved(sim, citizen.id)
        assert moved is not None  # a walker always moves
        if predicted is not None:  # the last tick's route and speed told where they'd be now
            assert sim.world.distance_m(citizen.position, predicted) < 1e-6
        if citizen.action is None:  # arrived: nothing ahead
            assert (moved.route, moved.speed_mps) == ([], 0.0)
            break
        walking_ticks += 1
        route = moved.route
        assert route[0] == RoutePoint(unit=citizen.position, height_m=citizen.height_m)
        assert all(sim.world.town_point(point.unit) is not None for point in route)
        assert all(point.height_m == sim.world.town.height_m for point in route)
        assert all(_walkable_segment(sim, a.unit, b.unit) for a, b in zip(route, route[1:], strict=False))
        assert all(a.unit != b.unit for a, b in zip(route, route[1:], strict=False))  # every leg has a direction
        assert moved.speed_mps == pytest.approx(FLAT_WALK_MPS * pace)
        ahead = _length_m(sim, route)
        goal = sim.world.places["training-ground"]
        ends_at_goal = sim.world.distance_m(route[-1].unit, goal.stand) < 1e-6
        if ends_at_goal:
            assert ahead <= WALK_AHEAD_TICKS * WALK_M_PER_TICK * pace + 1e-6
        else:
            assert ahead == pytest.approx(WALK_AHEAD_TICKS * WALK_M_PER_TICK * pace, abs=1e-6)
            assert ahead > 1.5 * moved.speed_mps * SECONDS_PER_TICK  # outlasts the tick, with time to spare
        predicted = _along(sim, route, moved.speed_mps * SECONDS_PER_TICK)
    assert walking_ticks >= 2


def test_nobody_standing_still_has_a_walk_ahead(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec())
    sim.step()
    assert _moved(sim, citizen.id) is None
    assert walk_ahead(sim.core, citizen) == ([], 0.0)
    WorldApi(sim, citizen.id).rest(30)
    sim.step()
    assert walk_ahead(sim.core, citizen) == ([], 0.0)


def test_a_follower_at_the_end_of_their_route_has_nothing_ahead_until_they_replan(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(knows_places=["town", "main-gate", "training-ground"]))
    WorldApi(sim, citizen.id).walk_to_place("the training ground")
    sim.step()
    walk = citizen.action
    assert walk is not None and walk.route is not None and walk_ahead(sim.core, citizen)[0]
    walk.leg, walk.along_m = len(walk.route.costs), 0.0  # as when the person they follow moved on (goal cleared)
    assert walk_ahead(sim.core, citizen) == ([], 0.0)


def test_an_exhausted_walker_goes_at_half_pace(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(knows_places=["town", "main-gate", "training-ground"]))
    citizen.body.energy = 5.0
    sim.step()  # feeling exhausted is news once; it would stop a walk started before
    sim.drain()
    WorldApi(sim, citizen.id).walk_to_place("the training ground")
    sim.step()
    moved = _moved(sim, citizen.id)
    assert moved is not None and moved.speed_mps == pytest.approx(FLAT_WALK_MPS / 2)
    assert _length_m(sim, moved.route) == pytest.approx(WALK_AHEAD_TICKS * WALK_M_PER_TICK / 2, abs=1e-6)


def test_a_forest_walker_is_slower_and_still_lands_on_the_streamed_path(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(site="band_b_camp", at=(0.0, 20.0), home=None, knows_places=["band_b_camp"]))
    assert sim.world.town_point(citizen.position) is None and sim.world.biome(citizen.cell) == "broadleaf_forest"
    WorldApi(sim, citizen.id).walk_towards("north", "a long walk")
    sim.drain()
    predicted: Vec3 | None = None
    for _ in range(4):  # the forest around band B's camp: terrain cost 1.5 the whole way
        sim.step()
        moved = _moved(sim, citizen.id)
        assert moved is not None and citizen.action is not None
        if predicted is not None:
            assert sim.world.distance_m(citizen.position, predicted) < 1e-6
        assert moved.route[0].unit == citizen.position
        assert moved.speed_mps == pytest.approx(FLAT_WALK_MPS / 1.5)
        for point in moved.route:
            cell = sim.world.nearest_cell(point.unit, citizen.cell)
            assert sim.world.biome(cell) == "broadleaf_forest"
            assert point.height_m == pytest.approx(float(sim.world.heights[cell]))
        predicted = _along(sim, moved.route, moved.speed_mps * SECONDS_PER_TICK)
