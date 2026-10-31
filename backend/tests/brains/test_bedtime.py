"""A drink or a meal comes before sleep when the night would leave you parched or starving.

Regression (#111): at night "sleep" (and "go home" to sleep) scored 70 and a drink for a little thirst 50, so anyone
a little thirsty at bedtime went to bed; a long night asleep carried thirst past "terribly thirsty" and the sleeper
lost health for the last hours of it (seed 7, Lia: 12 health, waking parched 83 m from the river).
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import JsonValue

from app.brains.brain import BEDTIME, BEDTIME_TRIES, UtilityBrain
from app.brains.profile import BrainProfile
from app.brains.routines import Option
from app.brains.senses import NIGHT_HUNGER, NIGHT_THIRST, Needs, harmful_by_morning
from app.sim.simulation import Simulation
from app.world_api.facade import ActionHandle, WorldApi
from app.world_api.models import Driver, Perception, SelfView
from tests.sim_helpers import GATE, make_spec, skip_to

SEED = 7


def test_a_thirsty_citizen_at_bedtime_drinks_first_then_goes_home_to_sleep(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    lia = sim.add_citizen(make_spec("lia", name="Lia", at=GATE))
    lia.body.thirst = 45.0  # "a little thirsty": at most 60 by the words, ~100 after a night asleep
    lia.body.energy = 40.0
    skip_to(sim, lia.position, night=True)
    api = WorldApi(sim, lia.id)
    while api.look_around().time_of_day != "night":  # deep dusk still reads "dusk", where a drink beats the evening
        sim.state.tick += 1
    profile = BrainProfile(citizen_id=lia.id, name=lia.name, role="farmer", region="town", home_area="the town")
    brain = UtilityBrain(api, profile, SEED)
    drank_at: int | None = None
    for _ in range(240):
        brain.tick()
        sim.step()
        if drank_at is None and lia.body.thirst < 10:
            drank_at = sim.tick
        if lia.body.asleep:
            break
    assert drank_at is not None, "went to bed thirsty"
    assert lia.body.asleep
    assert lia.action is not None and lia.action.kind == "sleep"
    assert lia.body.thirst < 10


def _brain(notes: dict[str, JsonValue]) -> UtilityBrain:
    api = cast(WorldApi, SimpleNamespace(notes=notes))
    return UtilityBrain(api, BrainProfile("lia", "Lia", "gatherer", "band_a", "Band A camp"), SEED)


def _option(driver: str, score: float, started: list[str]) -> Option:
    def start() -> ActionHandle:
        started.append(driver)
        return cast(ActionHandle, None)

    return Option(score, "drink" if driver == "thirst" else "eat", start, "Get it", cast(Driver, driver))


@pytest.mark.parametrize(
    ("driver", "needs", "now", "boosted"),
    [
        ("thirst", Needs(0, 1, 0), "night", True),
        ("thirst", Needs(0, 0, 0), "night", False),  # under 30: ~84 by morning, never parched
        ("thirst", Needs(0, 1, 0), "dusk", False),  # no sleep to beat yet
        ("hunger", Needs(1, 0, 0), "night", True),
        ("hunger", Needs(0, 1, 0), "night", False),  # thirst doesn't make a meal pressing
    ],
)
def test_a_need_the_night_would_make_harmful_outscores_sleep(
    driver: str, needs: Needs, now: str, boosted: bool
) -> None:
    started: list[str] = []
    option = _option(driver, 50.0, started)
    chosen = _brain({}).before_bed(option, needs, now)
    assert (chosen.score > 70) is boosted
    assert chosen.score == (BEDTIME if boosted else 50.0)


def test_a_bedtime_drink_is_tried_only_so_often_a_night() -> None:
    notes: dict[str, JsonValue] = {}
    brain = _brain(notes)
    started: list[str] = []
    for tries in range(BEDTIME_TRIES):
        option = brain.before_bed(_option("thirst", 50.0, started), Needs(0, 1, 0), "night")
        assert option.score == BEDTIME
        assert notes.get("bedtime", 0) == tries  # counted only when chosen
        option.start()
    assert started == ["thirst"] * BEDTIME_TRIES
    assert notes["bedtime"] == BEDTIME_TRIES
    assert brain.before_bed(_option("thirst", 50.0, started), Needs(0, 1, 0), "night").score == 50.0  # sleep wins


def test_the_tries_start_afresh_after_waking(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    lia = sim.add_citizen(make_spec("lia", name="Lia", at=GATE))
    skip_to(sim, lia.position, night=False)
    profile = BrainProfile(citizen_id=lia.id, name=lia.name, role="farmer", region="town", home_area="the town")
    brain = UtilityBrain(WorldApi(sim, lia.id), profile, SEED)
    brain.api.notes.update({"asleep": True, "bedtime": BEDTIME_TRIES})
    brain.decide()
    assert "bedtime" not in brain.api.notes


def test_the_night_estimate_counts_the_worst_the_words_can_mean() -> None:
    assert harmful_by_morning(1, NIGHT_THIRST) and harmful_by_morning(1, NIGHT_HUNGER)
    assert not harmful_by_morning(0, NIGHT_THIRST) and not harmful_by_morning(0, NIGHT_HUNGER)
    assert not harmful_by_morning(1, 29.0) and harmful_by_morning(1, 30.0)


def test_a_little_hunger_at_night_offers_a_bite_before_bed() -> None:
    brain = _brain({})
    you = SelfView(feeling=["a little hungry"], carrying=["a handful of roots"], doing="You are standing about.")
    look = Perception(
        you=you, place="at your home", time="It is night.", time_of_day="night", people=[], animals=[], things=[],
        heard=[],
    )  # fmt: skip
    option = brain.hunger_option(look, Needs(1, 0, 0), "night")
    assert option is not None and option.name == "eat"
    assert brain.before_bed(option, Needs(1, 0, 0), "night").score == BEDTIME
