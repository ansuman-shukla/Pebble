"""Every event type tells one readable line with the importance of 10-world-v1 §5.4."""

from typing import Any, get_args

import pytest

from app.observability.events import PAYLOAD_TYPES, EventType
from app.observability.lines import LINES, Told, tell
from tests.observability.payload_samples import V1_SAMPLES

NAMES = {
    "kaz": "Kaz",
    "goro": "Goro",
    "kenji": "Kenji",
    "tek": "Tek",
    "ama": "Ama",
    "lia": "Lia",
    "genzo": "Genzo",
    "fumiko": "Fumiko",
    "masanori": "Masanori",
    "wolf:2": "a wolf",
    "deer:7": "a deer",
    "band_a": "band A",
    "town": "the town",
}


def _name(ref: str) -> str:
    return NAMES.get(ref, ref)


def _tell(
    event_type: str, payload: dict[str, Any], actor: str | None = "tek", kind: str = "citizen"
) -> tuple[str, int]:
    return tell(Told(event_type, kind, actor, payload), _name)


def test_every_event_type_with_a_payload_has_a_line() -> None:
    assert set(PAYLOAD_TYPES) <= set(LINES)
    assert set(LINES) <= set(get_args(EventType))


@pytest.mark.parametrize("event_type", sorted(V1_SAMPLES))
def test_every_v1_event_reads_as_a_sentence_with_names_not_ids(event_type: str) -> None:
    line, importance = _tell(event_type, V1_SAMPLES[event_type])
    assert line and line[0].isupper()
    assert "{" not in line and "}" not in line and "_" not in line
    for ref in ("kaz", "goro", "kenji", "ama", "masanori"):
        assert f" {ref}" not in line  # an id where a name belongs
    assert importance in (0, 1, 2, 3)


@pytest.mark.parametrize(
    ("event_type", "payload", "actor", "kind", "line", "importance"),
    [
        # 3: death, an attack on a person, theft seen, a judgement, a predator's kill
        ("died", {"cause": "starvation"}, "tek", "citizen", "Tek dies (starvation)", 3),
        ("died", {"cause": "violence", "attacker": "kaz"}, "genzo", "citizen", "Kaz kills Genzo", 3),
        ("died", {"cause": "animal attack", "attacker": "wolf:2"}, "tek", "citizen", "A wolf kills Tek", 3),
        ("died", {"cause": "killed by a wolf"}, "deer:7", "animal", "A deer is killed by a wolf", 3),
        ("injured", {"amount": 9.0, "cause": "violence", "attacker": "kaz"}, "goro", "citizen", "Kaz strikes Goro", 3),
        (
            "injured",
            {"amount": 9.0, "cause": "animal attack", "attacker": "wolf:2"},
            "tek",
            "citizen",
            "A wolf attacks Tek",
            3,
        ),
        ("stole", V1_SAMPLES["stole"], "kaz", "citizen", "Kaz steals 5 rice from farmhouse-1, seen by Goro", 3),
        ("judged", V1_SAMPLES["judged"], "masanori", "citizen", "Masanori sentences Kaz to a fine of 20 mon", 3),
        (
            "judged",
            {**V1_SAMPLES["judged"], "sentence": "confine", "confine_h": 6.0},
            "masanori",
            "citizen",
            "Masanori sentences Kaz to 6 hours confined",
            3,
        ),
        # 2: a hunter's kill, a sale, trespass, a tree felled, an injury, a harvest
        ("died", {"cause": "hunted"}, "deer:7", "animal", "A deer is brought down by a hunter", 2),
        ("injured", {"amount": 4.0, "cause": "a fall"}, "tek", "citizen", "Tek is hurt (a fall)", 2),
        ("stole", {**V1_SAMPLES["stole"], "witnesses": []}, "kaz", "citizen", "Kaz steals 5 rice from farmhouse-1", 2),
        ("bought", V1_SAMPLES["bought"], "tek", "citizen", "Tek buys 4 rice for 8 mon", 2),
        ("sold", V1_SAMPLES["sold"], "tek", "citizen", "Tek sells 2 hide for 22 mon", 2),
        ("trespassed", V1_SAMPLES["trespassed"], "kaz", "citizen", "Kaz poaches 4 meat on the Lord's woods", 2),
        (
            "trespassed",
            {"kind": "walls", "owner": "town", "place": "the castle town"},
            "kaz",
            "citizen",
            "Kaz is inside the castle town at night",
            2,
        ),
        ("tree_felled", V1_SAMPLES["tree_felled"], "tek", "citizen", "Tek fells a tree", 2),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "kind": "rice_paddy", "item": "rice"},
            "genzo",
            "citizen",
            "Genzo harvests rice",
            2,
        ),
        # 1: speech, a node emptied, a fire lit
        ("said", {"words": "Hello", "volume": "normal", "heard_by": []}, "ama", "citizen", "Ama: “Hello”", 1),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "after": 0},
            "tek",
            "citizen",
            "Tek takes the last berries from a berry bush",
            1,
        ),
        (
            "fire_changed",
            {"id": "f", "kind": "pit", "lit": True, "strength": 1.0, "position": (0, 0, 1), "height_m": 1.0, "cell": 0},
            None,
            "world",
            "The camp's fire pit burns high",
            1,
        ),
        ("gestured", V1_SAMPLES["gestured"], "tek", "citizen", "Tek waved at Ama", 1),
        ("gestured", {"kind": "shake_head"}, "tek", "citizen", "Tek shook their head", 1),
        ("spoiled", V1_SAMPLES["spoiled"], None, "world", "Some of Tek's food spoils: 2 meat and 1 berries", 1),
        (
            "tax_paid",
            {"household": "farmhouse-1", "rice": 12, "coins": 0},
            "genzo",
            "citizen",
            "Farmhouse-1 pays 12 rice of tax",
            1,
        ),
        ("released", {"cause": "seizer_down"}, "kaz", "citizen", "Kaz goes free (the seizer is down)", 1),
        # 0: hidden
        (
            "fire_changed",
            {
                "id": "f",
                "kind": "basket",
                "lit": False,
                "strength": 0.0,
                "position": (0, 0, 1),
                "height_m": 1.0,
                "cell": 0,
            },
            None,
            "world",
            "A fire basket goes out",
            0,
        ),
        (
            "standing_changed",
            {**V1_SAMPLES["standing_changed"], "cause": "drift"},
            "kaz",
            "citizen",
            "Kaz's standing with the town drifts",
            0,
        ),
        (
            "action_started",
            {"number": 3, "action": "gather", "args": {}, "label": "berries"},
            "tek",
            "citizen",
            "Tek starts gathering berries",
            0,
        ),
        ("tick_summary", {"moved": {}, "bodies": {}}, None, "world", "The world moves on a minute", 0),
    ],
)
def test_lines_and_importance_follow_the_bible(
    event_type: str, payload: dict[str, Any], actor: str | None, kind: str, line: str, importance: int
) -> None:
    assert _tell(event_type, payload, actor, kind) == (line, importance)
