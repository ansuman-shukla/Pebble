"""Flat ground geometry in local metres (x east, z south)."""

from dataclasses import dataclass
from typing import Literal

Point = tuple[float, float]
Polygon = list[Point]
Rotation = Literal[0, 90, 180, 270]

# (cos, sin) per yaw; positive yaw turns +z toward +x, as three.js rotation.y does.
_COS_SIN: dict[Rotation, tuple[int, int]] = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle; x0 <= x1 and z0 <= z1."""

    x0: float
    z0: float
    x1: float
    z1: float

    def __post_init__(self) -> None:
        if self.x0 > self.x1 or self.z0 > self.z1:
            raise ValueError(f"rect corners are out of order: {self}")

    @classmethod
    def centred(cls, x: float, z: float, size_x: float, size_z: float) -> "Rect":
        return cls(x - size_x / 2, z - size_z / 2, x + size_x / 2, z + size_z / 2)

    def overlaps(self, other: "Rect", eps: float = 0.0) -> bool:
        """True when the rectangles share an area wider and deeper than eps (touching edges don't count)."""
        overlap_x = min(self.x1, other.x1) - max(self.x0, other.x0)
        overlap_z = min(self.z1, other.z1) - max(self.z0, other.z0)
        return overlap_x > eps and overlap_z > eps

    def contains(self, x: float, z: float) -> bool:
        return self.x0 <= x <= self.x1 and self.z0 <= z <= self.z1

    def inside(self, outer: "Rect") -> bool:
        return outer.x0 <= self.x0 and self.x1 <= outer.x1 and outer.z0 <= self.z0 and self.z1 <= outer.z1

    def rotated(self, rotation_deg: Rotation) -> "Rect":
        """This rectangle turned about the origin by a yaw."""
        corners = [rotate_point(x, z, rotation_deg) for x in (self.x0, self.x1) for z in (self.z0, self.z1)]
        xs = [x for x, _ in corners]
        zs = [z for _, z in corners]
        return Rect(min(xs), min(zs), max(xs), max(zs))

    def translated(self, dx: float, dz: float) -> "Rect":
        return Rect(self.x0 + dx, self.z0 + dz, self.x1 + dx, self.z1 + dz)

    def polygon(self) -> Polygon:
        return [(self.x0, self.z0), (self.x1, self.z0), (self.x1, self.z1), (self.x0, self.z1)]


def rotate_point(x: float, z: float, rotation_deg: Rotation) -> Point:
    cos, sin = _COS_SIN[rotation_deg]
    return (x * cos + z * sin, -x * sin + z * cos)


def facing(rotation_deg: Rotation) -> Point:
    """Unit vector a model faces after the yaw (models face +z at rotation 0)."""
    return rotate_point(0.0, 1.0, rotation_deg)


def point_in_polygon(x: float, z: float, polygon: Polygon) -> bool:
    """Even-odd ray cast; points exactly on an edge may land either side."""
    inside = False
    j = len(polygon) - 1
    for i, (xi, zi) in enumerate(polygon):
        xj, zj = polygon[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
            inside = not inside
        j = i
    return inside


def polygon_bounds(polygon: Polygon) -> Rect:
    xs = [x for x, _ in polygon]
    zs = [z for _, z in polygon]
    return Rect(min(xs), min(zs), max(xs), max(zs))
