"""Brains read the structured parts of a perception (time of day, kinds, nearness), not its prose."""

from typing import get_args

from app.brains.senses import (
    PHASES,
    Resource,
    afternoon,
    beside,
    fire_in_view,
    phase,
    resources_in_view,
    water_here,
    water_in_view,
    water_way,
)
from app.world_api.models import Nearness, Perception, ResourceName, Seen, SelfView, ThingKind, TimeOfDay


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


def _thing(label: str, nearness: Nearness, kind: ThingKind | None, resource: ResourceName | None = None) -> Seen:
    return Seen(label=label, where=f"{nearness} somewhere", nearness=nearness, kind=kind, resource=resource)


def _seeing(*things: Seen) -> Perception:
    return _perception("midday").model_copy(update={"things": list(things)})


def test_water_fire_and_plants_are_read_from_their_kinds_not_their_words() -> None:
    brook = _thing("a babbling brook", "right beside you", "water")
    far_brook = _thing("a babbling brook", "close by", "water")
    sea = _thing("the grey sea", "right beside you", "sea")
    named_river = _thing("a river", "right beside you", None)  # the words alone mean nothing to a brain
    assert water_here(_seeing(brook)) and water_in_view(_seeing(far_brook))
    assert not water_here(_seeing(far_brook, sea, named_river))
    assert not water_in_view(_seeing(sea, named_river))

    hearth = _thing("a ring of stones with embers", "a few paces", "fire")
    assert fire_in_view(_seeing(named_river, hearth)) == hearth
    assert fire_in_view(_seeing(_thing("the fire pit", "a few paces", "building"))) is None
    assert beside(hearth) and not beside(_thing("the fire pit", "close by", "fire"))

    plants = _seeing(
        _thing("thick reeds", "some way off", "material", "reeds"),
        _thing("a few edible roots", "right beside you", "food", "roots"),
        _thing("plenty of wood on the ground", "right beside you", "item"),  # lying about: not a plant to gather
        _thing("tall grass", "far away", "material", "wood"),
    )
    assert resources_in_view(plants) == [
        Resource("reeds", "off", True, "thick reeds"),
        Resource("roots", "here", False, "a few edible roots"),
        Resource("wood", "far", True, "tall grass"),
    ]


def test_the_way_to_the_water_is_its_compass_word() -> None:
    def water(where: str, kind: ThingKind = "water") -> Seen:
        return Seen(label="a river", where=where, nearness="close by", kind=kind)

    assert water_way(_seeing(water("close by to the north-east"))) == "north-east"  # not just "north"
    assert water_way(_seeing(water("some way off to the west"))) == "west"
    assert water_way(_seeing(water("close by to the south", "sea"))) is None  # the sea isn't drinking water
    assert water_way(_seeing(water("right beside you"))) is None
