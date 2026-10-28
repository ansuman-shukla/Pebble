"""Conversations: speech grouped into threads by the people in them and the time between lines."""

import pytest
from fastapi.testclient import TestClient

from app.world_api.facade import WorldApi
from tests.api.spectator import API, Story


@pytest.mark.usefixtures("spectator_session")
def test_no_run_yet_is_a_404(client: TestClient) -> None:
    assert client.get(f"{API}/conversations").status_code == 404


@pytest.mark.usefixtures("story")
def test_conversations_group_speech_by_place_and_time(client: TestClient) -> None:
    threads = client.get(f"{API}/conversations").json()["threads"]
    assert [t["start_tick"] for t in threads] == [36, 2]  # newest first
    lonely, greeting = threads
    assert [line["words"] for line in greeting["lines"]] == [
        "Hello there, I am Haru! Have you seen the temple?",
        "Good day, Haru!",
    ]
    assert [s["name"] for s in greeting["speakers"]] == ["Haru", "Aiko"]
    assert [p["id"] for p in greeting["listeners"]] == ["dev-genzo"]
    assert greeting["place"] == {"id": "market", "name": "the market"}  # where Haru began
    assert greeting["area"] == {"id": "town", "name": "The castle town"}
    assert (greeting["end_tick"], greeting["day"], greeting["time"]) == (6, 0, "08:02")
    assert [h["id"] for h in greeting["lines"][1]["heard_by"]] == ["dev-genzo", "dev-haru"]
    assert greeting["lines"][0]["volume"] == "shout"
    assert [line["words"] for line in lonely["lines"]] == ["Is anyone there?"] and lonely["listeners"] == []
    at_market = client.get(f"{API}/conversations", params={"place": "market"}).json()["threads"]
    assert [t["id"] for t in at_market] == [greeting["id"]]
    in_town = client.get(f"{API}/conversations", params={"place": "town"}).json()["threads"]
    assert len(in_town) == 2
    early = client.get(f"{API}/conversations", params={"to_tick": 10}).json()
    assert [t["id"] for t in early["threads"]] == [greeting["id"]] and early["to_tick"] == 10
    late = client.get(f"{API}/conversations", params={"from_tick": 7}).json()
    assert [t["id"] for t in late["threads"]] == [lonely["id"]]
    assert len(client.get(f"{API}/conversations", params={"limit": 1}).json()["threads"]) == 1


def test_a_silence_longer_than_the_gap_starts_a_new_thread(client: TestClient, story: Story) -> None:
    loop = story.loop
    WorldApi(loop.sim, "dev-haru").say("Still here?", "shout")
    loop.run_ticks(5, headless=True)
    WorldApi(loop.sim, "dev-aiko").say("Yes!", "shout")
    loop.run_ticks(11, headless=True)
    WorldApi(loop.sim, "dev-haru").say("Good.", "shout")
    loop.run_ticks(11, headless=True)
    WorldApi(loop.sim, "dev-haru").say("Hm.")  # nobody is within 30 m of the market: a thread of one
    loop.run_ticks(2, headless=True)
    WorldApi(loop.sim, "dev-aiko").say("Haru, over here!", "shout")  # she wasn't in it, but he hears her
    loop.run_ticks(1, headless=True)
    threads = client.get(f"{API}/conversations", params={"from_tick": 70}).json()["threads"]
    assert [[line["words"] for line in t["lines"]] for t in threads] == [
        ["Hm.", "Haru, over here!"],
        ["Good."],
        ["Still here?", "Yes!"],
    ]
    assert threads[0]["lines"][0]["heard_by"] == []
