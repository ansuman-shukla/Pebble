"""The hunt's numbers (10-world-v1 §4.6): the 1-D race, sensing and the strike reproduce the bible's worked odds."""

import math

import pytest

from app.core.rng import Rng
from app.sim import hunt
from app.sim.fauna import SPECIES

# predator, prey: G* (m), P(caught), P(strike), kill per attempt, kill per night (4 tries) — the bible's table
WORKED_ODDS = [
    ("lion", "antelope", 0.0, 0.31, 0.60, 0.19, 0.56),
    ("lion", "deer", 15.0, 0.31, 0.60, 0.19, 0.56),
    ("lion", "boar", 60.0, 1.00, 0.24, 0.24, 0.67),
    ("wolf", "deer", 30.0, 0.44, 0.50, 0.22, 0.63),
    ("wolf", "elk", 50.0, 0.72, 0.30, 0.22, 0.62),
    ("wolf", "goat", 45.0, 0.61, 0.50, 0.31, 0.77),
    ("wolf", "boar", 112.0, 1.00, 0.20, 0.20, 0.59),
    ("wolf", "rabbit", 19.0, 0.44, 0.50, 0.22, 0.63),
    ("bear", "boar", 30.0, 0.72, 0.20, 0.14, 0.46),
    ("fox", "rabbit", 9.0, 0.24, 0.70, 0.17, 0.52),
    ("fox", "duck", 21.0, 0.49, 0.70, 0.34, 0.81),
    ("polar_bear", "hare", 19.0, 0.35, 0.50, 0.18, 0.54),
]


@pytest.mark.parametrize(("predator", "prey", "gap", "caught", "strike", "kill", "night"), WORKED_ODDS)
def test_the_worked_odds_table(
    predator: str, prey: str, gap: float, caught: float, strike: float, kill: float, night: float
) -> None:
    assert hunt.largest_gap(SPECIES[predator], SPECIES[prey]) == pytest.approx(gap, abs=1.0)
    assert hunt.catch_odds(predator, prey) == pytest.approx(caught, abs=0.03)
    assert hunt.strike_chance(SPECIES[predator], SPECIES[prey]) == pytest.approx(strike, abs=0.03)
    assert hunt.kill_odds(predator, prey) == pytest.approx(kill, abs=0.03)
    assert hunt.kill_odds_a_night(predator, prey) == pytest.approx(night, abs=0.03)
    assert 0.14 <= hunt.kill_odds(predator, prey) <= 0.35  # the real predators' range (10 §4.6)


def _stalk(predator: str, prey: str, rng: Rng) -> bool:
    """One hunt from the stalk distance by the live sensing rule (`hunt.sense`), then the race."""
    hunter, quarry = SPECIES[predator], SPECIES[prey]
    gap = hunter.stalk_m
    while True:
        sensed = hunt.sense(gap, hunter, quarry, rng)
        if sensed == "pounce":
            return True
        if sensed == "noticed":
            seconds = hunt.race_seconds(hunter, quarry)
            return hunt.catch_time(hunt.dash(hunter), hunt.dash(quarry), gap, seconds) is not None
        gap -= hunt.stalk_step_m(hunter)


@pytest.mark.parametrize(("predator", "prey"), [(row[0], row[1]) for row in WORKED_ODDS])
def test_the_live_sensing_and_race_catch_as_often_as_the_table_says(predator: str, prey: str) -> None:
    rng = Rng.for_subsystem(5, "test.hunt")
    tries = 4000
    caught = sum(_stalk(predator, prey, rng) for _ in range(tries))
    assert caught / tries == pytest.approx(hunt.catch_odds(predator, prey), abs=0.03)


def test_the_race_catches_exactly_at_the_largest_gap() -> None:
    wolf, deer = SPECIES["wolf"], SPECIES["deer"]
    seconds = hunt.race_seconds(wolf, deer)
    assert seconds == wolf.race_s == 120.0
    # wolf 10 m/s for 30 s then 4.5; deer 11 for 20 s then 5: the wolf's lead peaks at 30 m, 30 s in
    assert hunt.catch_time(hunt.dash(wolf), hunt.dash(deer), 30.0, seconds) == pytest.approx(30.0)
    assert hunt.catch_time(hunt.dash(wolf), hunt.dash(deer), 30.5, seconds) is None
    assert hunt.catch_time(hunt.dash(wolf), hunt.dash(deer), 25.0, seconds) == pytest.approx(29.0)  # -20 at 20 s, +5/s
    assert hunt.catch_time(hunt.dash(wolf), hunt.dash(deer), 0.0, seconds) == 0.0
    # a goat reaches its cliff 15 s in: 45 m is the most a wolf closes
    goat = SPECIES["goat"]
    assert hunt.race_seconds(wolf, goat) == 15.0
    assert hunt.catch_time(hunt.dash(wolf), hunt.dash(goat), 44.0, 15.0) == pytest.approx(44.0 / 3.0)
    # a deer cornered after 40 m is caught by any wolf that can run its gap plus 40 m
    cornered = hunt.dash(deer, room_m=40.0)
    assert hunt.catch_time(hunt.dash(wolf), cornered, 100.0, seconds) == pytest.approx(14.0)
    # a winded wolf has no burst
    assert hunt.catch_time(hunt.dash(wolf, winded=True), hunt.dash(deer), 1.0, seconds) is None


def test_sensing_odds_by_gap() -> None:
    deer, wolf = SPECIES["deer"], SPECIES["wolf"]
    assert hunt.notice_chance(61.0, deer) == 0.0
    assert hunt.notice_chance(60.0, deer) == 0.15
    assert hunt.notice_chance(30.1, deer) == 0.15
    assert hunt.notice_chance(30.0, deer) == 0.30
    assert hunt.notice_chance(20.0, deer) == 1.0  # its "always senses" gap
    rng = Rng.for_subsystem(1, "test.sense")
    assert hunt.sense(wolf.pounce_m, wolf, deer, rng) == "pounce"  # unseen inside its pounce range: at once
    assert hunt.sense(wolf.pounce_m + 0.1, wolf, SPECIES["boar"], rng) in ("noticed", "unseen")
    assert hunt.stalk_step_m(wolf) == pytest.approx(0.6 * 1.2 * 10)


def test_a_dash_runs_its_burst_then_its_sustained_speed() -> None:
    run = hunt.Dash(10.0, 30.0, 4.5)
    assert run.metres(10.0) == 100.0
    assert run.metres(40.0) == 345.0
    assert run.seconds_to(345.0) == pytest.approx(40.0)
    assert run.breaks() == (30.0,)
    stopped = hunt.Dash(10.0, 30.0, 4.5, room_m=50.0)
    assert stopped.metres(60.0) == 50.0
    assert stopped.breaks() == (30.0, 5.0)
    assert math.isinf(stopped.seconds_to(51.0))
