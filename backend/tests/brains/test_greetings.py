"""Brains greet and answer only people near enough to hear a normal voice (03: speech carries ~30 m).

Regression (#25): brains greeted anyone known up to "close by" (under 50 m), so about one greeting in seven went to
someone out of earshot and nobody heard it. They don't shout instead: a shout carries 150 m and stops everyone's
work and sleep there.
"""

from collections.abc import Callable

import pytest

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.observability.events import Said
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec

SEED = 7
ROAD = (0.0, 150.0)  # on the approach road; the road and main street run north from here


def _north_of_aiko(apart_m: float) -> tuple[float, float]:
    return (ROAD[0], ROAD[1] - apart_m)


Pair = Callable[[float], tuple[Simulation, UtilityBrain, WorldApi]]


@pytest.fixture
def pair(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> Pair:
    """Aiko (a brain) on the approach road and Bo (driven by the test) `apart_m` north of her; they know each other."""

    def build(apart_m: float) -> tuple[Simulation, UtilityBrain, WorldApi]:
        sim = new_sim()
        aiko = sim.add_citizen(make_spec("aiko", at=ROAD, knows_people=["bo"]))
        bo = sim.add_citizen(make_spec("bo", at=_north_of_aiko(apart_m), knows_people=["aiko"]))
        profile = BrainProfile(citizen_id=aiko.id, name=aiko.name, role="farmer", region="town", home_area="the town")
        brain = UtilityBrain(WorldApi(sim, aiko.id), profile, SEED)
        monkeypatch.setattr(brain, "chance", lambda _odds: True)  # always greet: the test is about who
        sim.drain()
        return sim, brain, WorldApi(sim, bo.id)

    return build


def _said(sim: Simulation) -> list[Said]:
    return [event.payload for event in sim.drain() if isinstance(event.payload, Said)]


def test_a_greeting_reaches_the_person_greeted(pair: Pair) -> None:
    sim, aiko, _ = pair(10.0)
    assert aiko.socialise(aiko.api.look_around())
    [said] = _said(sim)
    assert "Bo" in said.words
    assert (said.volume, said.heard_by) == ("normal", ["bo"])


@pytest.mark.parametrize(("apart_m", "nearness"), [(40.0, "close by"), (100.0, "some way off")])
def test_nobody_out_of_earshot_is_greeted(pair: Pair, apart_m: float, nearness: str) -> None:
    sim, aiko, _ = pair(apart_m)
    seen = aiko.api.look_around()
    assert [(person.label, person.nearness) for person in seen.people] == [("Bo", nearness)]
    assert not aiko.socialise(seen)
    assert _said(sim) == []


def test_a_reply_reaches_the_greeter_or_waits_until_they_are_near_again(pair: Pair) -> None:
    sim, aiko, bo = pair(10.0)
    bo.say("Good morning, Aiko!")
    sim.drain()
    assert aiko.socialise(aiko.api.look_around())
    [reply] = _said(sim)
    assert "Bo" in reply.words
    assert (reply.volume, reply.heard_by) == ("normal", ["bo"])

    sim, aiko, bo = pair(10.0)
    bo.say("Good morning, Aiko!")
    sim.drain()
    sim.core.place_at(sim.citizen("bo"), sim.world.town.to_unit(*_north_of_aiko(40.0)))
    assert not aiko.socialise(aiko.api.look_around())  # gone out of earshot: no answer into thin air
    assert _said(sim) == []
    greeted = aiko.api.notes["greeted"]
    assert isinstance(greeted, list) and "Bo" not in greeted  # still greeted when they come near again
