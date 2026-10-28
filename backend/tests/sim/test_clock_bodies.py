import pytest

from app.sim.bodies import (
    HEAT_THIRST_RATE,
    Crossing,
    body_words,
    need_level,
    update_body,
)
from app.sim.clock import (
    daylight,
    is_night,
    local_minute,
    sun_altitude_deg,
    sun_direction,
    time_words,
    town_clock,
)
from app.sim.state import AGE_GROUPS, Body, age_group
from app.sim.vec import Vec3
from app.sim.world import SimWorld

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


def test_light_and_time_words() -> None:
    assert (daylight(10.0), daylight(-3.0), daylight(-6.0), daylight(-20.0)) == (1.0, 0.5, 0.0, 0.0)
    assert is_night(-6.1) and not is_night(-5.9)
    assert time_words(12 * 60) == "around midday; the sun is high"
    assert time_words(17.5 * 60) == "the sun is about to set"
    assert time_words(2 * 60) == "the middle of the night"
    assert time_words(23 * 60) == "night"


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
