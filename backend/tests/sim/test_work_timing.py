"""A work task may time itself by the world (`WorkTask.timing`): its minutes now, or why it can't be done now, decided
before anything is claimed."""

from collections.abc import Callable

import pytest

from app.sim import work
from app.sim.core import SimCore
from app.sim.simulation import Simulation
from app.sim.state import Citizen
from app.sim.work import WorkTask
from app.world_api.models import Work
from tests.sim_helpers import WELL, make_spec, without_animals


@pytest.fixture
def timed(monkeypatch: pytest.MonkeyPatch) -> list[int | str]:
    """A test task "draw water" at the well whose timing answers the next value in the list."""
    answers: list[int | str] = []

    def timing(_core: SimCore, _citizen: Citizen) -> int | str:
        return answers.pop(0)

    task = WorkTask("draw water", frozenset({"draw"}), 5, None, places=("well",), done="Done.", timing=timing)
    monkeypatch.setattr(work, "WORK_TASKS", (*work.WORK_TASKS, task))
    monkeypatch.setattr(work, "WORK_BY_NAME", {**work.WORK_BY_NAME, task.name: task})
    return answers


def _sim(new_sim: Callable[..., Simulation]) -> Simulation:
    sim = without_animals(new_sim(seed=4))
    sim.add_citizen(make_spec("tek", at=WELL))
    sim.drain()
    return sim


def test_a_timed_task_lasts_the_minutes_its_timing_gives(
    new_sim: Callable[..., Simulation], timed: list[int | str]
) -> None:
    sim = _sim(new_sim)
    timed.append(42)
    number = sim.start("tek", Work(task="draw"))
    action = sim.citizen("tek").action
    assert action is not None and action.number == number and action.until_tick == sim.tick + 42


def test_a_timed_task_refuses_with_its_timing_s_reason(
    new_sim: Callable[..., Simulation], timed: list[int | str]
) -> None:
    sim = _sim(new_sim)
    timed.append("Not now.")
    number = sim.start("tek", Work(task="draw"))
    result = sim.result("tek", number)
    assert result is not None and (result.outcome, result.text) == ("failed", "Not now.")
    assert sim.citizen("tek").action is None and not timed
