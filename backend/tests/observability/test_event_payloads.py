"""Every event type has exactly one typed payload, and the world v1 payloads read what streams will store (10 §6.3)."""

from typing import get_args

import pytest
from pydantic import ValidationError

from app.observability.events import PAYLOAD_TYPES, AnimalPose, Died, EventDraft, EventType, Injured, Moved, Target
from tests.observability.payload_samples import ANIMAL_POSE, UNIT, V1_SAMPLES

V1_TYPES: list[EventType] = [
    "node_changed",
    "tree_felled",
    "trespassed",
    "stole",
    "bought",
    "sold",
    "crafted",
    "spoiled",
    "tool_broke",
    "tax_assessed",
    "tax_paid",
    "tax_overdue",
    "ledger",
    "prices_changed",
    "accused",
    "seized",
    "released",
    "confined",
    "judged",
    "sentence_served",
    "standing_changed",
    "leader_changed",
    "bell_rang",
    "tended",
    "gestured",
    "goal_set",
]


def test_every_event_type_but_thought_has_a_payload() -> None:
    assert set(get_args(EventType)) - set(PAYLOAD_TYPES) == {"thought"}
    assert set(PAYLOAD_TYPES) <= set(get_args(EventType))


def test_the_bible_s_new_event_types_are_all_registered() -> None:
    assert len(V1_TYPES) == 26
    assert set(V1_TYPES) <= set(PAYLOAD_TYPES)
    assert set(V1_SAMPLES) == set(V1_TYPES)


@pytest.mark.parametrize("event_type", V1_TYPES)
def test_a_full_v1_payload_validates_and_keeps_every_value(event_type: EventType) -> None:
    payload = PAYLOAD_TYPES[event_type].model_validate(V1_SAMPLES[event_type])
    assert payload.model_dump(mode="json", exclude_unset=True) == V1_SAMPLES[event_type]


@pytest.mark.parametrize("event_type", V1_TYPES)
def test_v1_payloads_refuse_unknown_fields(event_type: EventType) -> None:
    with pytest.raises(ValidationError):
        PAYLOAD_TYPES[event_type].model_validate({**V1_SAMPLES[event_type], "surprise": 1})


def test_closed_vocabularies_refuse_other_words() -> None:
    with pytest.raises(ValidationError):
        PAYLOAD_TYPES["gestured"].model_validate({"kind": "dance"})
    with pytest.raises(ValidationError):
        PAYLOAD_TYPES["goal_set"].model_validate({"text": "eat", "driver": "greed"})
    with pytest.raises(ValidationError):
        PAYLOAD_TYPES["released"].model_validate({"cause": "escaped"})
    with pytest.raises(ValidationError):
        PAYLOAD_TYPES["trespassed"].model_validate({**V1_SAMPLES["trespassed"], "kind": "garden"})


def test_violence_names_the_attacker_and_old_events_still_read() -> None:
    assert Injured.model_validate({"amount": 12.0, "cause": "violence", "attacker": "kaz"}).attacker == "kaz"
    assert Died.model_validate({"cause": "violence", "attacker": "kaz"}).attacker == "kaz"
    assert Died.model_validate({"cause": "starvation"}).attacker is None  # stored before v1


def test_animal_poses_carry_a_drawn_path_and_what_the_animal_is_after() -> None:
    pose = AnimalPose.model_validate(ANIMAL_POSE)
    assert [point.t_s for point in pose.route] == [0.0, 60.0]
    assert (pose.speed_mps, pose.gait, pose.goal) == (5.0, "trot", "fleeing the wolf")
    assert pose.target == Target(kind="animal", id="wolf:2", name="a wolf", position=UNIT)
    old = AnimalPose.model_validate(
        {k: ANIMAL_POSE[k] for k in ("position", "height_m", "cell", "heading_deg")} | {"activity": "grazing"}
    )
    assert (old.route, old.speed_mps, old.gait, old.goal, old.target) == ([], 0.0, "walk", "", None)


def test_moves_say_their_gait() -> None:
    moved = Moved.model_validate({"position": UNIT, "height_m": 1.0, "cell": 0, "gait": "run"})
    assert moved.gait == "run"
    assert Moved.model_validate({"position": UNIT, "height_m": 1.0, "cell": 0}).gait == "walk"
    with pytest.raises(ValidationError):
        Moved.model_validate({"position": UNIT, "height_m": 1.0, "cell": 0, "gait": "trot"})  # an animal's gait


def test_an_event_draft_refuses_a_payload_of_another_type() -> None:
    payload = PAYLOAD_TYPES["bought"].model_validate(V1_SAMPLES["bought"])
    EventDraft(1, 0, "sold", "citizen", "tek", None, None, "public", None, payload)  # bought and sold share Traded
    with pytest.raises(TypeError):
        EventDraft(1, 0, "stole", "citizen", "kaz", None, None, "public", None, payload)
