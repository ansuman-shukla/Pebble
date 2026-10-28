import math

import numpy as np
import pytest

from app.sim.navigation import Planner, Route, walk_along
from app.sim.vec import Vec3, angle
from app.sim.world import SimWorld
from app.world.biomes import BIOME_IDS
from tests.sim_helpers import nearest_cell_of

GATE_PASSAGE_X = 1.3  # the main gatehouse leaves x in [-1.3, 1.3] open at z = 100
STEP_M = 0.1


def _local_route(world: SimWorld, route: Route) -> list[tuple[float, float]]:
    return [world.town.to_local(point) for point in route.points]


def _samples_inside_town(world: SimWorld, route: Route) -> list[tuple[float, float]]:
    """Points every 10 cm along every leg that lies in the town chart, in local metres."""
    samples = []
    for (ax, az), (bx, bz) in zip(_local_route(world, route), _local_route(world, route)[1:], strict=False):
        if not (world.town.contains(ax, az) and world.town.contains(bx, bz)):
            continue
        steps = max(1, math.ceil(math.hypot(bx - ax, bz - az) / STEP_M))
        samples += [(ax + (bx - ax) * i / steps, az + (bz - az) * i / steps) for i in range(steps + 1)]
    return samples


def _blocked_on_straight_line(world: SimWorld, a: tuple[float, float], b: tuple[float, float]) -> bool:
    steps = math.ceil(math.dist(a, b) / STEP_M)
    return any(
        not world.town.walk.is_walkable(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        for i in range(steps + 1)
    )


@pytest.mark.parametrize(
    ("start", "goal"),
    [
        ((0.0, 104.0), (-20.0, 52.5)),  # main gate -> well
        ((0.0, 20.0), (-104.0, 76.0)),  # inside the castle -> outside the west gate
        ((70.0, 85.0), (-70.0, -70.0)),  # storehouses -> training ground
    ],
)
def test_town_routes_never_cross_a_wall(
    sim_world: SimWorld, planner: Planner, start: tuple[float, float], goal: tuple[float, float]
) -> None:
    route = planner.plan(sim_world.town.to_unit(*start), sim_world.town.to_unit(*goal))
    assert route is not None
    samples = _samples_inside_town(sim_world, route)
    assert len(samples) > 100
    assert all(sim_world.town.walk.is_walkable(x, z) for x, z in samples)
    assert _local_route(sim_world, route)[-1] == pytest.approx(goal, abs=1e-6)


def test_a_target_straight_behind_the_wall_is_reached_through_the_gate(sim_world: SimWorld, planner: Planner) -> None:
    start, goal = (0.0, 130.0), (-50.0, 90.0)  # outside the main gate; inside the wall to the north-west
    assert _blocked_on_straight_line(sim_world, start, goal)
    route = planner.plan(sim_world.town.to_unit(*start), sim_world.town.to_unit(*goal))
    assert route is not None
    samples = _samples_inside_town(sim_world, route)
    assert all(sim_world.town.walk.is_walkable(x, z) for x, z in samples)
    crossing = [x for x, z in samples if 99.0 <= z <= 101.0]
    assert crossing and all(abs(x) < GATE_PASSAGE_X for x in crossing)
    length = sum(angle(a, b) for a, b in zip(route.points, route.points[1:], strict=False)) * sim_world.radius_m
    assert length > math.dist(start, goal) + 5  # the detour through the gate


def test_leaving_town_for_the_forest_goes_through_a_gate_and_stays_off_water(
    sim_world: SimWorld, planner: Planner
) -> None:
    start = sim_world.town.to_unit(-20.0, 52.5)
    forest = nearest_cell_of(sim_world, ("broadleaf_forest",), start)
    route = planner.plan(start, sim_world.unit(forest))
    assert route is not None
    samples = _samples_inside_town(sim_world, route)
    assert all(sim_world.town.walk.is_walkable(x, z) for x, z in samples)
    through_gate = [
        (x, z) for x, z in samples if (99 <= z <= 101 and abs(x) < 3) or (-101 <= x <= -99 and 73 <= z <= 79)
    ]
    assert through_gate
    _assert_outside_legs_on_land(sim_world, route)


def _assert_outside_legs_on_land(sim_world: SimWorld, route: Route) -> None:
    outside = [p for p in route.points if sim_world.town_point(p) is None]
    assert outside
    for point in outside[:-1]:
        cell = sim_world.nearest_cell(point)
        assert not sim_world.is_water(cell)
    cells = [sim_world.nearest_cell(p) for p in route.points[1:-1] if sim_world.town_point(p) is None]
    for a, b in zip(cells, cells[1:], strict=False):
        assert b in sim_world.neighbours[a] or a == b
    for leg_start, leg_end in zip(route.points, route.points[1:], strict=False):
        for t in np.linspace(0, 1, 9):
            point = _lerp(leg_start, leg_end, float(t))
            if sim_world.town_point(point) is None:
                assert not sim_world.is_water(sim_world.nearest_cell(point)), "a leg cuts across water"


def _lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    v = tuple((1 - t) * x + t * y for x, y in zip(a, b, strict=True))
    n = math.sqrt(sum(c * c for c in v))
    return (v[0] / n, v[1] / n, v[2] / n)


def test_long_walks_outside_avoid_water_and_are_cheapest(sim_world: SimWorld, planner: Planner) -> None:
    start = sim_world.town.to_unit(0.0, 120.0)
    camp = next(site for site in sim_world.sites if site.id == "standing_stones")
    goal_cell = planner.outer_cell_for(tuple(camp.anchor.position))  # type: ignore[arg-type]
    assert goal_cell is not None
    route = planner.plan(start, sim_world.unit(goal_cell))
    assert route is not None
    _assert_outside_legs_on_land(sim_world, route)
    # A* finds the same cost as a full Dijkstra between two outside cells
    first = planner.outer_cell_for(route.points[len(route.points) // 3])
    assert first is not None
    path = planner.outer.astar(first, goal_cell)
    assert path is not None
    cost = sum(dict(planner.outer.edges[a])[b] for a, b in zip(path, path[1:], strict=False))
    assert cost == pytest.approx(planner.outer.costs_to(first, {goal_cell})[goal_cell])


def test_forest_costs_more_than_grass(sim_world: SimWorld, planner: Planner) -> None:
    grass = int(np.flatnonzero((sim_world.biomes == BIOME_IDS["grassland"]) & ~sim_world.in_town)[0])
    forest = int(np.flatnonzero(sim_world.biomes == BIOME_IDS["broadleaf_forest"])[0])
    for cell, factor in ((grass, 1.0), (forest, 1.5)):
        for other, edge in planner.outer.edges[cell]:
            length = angle(sim_world.unit(cell), sim_world.unit(other)) * sim_world.radius_m
            assert edge == pytest.approx(length * (factor + planner.outer.cost[other]) / 2)


def test_no_route_into_the_sea_or_to_water_cells(sim_world: SimWorld, planner: Planner) -> None:
    sea = int(np.flatnonzero(sim_world.biomes == BIOME_IDS["deep_ocean"])[0])
    assert all(not planner.outer.allowed[c] for c in sim_world.neighbours[sea] if sim_world.is_water(c))
    neighbours_all_sea = all(sim_world.is_water(c) for c in sim_world.neighbours[sea])
    if neighbours_all_sea:
        assert planner.plan(sim_world.town.to_unit(0, 120), sim_world.unit(sea)) is None
    assert planner.outer.astar(sea, sea) is None


def test_walk_along_spends_the_budget_by_terrain_cost() -> None:
    a, b, c = (0.0, 0.0, 1.0), (math.sin(0.01), 0.0, math.cos(0.01)), (math.sin(0.02), 0.0, math.cos(0.02))
    route = Route(points=(a, b, c), costs=(1.0, 2.0))  # 20 m of grass then 20 m twice as hard (radius 2000)
    halfway = walk_along(route, 0, 0.0, 10.0, 2000.0)
    assert (halfway.leg, halfway.arrived) == (0, False)
    assert halfway.along_m == pytest.approx(10.0)
    into_hard = walk_along(route, 0, 0.0, 30.0, 2000.0)
    assert into_hard.leg == 1
    assert into_hard.along_m == pytest.approx(5.0)
    assert angle(a, into_hard.position) * 2000 == pytest.approx(25.0)
    done = walk_along(route, 0, 0.0, 61.0, 2000.0)
    assert done.arrived and done.position == c and done.cost_spent == pytest.approx(60.0)
    with pytest.raises(ValueError):
        Route(points=(a, b), costs=())
