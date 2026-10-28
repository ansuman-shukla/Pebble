"""Seeded 3D gradient noise and fractal sums over it, vectorised with numpy.

Lattice gradients come from an integer hash of (cell corner, seed) rather than a random generator, so the same seed
gives the same field on every numpy version.
"""

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

_MASK = 0xFFFFFFFF
_GRADIENTS = np.array(
    [(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0), (1, 0, 1), (-1, 0, 1)]
    + [(1, 0, -1), (-1, 0, -1), (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1)],
    dtype=np.float64,
)


def _hash(ix: NDArray[np.int64], iy: NDArray[np.int64], iz: NDArray[np.int64], seed: int) -> NDArray[np.uint64]:
    """A 32-bit integer mix (murmur3 finaliser) of the lattice corner and the seed."""
    mixed = (ix * 0x8DA6B343 + iy * 0xD8163841 + iz * 0xCB1AB31F + (seed & _MASK) * 0x165667B1) & _MASK
    h: NDArray[np.uint64] = mixed.astype(np.uint64)
    h ^= h >> np.uint64(16)
    h = (h * np.uint64(0x85EBCA6B)) & np.uint64(_MASK)
    h ^= h >> np.uint64(13)
    h = (h * np.uint64(0xC2B2AE35)) & np.uint64(_MASK)
    h ^= h >> np.uint64(16)
    return h


def _fade(t: FloatArray) -> FloatArray:
    return t * t * t * (t * (t * 6 - 15) + 10)


def gradient_noise(points: FloatArray, seed: int) -> FloatArray:
    """Perlin-style gradient noise at (n, 3) points; values in about [-1, 1], 0 at lattice corners."""
    base = np.floor(points)
    frac = points - base
    corner = base.astype(np.int64)
    fade = _fade(frac)
    total = np.zeros(len(points))
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                offset = np.array([dx, dy, dz])
                gradient = _GRADIENTS[_hash(corner[:, 0] + dx, corner[:, 1] + dy, corner[:, 2] + dz, seed) % 12]
                dot = np.einsum("ij,ij->i", gradient, frac - offset)
                weight = np.prod(np.where(offset == 1, fade, 1 - fade), axis=1)
                total += weight * dot
    return total


def fbm(
    points: FloatArray, seed: int, frequency: float, octaves: int, gain: float = 0.5, lacunarity: float = 2.0
) -> FloatArray:
    """Fractal sum of gradient noise, normalised by the total amplitude (about [-1, 1])."""
    total = np.zeros(len(points))
    amplitude, scale, norm = 1.0, frequency, 0.0
    for octave in range(octaves):
        total += amplitude * gradient_noise(points * scale, seed + 1013 * octave)
        norm += amplitude
        amplitude *= gain
        scale *= lacunarity
    return total / norm


def ridged(points: FloatArray, seed: int, frequency: float, octaves: int, gain: float = 0.5) -> FloatArray:
    """Ridged fractal noise in [0, 1]: sharp crests where the gradient noise crosses zero."""
    total = np.zeros(len(points))
    amplitude, scale, norm = 1.0, frequency, 0.0
    for octave in range(octaves):
        total += amplitude * (1 - np.abs(gradient_noise(points * scale, seed + 7919 * octave))) ** 2
        norm += amplitude
        amplitude *= gain
        scale *= 2.0
    return total / norm


def warp(points: FloatArray, seed: int, frequency: float, octaves: int, strength: float) -> FloatArray:
    """Points displaced by a vector of three fBm fields (domain warping)."""
    offsets = np.stack([fbm(points, seed + 31 * axis, frequency, octaves) for axis in range(3)], axis=1)
    return points + strength * offsets
