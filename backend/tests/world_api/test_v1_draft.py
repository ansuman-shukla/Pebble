"""Contract v1 draft (D96): every new action is reachable through the facade, and until its stream lands the world
answers it in-world ("You can't do that yet.") without waking a sleeper or stopping what the citizen is doing."""

from collections.abc import Callable

import pytest

from app.sim.actions import INSTANTS, NOT_YET, STARTS
from app.sim.simulation import Simulation
from app.world_api.facade import ActionHandle, WorldApi, run_until_done
from app.world_api.models import (
    INSTANT_ACTIONS,
    Accuse,
    Action,
    ActionName,
    ActionResult,
    Buy,
    Confinement,
    Craft,
    Fine,
    Gesture,
    Judge,
    Perception,
    Seize,
    SelfView,
    Sell,
    SetGoal,
    Stash,
    Tend,
)
from tests.sim_helpers import WELL, make_spec

V1_ACTIONS: dict[ActionName, Action] = {
    "buy": Buy(item="rice", amount=4),
    "sell": Sell(item="hide", amount=1),
    "stash": Stash(item="rice", amount=2),
    "craft": Craft(recipe="flint spear"),
    "accuse": Accuse(person="Ama", to="Kenji"),
    "seize": Seize(person="Ama"),
    "judge": Judge(person="Ama", sentence=Fine(mon=20)),
    "tend": Tend(person="Ama"),
    "gesture": Gesture(kind="wave"),
    "set_goal": SetGoal(text="find something to eat", driver="hunger"),
}
NOT_YET_ACTIONS = sorted(name for name in V1_ACTIONS if name not in INSTANTS and name not in STARTS)
INSTANT_NOT_YET = [name for name in NOT_YET_ACTIONS if name in INSTANT_ACTIONS]
DURATIVE_NOT_YET = [name for name in NOT_YET_ACTIONS if name not in INSTANT_ACTIONS]


def facade_call(me: WorldApi, action: Action) -> ActionResult | ActionHandle:
    """The action through its own `WorldApi` method (the way scripted brains call)."""
    match action:
        case Buy():
            return me.buy(action.item, action.amount)
        case Sell():
            return me.sell(action.item, action.amount)
        case Stash():
            return me.stash(action.item, action.amount)
        case Craft():
            return me.craft(action.recipe)
        case Accuse():
            return me.accuse(action.person, action.to)
        case Seize():
            return me.seize(action.person)
        case Judge():
            return me.judge(action.person, action.sentence)
        case Tend():
            return me.tend(action.person)
        case Gesture():
            return me.gesture(action.kind, action.to)
        case SetGoal():
            return me.set_goal(action.text, action.driver)
    raise AssertionError(f"no facade call for {action.action}")


def answer(sim: Simulation, outcome: Perception | SelfView | ActionResult | ActionHandle) -> ActionResult:
    if isinstance(outcome, ActionHandle):
        return run_until_done(sim, outcome, 1)
    assert isinstance(outcome, ActionResult)
    return outcome


def test_the_draft_names_every_new_action() -> None:
    assert sorted(V1_ACTIONS) == sorted(
        ["buy", "sell", "stash", "craft", "accuse", "seize", "judge", "tend", "gesture", "set_goal"]
    )
    assert NOT_YET_ACTIONS, "every v1 action has landed: retire this module's not-yet tests"


@pytest.mark.parametrize("name", NOT_YET_ACTIONS)
def test_an_action_not_in_the_world_yet_is_refused_in_world(
    name: ActionName, new_sim: Callable[..., Simulation]
) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    sim.drain()
    for outcome in (facade_call(me, V1_ACTIONS[name]), me.do(V1_ACTIONS[name])):
        assert isinstance(outcome, ActionResult) == (name in INSTANT_ACTIONS)
        assert answer(sim, outcome) == ActionResult(action=name, outcome="failed", text=NOT_YET)
    assert sim.citizen(me.citizen_id).action is None


@pytest.mark.parametrize("name", DURATIVE_NOT_YET)
def test_a_durative_action_not_in_the_world_yet_leaves_the_running_one_alone(
    name: ActionName, new_sim: Callable[..., Simulation]
) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    resting = me.rest(30)
    assert answer(sim, me.do(V1_ACTIONS[name])).text == NOT_YET
    action = sim.citizen(me.citizen_id).action
    assert action is not None and action.number == resting.number and not resting.done


@pytest.mark.parametrize("name", INSTANT_NOT_YET)
def test_an_instant_action_not_in_the_world_yet_wakes_nobody(
    name: ActionName, new_sim: Callable[..., Simulation]
) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    sim.citizen(me.citizen_id).body.energy = 20.0
    sleeping = me.sleep()
    assert sim.citizen(me.citizen_id).body.asleep
    assert answer(sim, me.do(V1_ACTIONS[name])).text == NOT_YET
    assert sim.citizen(me.citizen_id).body.asleep and not sleeping.done


def test_a_sentence_is_a_fine_in_coins_or_hours_confined() -> None:
    judged = Judge.model_validate({"person": "Kaz", "sentence": {"kind": "confine", "hours": 6}})
    assert judged.sentence == Confinement(hours=6)
    for wrong in ({"kind": "fine", "mon": 500}, {"kind": "confine", "hours": 24}, {"kind": "flog"}):
        with pytest.raises(ValueError):
            Judge.model_validate({"person": "Kaz", "sentence": wrong})
    with pytest.raises(ValueError):
        SetGoal.model_validate({"text": "x" * 81, "driver": "duty"})
    with pytest.raises(ValueError):
        Gesture.model_validate({"kind": "salute"})


def test_gathering_a_mineral_where_there_is_none_fails_in_world(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    for mineral in ("flint", "iron sand", "gold"):
        result = run_until_done(sim, me.gather(mineral), 1)
        assert result == ActionResult(action="gather", outcome="failed", text=f"You can't gather {mineral} here.")
