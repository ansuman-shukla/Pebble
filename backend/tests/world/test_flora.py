"""Usable flora (10-world-v1 §1.1, D78): generated, packed, capped and kept out of water, roads and the town."""

from collections import Counter

import numpy as np
import pytest

from app.world.biomes import BIOME_IDS, mean_spacing_m
from app.world.flora import BYTES_PER_ITEM, OFFSET_STEP_M, SPREAD, Flora, generate_flora
from app.world.generate import GeneratedWorld, generate_world
from app.world.hotspots import road_distance_m
from app.world.spec import BIOME_NAMES, CAMPS, WorldSpec, load_site_kinds, load_world_spec
from app.world.sphere import angle_between, tangent_frame
from app.world.surface import Surface, surface_from_view
from app.world.terrain import polyline_distance
from app.world.view import WorldView, decode_array


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
