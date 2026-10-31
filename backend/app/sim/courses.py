"""Timed courses: where an animal is at each game second (10-world-v1 §4.2: every move is drawn along the path the
sim walked, by its times).

A course is a list of timed points (a direction on the planet, the game second it is there, counted from the run's
first tick), straight between them. Behaviour changes a course from a moment on (`redirect`: what was walked before
stays); at the tick's end the animal stands where its course says, and the part walked this tick plus a little of
the part ahead is what spectators draw. A course spans ticks when it must (a wolf's two-minute chase).

    points ──▶ at(t) ──▶ cut at t ──▶ + new points ──▶ tick end: walked [t0, t1] │ ahead (t1, t1 + 60] │ rest kept
"""

from dataclasses import dataclass

from app.observability.events import AnimalGait
from app.sim.clock import SECONDS_PER_TICK
from app.sim.state import AnimalActivity
from app.sim.vec import Vec3, angle, normalize

TimedPoint = tuple[Vec3, float]  # a direction and the game second it is there
SAME_S = 1e-6  # points this close in time are one moment


@dataclass
class Course:
    points: list[TimedPoint]  # by time; the first is where it was when the course (or the tick) began
    gait: AnimalGait
    moving: AnimalActivity  # what it is shown doing on the way
    arrive: AnimalActivity | None = None  # what it does once there (None: what it was doing)

    @property
    def end_s(self) -> float:
        return self.points[-1][1]


def tick_start_s(tick: int) -> float:
    """The game second a tick begins (tick 1 begins at 0)."""
    return float((tick - 1) * SECONDS_PER_TICK)


def at(points: list[TimedPoint], seconds: float) -> Vec3:
    """Where the course is at that second: straight between its points, at its ends before and after them."""
    if seconds <= points[0][1]:
        return points[0][0]
    for (a, ta), (b, tb) in zip(points, points[1:], strict=False):
        if seconds <= tb:
            if tb - ta <= SAME_S:
                return b
            share = (seconds - ta) / (tb - ta)
            mixed = (a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share, a[2] + (b[2] - a[2]) * share)
            return normalize(mixed)
    return points[-1][0]


def cut(points: list[TimedPoint], seconds: float) -> list[TimedPoint]:
    """The course up to that second, ending where it is then."""
    kept = [point for point in points if point[1] < seconds - SAME_S]
    return [*kept, (at(points, seconds), seconds)]


def redirect(
    course: Course | None,
    standing: Vec3,
    seconds: float,
    points: list[TimedPoint],
    gait: AnimalGait,
    moving: AnimalActivity,
    arrive: AnimalActivity | None,
) -> Course:
    """A new course from `seconds` on: what was walked of the old one before then (or standing there since the
    tick began), then `points` (each later than `seconds`)."""
    if course is None:
        before = [(standing, min(seconds, points[0][1] if points else seconds))]
        if before[0][1] < seconds - SAME_S:
            before.append((standing, seconds))
    else:
        before = cut(course.points, seconds)
    return Course([*before, *(p for p in points if p[1] > seconds + SAME_S)], gait, moving, arrive)


def walked(points: list[TimedPoint], start_s: float, end_s: float) -> list[TimedPoint]:
    """The part of the course between two seconds: where it is at the start, the points passed, and where it is at
    the end if the course lasts that long (else it ends at its last point)."""
    inside = [point for point in points if start_s + SAME_S < point[1] < end_s - SAME_S]
    last = [(at(points, end_s), end_s)] if points[-1][1] >= end_s - SAME_S else []
    return [(at(points, start_s), start_s), *inside, *last]


def ahead(points: list[TimedPoint], start_s: float, end_s: float) -> list[TimedPoint]:
    """The points after `start_s` up to `end_s` (and where it is at `end_s` if the course goes on past it)."""
    inside = [point for point in points if start_s + SAME_S < point[1] <= end_s]
    if points[-1][1] > end_s + SAME_S:
        inside.append((at(points, end_s), end_s))
    return inside


def metres(points: list[TimedPoint], radius_m: float) -> float:
    return sum(angle(a, b) * radius_m for (a, _), (b, _) in zip(points, points[1:], strict=False))
