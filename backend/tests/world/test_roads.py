"""Roads, paths, bridges and signposts (10-world-v1 §1.3, D80)."""

import itertools

import numpy as np
import pytest

from app.world.biomes import walk_costs
from app.world.generate import GeneratedWorld, generate_world
from app.world.paths import cheapest_path
from app.world.roads import NONE, PATH, ROAD, cell_kinds, walk_costs_with_roads
from app.world.spec import WorldSpec, load_site_kinds, load_world_spec
from app.world.sphere import angle_between, unit_from_lat_lon
from app.world.surface import Surface, surface_from_view
from app.world.town import load_kinds, load_town
from app.world.view import Road
from app.world.walkability import town_walk_grid


@pytest.fixture(scope="module")
def spec() -> WorldSpec:
    return load_world_spec()


@pytest.fixture(scope="module")
def world(spec: WorldSpec) -> GeneratedWorld:
    return generate_world(spec, load_site_kinds())


@pytest.fixture(scope="module")
def surface(world: GeneratedWorld, spec: WorldSpec) -> Surface:
    return surface_from_view(world.view(), spec.roads.town_chart_half_m)


def _road(world: GeneratedWorld, road_id: str) -> Road:
    return next(road for road in world.places.roads if road.id == road_id)


def test_the_listed_roads_and_paths_link_their_stops_in_order(world: GeneratedWorld, spec: WorldSpec) -> None:
    roads = {road.id: road for road in world.places.roads}
    cells = {hotspot.id: hotspot.cell for hotspot in world.places.hotspots} | {s.id: s.cell for s in world.sites}

    for route in spec.roads.routes:
        road = roads[route.id]
        assert (road.kind, road.name, road.stops) == (route.kind, route.name, route.stops)
        stops = [stop for stop in route.stops if stop in cells]
        positions = [road.cells.index(cells[stop]) for stop in stops]
        assert positions == sorted(positions), route.id  # visited in order
    kinds = [road.kind for road in world.places.roads]
    assert kinds == sorted(kinds, key=lambda kind: kind == "path")  # roads first, most important first


def test_routes_are_unbroken_walks_outside_the_town_chart(world: GeneratedWorld, surface: Surface) -> None:
    for road in world.places.roads:
        for a, b in itertools.pairwise(road.cells):
            assert b in surface.grid.neighbours[a], road.id
        assert surface.walk[road.cells].all() and not surface.in_town[road.cells].any(), road.id


def test_gate_roads_start_with_a_lead_from_the_gate_to_the_chart_edge(world: GeneratedWorld, surface: Surface) -> None:
    for road in world.places.roads:
        if road.stops and road.stops[0].endswith("_gate"):
            local = surface.chart.local(np.array(road.lead))
            assert np.abs(local).max(axis=1)[-1] == pytest.approx(160, abs=0.01), road.id
            assert np.abs(local).max(axis=1)[0] < 110, road.id  # starts at the gate inside the walls
            first = surface.cell_unit(road.cells[0])
            assert angle_between(first[None], np.array(road.lead[-1]))[0] * surface.radius_m < 60, road.id
        else:
            assert road.lead == [], road.id


def test_the_west_road_leaves_the_west_gate_over_a_bridge_past_the_lords_woods_to_band_b(
    world: GeneratedWorld,
) -> None:
    road = _road(world, "west_road")
    camp = next(site for site in world.sites if site.id == "band_b_camp")
    woods = next(hotspot for hotspot in world.places.hotspots if hotspot.id == "lords_woods")
    bridges = [bridge for bridge in world.places.bridges if bridge.road == "west_road"]

    assert road.kind == "road" and road.stops[0] == "west_gate"
    assert road.cells[-1] == camp.cell and woods.cell in road.cells
    assert bridges[0].cell is None  # over the town's stream, on the lead


def test_every_river_crossing_of_a_road_or_path_is_a_bridge(world: GeneratedWorld, surface: Surface) -> None:
    on_network = {cell for road in world.places.roads for cell in road.cells}
    crossings = {cell for cell in on_network if surface.river[cell]}
    bridged = {bridge.cell for bridge in world.places.bridges if bridge.cell is not None}

    assert crossings
    assert bridged == crossings
    assert len(bridged) == len([bridge for bridge in world.places.bridges if bridge.cell is not None])


def test_town_stream_bridge_carries_the_west_lead_over_the_water(spec: WorldSpec) -> None:
    town = load_town()
    walk = town_walk_grid(town, load_kinds())
    gate = next(gate for gate in spec.roads.gates if gate.id == "west_gate")

    assert town.extent.max_x == spec.roads.town_chart_half_m == -town.extent.min_x
    assert any(placement.id == "stream-bridge" for placement in town.placements)
    for (x0, z0), (x1, z1) in itertools.pairwise(gate.lead):
        for t in np.linspace(0, 1, 200):
            x, z = x0 + (x1 - x0) * t, z0 + (z1 - z0) * t
            assert walk.is_walkable(max(x, town.extent.min_x + 0.01), z), (x, z)
    stream = next(water for water in town.water if water.id == "stream")
    xs = [x for x, _ in stream.polygon]
    assert min(xs) <= gate.bridges[0][0] <= max(xs)


def test_trips_between_hotspots_keep_to_roads_and_paths(world: GeneratedWorld, surface: Surface) -> None:
    kinds = cell_kinds(world.places.roads, surface.grid.cell_count)
    costs = walk_costs_with_roads(walk_costs(surface.biomes, surface.river), kinds, surface.river)
    allowed = surface.walk & ~surface.in_town
    trips = 0
    for a, b in itertools.combinations(world.places.hotspots, 2):
        if angle_between(np.array([a.centre]), np.array(b.centre))[0] * surface.radius_m <= 400:
            continue
        path = cheapest_path(surface.grid, allowed, costs, a.cell, b.cell)
        share = float((kinds[path] != NONE).mean())
        assert share >= 0.6, (a.id, b.id, round(share, 2))
        trips += 1
    assert trips >= 80


def test_later_routes_merge_into_earlier_trunks(world: GeneratedWorld) -> None:
    west, stones = _road(world, "west_road"), _road(world, "stones_road")
    falls, marsh = _road(world, "falls_road"), _road(world, "marsh_road")

    assert stones.cells[:3] == west.cells[:3]
    assert marsh.cells[:2] == falls.cells[:2]


def test_signposts_stand_beside_road_junctions_and_name_two_places(world: GeneratedWorld, surface: Surface) -> None:
    roads = world.places.roads
    names = {hotspot.name for hotspot in world.places.hotspots} | {site.name for site in world.sites}
    names |= {"The great trail"}
    signposts = [feature for feature in world.places.features if feature.kind == "signpost"]

    assert len(signposts) >= 8
    for post in signposts:
        through = [road for road in roads if post.cell in road.cells]
        assert len(through) >= 2 and any(road.kind == "road" for road in through), post.id
        assert len(post.names) == 2 and set(post.names) <= names, post.id
        offset = angle_between(np.array([post.position]), surface.cell_unit(post.cell))[0] * surface.radius_m
        assert offset == pytest.approx(4.0, abs=0.01)
    junction = next(post for post in signposts if set(post.names) == {"Band B camp", "Standing stones"})
    assert junction.cell in _road(world, "west_road").cells and junction.cell in _road(world, "stones_road").cells


def test_roads_paths_and_bridges_cost_what_d80_says() -> None:
    base = np.array([1.0, 1.5, 2.5, 1.0, 2.0, 1.5, 1.0])
    kinds = np.array([NONE, ROAD, ROAD, PATH, PATH, ROAD, NONE], dtype=np.uint8)
    river = np.array([False, False, False, False, False, True, True])

    costs = walk_costs_with_roads(base, kinds, river)

    assert costs.tolist() == pytest.approx([1.0, 0.8, 1.25, 0.9, 1.4, 0.8, 1.0])


def test_cell_kinds_let_a_road_win_over_a_path(world: GeneratedWorld) -> None:
    kinds = cell_kinds(world.places.roads, world.grid.cell_count)
    west, trail = _road(world, "west_road"), _road(world, "great_trail")

    assert (kinds[west.cells] == ROAD).all()
    shared = sorted(set(west.cells) & set(trail.cells))
    assert shared and (kinds[shared] == ROAD).all()
    assert set(np.flatnonzero(kinds == PATH)) <= {c for road in world.places.roads for c in road.cells}


def test_the_great_trail_is_a_closed_path_through_the_land_loop_waypoints(
    world: GeneratedWorld, spec: WorldSpec
) -> None:
    trail = _road(world, "great_trail")
    waypoints = [int(np.argmax(world.grid.positions @ unit_from_lat_lon(*w.at))) for w in spec.land_loop.waypoints]

    assert trail.kind == "path" and trail.name == "the great trail" and trail.stops == []
    assert trail.cells[0] == trail.cells[-1] and len(set(trail.cells)) == len(trail.cells) - 1
    on_trail = set(trail.cells)
    for cell in waypoints:  # through each waypoint (or beside it, where a doubled-back detour was cut off)
        assert cell in on_trail or on_trail & set(world.grid.neighbours[cell].tolist())
