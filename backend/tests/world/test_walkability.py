from collections.abc import Mapping

import pytest

from app.world.geometry import Point, Rect, polygon_bounds
from app.world.town import Extent, KindSpec, TownPlacement, TownView, TownWater, load_kinds, load_town
from app.world.walkability import (
    Obstacles,
    Reach,
    WalkGrid,
    build_walk_grid,
    town_obstacles,
    town_walk_grid,
)

BUILDINGS = {
    "townhouse",
    "farmhouse",
    "storehouse",
    "temple_hall",
    "teahouse",
    "pagoda",
    "bell_tower",
    "castle_keep",
    "lookout_tower",
}
MOAT_UNDER_BRIDGE = (0.0, 34.0)
MOAT_BESIDE_BRIDGE = (10.0, 34.0)
TOWN_GATES = ("main-gate", "west-gate")


@pytest.fixture(scope="module")
def town() -> TownView:
    return load_town()


@pytest.fixture(scope="module")
def kinds() -> Mapping[str, KindSpec]:
    return load_kinds()


@pytest.fixture(scope="module")
def grid(town: TownView, kinds: Mapping[str, KindSpec]) -> WalkGrid:
    return town_walk_grid(town, kinds)


@pytest.fixture(scope="module")
def reach(town: TownView, grid: WalkGrid) -> Reach:
    return grid.reachable_from(town.spawn.x, town.spawn.z)


def by_id(town: TownView, placement_id: str) -> TownPlacement:
    return next(placement for placement in town.placements if placement.id == placement_id)


def keep_front(town: TownView) -> Point:
    return by_id(town, "castle-keep").front()


def well_front(town: TownView) -> Point:
    return by_id(town, "well").front()


def without_kind(town: TownView, kind: str) -> TownView:
    return town.model_copy(update={"placements": [p for p in town.placements if p.kind != kind]})


def reach_with_solid_gates(town: TownView, kinds: Mapping[str, KindSpec]) -> Reach:
    """Reachability from spawn if the town gates were plugged: each gatehouse blocks its whole footprint."""
    obstacles = town_obstacles(town, kinds)
    plugs = tuple(by_id(town, gate_id).rect() for gate_id in TOWN_GATES)
    plugged = Obstacles(solids=obstacles.solids + plugs, surfaces=obstacles.surfaces, water=obstacles.water)
    return build_walk_grid(town.extent, plugged).reachable_from(town.spawn.x, town.spawn.z)


# --- the authored town ---


def test_every_building_front_is_reachable_from_spawn(town: TownView, reach: Reach) -> None:
    buildings = [placement for placement in town.placements if placement.kind in BUILDINGS]

    assert len(buildings) > 40
    assert [building.id for building in buildings if not reach.contains(*building.front())] == []


def test_every_street_and_road_is_reachable_from_spawn(town: TownView, reach: Reach) -> None:
    ways = [area for area in town.areas if area.kind in ("street", "road")]

    assert len(ways) >= 8
    for way in ways:
        bounds = polygon_bounds(way.polygon)
        assert reach.contains((bounds.x0 + bounds.x1) / 2, (bounds.z0 + bounds.z1) / 2), way.id


def test_keep_and_well_are_reachable_from_spawn(town: TownView, reach: Reach) -> None:
    assert reach.contains(*keep_front(town))
    assert reach.contains(*well_front(town))


def test_every_citizen_and_route_point_is_reachable(town: TownView, reach: Reach) -> None:
    for citizen in town.citizens:
        for point in [(citizen.x, citizen.z), *citizen.route]:
            assert reach.contains(*point), (citizen.look, point)


@pytest.mark.parametrize("gate_id", ["main-gate", "west-gate", "castle-gate"])
def test_gate_passages_are_open_and_reachable(gate_id: str, town: TownView, reach: Reach) -> None:
    gate = by_id(town, gate_id)

    assert reach.contains(gate.x, gate.z)


@pytest.mark.parametrize("gate_id", ["main-gate", "west-gate", "castle-gate"])
def test_gate_pillars_block(gate_id: str, town: TownView, grid: WalkGrid) -> None:
    gate = by_id(town, gate_id)
    side_x, side_z = (2.0, 0.0) if gate.rotation_deg == 0 else (0.0, 2.0)

    assert not grid.is_walkable(gate.x + side_x, gate.z + side_z)
    assert not grid.is_walkable(gate.x - side_x, gate.z - side_z)


def test_castle_is_reachable_only_over_the_bridge(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    bridgeless = without_kind(town, "moat_bridge")

    reach = town_walk_grid(bridgeless, kinds).reachable_from(town.spawn.x, town.spawn.z)

    assert not reach.contains(*keep_front(town))
    assert reach.contains(*well_front(town))


def test_town_is_reachable_only_through_its_gates(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    reach = reach_with_solid_gates(town, kinds)

    assert not reach.contains(*well_front(town))
    assert not reach.contains(*keep_front(town))
    assert not reach.contains(*by_id(town, "temple-hall").front())
    assert reach.contains(0, 150)  # the approach road outside stays open


def test_moat_water_blocks_except_under_the_bridge(
    town: TownView, kinds: Mapping[str, KindSpec], grid: WalkGrid
) -> None:
    assert grid.is_walkable(*MOAT_UNDER_BRIDGE)
    assert not grid.is_walkable(*MOAT_BESIDE_BRIDGE)
    assert not town_walk_grid(without_kind(town, "moat_bridge"), kinds).is_walkable(*MOAT_UNDER_BRIDGE)


def test_moat_hole_is_dry_land(grid: WalkGrid) -> None:
    assert grid.is_walkable(0, 15)  # the castle courtyard sits in the moat's hole


def test_stream_blocks(grid: WalkGrid) -> None:
    assert not grid.is_walkable(-156, 120)


def test_town_walls_block(grid: WalkGrid) -> None:
    assert not grid.is_walkable(40, 100)
    assert not grid.is_walkable(-100, 0)
    assert not grid.is_walkable(28, 0)


# --- the grid itself ---

EXTENT = Extent(min_x=-5, max_x=5, min_z=-5, max_z=5)
POOL = TownWater(id="pool", kind="moat", polygon=[(-2, -5), (2, -5), (2, 5), (-2, 5)])


def grid_with(
    solids: tuple[Rect, ...] = (), surfaces: tuple[Rect, ...] = (), water: tuple[TownWater, ...] = ()
) -> WalkGrid:
    return build_walk_grid(EXTENT, Obstacles(solids=solids, surfaces=surfaces, water=water))


def test_solids_block_only_cells_they_overlap() -> None:
    grid = grid_with(solids=(Rect(0, 0, 1, 1),))

    assert not grid.is_walkable(0.25, 0.25)
    assert not grid.is_walkable(0.75, 0.75)
    assert grid.is_walkable(-0.25, 0.25)  # touches the rect's edge only
    assert grid.is_walkable(1.25, 0.25)


def test_a_thin_solid_still_blocks_its_cell() -> None:
    grid = grid_with(solids=(Rect(0.1, 0.1, 0.2, 0.2),))

    assert not grid.is_walkable(0.25, 0.25)


def test_water_splits_the_grid_and_a_surface_bridges_it() -> None:
    dry = grid_with(water=(POOL,)).reachable_from(-4, 0)
    bridged = grid_with(water=(POOL,), surfaces=(Rect(-3, -0.5, 3, 0.5),)).reachable_from(-4, 0)

    assert not dry.contains(4, 0)
    assert bridged.contains(4, 0)


def test_water_holes_are_dry() -> None:
    ring = TownWater(id="ring", kind="moat", polygon=POOL.polygon, holes=[[(-1, -1), (1, -1), (1, 1), (-1, 1)]])
    grid = grid_with(water=(ring,))

    assert grid.is_walkable(0, 0)
    assert not grid.is_walkable(1.5, 0)


def test_a_wall_across_the_grid_cuts_reachability() -> None:
    reach = grid_with(solids=(Rect(-5, -0.1, 5, 0.1),)).reachable_from(0, -3)

    assert reach.contains(4.9, -4.9)
    assert not reach.contains(0, 3)


@pytest.mark.parametrize(("start", "other_side"), [((-4.75, 0.25), (4.75, 0.25)), ((4.75, 0.25), (-4.75, 0.25))])
def test_reachability_does_not_wrap_around_rows(start: Point, other_side: Point) -> None:
    reach = grid_with(solids=(Rect(-0.1, -5, 0.1, 5),)).reachable_from(*start)

    assert reach.contains(start[0], 4.75)
    assert not reach.contains(*other_side)


def test_reachability_from_a_blocked_start_fails() -> None:
    grid = grid_with(solids=(Rect(-1, -1, 1, 1),))

    with pytest.raises(ValueError, match="not walkable"):
        grid.reachable_from(0, 0)


def test_points_outside_the_extent_are_not_walkable() -> None:
    grid = grid_with()

    assert grid.is_walkable(4.9, 4.9)
    assert not grid.is_walkable(5.1, 0)
    assert not grid.is_walkable(0, -5.1)
