"""Gestures and goals (contract v1, 10 §6.1): a gesture is seen within sight and never heard; a goal is told to
spectators only. Both are instant: no tick passes and what the citizen is doing goes on."""

from collections.abc import Callable

from app.observability.events import EventDraft, Gestured, GoalSet
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from app.world_api.models import ActionResult, Gesture, SetGoal
from tests.sim_helpers import WELL, make_spec, skip_to

NEAR = (WELL[0] + 6.0, WELL[1])
OUT_OF_SIGHT = (-20.0, -140.0)  # ~190 m north of the well


def _town(new_sim: Callable[..., Simulation]) -> tuple[Simulation, WorldApi]:
    """Ann at the well by day, Bob (known to her) beside her, Carl out of sight and Dora asleep close by."""
    sim = new_sim()
    ann = sim.add_citizen(make_spec("ann", at=WELL))
    bob = sim.add_citizen(make_spec("bob", at=NEAR))
    sim.add_citizen(make_spec("carl", at=OUT_OF_SIGHT))
    dora = sim.add_citizen(make_spec("dora", at=(WELL[0], WELL[1] + 5.0)))
    ann.people.add(bob.id)
    skip_to(sim, ann.position, night=False)
    dora.body.energy = 20.0
    WorldApi(sim, dora.id).sleep()
    assert dora.body.asleep
    sim.drain()
    return sim, WorldApi(sim, ann.id)


def _text(outcome: object) -> str:
    assert isinstance(outcome, ActionResult)  # instant actions answer at once
    return outcome.text


def _payloads[P](events: list[EventDraft], kind: str, model: type[P]) -> list[P]:
    found = [event.payload for event in events if event.type == kind]
    assert all(isinstance(payload, model) for payload in found)
    return [payload for payload in found if isinstance(payload, model)]


def test_a_gesture_is_seen_by_everyone_awake_in_sight(new_sim: Callable[..., Simulation]) -> None:
    sim, ann = _town(new_sim)
    resting = ann.rest(30)
    tick = sim.tick
    assert ann.gesture("wave", "Bob") == ActionResult(action="gesture", outcome="done", text="You wave to Bob.")
    events = sim.drain()
    (event,) = [event for event in events if event.type == "gestured"]
    assert event.payload == Gestured(kind="wave", to="bob", seen_by=["bob"])  # not Carl (too far), not Dora (asleep)
    assert (event.actor_id, event.visibility, event.tick) == ("ann", "public", tick)
    assert sim.tick == tick and not resting.done
    action = sim.citizen("ann").action
    assert action is not None and action.number == resting.number
    assert all(citizen.heard == [] for citizen in sim.state.citizens.values())  # seen, never heard
    assert sim.citizen("dora").body.asleep


def test_a_gesture_to_someone_out_of_sight_is_refused_and_unseen(new_sim: Callable[..., Simulation]) -> None:
    sim, ann = _town(new_sim)
    result = ann.gesture("bow", "Carl")
    assert result == ActionResult(action="gesture", outcome="failed", text="You don't see anyone like that.")
    assert _payloads(sim.drain(), "gestured", Gestured) == []


def test_gestures_are_said_by_kind_and_strangers_by_how_they_look(new_sim: Callable[..., Simulation]) -> None:
    sim, ann = _town(new_sim)
    texts = [
        ann.gesture("shake_head", "a person in a dora cloak").text,
        ann.gesture("point", "Bob").text,
        ann.gesture("laugh", "Bob").text,  # laughing isn't aimed, but Bob is still who it was for
        ann.gesture("jump").text,
        _text(ann.do(Gesture(kind="nod", to="Bob"))),
    ]
    assert texts == [
        "You shake your head at a person in a dora cloak.",
        "You point at Bob.",
        "You laugh.",
        "You jump.",
        "You nod to Bob.",
    ]
    gestures = _payloads(sim.drain(), "gestured", Gestured)
    assert [(g.kind, g.to) for g in gestures] == [
        ("shake_head", "dora"),
        ("point", "bob"),
        ("laugh", "bob"),
        ("jump", None),
        ("nod", "bob"),
    ]


def test_a_sleeper_who_gestures_gets_up_first(new_sim: Callable[..., Simulation]) -> None:
    sim, _ = _town(new_sim)
    dora = WorldApi(sim, "dora")
    assert dora.gesture("wave").text == "You wave."
    assert not sim.citizen("dora").body.asleep
    (gestured,) = _payloads(sim.drain(), "gestured", Gestured)
    assert set(gestured.seen_by) == {"ann", "bob"}


def test_a_goal_is_told_to_spectators_only_and_takes_no_time(new_sim: Callable[..., Simulation]) -> None:
    sim, ann = _town(new_sim)
    resting = ann.rest(30)
    sim.drain()
    tick, before = sim.tick, sim.citizen("bob").heard[:]
    result = ann.set_goal("fetch water for the house", "thirst")
    assert result == ActionResult(action="set_goal", outcome="done", text="You set your mind on it.")
    events = sim.drain()
    (event,) = [event for event in events if event.type == "goal_set"]
    assert event.payload == GoalSet(text="fetch water for the house", driver="thirst")
    assert (event.actor_id, event.visibility) == ("ann", "private")
    assert [e.type for e in events] == ["goal_set"]
    assert sim.tick == tick and not resting.done and sim.citizen("bob").heard == before
    assert "water for the house" not in WorldApi(sim, "bob").look_around().text()


def test_setting_a_goal_leaves_a_sleeper_asleep(new_sim: Callable[..., Simulation]) -> None:
    sim, _ = _town(new_sim)
    dora = WorldApi(sim, "dora")
    assert _text(dora.do(SetGoal(text="sleep until dawn", driver="rest"))) == "You set your mind on it."
    assert sim.citizen("dora").body.asleep
    assert sim.citizen("dora").action is not None
    assert [e.type for e in sim.drain()] == ["goal_set"]
