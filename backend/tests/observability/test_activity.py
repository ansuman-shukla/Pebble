"""What spectators see someone doing, derived from the replayed state (action, sleep, speech, death)."""

from app.observability.replay import ReplayCitizen
from app.services.entities import TALKING_TICKS, activity


def _citizen(**overrides: object) -> ReplayCitizen:
    fields: dict[str, object] = {
        "id": "a",
        "name": "A",
        "look": "town-farmer",
        "appearance": "someone",
        "age": 30,
        "group": "young_adult",
        "home": None,
        "position": (0.0, 0.0, 1.0),
        "height_m": 0.0,
        "cell": 0,
        "body": (0.0, 0.0, 100.0, 100.0),
    }
    fields.update(overrides)
    return ReplayCitizen(**fields)  # type: ignore[arg-type]  # test data, typed by the dataclass itself


def test_activity_follows_the_action() -> None:
    expected = {
        "walk_to": "walking",
        "gather": "gathering",
        "eat": "eating",
        "drink": "drinking",
        "work": "working",
        "rest": "resting",
        "wait": "idle",
        None: "idle",
    }
    for action, seen in expected.items():
        assert activity(_citizen(action=action), 10) == seen, action


def test_sleep_death_and_speech_win_over_the_action() -> None:
    assert activity(_citizen(action="sleep", asleep=True), 10) == "sleeping"
    assert activity(_citizen(action="walk_to", alive=False), 10) == "dead"
    talker = _citizen(action="wait", said_tick=10)
    assert [activity(talker, 10 + t) for t in range(TALKING_TICKS + 1)] == ["talking"] * TALKING_TICKS + ["idle"]
    assert activity(_citizen(action="walk_to", said_tick=10), 10) == "walking"  # walking and talking: walking
