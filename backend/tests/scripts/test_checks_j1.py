"""J1's run checks: the bells of each whole day on time, standing in range, one leader a group."""

from collections.abc import Callable

from app.observability.events import BellRang, EventDraft
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.simulation import Simulation
from app.sim.society import SOCIETY
from scripts.checks import CHECKS, j1
from scripts.checks.base import Outcome


def _bell(tick: int, kind: str) -> EventDraft:
    payload = BellRang.model_validate({"kind": kind})
    return EventDraft(tick, tick, "bell_rang", "world", None, None, None, "public", None, payload)


def _at(day: int, minute: int) -> int:
    return day * DAY_MINUTES + minute - START_MINUTE


def test_the_bells_check_counts_each_whole_day_s_bells_rung_once_on_time(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = j1.Bells()
    check.start(sim)
    rung = [(1, 360, "dawn"), (1, 730, "noon"), (1, 1080, "dusk"), (2, 365, "dawn"), (2, 731, "noon")]
    rung += [(2, 1085, "dusk"), (2, 1090, "dusk")]  # a second dusk bell: day 2's dusk isn't "once"
    check.after_step(sim, [_bell(_at(day, minute), kind) for day, minute, kind in rung])
    sim.state.tick = _at(3, 8 * 60)  # the run ends at 08:00 on day 3: days 1 and 2 are whole
    outcome = check.outcome(sim)
    assert outcome == Outcome(
        1 - 2 / 6, False, "4/6 on time, missed day 2 noon, day 2 dusk, off time day 2 noon at 12:11"
    )
    assert j1.Bells in CHECKS


def test_the_standing_and_leaders_checks_hold_for_the_cast_and_catch_a_second_leader(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    standing, leaders = j1.Standing(), j1.Leaders()
    for check in (standing, leaders):
        check.start(sim)
    sim.step()
    events = sim.drain()
    standing.after_step(sim, events)
    leaders.after_step(sim, events)
    assert standing.outcome(sim).ok and leaders.outcome(sim) == Outcome(0, True, "none changed")
    SOCIETY.of(sim.state).members["tek"].titles.append("leader")
    SOCIETY.of(sim.state).standing["kaz"]["town"] = 101
    standing.after_step(sim, [])
    leaders.after_step(sim, [])
    assert standing.outcome(sim) == Outcome(1, False, "kaz 101 with town at tick 1")
    assert leaders.outcome(sim) == Outcome(1, False, "band_a led by ['ama', 'tek'] at tick 1")
