"""Game time and the sun.

Tick = 1 game minute. Tick 0 is 08:00 town time on day 0 (as the client's clock starts). v0 has no axial tilt: the
sun circles in the equator's plane, westward, and local time runs 4 minutes ahead per degree of longitude east of the
town (the same formula as the client's `game-clock.ts`).
"""

import math

from app.sim.vec import Vec3, dot

DAY_MINUTES = 24 * 60
START_MINUTE = 8 * 60
TICKS_PER_HOUR = 60
SECONDS_PER_TICK = 60  # game seconds
NIGHT_ALTITUDE_DEG = -6.0  # darker than civil twilight is night


def game_minute(tick: int) -> int:
    """Town time in minutes since midnight of day 0."""
    return START_MINUTE + tick


def town_clock(tick: int) -> tuple[int, str]:
    """(day, "HH:MM") in town time."""
    minute = game_minute(tick)
    return minute // DAY_MINUTES, f"{minute % DAY_MINUTES // 60:02d}:{minute % 60:02d}"


def sun_direction(tick: int, town_lon_deg: float) -> Vec3:
    lon = math.radians(town_lon_deg + (12 - (game_minute(tick) % DAY_MINUTES) / 60) * 15)
    return (math.sin(lon), 0.0, math.cos(lon))


def sun_altitude_deg(unit: Vec3, sun: Vec3) -> float:
    return math.degrees(math.asin(max(-1.0, min(1.0, dot(unit, sun)))))


def daylight(altitude_deg: float) -> float:
    """1 in daylight, 0 at night, linear through twilight."""
    return min(1.0, max(0.0, (altitude_deg - NIGHT_ALTITUDE_DEG) / -NIGHT_ALTITUDE_DEG))


def is_night(altitude_deg: float) -> bool:
    return altitude_deg < NIGHT_ALTITUDE_DEG


def local_minute(tick: int, town_lon_deg: float, lon_deg: float) -> float:
    """Local solar time of day in minutes (0 ≤ m < 1440) at a longitude."""
    local = game_minute(tick) + (lon_deg - town_lon_deg) * 4
    return local % DAY_MINUTES


_TIME_WORDS: tuple[tuple[float, str], ...] = (
    (4.0, "the middle of the night"),
    (5.5, "the dark before dawn"),
    (6.5, "dawn; the sun is rising"),
    (9.0, "early morning"),
    (11.0, "mid-morning"),
    (13.0, "around midday; the sun is high"),
    (15.5, "early afternoon"),
    (17.25, "late afternoon"),
    (18.0, "the sun is about to set"),
    (19.0, "dusk"),
    (24.0, "night"),
)


def time_words(local_minute_of_day: float) -> str:
    hour = local_minute_of_day / 60
    return next(words for until, words in _TIME_WORDS if hour < until)
