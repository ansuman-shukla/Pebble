"""Every event type tells one readable line with the importance of 10-world-v1 §5.4."""

from typing import Any, get_args

import pytest

from app.observability.events import PAYLOAD_TYPES, EventType
from app.observability.lines import LINES, Resident, Told, namer, tell
from tests.observability.payload_samples import V1_SAMPLES

PEOPLE = {
    ref: Resident(name, home, age)
    for ref, name, home, age in [
        ("masanori", "Masanori", "castle-keep", 55),
        ("kenji", "Kenji", "castle-keep", 34),
        ("goro", "Goro", "cross-s-1", 22),
        ("fumiko", "Fumiko", "main-e-2", 40),
        ("aiko", "Aiko", "farmhouse-1", 26),  # a household is named for its eldest member
        ("genzo", "Genzo", "farmhouse-1", 28),
        ("tokuji", "Tokuji", "farmhouse-2", 58),
        ("ama", "Ama", "band_a_camp:shelter-n", 44),
        ("lia", "Lia", "band_a_camp:shelter-n", 15),
        ("tek", "Tek", "band_a_camp:shelter-e", 24),
        ("kaz", "Kaz", None, 19),
    ]
}
NAMES = namer(PEOPLE)


def _tell(
    event_type: str, payload: dict[str, Any], actor: str | None = "tek", kind: str = "citizen", *, own: bool = False
) -> tuple[str, int]:
    return tell(Told(event_type, kind, actor, payload), NAMES, own=own)


def test_every_event_type_with_a_payload_has_a_line() -> None:
    assert set(PAYLOAD_TYPES) <= set(LINES)
    assert set(LINES) <= set(get_args(EventType))


def test_ids_read_as_names() -> None:
    names = [NAMES(ref) for ref in ("genzo", "farmhouse-1", "farmhouse-2", "castle-keep", "band_a_camp:shelter-n")]
    assert names == ["Genzo", "Genzo's house", "Tokuji's house", "Masanori's house", "Ama's shelter"]
    assert [NAMES(ref) for ref in ("wolf:2", "elk:1", "polar_bear:3")] == ["a wolf", "an elk", "a white bear"]
    assert [NAMES(ref) for ref in ("town", "band_a", "band_b")] == ["the town", "band A", "band B"]
    assert [NAMES(ref) for ref in ("the_gaol", "stall")] == ["the gaol", "stall"]  # anything else as given
    twins = {"b": Resident("Bo", "hut", 30), "a": Resident("Al", "hut", 30), "c": Resident("Cy", "hut", 29)}
    assert namer(twins)("hut") == "Al's house"  # the eldest; between equals, by id


# Every world v1 sample as Tek (a citizen) does it, or as the world for the world's own events.
V1_LINES: dict[str, tuple[str | None, str, int]] = {
    "node_changed": ("tek", "Tek gathers berries from a berry bush", 0),
    "tree_felled": ("tek", "Tek fells a tree", 2),
    "trespassed": ("tek", "Tek poaches 4 meat in the Lord's woods", 2),
    "stole": ("tek", "Tek steals 5 rice from Genzo's house, seen by Goro", 3),
    "bought": ("tek", "Tek buys 4 rice for 8 mon", 2),
    "sold": ("tek", "Tek sells 2 hide for 22 mon", 2),
    "crafted": ("tek", "Tek makes an iron sickle", 1),
    "spoiled": ("tek", "Tek finds 2 meat and 1 berries spoiled", 1),
    "tool_broke": ("tek", "Tek wears out their flint spear", 1),
    "tax_assessed": ("tek", "Tek adds 4 rice to the tax Genzo's house owes", 0),
    "tax_paid": ("tek", "Tek pays 12 rice of tax for Genzo's house", 1),
    "tax_overdue": ("tek", "Tek is 3 days behind on tax for Tokuji's house (8 rice, 12 mon)", 2),
    "ledger": ("tek", "Tek ends the day with 60 mon, worth 112 mon", 0),
    "prices_changed": (None, "Rice is dear at the stall now: 5 mon a lot of 2", 1),
    "accused": ("tek", "Tek accuses Kaz before Kenji", 2),
    "seized": ("tek", "Tek seizes Kaz", 2),
    "released": ("tek", "Tek goes free (judged)", 1),
    "confined": ("tek", "Tek is confined in the gaol", 2),
    "judged": ("tek", "Tek sentences Kaz to a fine of 20 mon", 3),
    "sentence_served": ("tek", "Tek has served the sentence (fine)", 1),
    "standing_changed": ("tek", "Tek is now distrusted by the town (theft)", 1),
    "leader_changed": ("tek", "Tek becomes leader of band A", 2),
    "bell_rang": ("tek", "Tek rings the dusk bell", 1),
    "tended": ("tek", "Tek tends Genzo", 1),
    "gestured": ("tek", "Tek waves to Ama", 1),
    "goal_set": ("tek", "Tek means to sell the hides and buy rice (hunger)", 0),
}


def test_every_v1_sample_has_its_line_pinned() -> None:
    assert set(V1_LINES) == set(V1_SAMPLES)


@pytest.mark.parametrize("event_type", sorted(V1_SAMPLES))
def test_every_v1_event_tells_its_line_and_importance(event_type: str) -> None:
    actor, line, importance = V1_LINES[event_type]
    kind = "world" if actor is None else "citizen"
    assert _tell(event_type, V1_SAMPLES[event_type], actor, kind) == (line, importance)


@pytest.mark.parametrize("event_type", sorted(V1_SAMPLES))
def test_a_v1_event_a_citizen_does_reads_on_their_timeline_without_their_name(event_type: str) -> None:
    actor, line, importance = V1_LINES[event_type]
    own = _tell(event_type, V1_SAMPLES[event_type], actor, "world" if actor is None else "citizen", own=True)
    if actor is None:  # the world's own events read the same
        assert own == (line, importance)
    else:
        assert line.startswith("Tek ") and own == (line.removeprefix("Tek "), importance)


@pytest.mark.parametrize(
    ("event_type", "payload", "actor", "kind", "line", "importance"),
    [
        # 3: death, an attack on a person, theft seen, a judgement, a predator's kill
        ("died", {"cause": "starvation"}, "tek", "citizen", "Tek dies (starvation)", 3),
        ("died", {"cause": "violence", "attacker": "kaz"}, "genzo", "citizen", "Kaz kills Genzo", 3),
        ("died", {"cause": "animal attack", "attacker": "wolf:2"}, "tek", "citizen", "A wolf kills Tek", 3),
        ("died", {"cause": "killed by a wolf"}, "deer:7", "animal", "A deer is killed by a wolf", 3),
        (
            "died",
            {"cause": "killed by a wolf", "attacker": "wolf:2"},
            "deer:7",
            "animal",
            "A wolf brings down a deer",
            3,
        ),
        ("injured", {"amount": 9.0, "cause": "violence", "attacker": "kaz"}, "goro", "citizen", "Kaz strikes Goro", 3),
        (
            "injured",
            {"amount": 9.0, "cause": "animal attack", "attacker": "wolf:2"},
            "tek",
            "citizen",
            "A wolf attacks Tek",
            3,
        ),
        (
            "judged",
            {**V1_SAMPLES["judged"], "sentence": "confine", "confine_h": 6.0},
            "masanori",
            "citizen",
            "Masanori sentences Kaz to 6 hours confined",
            3,
        ),
        (
            "judged",
            {**V1_SAMPLES["judged"], "sentence": "confine", "confine_h": 1.0},
            "masanori",
            "citizen",
            "Masanori sentences Kaz to 1 hour confined",
            3,
        ),
        # 2: a hunter's kill, a sale, trespass, a tree felled, an injury, a harvest
        ("died", {"cause": "hunted"}, "deer:7", "animal", "A deer is brought down by a hunter", 2),
        ("died", {"cause": "hunted", "attacker": "tek"}, "goat:3", "animal", "Tek brings down a goat", 2),
        ("injured", {"amount": 4.0, "cause": "a fall"}, "tek", "citizen", "Tek is hurt (a fall)", 2),
        (
            "stole",
            {**V1_SAMPLES["stole"], "witnesses": []},
            "kaz",
            "citizen",
            "Kaz steals 5 rice from Genzo's house",
            2,
        ),
        (
            "trespassed",
            {"kind": "ground", "owner": "band_a", "place": "band A's ground", "took": {"item": "meat", "count": 2}},
            "kaz",
            "citizen",
            "Kaz poaches 2 meat on band A's ground",
            2,
        ),
        (
            "trespassed",
            {"kind": "ground", "owner": "band_a", "place": "band A's ground"},
            "kaz",
            "citizen",
            "Kaz trespasses on band A's ground",
            2,
        ),
        (
            "trespassed",
            {"kind": "ground", "owner": "town", "place": "the Lord's woods"},
            "kaz",
            "citizen",
            "Kaz trespasses in the Lord's woods",
            2,
        ),
        (
            "trespassed",
            {"kind": "walls", "owner": "town", "place": "the castle town"},
            "kaz",
            "citizen",
            "Kaz is inside the castle town at night",
            2,
        ),
        (
            "trespassed",
            {"kind": "castle", "owner": "town", "place": "the castle"},
            "kaz",
            "citizen",
            "Kaz is inside the castle walls at night",
            2,
        ),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "kind": "rice_paddy", "item": "rice"},
            "genzo",
            "citizen",
            "Genzo harvests rice",
            2,
        ),
        (
            "tax_overdue",
            {"household": "farmhouse-1", "rice": 8, "coins": 0, "owed_rice": 8, "days": 1},
            None,
            "world",
            "Genzo's house is 1 day behind on tax (8 rice, 0 mon)",
            2,
        ),
        # 1: speech, a node emptied, a fire lit, an animal hurt or dead but not by a hunt or a predator, small news
        ("died", {"cause": "attacked by Tek"}, "deer:7", "animal", "A deer dies (attacked by Tek)", 1),
        (
            "injured",
            {"amount": 9.0, "cause": "attacked by Tek"},
            "deer:7",
            "animal",
            "A deer is wounded (attacked by Tek)",
            1,
        ),
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
        ("gestured", {"kind": "shake_head"}, "tek", "citizen", "Tek shakes their head", 1),
        ("gestured", {"kind": "bow", "to": "ama"}, "tek", "citizen", "Tek bows to Ama", 1),
        ("gestured", {"kind": "nod", "to": "ama"}, "tek", "citizen", "Tek nods to Ama", 1),
        ("gestured", {"kind": "point", "to": "ama"}, "tek", "citizen", "Tek points at Ama", 1),
        ("gestured", {"kind": "shake_head", "to": "ama"}, "tek", "citizen", "Tek shakes their head at Ama", 1),
        ("gestured", {"kind": "laugh", "to": "ama"}, "tek", "citizen", "Tek laughs", 1),
        ("gestured", {"kind": "jump"}, "tek", "citizen", "Tek jumps", 1),
        ("crafted", {**V1_SAMPLES["crafted"], "item": "arrow", "count": 3}, "tek", "citizen", "Tek makes 3 arrow", 1),
        (
            "spoiled",
            V1_SAMPLES["spoiled"],
            None,
            "world",
            "Some of Tek's food spoils: 2 meat and 1 berries",
            1,
        ),
        (
            "tax_paid",
            {"household": "farmhouse-1", "rice": 12, "coins": 24},
            "genzo",
            "citizen",
            "Genzo pays 12 rice and 24 mon of tax for Genzo's house",
            1,
        ),
        (
            "tax_paid",
            {"household": "farmhouse-1", "rice": 0, "coins": 24},
            "genzo",
            "citizen",
            "Genzo pays 24 mon of tax for Genzo's house",
            1,
        ),
        ("released", {"cause": "seizer_down"}, "kaz", "citizen", "Kaz goes free (the seizer is down)", 1),
        ("seized", {"person": "kaz", "held": False}, "goro", "citizen", "Goro tries to seize Kaz", 2),
        (
            "standing_changed",
            {"group": "band_a", "before": 15, "after": 25, "word": "well regarded", "cause": "sale"},
            "tek",
            "citizen",
            "Tek is now well regarded by band A (sale)",
            1,
        ),
        (
            "standing_changed",
            {"group": "town", "before": -55, "after": -65, "word": "outcast", "cause": "theft"},
            "kaz",
            "citizen",
            "Kaz is now cast out by the town (theft)",
            1,
        ),
        ("bell_rang", {"kind": "dawn"}, None, "world", "The dawn bell rings", 1),
        # 0: hidden
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "kind": "deadwood", "item": "wood"},
            "tek",
            "citizen",
            "Tek gathers wood from a deadwood pile",
            0,
        ),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "kind": "obsidian_field", "item": "obsidian"},
            "tek",
            "citizen",
            "Tek mines obsidian from an obsidian field",
            0,
        ),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "kind": "fishing_spot", "item": "fish"},
            "tek",
            "citizen",
            "Tek catches fish",
            0,
        ),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "kind": "rice_paddy", "item": "rice", "before": 0, "after": 60},
            "genzo",
            "citizen",
            "Genzo tends a rice paddy",
            0,
        ),
        (
            "node_changed",
            {**V1_SAMPLES["node_changed"], "before": 6, "after": 7},
            None,
            "world",
            "A berry bush grows more berries",
            0,
        ),
        ("node_changed", V1_SAMPLES["node_changed"], None, "world", "A berry bush now has 7 berries", 0),
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
            "Kaz drifts back toward their old standing with the town",
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
        (
            "action_started",
            {"number": 4, "action": "walk_to", "args": {}, "label": "to the west"},
            "tek",
            "citizen",
            "Tek starts walking to the west",
            0,
        ),
        (
            "action_started",
            {"number": 4, "action": "walk_to", "args": {}, "label": "home"},
            "tek",
            "citizen",
            "Tek starts walking home",
            0,
        ),
        (
            "action_started",
            {"number": 4, "action": "walk_to", "args": {}, "label": "the well"},
            "tek",
            "citizen",
            "Tek starts walking to the well",
            0,
        ),
        (
            "action_started",
            {"number": 5, "action": "work", "args": {}, "label": "tending the rice paddies"},
            "genzo",
            "citizen",
            "Genzo starts tending the rice paddies",
            0,
        ),
        (
            "action_started",
            {"number": 5, "action": "fish", "args": {}, "label": "fish"},
            "tek",
            "citizen",
            "Tek starts fishing",
            0,
        ),
        (
            "action_started",
            {"number": 5, "action": "make_fire", "args": {}, "label": "the fire pit"},
            "tek",
            "citizen",
            "Tek starts making a fire in the fire pit",
            0,
        ),
        (
            "action_started",
            {"number": 5, "action": "feed_fire", "args": {}, "label": "the fire basket"},
            "tek",
            "citizen",
            "Tek starts feeding the fire basket",
            0,
        ),
        (
            "action_finished",
            {"number": 4, "action": "walk_to", "outcome": "done", "text": "You arrive."},
            "tek",
            "citizen",
            "Tek is done walking",
            0,
        ),
        (
            "action_finished",
            {"number": 4, "action": "gather", "outcome": "failed", "text": "No."},
            "tek",
            "citizen",
            "Tek fails at gathering",
            0,
        ),
        ("tick_summary", {"moved": {}, "bodies": {}}, None, "world", "The world moves on a minute", 0),
    ],
)
def test_lines_and_importance_follow_the_bible(
    event_type: str, payload: dict[str, Any], actor: str | None, kind: str, line: str, importance: int
) -> None:
    assert _tell(event_type, payload, actor, kind) == (line, importance)
