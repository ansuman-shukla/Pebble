import numpy as np
import pytest

from app.world.sphere import (
    angle_between,
    globe_to_local,
    lat_lon,
    local_to_globe,
    tangent_frame,
    unit_from_lat_lon,
)

RADIUS = 2000.0


def test_lat_lon_follow_the_contract_axes() -> None:
    np.testing.assert_allclose(unit_from_lat_lon(0, 0), [0, 0, 1], atol=1e-12)
    np.testing.assert_allclose(unit_from_lat_lon(0, 90), [1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(unit_from_lat_lon(90, 0), [0, 1, 0], atol=1e-12)


def test_lat_lon_round_trip() -> None:
    lat, lon = lat_lon(np.stack([unit_from_lat_lon(35.5, -120.25), unit_from_lat_lon(-60, 170)]))

    np.testing.assert_allclose(lat, [35.5, -60])
    np.testing.assert_allclose(lon, [-120.25, 170])


def test_angle_between_matches_the_great_circle() -> None:
    units = np.stack([unit_from_lat_lon(0, 0), unit_from_lat_lon(0, 90), unit_from_lat_lon(10, 0)])

    np.testing.assert_allclose(np.degrees(angle_between(units, unit_from_lat_lon(0, 0))), [0, 90, 10], atol=1e-9)


@pytest.mark.parametrize(("lat", "lon"), [(20, 30), (-45, 170), (89.9999999, 0), (90, 0), (-90, 0)])
def test_tangent_frame_is_right_handed_with_local_axes(lat: float, lon: float) -> None:
    frame = tangent_frame(unit_from_lat_lon(lat, lon))

    for axis in (frame.up, frame.east, frame.north):
        assert np.linalg.norm(axis) == pytest.approx(1)
    assert np.dot(frame.east, frame.up) == pytest.approx(0, abs=1e-12)
    assert np.dot(frame.north, frame.up) == pytest.approx(0, abs=1e-12)
    np.testing.assert_allclose(np.cross(frame.east, frame.up), frame.south, atol=1e-12)


def test_east_points_toward_growing_longitude_and_north_to_the_pole() -> None:
    frame = tangent_frame(unit_from_lat_lon(10, 40))

    _, lon = lat_lon((frame.up + 1e-3 * frame.east)[None])
    lat, _ = lat_lon((frame.up + 1e-3 * frame.north)[None])
    assert lon[0] > 40
    assert lat[0] > 10


def test_local_mapping_round_trips_within_a_micrometre() -> None:
    frame = tangent_frame(unit_from_lat_lon(25, -12))
    x, z = (a.ravel() for a in np.meshgrid(np.linspace(-200, 200, 41), np.linspace(-200, 200, 41)))

    points = local_to_globe(frame, RADIUS, 8.0, x, z)
    back = globe_to_local(frame, RADIUS, 8.0, points)

    np.testing.assert_allclose(np.linalg.norm(points, axis=1), RADIUS + 8.0)
    np.testing.assert_allclose(back[:, 0], x, atol=1e-6)
    np.testing.assert_allclose(back[:, 1], z, atol=1e-6)


def test_local_axes_point_east_and_south_on_the_globe() -> None:
    frame = tangent_frame(unit_from_lat_lon(0, 0))

    east, south = local_to_globe(frame, RADIUS, 0.0, np.array([10.0, 0.0]), np.array([0.0, 10.0]))

    assert east[0] > 0 and abs(east[1]) < 1e-9
    assert south[1] < 0 and abs(south[0]) < 1e-9
