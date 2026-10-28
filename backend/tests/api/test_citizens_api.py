"""Citizen endpoints: everyone, one profile (now and replayed), the timeline and needs over time."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.engine import EngineLoop
from app.services import citizens as citizens_service
from app.sim.citizens import CITIZENS, load_citizens
from tests.api.spectator import API, Story, timeline


@pytest.mark.usefixtures("spectator_session")
def test_no_run_yet_is_a_404(client: TestClient) -> None:
    for path in ("/citizens", "/citizens/x", "/citizens/x/timeline", "/citizens/x/needs"):
        assert client.get(API + path).status_code == 404, path


def test_citizens_list_everyone_with_what_they_do(client: TestClient, cast: EngineLoop) -> None:
    body = client.get(f"{API}/citizens").json()
    assert (body["tick"], body["day"], body["time"]) == (70, 0, "09:10")
    specs = {spec.id: spec for spec in load_citizens(CITIZENS).citizens}
    assert [c["id"] for c in body["citizens"]] == sorted(specs)
    entities = {c["id"]: c for c in client.get(f"{API}/entities").json()["citizens"]}
    for listed in body["citizens"]:
        spec, sim = specs[listed["id"]], cast.sim.citizen(listed["id"])
        assert (listed["name"], listed["role"], listed["region"], listed["age"], listed["look"]) == (
            spec.name,
            spec.role,
            spec.region,
            spec.age,
            spec.look,
        )
        assert listed["alive"] is sim.body.alive is True
        entity = entities[listed["id"]]
        assert (listed["activity"], listed["action_label"], listed["state"]) == (
            entity["activity"],
            entity["action_label"],
            entity["state"],
        )
    places = {c["id"]: c["place"] for c in body["citizens"]}
    camp = cast.sim.world.places["band_a_camp"]
    at_camp = [  # whoever of band A is in camp (the hunters may be out after game)
        citizen.id
        for citizen in cast.sim.state.citizens.values()
        if citizen.region == "band_a" and cast.sim.world.distance_m(citizen.position, camp.centre) < camp.radius_m - 5
    ]
    assert at_camp and all(places[cid] == {"id": "band_a_camp", "name": "Band A camp"} for cid in at_camp)
    assert places["barro"] == {"id": "band_b_camp", "name": "Band B camp"}  # band B sleeps through its night


@pytest.mark.usefixtures("story")
def test_citizens_replay_a_past_tick(client: TestClient) -> None:
    start = {c["id"]: c for c in client.get(f"{API}/citizens", params={"at": 0}).json()["citizens"]}
    assert start["dev-haru"]["place"] == {"id": "market", "name": "the market"}
    assert start["dev-aiko"]["place"] == {"id": "well", "name": "the well"}
    assert all(c["alive"] for c in start.values())
    end = {c["id"]: c for c in client.get(f"{API}/citizens").json()["citizens"]}
    assert end["dev-genzo"]["alive"] is False
    assert end["dev-genzo"]["activity"] == "dead" and end["dev-genzo"]["cause_of_death"] == "dehydration"
    assert end["dev-aiko"]["place"] == {"id": "main-gate", "name": "the main gate"}
    assert client.get(f"{API}/citizens", params={"at": 76}).status_code == 404
    assert client.get(f"{API}/citizens", params={"at": -1}).status_code == 422


def test_profile_says_who_they_are(client: TestClient, cast: EngineLoop) -> None:
    profile = client.get(f"{API}/citizens/genzo").json()
    spec = next(spec for spec in load_citizens(CITIZENS).citizens if spec.id == "genzo")
    assert profile["personality"] == spec.personality and profile["personality"]
    assert (profile["sex"], profile["age_group"], profile["skills"]) == ("male", "young_adult", ["farming"])
    assert profile["home"] == {"id": "farmhouse-1", "name": "a farmhouse in the castle town"}
    assert {p["id"] for p in profile["known_places"]} == set(spec.knows_places)
    assert {"id": "rice-fields", "name": "the rice fields", "level": "visited"} in profile["known_places"]
    assert {p["id"]: p["name"] for p in profile["known_people"]} == {
        "aiko": "Aiko",
        "fumiko": "Fumiko",
        "hana": "Hana",
        "kenji": "Kenji",
        "masanori": "Masanori",
    }
    ama = client.get(f"{API}/citizens/ama").json()
    assert ama["home"] == {"id": "band_a_camp:shelter-n", "name": "a lean-to at Band A camp"}
    sim = cast.sim.citizen("ama")
    meat = next(h for h in ama["inventory"] if h["item"] == "dried meat")
    assert meat["words"] == ("some dried meat" if meat["count"] <= 12 else "plenty of dried meat")
    assert {h["item"]: h["count"] for h in ama["inventory"]} == {k: v for k, v in sim.inventory.items() if v}


def test_profile_now_matches_the_simulation(client: TestClient, story: Story) -> None:
    sim = story.loop.sim.citizen("dev-aiko")
    profile = client.get(f"{API}/citizens/dev-aiko").json()
    assert profile["tick"] == 75 and profile["alive"] is True
    needs = {n["need"]: n for n in profile["needs"]}
    assert [n["need"] for n in profile["needs"]] == ["hunger", "thirst", "energy", "health"]
    assert needs["hunger"]["value"] == pytest.approx(sim.body.hunger)
    assert needs["energy"]["value"] == pytest.approx(sim.body.energy)
    assert {n["word"] for n in profile["needs"]} == {"fed", "quenched", "rested", "well"}
    assert tuple(profile["position"]["unit"]) == pytest.approx(sim.position, abs=1e-12)
    life = timeline(client, "dev-aiko")
    assert profile["recent"] == life[::-1][: citizens_service.RECENT_ENTRIES]
    genzo = client.get(f"{API}/citizens/dev-genzo").json()["recent"]
    assert len(genzo) == citizens_service.RECENT_ENTRIES and genzo[0]["summary"] == "dies: dehydration"


def test_profile_replays_the_state_at_a_past_tick(client: TestClient, story: Story) -> None:
    for citizen_id, then in story.at_65.items():
        profile = client.get(f"{API}/citizens/{citizen_id}", params={"at": 65}).json()
        assert profile["tick"] == 65 and profile["time"] == "09:05"
        values = [n["value"] for n in profile["needs"]]
        assert values == pytest.approx([then.body.hunger, then.body.thirst, then.body.energy, then.body.health])
        assert tuple(profile["position"]["unit"]) == pytest.approx(then.position, abs=1e-12)
        assert {p["id"]: p["level"] for p in profile["known_places"]} == {
            place_id: known.level for place_id, known in then.places.items()
        }
        assert {p["id"] for p in profile["known_people"]} == then.people
        assert profile["alive"] is then.body.alive is True
    aiko = client.get(f"{API}/citizens/dev-aiko", params={"at": 65}).json()
    assert {"id": "temple", "name": "the temple", "level": "rough"} in aiko["known_places"]  # Haru shouted of it
    assert {"id": "dev-haru", "name": "Haru", "role": ""} in aiko["known_people"]
    before = client.get(f"{API}/citizens/dev-aiko", params={"at": 0}).json()
    assert "temple" not in {p["id"] for p in before["known_places"]}
    assert "dev-haru" not in {p["id"] for p in before["known_people"]}
    dead = client.get(f"{API}/citizens/dev-genzo").json()
    assert (dead["alive"], dead["activity"], dead["cause_of_death"]) == (False, "dead", "dehydration")
    assert client.get(f"{API}/citizens/nobody").status_code == 404
    assert client.get(f"{API}/citizens/dev-aiko", params={"at": 99}).status_code == 404


# --- timeline ---


@pytest.mark.usefixtures("story")
def test_timeline_tells_a_life_in_order(client: TestClient) -> None:
    entries = timeline(client, "dev-aiko")
    assert [e["seq"] for e in entries] == sorted(e["seq"] for e in entries)
    assert not {"tick_summary", "perceived", "snapshot"} & {e["type"] for e in entries}
    lines = [(e["tick"], e["summary"]) for e in entries]
    assert lines[0] == (0, "comes into the world at the well")
    assert (2, 'hears Haru: "Hello there, I am Haru! Have you seen the temple?"') in lines
    assert (2, "gets to know Haru") in lines and (2, "hears of the temple") in lines
    shout = next(e for e in entries if e["type"] == "said" and e["summary"].startswith("shouts"))
    assert (shout["tick"], shout["summary"]) == (6, 'shouts "Good day, Haru!"')
    assert shout["detail"] == "heard by Genzo and Haru" and shout["related"] == ["dev-genzo", "dev-haru"]
    assert (36, "walks to the main gate") in lines
    arrived = next(e for e in entries if e["type"] == "action_finished" and e["tick"] >= 36)
    assert arrived["summary"] == "arrives at the main gate" and arrived["detail"] == "You arrive at the main gate."
    assert (entries[0]["day"], entries[0]["time"]) == (0, "08:00")
    genzo = [e["summary"] for e in timeline(client, "dev-genzo")]
    assert 'whispers "Is anyone there?"' in genzo and genzo[-1] == "dies: dehydration"
    whisper = next(e for e in timeline(client, "dev-genzo") if e["summary"].startswith("whispers"))
    assert whisper["detail"] == "nobody heard"


@pytest.mark.usefixtures("story")
def test_timeline_pages_filters_and_orders(client: TestClient) -> None:
    everything = timeline(client, "dev-aiko")
    assert timeline(client, "dev-aiko", order="desc") == everything[::-1]
    pages: list[dict[str, Any]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 3, **({"cursor": cursor} if cursor is not None else {})}
        page = client.get(f"{API}/citizens/dev-aiko/timeline", params=params).json()
        pages += page["entries"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == everything
    whole = client.get(f"{API}/citizens/dev-aiko/timeline", params={"limit": len(everything) + 1}).json()
    assert whole["next_cursor"] is None and len(whole["entries"]) == len(everything)
    exact = client.get(f"{API}/citizens/dev-aiko/timeline", params={"limit": len(everything) - 1}).json()
    assert exact["next_cursor"] == everything[-2]["seq"]
    window = timeline(client, "dev-aiko", from_tick=2, to_tick=6)
    assert window == [e for e in everything if 2 <= e["tick"] <= 6] and len(window) >= 4
    looks = timeline(client, "dev-aiko", type="perceived")
    assert all(e["type"] == "perceived" and e["summary"] == "looks around" for e in looks)
    knowledge = timeline(client, "dev-aiko", type="knowledge_changed")
    assert [e["summary"] for e in knowledge] == ["gets to know Haru", "hears of the temple"]
    unheard = timeline(client, "dev-aiko", type="action_started")
    assert all(e["type"] == "action_started" for e in unheard) and unheard
    assert client.get(f"{API}/citizens/nobody/timeline").status_code == 404
    assert client.get(f"{API}/citizens/dev-aiko/timeline", params={"limit": 0}).status_code == 422


# --- needs ---


def test_needs_follow_the_tick_summaries(client: TestClient, story: Story) -> None:
    series = client.get(f"{API}/citizens/dev-aiko/needs", params={"from_tick": 0, "step": 1}).json()
    assert (series["from_tick"], series["to_tick"], series["step"]) == (0, 75, 1)
    assert [p["tick"] for p in series["points"]] == list(range(1, 76))
    for point in series["points"]:
        expected = story.bodies[point["tick"]]["dev-aiko"]
        assert (point["hunger"], point["thirst"], point["energy"], point["health"]) == pytest.approx(expected)
    stepped = client.get(f"{API}/citizens/dev-aiko/needs", params={"from_tick": 5, "to_tick": 50, "step": 10}).json()
    assert [p["tick"] for p in stepped["points"]] == [5, 15, 25, 35, 45]
    default = client.get(f"{API}/citizens/dev-aiko/needs").json()
    assert (default["from_tick"], default["to_tick"], default["step"]) == (0, 75, 1)
    genzo = client.get(f"{API}/citizens/dev-genzo/needs", params={"step": 1}).json()["points"]
    last = genzo[-1]
    assert last["tick"] < 75 and last["health"] < 0.15 and genzo[-2]["tick"] == last["tick"] - 1
    assert all(story.bodies[p["tick"]]["dev-genzo"][3] == pytest.approx(p["health"]) for p in genzo)
    assert client.get(f"{API}/citizens/nobody/needs").status_code == 404


@pytest.mark.usefixtures("story")
def test_needs_cap_the_number_of_points(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citizens_service, "MAX_NEED_POINTS", 10)
    series = client.get(f"{API}/citizens/dev-aiko/needs", params={"from_tick": 0, "step": 1}).json()
    assert series["step"] == 8 and [p["tick"] for p in series["points"]] == list(range(8, 76, 8))


def test_every_arrival_is_named(client: TestClient, cast: EngineLoop) -> None:
    arrivals = 0
    for citizen_id in cast.sim.state.citizens:
        for entry in timeline(client, citizen_id, type=["action_started", "action_finished"]):
            text = entry["detail"] or ""
            if entry["type"] == "action_finished" and text.startswith("You arrive at "):
                arrivals += 1
                assert entry["summary"] == "arrives at " + text.removeprefix("You arrive at ").rstrip("."), entry
    assert arrivals >= 5
