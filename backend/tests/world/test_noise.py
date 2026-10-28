import numpy as np

from app.world.noise import fbm, gradient_noise, ridged, warp


def _points(count: int = 4000, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-20, 20, size=(count, 3))


def test_noise_is_deterministic_per_seed() -> None:
    points = _points()

    np.testing.assert_array_equal(gradient_noise(points, 7), gradient_noise(points.copy(), 7))
    assert not np.allclose(gradient_noise(points, 7), gradient_noise(points, 8))


def test_noise_is_zero_on_the_lattice_and_bounded() -> None:
    lattice = np.random.default_rng(1).integers(-50, 50, size=(500, 3)).astype(np.float64)
    values = gradient_noise(_points(), 3)

    np.testing.assert_allclose(gradient_noise(lattice, 3), 0.0, atol=1e-12)
    assert np.abs(values).max() <= 1.5
    assert values.std() > 0.1
    assert abs(values.mean()) < 0.05


def test_noise_is_continuous() -> None:
    points = _points()
    step = np.full(3, 1e-4)

    assert np.abs(gradient_noise(points + step, 5) - gradient_noise(points, 5)).max() < 1e-2


def test_noise_varies_between_lattice_cells() -> None:
    centres = np.random.default_rng(2).integers(-50, 50, size=(500, 3)).astype(np.float64) + 0.37

    assert len(np.unique(np.round(gradient_noise(centres, 9), 6))) > 400


def test_fbm_adds_detail_and_stays_normalised() -> None:
    points = _points() / 20

    coarse = fbm(points, 4, frequency=2, octaves=1)
    detailed = fbm(points, 4, frequency=2, octaves=5)

    assert np.abs(detailed).max() <= 1.5
    assert not np.allclose(coarse, detailed)
    np.testing.assert_allclose(coarse, gradient_noise(points * 2, 4))


def test_ridged_noise_is_in_unit_range() -> None:
    values = ridged(_points() / 20, 11, frequency=3, octaves=4)

    assert values.min() >= 0 and values.max() <= 1
    assert values.std() > 0.05


def test_warp_moves_points_by_at_most_the_strength() -> None:
    points = _points() / 20

    moved = warp(points, 2, frequency=2, octaves=3, strength=0.1)

    shift = np.linalg.norm(moved - points, axis=1)
    assert shift.max() <= 0.1 * 1.5 * np.sqrt(3)
    assert shift.mean() > 0.005
