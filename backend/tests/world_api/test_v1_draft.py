"""Contract v1 draft (D96): every new action is reachable through the facade and in the world (each stream's own tests
cover what it does); the new perception fields are told in words."""

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
    Sell,
    SetGoal,
    Stash,
    Tend,
)
from tests.sim_helpers import WELL, make_spec

V1_ACTIONS: dict[ActionName, Action] = {
    "buy": Buy(item="rice", amount=4),
    "sell": Sell(item="hide", amount=1),
    "stash": Stash(item="dried meat", amount=2),
    "craft": Craft(recipe="flint spear"),
    "accuse": Accuse(person="Ama", to="Kenji"),
    "seize": Seize(person="Ama"),
    "judge": Judge(person="Ama", sentence=Fine(mon=20)),
    "tend": Tend(person="Ama"),
    "gesture": Gesture(kind="wave"),
    "set_goal": SetGoal(text="find something to eat", driver="hunger"),
}


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


def test_the_draft_names_every_new_action() -> None:
    assert sorted(V1_ACTIONS) == sorted(
        ["buy", "sell", "stash", "craft", "accuse", "seize", "judge", "tend", "gesture", "set_goal"]
    )
    assert all((name in INSTANTS) == (name in INSTANT_ACTIONS) for name in V1_ACTIONS)
    assert all(name in INSTANTS or name in STARTS for name in V1_ACTIONS)  # every v1 action is in the world


@pytest.mark.parametrize("name", sorted(V1_ACTIONS))
def test_each_facade_method_sends_its_action_whole(
    name: ActionName, new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = new_sim()
    me = WorldApi(sim, sim.add_citizen(make_spec(at=WELL)).id)
    sent: list[Action] = []

    def instant(_citizen_id: str, action: Action) -> ActionResult:
        sent.append(action)
        return ActionResult(action=action.action, outcome="failed", text=NOT_YET)

    def start(_citizen_id: str, action: Action) -> int:
        sent.append(action)
        return 0

    monkeypatch.setattr(sim, "instant", instant)
    monkeypatch.setattr(sim, "start", start)
    facade_call(me, V1_ACTIONS[name])
    assert sent == [V1_ACTIONS[name]]


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
    told = {"flint": "There are no flint nodules", "iron sand": "There is no iron sand", "gold": "There is no gold"}
    for mineral, none in told.items():  # minerals are nodes (N1): none in sight of the town's well
        result = run_until_done(sim, me.gather(mineral), 1)
        assert result == ActionResult(action="gather", outcome="failed", text=f"{none} within reach.")


def _look(you: dict[str, object] | None = None, **v1: object) -> Perception:
    body = {"feeling": ["a little hungry"], "carrying": ["two fish"], "doing": "You are resting."}
    seen = {
        "you": body | (you or {}),
        "place": "at the well",
        "time": "It is midday.",
        "time_of_day": "midday",
        "people": [{"label": "Genzo", "where": "a few paces to the north", "nearness": "a few paces"}],
        "animals": [],
        "things": [],
        "heard": [],
    }
    return Perception.model_validate(seen | v1)


def test_a_look_without_the_v1_fields_reads_as_in_v0() -> None:
    assert _look().text() == (
        "You are at the well. It is midday.\n"
        "You feel a little hungry. You carry two fish. You are resting.\n"
        "You see Genzo a few paces to the north."
    )


def test_the_v1_fields_are_told_in_words_when_set() -> None:
    look = _look(
        you={
            "purse": "seven coins",
            "load": "carrying a heavy load",
            "titles": ["the lord"],
            "standing": "People here regard you well.",
            "wanted": "You are wanted in the castle town for theft.",
            "held": "Kenji holds you fast.",
            "confined": "You are confined in the gaol.",
        },
        day_of_week="the seventh day of the week, court day",
        ground="the Lord's woods",
        safety="exposed",
        people=[
            {
                "label": "Genzo",
                "where": "a few paces to the north",
                "nearness": "a few paces",
                "doing": "farming",
                "relation": "your father",
                "regard": "well regarded",
            }
        ],
        market={
            "items": [
                {"item": "rice", "price": "four coins for two measures; it pays three coins", "word": "fair"},
                {"item": "hide", "price": "fifteen coins each", "word": "dear"},
            ]
        },
        chest={"holds": ["twenty measures of rice", "a sickle"]},
        noticed=["Kenji bows to you.", "The temple bell rings."],
    )
    assert look.text() == (
        "You are at the well. It is midday. It is the seventh day of the week, court day.\n"
        "You feel a little hungry. You carry two fish. You are resting. You have seven coins. You are carrying a heavy"
        " load. You are the lord. People here regard you well. You are wanted in the castle town for theft. Kenji holds"
        " you fast. You are confined in the gaol.\n"
        "This is the Lord's woods. You are exposed.\n"
        "You see Genzo, your father, well regarded, a few paces to the north (farming).\n"
        "At the stall: rice, four coins for two measures; it pays three coins (fair)."
        " Hide, fifteen coins each (dear).\n"
        "Your chest holds twenty measures of rice and a sickle.\n"
        "Kenji bows to you. The temple bell rings."
    )
    purse_only = _look(you={"carrying": [], "purse": "seven coins"}).you.text()
    assert purse_only == "You feel a little hungry. You are resting. You have seven coins."  # not "You carry nothing."
    assert (
        _look(chest={"holds": []}, market={"items": []})
        .text()
        .endswith("At the stall: nothing for sale.\nYour chest is empty.")
    )
    with pytest.raises(ValueError):
        _look(safety="safe enough")


def test_someone_known_is_told_apart_from_a_group_without_doubled_commas() -> None:
    here = {"where": "a few paces to the north", "nearness": "a few paces", "doing": "farming"}
    people = [
        {"label": "Suna", **here},
        {"label": "Genzo", "relation": "your father", **here},
        {"label": "Tek", **here},
        {"label": "Ama", **here},
    ]
    text = _look(people=people).text()
    assert text.splitlines()[2] == (
        "You see Suna, Tek and Ama a few paces to the north (farming); "
        "Genzo, your father, a few paces to the north (farming)."
    )
    assert ",," not in text
    first = _look(people=[people[1], people[0], people[2]]).text().splitlines()[2]
    assert first == (
        "You see Genzo, your father, a few paces to the north (farming); "
        "Suna and Tek a few paces to the north (farming)."
    )
