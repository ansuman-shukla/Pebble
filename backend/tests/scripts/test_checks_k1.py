"""K1's run checks: looks stay in-world words and their sight lines within the budget at the median."""

from collections.abc import Callable

from app.observability.events import EventDraft, Perceived
from app.sim.simulation import Simulation
from scripts.checks import CHECKS, k1
from scripts.checks.base import Outcome

QUIET = "You are at the well. It is midday.\nYou feel fine.\nYou see Aiko a few paces to the north."
BUSY = QUIET + "\nAnimals: two deer close by to the east (grazing).\nAround you: the well right beside you."


def _look(text: str, kind: str = "look_around") -> EventDraft:
    payload = Perceived.model_validate({"kind": kind, "text": text})
    return EventDraft(1, 1, "perceived", "citizen", "aiko", None, None, "private", None, payload)


def test_the_sight_lines_are_counted_without_their_leading_words() -> None:
    assert k1.sight_words(QUIET) == len("Aiko a few paces to the north.".split())
    assert k1.sight_words(BUSY) == 7 + 8 + 5


def test_the_look_words_check_takes_the_median_awake_look(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = k1.LookWords()
    check.start(sim)
    assert check.outcome(sim) == Outcome(0.0, False, "nobody looked around")
    asleep = "You are asleep. It is midnight.\n" + "You see " + "Aiko and Tek, " * 100
    check.after_step(sim, [_look(QUIET), _look(BUSY), _look(BUSY), _look(asleep), _look(BUSY * 9, "check_self")])
    outcome = check.outcome(sim)
    assert (outcome.value, outcome.ok) == (20, True)
    assert outcome.words == f"median 20 sight words, {len(BUSY.split())} in all, 3 looks"
    crowd = "You see " + "Aiko and Tek a few paces to the north; " * 20
    check.after_step(sim, [_look(crowd)] * 4)
    assert not check.outcome(sim).ok
    assert k1.LookWords in CHECKS and k1.InWorldWords in CHECKS


def test_a_digit_or_an_id_in_any_look_or_self_check_fails(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = k1.InWorldWords()
    check.start(sim)
    check.after_step(sim, [_look(QUIET), _look("You carry seven coins.", "check_self")])
    assert check.outcome(sim) == Outcome(0, True, "0 of 2 leak")
    for leak in ("You carry 7 coins.", "You see main-w-3 close by.", "You are at band_a_camp."):
        check.after_step(sim, [_look(leak, "check_self")])
    outcome = check.outcome(sim)
    assert (outcome.value, outcome.ok) == (3, False)
    assert outcome.words.startswith("3 of 5 leak: 'You carry 7 coins.'")
    overall = k1.InWorldWords.overall({1: Outcome(0, True, ""), 2: outcome})
    assert (overall.value, overall.ok) == (3, False)
    assert k1.InWorldWords.overall({1: Outcome(0, True, ""), 2: Outcome(0, True, "")}).ok
