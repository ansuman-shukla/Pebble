"""Walking at the body's speed in the simulation (10-world-v1 §4.1): gaits, factors, pace, run endurance, caps."""

import random
from collections.abc import Callable

import pytest

from app.sim import movement
from app.sim.core import Stride
from app.sim.locomotion import load_bodies
from app.sim.navigation import Route
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.sim.state import AgeGroup, Citizen, Fire
from app.sim.vec import bearing_deg, step_towards
from app.world_api.facade import WorldApi
from tests.sim_helpers import add_animal, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

CAPS_M = {"walk": 84.0, "jog": 150.0, "run": 210.0, "stalk": 48.0}
AGES: dict[AgeGroup, int] = {"child": 8, "teen": 15, "young_adult": 25, "middle_aged": 45, "elder": 70}


def _walker(
    new_sim: Callable[..., Simulation], group: AgeGroup = "young_adult", night: bool = False, **spec: object
) -> tuple[Simulation, Citizen]:
    sim = without_animals(new_sim())
    citizen = sim.add_citizen(make_spec("kenji", name="Kenji", age=AGES[group], home=None, **spec))
    put_in_the_wild(sim, citizen.id, wild_cell(sim, flat_m=2.0))
    skip_to(sim, citizen.position, night=night)
    return sim, citizen


def _walk(sim: Simulation, citizen: Citizen, pace: str = "walk") -> None:
    """A long walk north over flat open ground (one leg costing 1 a metre) at the pace."""
    WorldApi(sim, citizen.id).walk_towards("north", "a long walk")
    walk = citizen.action
    assert walk is not None
    far = step_towards(citizen.position, 0.0, 2000.0, sim.world.radius_m)
    walk.route, walk.leg, walk.along_m = Route(points=(citizen.position, far), costs=(1.0,)), 0, 0.0
    walk.args["pace"] = pace  # C1's contract v1 adds `pace` to walk_to


def _flee(sim: Simulation, citizen: Citizen) -> None:
    """Flee a sleeping wolf 40 m east, the route stretched to 2 km of flat open ground so the run can outlast the
    endurance."""
    spot = step_towards(citizen.position, 90.0, 40.0, sim.world.radius_m)
    wolf = add_animal(sim, "wolf", spot, activity="sleeping", until=10**9)
    WorldApi(sim, citizen.id).flee()
    flee = citizen.action
    assert flee is not None and flee.kind == "flee"
    away = bearing_deg(wolf.position, citizen.position)
    far = step_towards(citizen.position, away, 2000.0, sim.world.radius_m)
    flee.route, flee.leg, flee.along_m = Route(points=(citizen.position, far), costs=(1.0,)), 0, 0.0


def _stride(sim: Simulation, citizen: Citizen) -> Stride:
    sim.step()
    return sim.core.strides[citizen.id]


def _metres(sim: Simulation, stride: Stride) -> float:
    spots = [unit for unit, _ in stride.walked]
    return sum(sim.world.distance_m(a, b) for a, b in zip(spots, spots[1:], strict=False))


def _mps(sim: Simulation, stride: Stride) -> float:
    return _metres(sim, stride) / stride.walked[-1][1]


def test_an_adult_walks_1_4_metres_a_second_on_flat_ground_by_day(new_sim: Callable[..., Simulation]) -> None:
    sim, citizen = _walker(new_sim)
    _walk(sim, citizen)
    stride = _stride(sim, citizen)
    assert stride.gait == "walk"
    assert _metres(sim, stride) == pytest.approx(84.0, abs=0.05)  # a whole minute on flat ground
    assert stride.walked[-1][1] == pytest.approx(60.0)


@pytest.mark.parametrize(
    ("group", "wood_kg", "factor"),
    [
        ("elder", 0, 0.6),
        ("child", 0, 0.7),
        ("middle_aged", 0, 0.9),
        ("young_adult", 12, 1.0),  # 12 of 25 kg: under half
        ("young_adult", 13, 0.85),  # over half: walking carrying
        ("young_adult", 23, 0.7),  # 92 %
    ],
)
def test_age_and_load_slow_the_walk(
    new_sim: Callable[..., Simulation], group: AgeGroup, wood_kg: int, factor: float
) -> None:
    sim, citizen = _walker(new_sim, group, inventory={"wood": wood_kg} if wood_kg else {})
    _walk(sim, citizen)
    assert _mps(sim, _stride(sim, citizen)) == pytest.approx(1.4 * factor, rel=1e-3)


def test_health_energy_and_the_dark_slow_the_walk(new_sim: Callable[..., Simulation]) -> None:
    for need, value, factor in (("health", 45.0, 0.85), ("health", 15.0, 0.5), ("energy", 8.0, 0.5)):
        sim, citizen = _walker(new_sim)
        setattr(citizen.body, need, value)
        _walk(sim, citizen)
        assert _mps(sim, _stride(sim, citizen)) == pytest.approx(1.4 * factor, rel=1e-3)
    sim, citizen = _walker(new_sim, night=True)
    _walk(sim, citizen)
    assert _mps(sim, _stride(sim, citizen)) == pytest.approx(1.4 * 0.8, rel=1e-3)


def test_a_lit_fire_close_by_lifts_the_night_slowdown(new_sim: Callable[..., Simulation]) -> None:
    sim, citizen = _walker(new_sim, night=True)
    camp = Fire(id="fire:5", kind="campfire", position=citizen.position, cell=citizen.cell, height_m=citizen.height_m)
    camp.fuel, camp.lit, camp.level = 120, True, 3
    sim.state.fires[camp.id] = camp
    _walk(sim, citizen)
    assert _mps(sim, _stride(sim, citizen)) == pytest.approx(1.4, rel=1e-3)


def test_a_run_lasts_three_minutes_then_jogs_and_comes_back_with_rest(new_sim: Callable[..., Simulation]) -> None:
    sim, citizen = _walker(new_sim)
    _walk(sim, citizen, "run")
    strides = [_stride(sim, citizen) for _ in range(5)]
    assert [s.gait for s in strides] == ["run", "run", "run", "jog", "jog"]
    assert _metres(sim, strides[0]) == pytest.approx(210.0, abs=0.1)
    assert _metres(sim, strides[3]) == pytest.approx(150.0, abs=0.1)
    assert movement.run_left_s(sim.core, citizen) == 0.0  # jogging doesn't get it back...
    _walk(sim, citizen, "walk")
    assert [_stride(sim, citizen).gait for _ in range(2)] == ["walk", "walk"]
    assert movement.run_left_s(sim.core, citizen) == 60.0  # ...two minutes of walking give a minute of running
    _walk(sim, citizen, "run")
    assert [_stride(sim, citizen).gait for _ in range(3)] == ["run", "jog", "jog"]


def test_a_fleeing_adult_runs_until_the_endurance_is_spent_then_jogs(new_sim: Callable[..., Simulation]) -> None:
    sim, citizen = _walker(new_sim)
    _flee(sim, citizen)
    strides = [_stride(sim, citizen) for _ in range(4)]
    assert [s.gait for s in strides] == ["run", "run", "run", "jog"]
    assert _metres(sim, strides[0]) == pytest.approx(210.0, abs=0.1)


def test_a_fleeing_elder_jogs(new_sim: Callable[..., Simulation]) -> None:
    sim, citizen = _walker(new_sim, "elder")
    _flee(sim, citizen)
    stride = _stride(sim, citizen)
    assert stride.gait == "jog"
    assert _mps(sim, stride) <= 2.0


def test_a_runner_spends_energy_and_gets_thirsty_twice_as_fast(new_sim: Callable[..., Simulation]) -> None:
    changes = {}
    for pace in ("jog", "run"):  # jogging costs what walking does
        sim, citizen = _walker(new_sim)
        _walk(sim, citizen, "run")
        if pace == "jog":
            movement.RUNNING.of(sim.state)[citizen.id] = 0.0
        before = (citizen.body.energy, citizen.body.thirst)
        sim.step()
        changes[pace] = (citizen.body.energy - before[0], citizen.body.thirst - before[1])
    run = load_bodies().run
    assert changes["run"][0] == pytest.approx(changes["jog"][0] - run.energy_per_minute)
    assert changes["run"][1] == pytest.approx(changes["jog"][1] * run.thirst_rate)


def test_children_elders_and_heavy_loads_jog_at_most(new_sim: Callable[..., Simulation]) -> None:
    for group, wood in (("child", 0), ("elder", 0), ("young_adult", 23)):
        sim, citizen = _walker(new_sim, group, inventory={"wood": wood} if wood else {})  # type: ignore[arg-type]
        _walk(sim, citizen, "run")
        stride = _stride(sim, citizen)
        assert stride.gait == "jog"
        assert _mps(sim, stride) <= 2.0 or group == "young_adult"


def test_running_endurance_survives_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim, citizen = _walker(new_sim)
    _walk(sim, citizen, "run")
    _stride(sim, citizen)
    restored = restore(take_snapshot(sim.state))
    assert movement.RUNNING.of(restored) == {citizen.id: 120.0}


def test_nobody_moves_further_in_a_tick_than_their_gait_allows(new_sim: Callable[..., Simulation]) -> None:
    rng = random.Random(7)
    for trial in range(12):
        group: AgeGroup = rng.choice(list(AGES))
        sim, citizen = _walker(new_sim, group, night=rng.random() < 0.3)
        citizen.body.health = rng.choice([100.0, 45.0, 15.0])
        citizen.body.energy = rng.choice([100.0, 8.0])
        _walk(sim, citizen, rng.choice(["walk", "run"]))
        for _ in range(6):
            start = citizen.position
            stride = _stride(sim, citizen)
            moved = sim.world.distance_m(start, citizen.position)
            assert moved <= _metres(sim, stride) + 1e-6 <= CAPS_M[stride.gait] * 1.01, (trial, group, stride.gait)
            if group == "elder":
                assert _mps(sim, stride) <= 2.0
            if citizen.action is None:
                break


def test_the_dark_doesnt_slow_anyone_inside_the_town(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    citizen = sim.add_citizen(make_spec("kenji", name="Kenji", at=(0.0, 120.0), home=None))
    skip_to(sim, citizen.position, night=True)
    _walk(sim, citizen)
    assert _mps(sim, _stride(sim, citizen)) == pytest.approx(1.4, rel=1e-3)
