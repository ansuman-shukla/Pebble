"""One-line timeline summaries for each kind of event, as a spectator reads them."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.db.models import Event
from app.observability.lines import Resident, namer
from app.services.citizens import PersonRef, timeline_entry
from app.services.places import PlaceIndex
from app.sim.world import SimWorld

PEOPLE = {
    "me": PersonRef(id="me", name="Aiko", role="weaver"),
    "you": PersonRef(id="you", name="Genzo", role="farmer"),
    "kid": PersonRef(id="kid", name="Hana", role="child"),
}
NAMES = namer(
    {
        "me": Resident("Aiko", "farmhouse-1", 26),
        "you": Resident("Genzo", "farmhouse-1", 28),
        "kid": Resident("Hana", "farmhouse-1", 9),
    }
)


def _event(kind: str, payload: dict[str, Any], actor: str = "me") -> Event:
    return Event(
        id="01",
        run_id="r",
        seq=1,
        world_seed=1,
        tick=1500,
        game_time=1980,
        real_time=datetime.now(UTC),
        actor_kind="citizen",
        actor_id=actor,
        type=kind,
        visibility="public",
        payload=payload,
    )


def _inv(who: str) -> dict[str, Any]:
    return {"kind": "inventory", "id": who}


def _store(store: str) -> dict[str, Any]:
    return {"kind": "store", "id": store}


CASES: list[tuple[str, dict[str, Any], str, str, dict[int, str]]] = [
    ("need_changed", {"need": "hunger", "level": "hungry", "value": 61, "worse": True}, "me", "feels hungry", {}),
    ("need_changed", {"need": "hunger", "level": "fed", "value": 20, "worse": False}, "me", "feels fed again", {}),
    ("injured", {"amount": 12.4, "cause": "a fall"}, "me", "is hurt: a fall", {}),
    ("injured", {"amount": 9.0, "cause": "violence", "attacker": "you"}, "me", "is struck by Genzo", {}),
    ("injured", {"amount": 9.0, "cause": "animal attack", "attacker": "wolf:2"}, "me", "is attacked by a wolf", {}),
    ("died", {"cause": "starvation"}, "me", "dies: starvation", {}),
    ("died", {"cause": "violence", "attacker": "you"}, "me", "is killed by Genzo", {}),
    ("died", {"cause": "animal attack", "attacker": "bear:1"}, "me", "is killed by a bear", {}),
    # world v1 events read as the feed tells them (the line registry), without the name in front; names not ids
    (
        "bought",
        {"item": "rice", "count": 4, "lots": 2, "coins": 8, "stall": "stall", "merchant": "you"},
        "me",
        "buys 4 rice for 8 mon",
        {},
    ),
    ("gestured", {"kind": "wave", "to": "kid", "seen_by": ["kid"]}, "me", "waves to Hana", {}),
    (
        "standing_changed",
        {"group": "band_a", "before": 0, "after": 3, "word": "nothing said", "cause": "sale"},
        "me",
        "is now neither trusted nor distrusted by band A (sale)",
        {},
    ),
    (
        "node_changed",
        {"node": "node-412", "kind": "berry_bush", "item": "berries", "before": 12, "after": 7, "stage": "half"},
        "me",
        "gathers berries from a berry bush",
        {},
    ),
    (
        "tax_paid",
        {"household": "farmhouse-1", "rice": 12, "coins": 0, "owed_rice": 0, "owed_coins": 24},
        "me",
        "pays 12 rice of tax for Genzo's house",
        {},
    ),
    ("knowledge_changed", {"about": "person", "ref": "you", "level": "known"}, "me", "gets to know Genzo", {}),
    ("knowledge_changed", {"about": "place", "ref": "temple", "level": "rough"}, "me", "hears of the temple", {}),
    (
        "knowledge_changed",
        {"about": "place", "ref": "temple", "level": "visited"},
        "me",
        "comes to the temple for the first time",
        {},
    ),
    ("perceived", {"kind": "look_around", "text": "You see the well."}, "me", "looks around", {}),
    ("said", {"words": "Psst", "volume": "whisper", "heard_by": ["you"]}, "me", 'whispers "Psst"', {}),
    ("said", {"words": "Hey!", "volume": "normal", "heard_by": ["me", "kid"]}, "you", 'hears Genzo: "Hey!"', {}),
    (
        "action_started",
        {"number": 1, "action": "walk_to", "args": {}, "label": "your home"},
        "me",
        "walks home",
        {},
    ),
    (
        "action_started",
        {"number": 1, "action": "walk_to", "args": {}, "label": "to the north-west"},
        "me",
        "walks to the north-west",
        {},
    ),
    ("action_started", {"number": 1, "action": "wait", "args": {"minutes": 5}, "label": ""}, "me", "waits 5 min", {}),
    ("action_started", {"number": 1, "action": "sleep", "args": {}, "label": ""}, "me", "lies down to sleep", {}),
    (
        "action_started",
        {"number": 1, "action": "drink", "args": {}, "label": "the river"},
        "me",
        "drinks at the river",
        {},
    ),
    (
        "action_finished",
        {"number": 4, "action": "walk_to", "outcome": "done", "text": "You arrive home."},
        "me",
        "arrives home",
        {4: "your home"},
    ),
    (
        "action_finished",
        {"number": 4, "action": "walk_to", "outcome": "done", "text": "You are there."},
        "me",
        "finishes walking to the north",
        {4: "to the north"},
    ),
    (
        "action_interrupted",
        {"number": 4, "action": "gather", "outcome": "interrupted", "text": "You stop."},
        "me",
        "stops gathering berries",
        {4: "berries"},
    ),
    (
        "action_finished",
        {"number": 4, "action": "sleep", "outcome": "done", "text": "You wake."},
        "me",
        "wakes up",
        {4: ""},
    ),
    (
        "action_finished",
        {"number": 4, "action": "work", "outcome": "failed", "text": "You can't."},
        "me",
        "fails at tending the rice paddies",
        {4: "tending the rice paddies"},
    ),
    (
        "action_finished",
        {"number": 9, "action": "rest", "outcome": "done", "text": "You rest."},
        "me",
        "finishes resting",
        {},
    ),
    (
        "item_moved",
        {"item": "rice", "count": 2, "source": _inv("me"), "destination": {"kind": "eaten"}},
        "me",
        "eats a little rice",
        {},
    ),
    (
        "item_moved",
        {"item": "rice", "count": 24, "source": _inv("me"), "destination": _store("store-2")},
        "me",
        "puts plenty of rice in the storehouse",
        {},
    ),
    (
        "item_moved",
        {"item": "berries", "count": 5, "source": _inv("me"), "destination": _inv("kid")},
        "me",
        "gives a handful of berries to Hana",
        {},
    ),
    (
        "item_moved",
        {"item": "berries", "count": 1, "source": _inv("me"), "destination": {"kind": "ground", "id": "g1"}},
        "me",
        "puts down a berry",
        {},
    ),
    (
        "item_moved",
        {"item": "roots", "count": 3, "source": {"kind": "resource", "cell": 5}, "destination": _inv("me")},
        "me",
        "gathers a few roots",
        {},
    ),
    (
        "item_moved",
        {"item": "rice", "count": 12, "source": _store("rice-fields"), "destination": _inv("me")},
        "me",
        "takes some rice from the rice fields",
        {},
    ),
    (
        "item_moved",
        {"item": "nuts", "count": 50, "source": {"kind": "ground", "id": "g1"}, "destination": _inv("me")},
        "me",
        "picks up a great many nuts",
        {},
    ),
    (
        "item_moved",
        {"item": "nuts", "count": 2, "source": _inv("you"), "destination": _inv("me")},
        "me",
        "gets a few nuts from Genzo",
        {},
    ),
    (
        "item_moved",
        {"item": "rice", "count": 12, "source": {"kind": "world"}, "destination": _store("rice-fields")},
        "me",
        "some rice ripens in the rice fields",
        {},
    ),
]


@pytest.mark.parametrize(("kind", "payload", "actor", "summary", "labels"), CASES)
def test_summary(
    sim_world: SimWorld, kind: str, payload: dict[str, Any], actor: str, summary: str, labels: dict[int, str]
) -> None:
    entry = timeline_entry(_event(kind, payload, actor), "me", PEOPLE, PlaceIndex(sim_world), labels, NAMES)
    assert entry.summary == summary
    assert (entry.day, entry.time) == (1, "09:00")


def test_details_and_related_people(sim_world: SimWorld) -> None:
    places = PlaceIndex(sim_world)
    shout = _event("said", {"words": "Hey!", "volume": "shout", "heard_by": ["you", "kid"]})
    entry = timeline_entry(shout, "me", PEOPLE, places, {}, NAMES)
    assert (entry.summary, entry.detail, entry.related) == ('shouts "Hey!"', "heard by Genzo and Hana", ["you", "kid"])
    heard = timeline_entry(
        _event("said", {"words": "Hi", "volume": "normal", "heard_by": ["me"]}, "you"), "me", PEOPLE, places, {}, NAMES
    )
    assert heard.related == ["you"] and heard.detail is None
    ended = _event("action_finished", {"number": 1, "action": "eat", "outcome": "done", "text": "You eat."})
    assert timeline_entry(ended, "me", PEOPLE, places, {1: "berries"}, NAMES).detail == "You eat."
    hurt = timeline_entry(_event("injured", {"amount": 12.4, "cause": "a fall"}), "me", PEOPLE, places, {}, NAMES)
    assert hurt.detail == "lost 12 health"
    struck = _event("injured", {"amount": 9.0, "cause": "violence", "attacker": "you"})
    assert timeline_entry(struck, "me", PEOPLE, places, {}, NAMES).related == ["you"]  # attackers who are people
    bitten = _event("injured", {"amount": 9.0, "cause": "animal attack", "attacker": "wolf:2"})
    assert timeline_entry(bitten, "me", PEOPLE, places, {}, NAMES).related == []
    killed = _event("died", {"cause": "animal attack", "attacker": "wolf:2"})
    assert timeline_entry(killed, "me", PEOPLE, places, {}, NAMES).related == []
