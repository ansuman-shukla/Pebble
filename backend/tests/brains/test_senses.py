"""Brains read the structured parts of a perception (time of day, kinds, nearness), not its prose."""

from typing import get_args

from app.brains.senses import PHASES, afternoon, phase
from app.world_api.models import Perception, SelfView, TimeOfDay


def _perception(when: TimeOfDay, time: str = "Words for minds only.") -> Perception:
    you = SelfView(feeling=[], carrying=[], doing="You are standing still.")
    return Perception(
        you=you, place="somewhere", time=time, time_of_day=when, people=[], animals=[], things=[], heard=[]
    )


def test_every_time_of_day_has_a_phase() -> None:
    assert set(PHASES) == set(get_args(TimeOfDay))


def test_the_phase_comes_from_the_time_of_day_not_the_sentence() -> None:
    assert phase(_perception("sunset", "It is early morning.")) == "dusk"
    assert phase(_perception("pre-dawn")) == "night"
    assert phase(_perception("dawn")) == "morning"
    assert phase(_perception("midday")) == "day"
    assert afternoon(_perception("late afternoon", "It is mid-morning."))
    assert not afternoon(_perception("mid-morning", "It is late afternoon."))
