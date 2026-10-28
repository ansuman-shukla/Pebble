from collections import Counter

from fastapi.testclient import TestClient

from app.core.config import settings
from app.world.town import TownView

TOWN_URL = f"{settings.API_V1_STR}/town"
TOWN_LOOKS = {"town-lord", "town-samurai", "town-merchant", "town-farmer", "town-weaver", "town-child"}


def test_town_is_served(client: TestClient) -> None:
    response = client.get(TOWN_URL)

    assert response.status_code == 200
    town = TownView.model_validate(response.json())
    extent = town.extent
    assert extent.min_x <= town.spawn.x <= extent.max_x
    assert extent.min_z <= town.spawn.z <= extent.max_z
    assert Counter(placement.kind for placement in town.placements)["castle_keep"] == 1
    assert len(town.citizens) == 6
    assert {citizen.look for citizen in town.citizens} == TOWN_LOOKS


def test_town_response_uses_the_contract_fields(client: TestClient) -> None:
    body = client.get(TOWN_URL).json()

    assert set(body) == {"name", "extent", "spawn", "areas", "water", "placements", "citizens"}
    assert set(body["spawn"]) == {"x", "z", "heading_deg"}
    assert set(body["placements"][0]) == {"id", "kind", "x", "z", "rotation_deg", "footprint", "walk"}
    assert set(body["citizens"][0]) == {"look", "x", "z", "heading_deg", "route"}
    moat = next(water for water in body["water"] if water["id"] == "moat")
    assert moat["holes"] == [[[-31, -31], [31, -31], [31, 31], [-31, 31]]]


def test_town_schema_names_the_town_models(client: TestClient) -> None:
    schemas = client.get(f"{settings.API_V1_STR}/openapi.json").json()["components"]["schemas"]

    for name in ("TownView", "TownPlacement", "TownWater", "TownArea", "TownCitizen", "Spawn", "Extent", "Footprint"):
        assert name in schemas, name
