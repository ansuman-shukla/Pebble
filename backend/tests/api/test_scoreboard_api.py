"""`GET /scoreboard` (10-world-v1 §7) on the real cast's first 70 minutes."""

import pytest
from fastapi.testclient import TestClient

from app.engine import EngineLoop
from app.sim.society import SOCIETY
from app.sim.tax import chest_share, household_goods, wealth_mon
from tests.api.spectator import API


@pytest.mark.usefixtures("spectator_session")
def test_no_run_yet_is_a_404(client: TestClient) -> None:
    assert client.get(f"{API}/scoreboard").status_code == 404


def test_the_board_reads_the_run_now_and_at_a_past_tick(client: TestClient, cast: EngineLoop) -> None:
    board = client.get(f"{API}/scoreboard").json()
    state = cast.sim.state
    society = SOCIETY.of(state)
    assert (board["tick"], len(board["citizens"])) == (70, 22)
    assert (board["money_supply"], board["money_supply_ok"]) == (3000, True)
    residents = {"castle-keep": 2, "farmhouse-1": 3}  # the lord and his samurai; Genzo's household
    for row in board["citizens"]:
        citizen = state.citizens[row["id"]]
        goods = household_goods(state.stores, citizen.home) if citizen.home else {}  # its chest and field racks
        share = chest_share(goods, residents.get(citizen.home or "", 1))
        assert row["coins"] == citizen.inventory.get("coins", 0)
        assert row["wealth_mon"] == wealth_mon(citizen.inventory, citizen.region, share)
        assert (row["rank"], row["titles"]) == (society.members[citizen.id].rank, society.members[citizen.id].titles)
        assert row["standing"] == society.standing[citizen.id][citizen.region]
        assert row["ambition"] is not None and 0 <= row["ambition"]["progress"] <= 100
    rows = {row["id"]: row for row in board["citizens"]}
    assert rows["masanori"]["titles"] == ["lord"] and rows["masanori"]["wealth_mon"] > 1000  # half the treasury
    assert rows["fumiko"]["ambition"]["done"]  # 500 coins of the 300 she wants
    (stall,) = board["stalls"]
    rice = state.stores["market-stall"].get("rice", 0)  # the town buys and sells from the first hour (BR1)
    assert stall["keeper"] == "Fumiko" and {g["item"]: g["stock"] for g in stall["goods"]}["rice"] == rice

    first = client.get(f"{API}/scoreboard", params={"at": 0}).json()
    assert first["tick"] == 0 and all(row["income_24h"] == 0 for row in first["citizens"])
    assert client.get(f"{API}/scoreboard", params={"at": 71}).status_code == 404
