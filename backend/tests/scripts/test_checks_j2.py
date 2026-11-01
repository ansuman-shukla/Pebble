"""J2's run checks: the held kept close, custody within 12 h, judgements on known grounds, sentences and tends."""

from collections.abc import Callable

from app.observability.events import EventDraft, EventType, Judged, Payload, SentenceServed, Tended
from app.sim import justice
from app.sim.clock import TICKS_PER_HOUR
from app.sim.simulation import Simulation
from app.sim.society import SOCIETY
from scripts.checks import CHECKS, j2
from scripts.checks.base import Outcome
from tests.sim_helpers import make_spec


def _event(tick: int, kind: EventType, actor: str, payload: Payload) -> EventDraft:
    return EventDraft(tick, tick, kind, "citizen", actor, None, None, "public", None, payload)


def _pair(new_sim: Callable[..., Simulation]) -> Simulation:
    sim = new_sim()
    sim.add_citizen(make_spec("goro", at=(-30.0, 50.0)))
    sim.add_citizen(make_spec("kaz", at=(-31.0, 50.0)))
    return sim


def test_the_held_close_check_catches_a_held_person_over_3_m_off(new_sim: Callable[..., Simulation]) -> None:
    sim = _pair(new_sim)
    check = j2.HeldClose()
    check.start(sim)
    justice.JUSTICE.of(sim.state).custody["kaz"] = justice.Custody(since=0, keeper="goro")
    check.after_step(sim, [])
    assert check.outcome(sim) == Outcome(0, True, "1 held ticks, all within 3 m")
    sim.core.place_at(sim.citizen("kaz"), sim.world.town.to_unit(-33.5, 50.0))
    check.after_step(sim, [])
    assert check.outcome(sim) == Outcome(1, False, "kaz 3.5 m from goro at tick 0")
    assert all(row in CHECKS for row in j2.CHECKS)


def test_the_custody_check_fails_past_twelve_hours(new_sim: Callable[..., Simulation]) -> None:
    sim = _pair(new_sim)
    check = j2.Custody()
    check.start(sim)
    justice.JUSTICE.of(sim.state).custody["kaz"] = justice.Custody(since=0, keeper=None, place="gaol")
    sim.state.tick = 12 * TICKS_PER_HOUR
    check.after_step(sim, [])
    assert check.outcome(sim).ok
    sim.state.tick += 1
    check.after_step(sim, [])
    assert check.outcome(sim) == Outcome(12 + 1 / 60, False, "0 released, longest 12.0 h")


def test_the_grounds_check_wants_a_known_deed_or_arrears(new_sim: Callable[..., Simulation]) -> None:
    sim = _pair(new_sim)
    check = j2.Grounds()
    check.start(sim)
    SOCIETY.of(sim.state).known["goro"] = [5]
    check.after_step(sim, [_event(1, "judged", "goro", Judged(person="kaz", sentence="fine", fine_mon=5, deeds=[5]))])
    check.after_step(
        sim, [_event(2, "judged", "goro", Judged(person="kaz", sentence="fine", fine_mon=5, arrears=True))]
    )
    assert check.outcome(sim) == Outcome(0, True, "2 judgements, all on known grounds")
    check.after_step(sim, [_event(3, "judged", "goro", Judged(person="kaz", sentence="fine", fine_mon=5))])
    check.after_step(sim, [_event(4, "judged", "goro", Judged(person="kaz", sentence="fine", fine_mon=5, deeds=[6]))])
    assert check.outcome(sim) == Outcome(2, False, "goro judged kaz at tick 3")


def test_sentences_served_and_tends_are_summed_over_the_seeds(new_sim: Callable[..., Simulation]) -> None:
    sim = _pair(new_sim)
    served, tends = j2.Served(), j2.Tends()
    for check in (served, tends):
        check.start(sim)
        check.after_step(sim, [_event(1, "sentence_served", "kaz", SentenceServed(sentence="fine"))])
        check.after_step(sim, [_event(1, "tended", "goro", Tended(person="kaz", health=1.5))])
    assert served.outcome(sim) == Outcome(1, False, "1 sentences served")
    assert tends.outcome(sim) == Outcome(1, False, "1 tended")
    assert j2.Served.overall({1: Outcome(1, False, ""), 7: Outcome(1, False, "")}).ok
    assert not j2.Tends.overall({1: Outcome(1, False, ""), 7: Outcome(0, False, "")}).ok
    assert j2.Served.pending is not None and j2.Tends.pending is not None
    assert j2.HeldClose.pending is None and j2.Custody.pending is None and j2.Grounds.pending is None
