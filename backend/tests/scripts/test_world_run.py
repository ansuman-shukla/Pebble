"""The run harness: which seeds and checks a world run uses, and how each check sees the run."""

import argparse
from typing import override

import pytest

from app.observability.events import EventDraft
from app.sim.clock import DAY_MINUTES
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from scripts.checks import CHECKS, x0
from scripts.checks.base import Check, Outcome
from scripts.world_run import SWEEP_SEEDS, main, parse_seeds, run_seed, select


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
    assert recorded.words == "15 citizens, start 0 | before 0 | after 1 tick_summary | before 1"
    assert outcomes["x0.deaths"] == Outcome(0, True, "none")
    assert not outcomes["x0.actions"].ok and "make_fire" not in outcomes["x0.actions"].words  # a day uses some
    assert 0 < outcomes["x0.stall"].value < x0.MAX_STALL_H and outcomes["x0.stall"].ok
    assert outcomes["x0.need_damage"].ok


def test_the_overall_verdict_needs_every_seed_to_pass() -> None:
    passing, failing = Outcome(2.0, True, "a"), Outcome(7.0, False, "b")
    assert x0.Stall.overall({1: passing, 2: passing}) == Outcome(2.0, True, "2/2 seeds pass, worst 2")
    assert x0.Stall.overall({1: passing, 2: failing}) == Outcome(7.0, False, "1/2 seeds pass, worst 7")


def test_a_run_prints_and_exits_by_its_checks(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--days", "1", "--seeds", "7,", "--only", "x0.deaths"]) == 0
    out = capsys.readouterr().out
    assert "seed 7: x0.deaths none" in out and "ok   x0.deaths" in out
    assert main(["--days", "1", "--seeds", "7,", "--only", "x0.actions"]) == 1
    assert "FAIL x0.actions" in capsys.readouterr().out
