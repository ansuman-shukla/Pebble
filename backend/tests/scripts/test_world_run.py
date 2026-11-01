"""The run harness: which seeds and checks a world run uses, and how each check sees the run."""

import argparse
from collections.abc import Callable
from typing import override

import pytest

from app.observability.events import EventDraft
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from scripts import world_run
from scripts.checks import CHECKS, x0
from scripts.checks.base import Check, Outcome
from scripts.world_run import SWEEP_SEEDS, main, parse_seeds, run_seed, select
from tests.sim_helpers import make_spec


class Recorder(Check):
    name = "test.recorder"

    @override
    def start(self, sim: Simulation) -> None:
        self.calls = [f"start {sim.tick}"]
        self.citizens = len(sim.state.citizens)

    @override
    def before_step(self, sim: Simulation) -> None:
        self.calls.append(f"before {sim.tick}")

    @override
    def after_step(self, sim: Simulation, events: list[EventDraft]) -> None:
        self.calls.append(f"after {sim.tick} {events[-1].type}")

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(len(self.calls), True, f"{self.citizens} citizens, {' | '.join(self.calls[:4])}")


class Failing(Check):
    name = "test.failing"

    @override
    def outcome(self, sim: Simulation) -> Outcome:
        return Outcome(1, False, "always")


def test_seeds_are_a_list_or_a_count_of_sweep_seeds() -> None:
    assert parse_seeds("20261028,7") == (20261028, 7)
    assert parse_seeds("7,") == (7,)
    assert parse_seeds("5") == SWEEP_SEEDS[:5] == (20261028, 7, 1, 2, 3)
    for bad in ("0", str(len(SWEEP_SEEDS) + 1)):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_seeds(bad)


def test_only_picks_checks_by_name_or_stream() -> None:
    assert select(CHECKS, None) == list(CHECKS)
    assert select(CHECKS, "x0") == list(x0.CHECKS)
    assert select(CHECKS, "x0.deaths, x0.stall") == [x0.Stall, x0.Deaths]
    with pytest.raises(SystemExit):
        select(CHECKS, "x0.nothing")
    assert len({check.name for check in CHECKS}) == len(CHECKS)


def test_each_check_sees_every_tick_of_its_seeds_run(planner: Planner) -> None:
    outcomes = run_seed(7, 1, [Recorder, x0.Deaths, x0.Actions, x0.Stall, x0.NeedDamage], planner)
    recorded = outcomes["test.recorder"]
    assert recorded.value == 1 + 2 * DAY_MINUTES
    cast = len(load_citizens(CITIZENS).citizens)
    assert recorded.words == f"{cast} citizens, start 0 | before 0 | after 1 tick_summary | before 1"
    assert outcomes["x0.deaths"] == Outcome(0, True, "none")
    actions = outcomes["x0.actions"]  # a day uses every required one; the lucky ones are only reported
    assert actions.ok and set(actions.words.split(", ")) <= x0.LUCKY_ACTIONS | {"all used"}
    assert 0 < outcomes["x0.stall"].value < x0.MAX_STALL_H and outcomes["x0.stall"].ok
    assert outcomes["x0.need_damage"].ok


def test_the_overall_verdict_needs_every_seed_to_pass() -> None:
    passing, failing = Outcome(2.0, True, "a"), Outcome(7.0, False, "b")
    assert x0.Stall.overall({1: passing, 2: passing}) == Outcome(2.0, True, "2/2 seeds pass, worst 2")
    assert x0.Stall.overall({1: passing, 2: failing}) == Outcome(7.0, False, "1/2 seeds pass, worst 7")


def test_a_run_prints_and_exits_by_its_checks(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["--days", "1", "--seeds", "7,", "--only", "x0.deaths"]) == 0
    out = capsys.readouterr().out
    assert "seed 7: x0.deaths none" in out and "ok   x0.deaths" in out
    monkeypatch.setattr(world_run, "CHECKS", (Failing,))
    assert main(["--days", "1", "--seeds", "7,"]) == 1
    assert "FAIL test.failing" in capsys.readouterr().out


class Waiting(Failing):
    name = "test.waiting"
    pending = "another stream"


def test_a_pending_check_is_printed_but_does_not_fail_the_run(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(world_run, "CHECKS", (Waiting,))
    assert main(["--days", "1", "--seeds", "7,"]) == 0
    out = capsys.readouterr().out
    assert "pending (another stream) test.waiting" in out and "FAIL" not in out
    monkeypatch.setattr(world_run, "CHECKS", (Waiting, Failing))
    assert main(["--days", "1", "--seeds", "7,"]) == 1


def test_the_threat_checks_wait_for_the_exposure_schedules() -> None:
    pending = {check.name for check in CHECKS if check.pending is not None}
    assert {"a1.approaches", "a1.attacks", "a1.den_charges", "a1.people_flights"} <= pending
    assert "a1.kills" not in pending and "a1.herds_kept" not in pending


def test_the_home_ring_check_waits_for_band_trips_and_the_node_checks_count() -> None:
    pending = {check.name: check.pending for check in CHECKS if check.pending is not None}
    assert pending["n1.home_ring"] == "BR2 band trips"
    assert not {"n1.reach", "n1.in_paddies", "n1.regrowing"} & pending.keys()


def test_a_death_fails_the_deaths_check(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    victim = sim.add_citizen(make_spec("victim"))
    check = x0.Deaths()
    check.start(sim)
    sim.core.injure(victim, 200.0, "animal attack", "a wolf attacks you")
    check.after_step(sim, sim.drain())
    assert check.outcome(sim) == Outcome(1, False, "victim")


def test_stall_and_need_damage_read_none_until_something_happens(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    idle = sim.add_citizen(make_spec("idle"))
    stall, damage = x0.Stall(), x0.NeedDamage()
    stall.start(sim)
    damage.start(sim)
    assert stall.outcome(sim) == Outcome(0.0, True, "none")
    assert damage.outcome(sim) == Outcome(0.0, True, "none")
    stall.before_step(sim)
    damage.before_step(sim)
    sim.step()
    idle.body.health -= 2.5  # as if hunger took it this tick
    events = sim.drain()
    stall.after_step(sim, events)
    damage.after_step(sim, events)
    assert stall.outcome(sim).words == "0.0 h (idle)"
    assert damage.outcome(sim) == Outcome(2.5, True, "2.5 health (idle)")
