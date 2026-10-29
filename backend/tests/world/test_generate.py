import hashlib

import numpy as np
import pytest

from app.world.biomes import BIOME_IDS, WATER_BIOMES, hop_distance, mean_spacing_m, walkable
from app.world.generate import GENERATOR_VERSION, GeneratedWorld, generate_world
from app.world.hydrology import components
from app.world.paths import reachable
from app.world.spec import BIOME_NAMES, SITE_IDS, WorldSpec, load_site_kinds, load_world_spec
from app.world.sphere import angle_between, lat_lon
from app.world.terrain import base_terrain
from app.world.view import decode_array

LAND_BIOMES = sorted(set(range(len(BIOME_NAMES))) - WATER_BIOMES)


@pytest.fixture(scope="module")
def spec() -> WorldSpec:
    return load_world_spec()


@pytest.fixture(scope="module")
def world(spec: WorldSpec) -> GeneratedWorld:
    return generate_world(spec, load_site_kinds())


def _digest(world: GeneratedWorld) -> str:
    view = world.view()
    payload = "|".join([view.positions, view.heights, view.biomes, view.triangles, str(view.land_loop)])
    return hashlib.sha256(payload.encode()).hexdigest()


def _site(world: GeneratedWorld, site_id: str) -> int:
    return next(site.cell for site in world.sites if site.id == site_id)


def _distance_m(world: GeneratedWorld, a: int, b: int) -> float:
    return float(angle_between(world.grid.positions[[a]], world.grid.positions[b])[0] * world.spec.radius_m)


def _walkable(world: GeneratedWorld) -> np.ndarray:
    return walkable(world.biomes)


def test_same_seed_and_spec_give_identical_worlds(spec: WorldSpec, world: GeneratedWorld) -> None:
    again = generate_world(spec, load_site_kinds())

    assert _digest(again) == _digest(world)
    assert again.view().model_dump() == world.view().model_dump()


def test_another_seed_gives_another_terrain(spec: WorldSpec, world: GeneratedWorld) -> None:
    # (only the terrain: the hotspots are laid out for this seed's ground and may not fit another's)
    other = base_terrain(spec.model_copy(update={"seed": spec.seed + 1}), world.grid)

    assert not np.array_equal(other.heights, base_terrain(spec, world.grid).heights)


def test_world_view_carries_the_generator_version_and_sizes(world: GeneratedWorld) -> None:
    view = world.view()

    assert view.generator_version == GENERATOR_VERSION
    assert view.cell_count == 36_002
    assert view.biome_names == list(BIOME_NAMES)
    assert {site.id for site in view.sites} == set(SITE_IDS)


def test_heights_stay_in_the_contract_range(world: GeneratedWorld) -> None:
    heights = world.heights

    assert -125 <= heights.min() <= -100
    land = heights[_walkable(world)]
    assert 200 <= np.sort(land)[-50] <= 251
    volcano = _site(world, "smoking_mountain")
    near_volcano = angle_between(world.grid.positions, world.grid.positions[volcano]) * world.spec.radius_m < 150
    assert heights.max() == pytest.approx(heights[near_volcano].max())
    assert 290 <= heights.max() <= 330


def _edge_slopes_deg(world: GeneratedWorld) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    triangles = world.grid.triangles
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    a, b = edges[edges[:, 0] < edges[:, 1]].T
    run = np.linalg.norm(world.grid.positions[a] - world.grid.positions[b], axis=1) * world.spec.radius_m
    return np.degrees(np.arctan(np.abs(world.heights[a] - world.heights[b]) / run)), a, b


def test_the_land_is_calm_and_the_coasts_are_gentle(world: GeneratedWorld) -> None:
    slopes, a, b = _edge_slopes_deg(world)
    land = (world.heights[a] > 0) & (world.heights[b] > 0)
    coast = (world.heights[a] > 0) != (world.heights[b] > 0)

    # unsmoothed (m3.1): 10 % of land edges over 40°, p95 49°, coast p95 44°
    assert (slopes[land] > 40).mean() < 0.015
    assert np.percentile(slopes[land], 95) < 32
    assert np.percentile(slopes[coast], 95) < 38


def test_biome_shares_are_in_range(world: GeneratedWorld) -> None:
    shares = np.bincount(world.biomes, minlength=len(BIOME_NAMES)) / world.grid.cell_count
    ocean = shares[BIOME_IDS["deep_ocean"]] + shares[BIOME_IDS["shallow_ocean"]]

    assert 0.30 <= ocean <= 0.50
    assert 0.005 <= shares[BIOME_IDS["lake"]] <= 0.03
    for biome in LAND_BIOMES:
        assert shares[biome] > 0.001, BIOME_NAMES[biome]
    for big in ("grassland", "broadleaf_forest", "hills"):
        assert shares[BIOME_IDS[big]] > 0.05, big


def test_poles_are_frozen(world: GeneratedWorld) -> None:
    lat, _ = lat_lon(world.grid.positions)
    frozen = np.isin(world.biomes, [BIOME_IDS["ice"], BIOME_IDS["snow"]])
    polar_land = (np.abs(lat) > 75) & _walkable(world)

    assert polar_land.sum() > 100
    assert frozen[polar_land].mean() > 0.95
    assert (world.biomes[(np.abs(lat) > 80) & _walkable(world)] == BIOME_IDS["ice"]).mean() > 0.9
    assert not frozen[(np.abs(lat) < 20) & (world.heights < 100)].any()


def test_the_volcano_is_volcanic_with_a_crater(world: GeneratedWorld) -> None:
    cell = _site(world, "smoking_mountain")
    distance = angle_between(world.grid.positions, world.grid.positions[cell]) * world.spec.radius_m

    assert world.biomes[cell] == BIOME_IDS["volcanic"]
    assert (world.biomes[distance < 150] == BIOME_IDS["volcanic"]).all()
    rim = world.heights[(distance > 60) & (distance < 130)].max()
    assert rim - world.heights[cell] >= 20


def test_land_loop_is_a_closed_walkable_cycle_around_the_planet(spec: WorldSpec, world: GeneratedWorld) -> None:
    loop = world.land_loop
    walk = _walkable(world)

    assert len(loop) == len(set(loop)) > 300
    for a, b in zip(loop, loop[1:] + loop[:1], strict=True):
        assert b in world.grid.neighbours[a]
    assert walk[loop].all()
    _, lon = lat_lon(world.grid.positions[loop + loop[:1]])
    turn = (np.diff(lon) + 180) % 360 - 180
    assert abs(abs(turn.sum()) - 360) < 1e-6
    assert _site(world, spec.loop_gate) in loop


def test_the_ice_gate_is_a_narrow_ice_bridge_at_high_latitude(world: GeneratedWorld) -> None:
    gate = _site(world, "ice_gate")
    lat, _ = lat_lon(world.grid.positions[[gate]])
    near = angle_between(world.grid.positions, world.grid.positions[gate]) * world.spec.radius_m < 300

    assert lat[0] > 65
    assert world.biomes[gate] == BIOME_IDS["ice"]
    assert np.isin(world.biomes[near], sorted(WATER_BIOMES)).mean() > 0.3


def test_every_site_is_reachable_on_foot_from_the_town(world: GeneratedWorld) -> None:
    seen = reachable(world.grid, _walkable(world), _site(world, "town"))

    for site in world.sites:
        assert seen[site.cell], site.id


def test_town_sits_on_a_flat_plateau(world: GeneratedWorld) -> None:
    town = next(site for site in world.sites if site.id == "town")
    distance = angle_between(world.grid.positions, np.array(town.anchor.position)) * world.spec.radius_m
    plateau = distance <= 200

    assert town.anchor.height_m == 8
    assert plateau.sum() > 50
    np.testing.assert_allclose(world.heights[plateau], 8, atol=0.01)
    assert _walkable(world)[plateau].all()


def test_town_lies_in_a_temperate_river_valley_near_the_coast(world: GeneratedWorld) -> None:
    town = _site(world, "town")
    lat, _ = lat_lon(world.grid.positions[[town]])
    ocean = np.isin(world.biomes, [BIOME_IDS["deep_ocean"], BIOME_IDS["shallow_ocean"]])
    spacing = mean_spacing_m(world.grid, world.spec.radius_m)

    assert 30 <= lat[0] <= 50
    assert hop_distance(world.grid, ocean)[town] * spacing < 500
    assert hop_distance(world.grid, world.river_cells)[town] * spacing < 250


def test_rivers_flow_downhill_and_end_in_water(world: GeneratedWorld) -> None:
    heights = decode_array(world.view().heights, "<f4")  # the served float32 heights
    water = (world.heights < 0) | world.lake
    by_cell = {cell: river for river in world.rivers for cell in river.cells[:-1]}

    assert len(world.rivers) >= 20
    for river in world.rivers:
        cells = river.cells
        assert len(cells) >= 2
        assert all(b in world.grid.neighbours[a] for a, b in zip(cells, cells[1:], strict=False))
        assert (np.diff(heights[cells]) <= 0).all(), river.id
        end, seen = cells[-1], {river.id}
        while not water[end]:  # a tributary ends where it joins another river; follow that one down
            joined = by_cell[end]
            assert joined.id not in seen
            seen.add(joined.id)
            end = joined.cells[-1]


def test_great_falls_drops_off_a_cliff_into_a_lake(world: GeneratedWorld) -> None:
    lip = _site(world, "great_falls")
    falls = next(river for river in world.rivers if lip in river.cells)

    assert world.biomes[falls.cells[-1]] == BIOME_IDS["lake"]
    assert world.heights[lip] - world.heights[falls.cells[-1]] >= 25
    lake = reachable(world.grid, world.lake, falls.cells[-1])
    assert any(lake[river.cells[0]] for river in world.rivers if river is not falls), "the falls lake drains on"


def test_sites_match_the_world_description(world: GeneratedWorld) -> None:
    cells = {site.id: site.cell for site in world.sites}
    water = np.isin(world.biomes, sorted(WATER_BIOMES)) | world.river_cells
    near_water = hop_distance(world.grid, water) * mean_spacing_m(world.grid, world.spec.radius_m)

    for camp in ("band_a_camp", "band_b_camp"):
        assert near_water[cells[camp]] <= 120, camp
    assert _distance_m(world, cells["band_a_camp"], cells["town"]) >= 2500
    assert 1200 <= _distance_m(world, cells["band_b_camp"], cells["town"]) <= 1700  # 10-world-v1 §1.2
    assert _distance_m(world, cells["band_a_camp"], cells["band_b_camp"]) >= 1500
    assert _distance_m(world, cells["painted_cave"], cells["band_a_camp"]) <= 600
    assert world.biomes[cells["elder_tree"]] == BIOME_IDS["broadleaf_forest"]
    assert world.biomes[cells["standing_stones"]] == BIOME_IDS["grassland"]
    assert world.biomes[cells["hot_springs"]] in {BIOME_IDS["mountain"], BIOME_IDS["snow"], BIOME_IDS["hills"]}
    stones = cells["standing_stones"]
    around = angle_between(world.grid.positions, world.grid.positions[stones]) * world.spec.radius_m
    assert world.heights[stones] > np.median(world.heights[(around > 150) & (around < 250)]) + 10


def test_site_anchors_are_tangent_frames_at_their_plateau_height(world: GeneratedWorld) -> None:
    for site in world.sites:
        anchor = site.anchor
        up, east, north = (np.array(v) for v in (anchor.position, anchor.east, anchor.north))
        for axis in (up, east, north):
            assert np.linalg.norm(axis) == pytest.approx(1)
        np.testing.assert_allclose(np.cross(up, east), north, atol=1e-12)
        assert east[1] == pytest.approx(0, abs=1e-12)
        assert np.argmax(world.grid.positions @ up) == site.cell
        if site.id != "smoking_mountain":
            assert world.heights[site.cell] == pytest.approx(anchor.height_m, abs=0.01), site.id


def test_site_placements_use_known_kinds(world: GeneratedWorld) -> None:
    kinds = load_site_kinds()
    placements = {site.id: site.placements for site in world.sites}

    assert placements["town"] == []
    for site_id, items in placements.items():
        assert all(item.kind in kinds for item in items), site_id
        assert len({item.id for item in items}) == len(items), site_id
    camp_kinds = [item.kind for item in placements["band_a_camp"]]
    assert camp_kinds.count("lean_to") in (2, 3)
    assert {"fire_pit", "firewood", "cook_tripod", "drying_rack", "reed_basket", "reed_torch"} <= set(camp_kinds)
    assert 7 <= [item.kind for item in placements["standing_stones"]].count("rock_spire") <= 9
    assert [item.kind for item in placements["elder_tree"]].count("giant_tree") == 1


def test_lakes_are_level(world: GeneratedWorld) -> None:
    # the smoothed terrain leaves no depressions near the poles; frozen lakes turning to ice is tested on classify
    assert (world.heights[world.lake] >= 0).all()
    for group in _lake_groups(world):
        assert np.ptp(world.heights[group]) == 0
    assert (world.biomes[world.biomes == BIOME_IDS["lake"]] == BIOME_IDS["lake"]).all()
    assert world.lake[world.biomes == BIOME_IDS["lake"]].all()


def _lake_groups(world: GeneratedWorld) -> list[list[int]]:
    return components(world.grid, world.lake)
