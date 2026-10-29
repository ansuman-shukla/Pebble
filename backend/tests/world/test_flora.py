"""Usable flora (10-world-v1 §1.1, D78): generated, packed, capped and kept out of water, roads and the town."""

from collections import Counter

import numpy as np
import pytest

from app.world.biomes import BIOME_IDS, mean_spacing_m
from app.world.flora import BYTES_PER_ITEM, OFFSET_STEP_M, SPREAD, Flora, generate_flora
from app.world.generate import GeneratedWorld, generate_world
from app.world.hotspots import road_distance_m
from app.world.spec import BIOME_NAMES, CAMPS, WorldSpec, load_site_kinds, load_world_spec
from app.world.sphere import angle_between, bearing_deg, destination, tangent_frame
from app.world.surface import Surface, surface_from_view
from app.world.terrain import polyline_distance
from app.world.view import WorldView, decode_array, encode_array


@pytest.fixture(scope="module")
def spec() -> WorldSpec:
    return load_world_spec()


@pytest.fixture(scope="module")
def world(spec: WorldSpec) -> GeneratedWorld:
    return generate_world(spec, load_site_kinds())


@pytest.fixture(scope="module")
def view(world: GeneratedWorld) -> WorldView:
    return world.view()


@pytest.fixture(scope="module")
def flora(view: WorldView, spec: WorldSpec) -> Flora:
    return generate_flora(view, spec)


@pytest.fixture(scope="module")
def surface(view: WorldView, spec: WorldSpec) -> Surface:
    return surface_from_view(view, spec.roads.town_chart_half_m)


def _nodes(view: WorldView, flora: Flora) -> np.ndarray:
    return np.array(view.places.flora_nodes)[flora.kind]


def _metres(surface: Surface, flora: Flora, unit: np.ndarray) -> np.ndarray:
    return angle_between(flora.units, unit) * surface.radius_m


def test_same_world_gives_the_same_table_and_another_seed_another(
    view: WorldView, spec: WorldSpec, flora: Flora
) -> None:
    assert generate_flora(view, spec).pack() == flora.pack()
    other = generate_flora(view, spec.model_copy(update={"seed": spec.seed + 1}))
    assert other.pack() != flora.pack()


def test_the_table_packs_and_unpacks_losslessly(flora: Flora, world: GeneratedWorld) -> None:
    data = flora.pack()
    again = Flora.unpack(data, world.grid, world.spec.radius_m)

    assert len(data) == BYTES_PER_ITEM * len(flora) == 9 * len(flora)
    for name in ("cell", "east", "north", "kind", "scale", "yaw"):
        assert np.array_equal(getattr(again, name), getattr(flora, name)), name
    assert np.frombuffer(data[: 4 * len(flora)], dtype="<u4").tolist() == flora.cell.tolist()
    assert np.all(np.diff(flora.cell.astype(np.int64)) >= 0)  # sorted by cell
    with pytest.raises(ValueError, match="multiple of 9"):
        Flora.unpack(data[:-1], world.grid, world.spec.radius_m)


def test_positions_decode_from_the_cell_frame(flora: Flora, world: GeneratedWorld) -> None:
    index = len(flora) // 2
    cell = int(flora.cell[index])
    frame = tangent_frame(world.grid.positions[cell])
    v = frame.up * world.spec.radius_m + frame.east * (int(flora.east[index]) * OFFSET_STEP_M)
    v += frame.north * (int(flora.north[index]) * OFFSET_STEP_M)

    assert np.allclose(flora.units[index], v / np.linalg.norm(v))
    offsets = np.hypot(flora.east.astype(float), flora.north.astype(float)) * OFFSET_STEP_M
    assert offsets.max() <= SPREAD * mean_spacing_m(world.grid, world.spec.radius_m) + 8  # placed items: nearest cell
    assert 0.5 <= (flora.scale / 100).min() and (flora.scale / 100).max() <= 1.35


def test_totals_match_the_bible(view: WorldView, flora: Flora) -> None:
    nodes = Counter(_nodes(view, flora).tolist())

    assert 36_000 <= nodes["tree"] <= 48_000  # ≈ 42 k
    others = sum(count for node, count in nodes.items() if node != "tree")
    assert 5_000 <= others <= 7_000  # ≈ 6 k
    assert set(nodes) == {"tree", "nut_tree", "berry_bush", "root_patch", "reed_bed", "deadwood"}
    assert len(flora.pack()) <= 520_000


def test_flora_per_biome_is_within_15_percent_of_its_density(spec: WorldSpec, flora: Flora, surface: Surface) -> None:
    land = surface.walk & ~surface.in_town
    owners = flora.cell.astype(np.int64)
    checked = 0
    for biome, table in spec.flora.per_cell.items():
        cells = land & (surface.biomes == BIOME_IDS[biome])
        target = sum(table.values()) * int(cells.sum())
        if target < 200:
            continue
        actual = int(cells[owners].sum())
        assert actual == pytest.approx(target, rel=0.15), biome
        checked += 1
    assert checked >= 6


def test_each_camps_home_ring_holds_exactly_its_budget(
    view: WorldView, spec: WorldSpec, flora: Flora, surface: Surface
) -> None:
    nodes = _nodes(view, flora)
    for camp in CAMPS:
        inside = _metres(surface, flora, surface.site_unit(camp)) <= spec.hotspots.rings.home_m
        counts = Counter(nodes[inside].tolist())
        assert {node: counts.get(node, 0) for node in spec.hotspots.home_ring_flora} == {
            "berry_bush": 8,
            "root_patch": 8,
            "deadwood": 6,
            "nut_tree": 0,
        }, camp
    savanna = next(hotspot for hotspot in view.places.hotspots if hotspot.id == "a_savanna")
    in_savanna = _metres(surface, flora, np.array(savanna.centre)) <= savanna.radius_m
    assert int((in_savanna & (nodes == "root_patch")).sum()) == 8  # the home ring's 8 lie at the A savanna


def test_each_hotspot_holds_its_exact_counts(view: WorldView, flora: Flora, surface: Surface) -> None:
    nodes = _nodes(view, flora)
    for hotspot in view.places.hotspots:
        inside = _metres(surface, flora, np.array(hotspot.centre)) <= hotspot.radius_m
        for node, count in hotspot.flora.items():
            assert int((inside & (nodes == node)).sum()) == count, (hotspot.id, node)
    elder = next(hotspot for hotspot in view.places.hotspots if hotspot.id == "elder_grove")
    assert elder.flora == {"berry_bush": 25, "nut_tree": 10}


def test_woodlots_grow_half_again_as_many_trees(
    view: WorldView, flora: Flora, surface: Surface, spec: WorldSpec
) -> None:
    trees = _nodes(view, flora) == "tree"
    owners = flora.cell.astype(np.int64)
    forest = surface.biomes == BIOME_IDS["broadleaf_forest"]
    per_cell = spec.flora.per_cell["broadleaf_forest"]
    tree_density = sum(count for kind, count in per_cell.items() if kind in ("oak_tree", "birch_tree"))
    for hotspot_id in ("north_woods", "lords_woods"):
        hotspot = next(hotspot for hotspot in view.places.hotspots if hotspot.id == hotspot_id)
        cells = forest & (
            angle_between(surface.grid.positions, np.array(hotspot.centre)) * surface.radius_m < hotspot.radius_m - 25
        )
        grown = int((trees & cells[owners]).sum()) / int(cells.sum())
        assert grown == pytest.approx(1.5 * tree_density, rel=0.2), hotspot_id


def test_nothing_grows_in_water_the_town_camps_props_rivers_or_roads(
    view: WorldView, flora: Flora, surface: Surface
) -> None:
    units = flora.units
    assert surface.walk[_owners(surface, flora)].all()
    assert not surface.chart.contains(units).any()
    for camp in CAMPS:
        assert _metres(surface, flora, surface.site_unit(camp)).min() >= 12
    reeds = _nodes(view, flora) == "reed_bed"
    for road in view.places.roads:
        clearance = 2.5 if road.kind == "road" else 1.75
        near = road_distance_m(units, [road], surface) < clearance - 0.05
        assert not near.any(), road.id
    for river in surface.rivers:
        points = [surface.cell_unit(cell) for cell in river.cells]
        if len(points) < 2:
            continue
        distance = polyline_distance(units, points, [1.0] * len(points), closed=False) * surface.radius_m
        assert (distance[~reeds] >= 6 - 0.05).all() and (distance[reeds] >= 3 - 0.05).all(), river.id
    for feature in view.places.features:
        assert _metres(surface, flora, np.array(feature.position)).min() >= 3 - 0.05, feature.id


def _owners(surface: Surface, flora: Flora) -> np.ndarray:
    cells = flora.cell.astype(np.int64)
    candidates = np.concatenate([cells[:, None], surface.padded_neighbours[cells]], axis=1)
    scores = np.einsum(
        "ijk,ik->ij", np.concatenate([surface.grid.positions, np.zeros((1, 3))])[candidates], flora.units
    )
    scores[candidates == surface.grid.cell_count] = -np.inf
    return np.asarray(candidates[np.arange(len(cells)), scores.argmax(axis=1)])


def test_every_kind_grows_only_in_its_biomes(view: WorldView, spec: WorldSpec, flora: Flora) -> None:
    biomes = decode_array(view.biomes, "u1")[flora.cell.astype(np.int64)]
    kinds = view.places.flora_kinds
    natural = {(biome, kind) for biome, table in spec.flora.per_cell.items() for kind in table}
    natural |= {(biome, kind) for biome in spec.flora.river_biomes for kind in spec.flora.river_per_cell}
    seen = Counter((BIOME_NAMES[biome], kinds[kind]) for biome, kind in zip(biomes, flora.kind, strict=True))
    strays = {pair: count for pair, count in seen.items() if pair not in natural}
    assert sum(strays.values()) <= 0.002 * len(flora), strays  # placed nodes take their biome's kind


def test_nothing_grows_seaward_of_the_drawn_shore(flora: Flora, surface: Surface) -> None:
    owners = _owners(surface, flora)
    triangles = surface.grid.triangles
    by_sea = np.flatnonzero(np.append(surface.ocean, False)[surface.padded_neighbours[owners]].any(axis=1))
    for index in by_sea.tolist():
        point, owner = flora.units[index], int(owners[index])
        for corners in triangles[(triangles == owner).any(axis=1)]:
            a, b, c = surface.grid.positions[corners]
            normal = np.cross(b - a, c - a)
            hit = point * (a @ normal) / (point @ normal)
            wa = float(np.cross(c - b, hit - b) @ normal / (normal @ normal))
            wb = float(np.cross(a - c, hit - c) @ normal / (normal @ normal))
            weights = np.array([wa, wb, 1 - wa - wb])
            if weights.min() >= -1e-9:
                if surface.ocean[corners].any():
                    assert float(weights @ surface.heights[corners]) >= 0.3 - 1e-6, index
                break
    assert len(by_sea) > 100


def test_an_edge_dens_grove_puts_its_first_bush_36_m_off_even_when_sparse(
    view: WorldView, spec: WorldSpec, flora: Flora, surface: Surface
) -> None:
    sparse = view.model_copy(deep=True)
    for hotspot in sparse.places.hotspots:
        if hotspot.id == "b_wood":
            hotspot.flora["berry_bush"] = 2  # two bushes in a 130 m wood would seldom stand near its den
    for table, world_view in ((flora, view), (generate_flora(sparse, spec), sparse)):
        bushes = _nodes(world_view, table) == "berry_bush"
        for hotspot in world_view.places.hotspots:
            if hotspot.id not in ("elder_grove", "b_wood"):
                continue
            grove = bushes & (_metres(surface, table, np.array(hotspot.centre)) <= hotspot.radius_m)
            den = next(feature for feature in world_view.places.features if feature.id == f"{hotspot.id}:den")
            nearest = np.sort(_metres(surface, table, np.array(den.position))[grove])
            assert 33 <= nearest[0] <= 39, hotspot.id


def test_camps_keep_their_worn_ground_clear_even_in_a_forest(view: WorldView, spec: WorldSpec) -> None:
    forested = decode_array(view.biomes, "u1").copy()
    surface = surface_from_view(view, spec.roads.town_chart_half_m)
    for camp in CAMPS:
        near = surface.distances_m(surface.site_unit(camp)) < 80
        forested[near & surface.walk] = BIOME_IDS["broadleaf_forest"]
    wooded = view.model_copy(update={"biomes": encode_array(forested, "u1")})
    flora = generate_flora(wooded, spec)
    trees = np.array(view.places.flora_nodes)[flora.kind] == "tree"
    for camp in CAMPS:
        distance = _metres(surface, flora, surface.site_unit(camp))
        assert distance.min() >= 12, camp
        assert ((distance < 40) & trees).sum() >= 5, camp  # the forest reaches the clearing


def test_a_home_ring_hotspot_on_the_ring_s_edge_keeps_its_counts_in_the_ring(
    view: WorldView, spec: WorldSpec, surface: Surface
) -> None:
    camp = surface.site_unit("band_a_camp")
    edged = view.model_copy(deep=True)
    savanna = next(hotspot for hotspot in edged.places.hotspots if hotspot.id == "a_savanna")
    away = float(bearing_deg(camp, np.array([savanna.centre]))[0])
    centre = destination(camp, away, 360 / surface.radius_m)  # 2/3 of its 120 m disc lies beyond the 400 m ring
    savanna.centre = (float(centre[0]), float(centre[1]), float(centre[2]))
    flora = generate_flora(edged, spec)

    roots = _nodes(edged, flora) == "root_patch"
    in_savanna = roots & (_metres(surface, flora, centre) <= savanna.radius_m)
    assert int(in_savanna.sum()) == 8
    assert (_metres(surface, flora, camp)[in_savanna] <= spec.hotspots.rings.home_m).all()
    assert int((roots & (_metres(surface, flora, camp) <= spec.hotspots.rings.home_m)).sum()) == 8
