import numpy as np
import pytest

from app.world.grid import build_grid
from app.world.spec import Falls, Hill, Plateau, SiteSpec, Volcano, load_world_spec
from app.world.sphere import angle_between, unit_from_lat_lon
from app.world.terrain import BLEND_GRADE, base_terrain, loop_band, polyline_distance, shape_site, smooth, smoothstep

GRID = build_grid(30)
SPEC = load_world_spec()


def _site(terrain: Plateau | Hill | Volcano | Falls, at: tuple[float, float] = (10, 20)) -> SiteSpec:
    return SiteSpec(id="test", kind="landmark", name="Test", at=at, terrain=terrain)


def _distance_m(at: tuple[float, float]) -> np.ndarray:
    return angle_between(GRID.positions, unit_from_lat_lon(*at)) * SPEC.radius_m


def test_smoothstep_clamps_and_eases() -> None:
    np.testing.assert_allclose(smoothstep(0, 1, np.array([-1, 0, 0.5, 1, 2])), [0, 0, 0.5, 1, 1])
    np.testing.assert_allclose(smoothstep(1, 0, np.array([0.0, 1.0])), [1, 0])


def test_polyline_distance_measures_to_arcs_and_ends() -> None:
    points = [unit_from_lat_lon(0, 0), unit_from_lat_lon(0, 60)]
    units = np.stack([unit_from_lat_lon(10, 30), unit_from_lat_lon(0, 70), unit_from_lat_lon(0, 30)])

    distance = polyline_distance(units, points, [1.0, 1.0], closed=False)

    np.testing.assert_allclose(np.degrees(distance), [10, 10, 0], atol=1e-9)
    halfway = polyline_distance(units[:1], points, [1.0, 3.0], closed=False)
    np.testing.assert_allclose(np.degrees(halfway), [5], atol=1e-9)


def test_the_land_loop_core_is_always_land() -> None:
    core = loop_band(SPEC, GRID.positions, SPEC.land_loop.core_fraction) <= 1

    heights = base_terrain(SPEC, GRID).heights

    assert core.sum() > 100
    assert (heights[core] >= SPEC.land_loop.core_height_m).all()


def test_smoothing_moves_cells_toward_their_neighbours_mean() -> None:
    spike = np.zeros(GRID.cell_count)
    spike[100] = 60.0
    neighbours = [n for n in GRID.neighbours[100] if n >= 0]

    once = smooth(spike, GRID.neighbours, passes=1, strength=0.5)

    assert once[100] == pytest.approx(30.0)
    np.testing.assert_allclose(once[neighbours], 60.0 / 6 * 0.5)
    np.testing.assert_array_equal(smooth(spike, GRID.neighbours, passes=0, strength=0.5), spike)
    np.testing.assert_allclose(smooth(np.full(GRID.cell_count, 7.0), GRID.neighbours, 3, 0.5), 7.0)
    assert smooth(spike, GRID.neighbours, passes=4, strength=0.5)[100] < once[100]


def test_smoothing_keeps_the_coastline() -> None:
    base = base_terrain(SPEC, GRID)

    np.testing.assert_array_equal(base.heights > 0, base.continental > 0)
    assert (base.heights[base.continental > 0] >= 1.0).all()
    assert (base.heights[base.continental <= 0] <= -2.0).all()


def test_plateau_flattens_to_its_height_and_blends_out() -> None:
    heights = base_terrain(SPEC, GRID).heights
    before = heights.copy()
    distance = _distance_m((38, 12))

    area = shape_site(
        SPEC, _site(Plateau(type="plateau", radius_m=230, blend_m=70, height_m=8), (38, 12)), GRID.positions, heights
    )

    assert area.height_m == 8 and area.authored_height
    np.testing.assert_array_equal(heights[distance <= 230], 8)
    np.testing.assert_array_equal(area.flat, distance <= 230)
    # past the blend the terrain is untouched unless it rises or falls faster than the blend grade from the rim
    outside = distance > 300
    reach = (distance[outside] - 230) * BLEND_GRADE
    np.testing.assert_array_equal(heights[outside], np.clip(before[outside], 8 - reach, 8 + reach))
    assert (heights[outside] != before[outside]).any()
    ring = (distance > 240) & (distance < 290)
    between = (np.minimum(before[ring], 8) <= heights[ring] + 1e-9) & (
        heights[ring] <= np.maximum(before[ring], 8) + 1e-9
    )
    assert between.all()
    rim = distance > 230
    assert (np.abs(heights[rim] - 8) <= (distance[rim] - 230) * BLEND_GRADE + 1e-9).all()


def test_hill_rises_above_the_terrain() -> None:
    heights = base_terrain(SPEC, GRID).heights
    anchor = int(np.argmin(_distance_m((28, -4))))
    ground = heights[anchor]

    area = shape_site(
        SPEC, _site(Hill(type="hill", radius_m=40, blend_m=90, rise_m=18), (28, -4)), GRID.positions, heights
    )

    assert area.height_m == pytest.approx(max(ground, SPEC.terrain.beach_m) + 18)
    assert not area.authored_height


def test_volcano_has_a_cone_and_a_crater() -> None:
    heights = np.zeros(GRID.cell_count)
    shape = Volcano(
        type="volcano",
        peak_m=320,
        base_radius_m=400,
        crater_radius_m=95,
        crater_depth_m=30,
        floor_radius_m=45,
        volcanic_radius_m=200,
    )
    distance = _distance_m((10, 20))

    area = shape_site(SPEC, _site(shape), GRID.positions, heights)

    assert area.height_m == 290
    np.testing.assert_array_equal(area.basin, distance <= 95)
    assert heights.max() <= 320 + 1e-9
    assert heights[(distance > 95) & (distance < 140)].max() > 250
    assert (heights[distance > 400] == 0).all()
    cone = (distance > 100) & (distance < 400)
    order = np.argsort(distance[cone])
    assert (np.diff(heights[cone][order]) <= 1e-9).all()


def test_falls_has_a_lip_above_a_lake_bowl() -> None:
    heights = np.full(GRID.cell_count, 50.0)
    shape = Falls(
        type="falls",
        lip_m=70,
        drop_m=40,
        bearing_deg=180,
        lake_distance_m=125,
        lake_radius_m=100,
        lake_depth_m=5,
        upland_radius_m=260,
        flat_radius_m=25,
    )

    area = shape_site(SPEC, _site(shape), GRID.positions, heights)

    assert area.bowl.any() and area.bowl_level == 30
    assert (heights[area.bowl] < 30).all()
    assert (heights[area.flat] == 70).all()
    lake_centre = unit_from_lat_lon(10 - 125 / SPEC.radius_m * 180 / np.pi, 20)
    assert area.bowl[int(np.argmax(GRID.positions @ lake_centre))]
