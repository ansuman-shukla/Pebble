"""Sphere math in the contract frame.

+Y = north pole, lon 0 at +Z, lon +90° at +X; local axes X = east, Y = up, Z = south.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

_POLE_EPS = 1e-6
_Y = np.array([0.0, 1.0, 0.0])
_Z = np.array([0.0, 0.0, 1.0])


def unit_from_lat_lon(lat_deg: float, lon_deg: float) -> FloatArray:
    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    return np.array([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)])


def lat_lon(units: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Latitude and longitude in degrees of (n, 3) unit vectors; longitude in (-180, 180]."""
    lat = np.degrees(np.arcsin(np.clip(units[..., 1], -1, 1)))
    lon = np.degrees(np.arctan2(units[..., 0], units[..., 2]))
    return lat, lon


def angle_between(units: FloatArray, target: FloatArray) -> FloatArray:
    """Great-circle angle in radians between each row of (n, 3) unit vectors and one unit vector."""
    return np.arctan2(np.linalg.norm(np.cross(units, target), axis=-1), units @ target)


@dataclass(frozen=True)
class TangentFrame:
    up: FloatArray
    east: FloatArray
    north: FloatArray

    @property
    def south(self) -> FloatArray:
        return -self.north


def tangent_frame(up: FloatArray) -> TangentFrame:
    up = up / np.linalg.norm(up)
    east = np.cross(_Y, up)
    if np.linalg.norm(east) < _POLE_EPS:
        east = np.cross(_Z, up)
    east /= np.linalg.norm(east)
    return TangentFrame(up=up, east=east, north=np.cross(up, east))


def local_to_globe(frame: TangentFrame, radius_m: float, height_m: float, x: FloatArray, z: FloatArray) -> FloatArray:
    """Gnomonic forward mapping of local metres (x east, z south) on a plateau at height_m to world points (n, 3)."""
    v = frame.up * (radius_m + height_m) + np.multiply.outer(x, frame.east) + np.multiply.outer(z, frame.south)
    units = v / np.linalg.norm(v, axis=-1, keepdims=True)
    return units * (radius_m + height_m)


def globe_to_local(frame: TangentFrame, radius_m: float, height_m: float, points: FloatArray) -> FloatArray:
    """Inverse of local_to_globe: world points (n, 3) to local (x, z) metres (n, 2)."""
    v = points / np.linalg.norm(points, axis=-1, keepdims=True)
    t = (radius_m + height_m) / (v @ frame.up)
    return np.stack([t * (v @ frame.east), t * (v @ frame.south)], axis=-1)
