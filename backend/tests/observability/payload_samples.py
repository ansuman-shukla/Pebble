"""One full sample payload per world v1 event type (10-world-v1 §6.3), as stored (JSON)."""

from typing import Any

UNIT = (0.6, 0.48, 0.64)

V1_SAMPLES: dict[str, dict[str, Any]] = {
    "node_changed": {
        "node": "node-412",
        "kind": "berry_bush",
        "item": "berries",
        "before": 12,
        "after": 7,
        "stage": "half",
    },
    "tree_felled": {"node": "flora-9031", "yaw_deg": 135.0, "logs": 10, "stack": "stack-88"},
    "trespassed": {
        "kind": "ground",
        "owner": "town",
        "place": "the Lord's woods",
        "took": {"item": "meat", "count": 4},
        "witnesses": ["kenji"],
    },
    "stole": {
        "thief": "kaz",
        "owner": "farmhouse-1",
        "store": "rack-1",
        "item": "rice",
        "count": 5,
        "witnesses": ["goro"],
    },
    "bought": {"item": "rice", "count": 4, "lots": 2, "coins": 8, "stall": "stall", "merchant": "fumiko"},
    "sold": {"item": "hide", "count": 2, "lots": 2, "coins": 22, "stall": "stall", "merchant": "fumiko"},
    "crafted": {"recipe": "iron sickle", "item": "iron sickle", "count": 1, "station": "forge"},
    "spoiled": {"holder": "tek", "holder_kind": "inventory", "items": {"meat": 2, "berries": 1}},
    "tool_broke": {"item": "flint spear", "use": "hunt"},
    "tax_assessed": {"household": "farmhouse-1", "rice": 4, "owed_rice": 12},
    "tax_paid": {"household": "farmhouse-1", "rice": 12, "coins": 0, "owed_rice": 0, "owed_coins": 24},
    "tax_overdue": {"household": "farmhouse-2", "rice": 8, "coins": 12, "owed_rice": 8, "owed_coins": 12, "days": 3},
    "ledger": {
        "coins": 60,
        "wealth_mon": 112,
        "income_24h": 27,
        "spent_24h": 24,
        "owed_rice": 0,
        "owed_coins": 24,
    },
    "prices_changed": {
        "stall": "stall",
        "item": "rice",
        "word": "dear",
        "before": "fair",
        "lot": 2,
        "sell": 5,
        "buy": 3,
    },
    "accused": {"person": "kaz", "to": "kenji", "deeds": [4410]},
    "seized": {"person": "kaz", "held": True, "helpers": ["goro"]},
    "released": {"cause": "judged", "by": "masanori"},
    "confined": {"place": "the gaol", "until_tick": 1440, "by": "kenji"},
    "judged": {
        "person": "kaz",
        "sentence": "fine",
        "fine_mon": 20,
        "confine_h": 0.0,
        "deeds": [4410],
        "arrears": False,
    },
    "sentence_served": {"sentence": "fine", "judgement": 4502},
    "standing_changed": {
        "group": "town",
        "before": -10,
        "after": -25,
        "word": "distrusted",
        "cause": "theft",
        "deed": 4410,
    },
    "leader_changed": {"group": "band_a", "title": "leader", "previous": "ama", "cause": "standing"},
    "bell_rang": {"kind": "dusk"},
    "tended": {"person": "genzo", "health": 1.5},
    "gestured": {"kind": "wave", "to": "ama", "seen_by": ["ama", "lia"]},
    "goal_set": {"text": "sell the hides and buy rice", "driver": "hunger"},
}

ANIMAL_POSE = {
    "position": UNIT,
    "height_m": 12.0,
    "cell": 3,
    "heading_deg": 90.0,
    "activity": "running",
    "route": [
        {"unit": UNIT, "height_m": 12.0, "t_s": 0.0},
        {"unit": (0.61, 0.47, 0.64), "height_m": 12.5, "t_s": 60.0},
    ],
    "speed_mps": 5.0,
    "gait": "trot",
    "goal": "fleeing the wolf",
    "target": {"kind": "animal", "id": "wolf:2", "name": "a wolf", "position": UNIT},
}
