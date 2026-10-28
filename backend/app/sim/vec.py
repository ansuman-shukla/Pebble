"""Small 3-vector helpers in plain Python: per-entity math is faster without numpy's per-call overhead."""

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

Vec3 = tuple[float, float, float]


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Vec3) -> Vec3:
    length = norm(a)
    if length == 0:
        raise ValueError("cannot normalize a zero vector")
    return (a[0] / length, a[1] / length, a[2] / length)


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec3, factor: float) -> Vec3:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def angle(a: Vec3, b: Vec3) -> float:
    """Great-circle angle in radians between two unit vectors."""
    return math.atan2(norm(cross(a, b)), dot(a, b))


def slerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """The unit vector a fraction t of the way along the great circle from a to b."""
    theta = angle(a, b)
    if theta < 1e-12:
        return b
    sin_theta = math.sin(theta)
    wa = math.sin((1 - t) * theta) / sin_theta
    wb = math.sin(t * theta) / sin_theta
    return normalize((a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb, a[2] * wa + b[2] * wb))


def as_vec(values: Sequence[float] | NDArray[np.float64]) -> Vec3:
    """A Vec3 of floats from a 3-sequence (numpy row, tuple, list)."""
    if len(values) != 3:
        raise ValueError(f"expected 3 components, got {len(values)}")
    return (float(values[0]), float(values[1]), float(values[2]))


def lat_lon_deg(unit: Vec3) -> tuple[float, float]:
    """Latitude and longitude of a unit vector in the contract frame (+Y north, lon 0 at +Z, +90 at +X)."""
    return math.degrees(math.asin(max(-1.0, min(1.0, unit[1])))), math.degrees(math.atan2(unit[0], unit[2]))


def bearing_deg(origin: Vec3, target: Vec3) -> float:
    """Compass bearing (0 = north, 90 = east) from origin to target along the surface."""
    east = cross((0.0, 1.0, 0.0), origin)
    if norm(east) < 1e-9:
        east = cross((0.0, 0.0, 1.0), origin)
    east = normalize(east)
    north = cross(origin, east)
    offset = (target[0] - origin[0], target[1] - origin[1], target[2] - origin[2])
    return math.degrees(math.atan2(dot(offset, east), dot(offset, north))) % 360


def step_towards(origin: Vec3, bearing: float, distance_m: float, radius_m: float) -> Vec3:
    """The point distance_m along the surface from origin in the compass bearing."""
    east = cross((0.0, 1.0, 0.0), origin)
    if norm(east) < 1e-9:
        east = cross((0.0, 0.0, 1.0), origin)
    east = normalize(east)
    north = cross(origin, east)
    rad = math.radians(bearing)
    direction = add(scale(north, math.cos(rad)), scale(east, math.sin(rad)))
    theta = distance_m / radius_m
    return normalize(add(scale(origin, math.cos(theta)), scale(direction, math.sin(theta))))
