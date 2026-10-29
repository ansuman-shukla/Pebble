import itertools

import pytest

from app.sim.locomotion import body_factor, gait_for, gait_mps, load_bodies, night_factor, top_gait
from app.sim.state import AGE_GROUPS, AgeGroup, Body, Citizen

CAPS_M_PER_TICK = {"walk": 84.0, "jog": 150.0, "run": 210.0}  # 10-world-v1 §4.1 hard caps


def _citizen(group: AgeGroup = "young_adult", health: float = 100.0, energy: float = 100.0) -> Citizen:
    return Citizen(
        id="kenji",
        name="Kenji",
        look="town-farmer",
        appearance="a man",
        age=30,
        group=group,
        home=None,
        position=(0.0, 0.0, 1.0),
        cell=0,
        height_m=0.0,
        body=Body(health=health, energy=energy),
    )


def test_gaits_follow_the_speed_table() -> None:
    assert {gait: gait_mps(gait) for gait in ("walk", "jog", "run", "stalk")} == {
        "walk": 1.4,
        "jog": 2.5,
        "run": 3.5,
        "stalk": 0.8,
    }
    for gait, cap in CAPS_M_PER_TICK.items():
        assert gait_mps(gait) * 60 <= cap  # type: ignore[arg-type]


def test_each_factor_slows_the_body() -> None:
    assert body_factor(_citizen(), 0.0) == 1.0
    assert body_factor(_citizen("elder"), 0.0) == 0.6
    assert body_factor(_citizen("child"), 0.0) == 0.7
    assert body_factor(_citizen("middle_aged"), 0.0) == 0.9
    assert body_factor(_citizen(), 0.49) == 1.0
    assert body_factor(_citizen(), 0.5) == 0.85  # walking carrying
    assert body_factor(_citizen(), 0.89) == 0.85
    assert body_factor(_citizen(), 0.9) == 0.7
    assert body_factor(_citizen(), 1.0) == 0.7
    assert body_factor(_citizen(health=51), 0.0) == 1.0
    assert body_factor(_citizen(health=50), 0.0) == 0.85
    assert body_factor(_citizen(health=21), 0.0) == 0.85
    assert body_factor(_citizen(health=20), 0.0) == 0.5  # limping
    assert body_factor(_citizen(energy=11), 0.0) == 1.0
    assert body_factor(_citizen(energy=10), 0.0) == 0.5  # exhausted
    assert night_factor(dark_outside=True) == 0.8
    assert night_factor(dark_outside=False) == 1.0


def test_factors_multiply() -> None:
    assert body_factor(_citizen("elder", health=20, energy=5), 0.9) == pytest.approx(0.6 * 0.7 * 0.5 * 0.5)


def test_children_elders_and_heavy_loads_never_run() -> None:
    assert top_gait(_citizen(), 0.0) == "run"
    assert top_gait(_citizen("teen"), 0.89) == "run"
    assert top_gait(_citizen("middle_aged"), 0.0) == "run"
    assert top_gait(_citizen("elder"), 0.0) == "jog"
    assert top_gait(_citizen("child"), 0.0) == "jog"
    assert top_gait(_citizen(), 0.9) == "jog"


def test_a_run_lasts_while_the_endurance_does_then_jogs() -> None:
    assert gait_for("walk", "run", 180.0) == "walk"
    assert gait_for("run", "run", 180.0) == "run"
    assert gait_for("run", "run", 60.0) == "run"  # a whole minute of running left
    assert gait_for("run", "run", 59.0) == "jog"
    assert gait_for("run", "run", 0.0) == "jog"
    assert gait_for("run", "jog", 180.0) == "jog"
    assert gait_for("walk", "jog", 0.0) == "walk"
    run = load_bodies().run
    assert (run.endurance_s, run.energy_per_minute, run.thirst_rate) == (180.0, 1.0, 2.0)


def test_nobody_outruns_their_cap_and_elders_stay_under_two_metres_a_second() -> None:
    for group, share, health, energy, pace in itertools.product(
        AGE_GROUPS, (0.0, 0.5, 0.9), (100.0, 50.0, 20.0), (100.0, 10.0), ("walk", "run")
    ):
        citizen = _citizen(group, health, energy)
        gait = gait_for(pace, top_gait(citizen, share), 180.0)  # type: ignore[arg-type]
        speed = gait_mps(gait) * body_factor(citizen, share)
        assert speed * 60 <= CAPS_M_PER_TICK[gait]
        if group == "elder":
            assert speed <= 2.0
