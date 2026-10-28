import re
from collections.abc import Callable
from typing import get_args

import pytest

from app.sim.bodies import (
    HEAT_THIRST_RATE,
    Crossing,
    body_words,
    need_level,
    update_body,
)
from app.sim.clock import (
    DAY_MINUTES,
    daylight,
    is_night,
    local_minute,
    sun_altitude_deg,
    sun_direction,
    time_of_day,
    town_clock,
)
from app.sim.simulation import Simulation
from app.sim.state import AGE_GROUPS, Body, age_group
from app.sim.vec import Vec3
from app.sim.world import SimWorld
from app.world_api.models import TimeOfDay
from tests.sim_helpers import make_spec

ADULT = AGE_GROUPS["young_adult"]


def _hours(body: Body, hours: float, activity: str | None = None, hot: bool = False) -> list[Crossing]:
    crossings: list[Crossing] = []
    for _ in range(round(hours * 60)):
        crossings += update_body(body, ADULT, activity, hot).crossings
    return crossings


def test_town_clock_starts_at_eight_and_rolls_over_days() -> None:
    assert town_clock(0) == (0, "08:00")
    assert town_clock(16 * 60) == (1, "00:00")
    assert town_clock(16 * 60 + 61) == (1, "01:01")


def test_sun_is_overhead_at_town_noon_and_below_at_midnight(sim_world: SimWorld) -> None:
    town: Vec3 = tuple(float(v) for v in sim_world.town.frame.up)  # type: ignore[assignment]
    noon, midnight = 4 * 60, 16 * 60
    lat = 38.0  # the town's latitude: no axial tilt, so the noon sun stands 90 - lat high
    assert sun_altitude_deg(town, sun_direction(noon, sim_world.town_lon_deg)) == pytest.approx(90 - lat, abs=0.01)
    assert sun_altitude_deg(town, sun_direction(midnight, sim_world.town_lon_deg)) == pytest.approx(lat - 90, abs=0.01)
    assert sun_altitude_deg(town, sun_direction(-2 * 60, sim_world.town_lon_deg)) == pytest.approx(0.0, abs=0.01)


def test_local_time_runs_ahead_four_minutes_per_degree_east() -> None:
    assert local_minute(0, 12.0, 12.0) == 480
    assert local_minute(0, 12.0, 27.0) == 540
    assert local_minute(0, 12.0, 12.0 - 135.0) == 1380  # 23:00 the evening before


def test_light() -> None:
    assert (daylight(10.0), daylight(-3.0), daylight(-6.0), daylight(-20.0)) == (1.0, 0.5, 0.0, 0.0)
    assert is_night(-6.1) and not is_night(-5.9)


DAY_PHASES: list[tuple[float, TimeOfDay, str]] = [  # (local hour, time of day, what a citizen reads)
    (0.0, "night", "It is the middle of the night."),
    (3.9, "night", "It is the middle of the night."),
    (4.0, "pre-dawn", "It is the dark before dawn."),
    (6.0, "dawn", "It is dawn; the sun is rising."),
    (6.5, "early morning", "It is early morning."),
    (10.0, "mid-morning", "It is mid-morning."),
    (12.0, "midday", "It is around midday; the sun is high."),
    (14.0, "early afternoon", "It is early afternoon."),
    (16.0, "late afternoon", "It is late afternoon."),
    (17.5, "sunset", "The sun is about to set."),
    (18.5, "dusk", "It is dusk."),
    (19.0, "night", "It is night."),
    (23.99, "night", "It is night."),
]
# One sentence: a capital, a full stop, and clauses (split at "; ") that each have one subject and one "is"
# ("It is the sun is about to set." has two).
WELL_FORMED = re.compile(r"(It|The sun) is [a-z][a-z -]*(; the sun is [a-z ]+)?\.")


@pytest.mark.parametrize(("hour", "when", "sentence"), DAY_PHASES)
def test_every_phase_of_the_day_reads_as_one_well_formed_sentence(hour: float, when: str, sentence: str) -> None:
    assert time_of_day(hour * 60) == (when, sentence)
    assert WELL_FORMED.fullmatch(sentence), sentence
    assert all(clause.count(" is ") == 1 for clause in sentence.rstrip(".").split("; "))


def test_the_day_covers_every_time_of_day() -> None:
    assert {time_of_day(minute)[0] for minute in range(DAY_MINUTES)} == set(get_args(TimeOfDay))
    assert {when for _, when, _ in DAY_PHASES} == set(get_args(TimeOfDay))


def test_needs_rise_at_the_documented_rates() -> None:
    body = Body()
    _hours(body, 10)
    assert body.hunger == pytest.approx(40.0)
    assert body.thirst == pytest.approx(60.0)
    assert body.energy == pytest.approx(50.0)
    assert body.health == 100.0


def test_activity_heat_and_sleep_change_the_rates() -> None:
    walking, hot, asleep, resting = Body(), Body(), Body(asleep=True, energy=10.0), Body(energy=10.0)
    _hours(walking, 2, "walk_to")
    _hours(hot, 2, hot=True)
    _hours(asleep, 2)
    _hours(resting, 2, "rest")
    assert walking.hunger == pytest.approx(10.0)  # 4/h x 1.25
    assert hot.thirst == pytest.approx(12.0 * HEAT_THIRST_RATE)
    assert asleep.energy == pytest.approx(34.0) and asleep.hunger == pytest.approx(6.0)
    assert resting.energy == pytest.approx(16.0)


def test_age_groups_and_their_traits() -> None:
    assert [age_group(a) for a in (5, 12, 13, 17, 18, 30, 31, 50, 51)] == [
        "child",
        "child",
        "teen",
        "teen",
        "young_adult",
        "young_adult",
        "middle_aged",
        "middle_aged",
        "elder",
    ]
    assert (AGE_GROUPS["child"].speed, AGE_GROUPS["elder"].carry_kg) == (0.7, 10.0)
    with pytest.raises(ValueError):
        age_group(4)


def test_threshold_crossings_are_reported_once_each_way() -> None:
    body = Body(hunger=59.99)
    crossings = _hours(body, 1 / 60)
    assert [(c.need, c.words, c.worse) for c in crossings] == [("hunger", "hungry", True)]
    assert _hours(body, 1 / 60) == []
    body.hunger = 10.0  # ate
    assert [(c.need, c.words, c.worse) for c in _hours(body, 1 / 60)] == [("hunger", "fed", False)]
    assert (need_level("energy", 31), need_level("energy", 30), need_level("energy", 10)) == (0, 1, 2)


def test_starvation_and_dehydration_kill_with_the_right_cause() -> None:
    starving = Body(hunger=95.0)
    thirsty = Body(thirst=95.0)
    for body in (starving, thirsty):
        for _ in range(60 * 60):
            if not body.alive:
                break
            if body is starving:
                body.thirst = 0.0
            change = update_body(body, ADULT, None, False)
    assert (starving.alive, starving.cause_of_death) == (False, "starvation")
    assert (thirsty.alive, thirsty.cause_of_death) == (False, "dehydration")
    assert starving.health == 0.0
    with pytest.raises(ValueError):
        update_body(starving, ADULT, None, False)
    assert change.died is None or change.died in ("starvation", "dehydration")


def test_starvation_takes_two_health_an_hour_and_heals_when_fed() -> None:
    body = Body(hunger=95.0)
    _hours(body, 5)
    assert body.health == pytest.approx(90.0)
    body.hunger, body.thirst = 0.0, 0.0
    _hours(body, 5)
    assert body.health == pytest.approx(95.0)


def test_collapse_at_zero_energy_and_values_stay_in_range() -> None:
    body = Body(energy=0.02, hunger=99.99, thirst=99.99)
    change = update_body(body, ADULT, None, False)
    assert change.collapsed
    assert (body.energy, body.hunger, body.thirst) == (0.0, 100.0, 100.0)


def test_body_words_are_coarse() -> None:
    assert body_words(Body()) == []
    assert body_words(Body(hunger=65, thirst=95, energy=25, health=40)) == [
        "hungry",
        "terribly thirsty",
        "tired",
        "weak and aching",
    ]


def test_healing_needs_food_and_water() -> None:
    hungry, thirsty, fed = Body(health=50.0, hunger=70.0), Body(health=50.0, thirst=70.0), Body(health=50.0)
    for body in (hungry, thirsty, fed):
        _hours(body, 2)
    assert (hungry.health, thirsty.health) == (50.0, 50.0)
    assert fed.health == pytest.approx(52.0)


def test_walkers_face_where_they_go(new_sim: Callable[..., Simulation]) -> None:
    """heading_deg is the town's yaw: 0 = facing south (+z), 90 = east, 180 = north, 270 = west."""
    sim = new_sim()
    citizen = sim.add_citizen(make_spec(at=(-20.0, 60.0)))
    for target, heading in (
        ((-20.0, 63.0), 0.0),
        ((-14.0, 63.0), 90.0),
        ((-14.0, 59.0), 180.0),
        ((-19.0, 59.0), 270.0),
    ):
        sim.core.place_at(citizen, sim.world.town.to_unit(*target))
        assert abs((citizen.heading_deg - heading + 180) % 360 - 180) < 1.0, target
    standing = citizen.heading_deg
    sim.core.place_at(citizen, citizen.position)
    assert citizen.heading_deg == standing  # standing still keeps the facing
