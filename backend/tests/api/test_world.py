import hashlib
from collections.abc import Iterator, Mapping

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_place_index, get_session, get_world_generator
from app.core.config import settings
from app.main import app
from app.services import places as places_service
from app.services.places import PlaceIndex
from app.sim.furniture import Furniture
from app.sim.world import SimWorld
from app.world.flora import generate_flora
from app.world.generate import GENERATOR, generate_view
from app.world.spec import BIOME_NAMES, SITE_IDS, WorldSpec, load_world_spec
from app.world.store import WorldGenerator
from app.world.town import KindSpec
from app.world.view import WorldPlaces, WorldView, decode_array
from tests.sim.test_furniture import furniture_of

WORLD_URL = f"{settings.API_V1_STR}/world"


class CountingGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, spec: WorldSpec, kinds: Mapping[str, KindSpec]) -> WorldView:
        self.calls += 1
        return generate_view(spec, kinds)


@pytest.fixture
def counting(db_session: Session) -> Iterator[CountingGenerator]:
    counting = CountingGenerator()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_world_generator] = lambda: WorldGenerator(
        version=f"{GENERATOR.version}-api-test", generate=counting
    )
    yield counting


@pytest.fixture
def world_response(client: TestClient, counting: CountingGenerator) -> dict[str, object]:
    response = client.get(WORLD_URL)
    assert response.status_code == 200
    assert counting.calls == 1
    body: dict[str, object] = response.json()
    return body


def test_world_is_served_with_the_contract_fields(world_response: dict[str, object]) -> None:
    assert set(world_response) == {
        "seed",
        "generator_version",
        "radius_m",
        "frequency",
        "cell_count",
        "biome_names",
        "positions",
        "heights",
        "biomes",
        "triangles",
        "rivers",
        "land_loop",
        "sites",
        "places",
    }
    world = WorldView.model_validate(world_response)
    assert world.generator_version == GENERATOR.version
    assert world.biome_names == list(BIOME_NAMES)
    assert {site.id for site in world.sites} == set(SITE_IDS)
    site = world.sites[0].model_dump()
    assert set(site) == {"id", "kind", "name", "cell", "anchor", "placements"}
    assert set(site["anchor"]) == {"position", "east", "north", "height_m"}


def test_world_arrays_decode_to_the_right_lengths(world_response: dict[str, object]) -> None:
    world = WorldView.model_validate(world_response)
    n = world.cell_count

    positions = decode_array(world.positions, "<f4").reshape(n, 3)
    heights = decode_array(world.heights, "<f4")
    biomes = decode_array(world.biomes, "u1")
    triangles = decode_array(world.triangles, "<u4").reshape(-1, 3)

    assert n == 36_002 and len(heights) == n and len(biomes) == n
    assert len(triangles) == 72_000 and int(triangles.max()) == n - 1
    np.testing.assert_allclose(np.linalg.norm(positions, axis=1), 1, atol=1e-6)
    assert int(biomes.max()) < len(BIOME_NAMES)
    assert all(0 <= cell < n for river in world.rivers for cell in river.cells)


def test_second_request_reads_the_stored_world(client: TestClient, counting: CountingGenerator) -> None:
    first = client.get(WORLD_URL)
    second = client.get(WORLD_URL)

    assert counting.calls == 1
    assert first.content == second.content


def test_world_is_gzipped_when_asked(client: TestClient, counting: CountingGenerator) -> None:
    zipped = client.get(WORLD_URL, headers={"Accept-Encoding": "gzip"})
    plain = client.get(WORLD_URL, headers={"Accept-Encoding": "identity"})

    assert zipped.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in plain.headers
    assert zipped.content == plain.content  # the client decodes gzip transparently
    assert int(zipped.headers["content-length"]) < len(plain.content) / 2
    assert counting.calls == 1


def test_world_schema_names_the_world_models(client: TestClient) -> None:
    schemas = client.get(f"{settings.API_V1_STR}/openapi.json").json()["components"]["schemas"]

    for name in ("WorldView", "Site", "Anchor", "River", "TownPlacement"):
        assert name in schemas, name


def test_places_are_served_from_the_stored_world(client: TestClient, counting: CountingGenerator) -> None:
    world = WorldView.model_validate(client.get(WORLD_URL).json())
    response = client.get(f"{WORLD_URL}/places")

    assert response.status_code == 200
    places = WorldPlaces.model_validate(response.json())
    assert places == world.places
    assert len(places.hotspots) == 14 and places.flora_kinds[0] == "oak_tree"
    assert counting.calls == 1


def test_flora_is_served_packed_cached_and_revalidated(client: TestClient, counting: CountingGenerator) -> None:
    world = WorldView.model_validate(client.get(WORLD_URL).json())
    response = client.get(f"{WORLD_URL}/flora")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content == generate_flora(world, load_world_spec()).pack()
    assert len(response.content) % 9 == 0 and len(response.content) > 9 * 40_000
    etag = response.headers["etag"]
    assert etag == f'"{hashlib.sha256(response.content).hexdigest()[:32]}"'
    assert response.headers["cache-control"] == "no-cache"
    again = client.get(f"{WORLD_URL}/flora", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == etag and again.headers["cache-control"] == "no-cache"
    assert counting.calls == 1


@pytest.mark.usefixtures("counting")
def test_new_flora_code_on_the_same_world_is_new_bytes_under_a_new_etag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = client.get(f"{WORLD_URL}/flora")
    monkeypatch.setattr(places_service, "_layouts", {})  # a new api process with new flora code
    monkeypatch.setattr(places_service, "generate_flora", lambda *_: _Packed(bytes(9)))

    new = client.get(f"{WORLD_URL}/flora", headers={"If-None-Match": old.headers["etag"]})

    assert new.status_code == 200 and new.content == bytes(9)
    assert new.headers["etag"] != old.headers["etag"]


class _Packed:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def pack(self) -> bytes:
        return self.data


def test_world_schema_names_the_places_models(client: TestClient) -> None:
    schemas = client.get(f"{settings.API_V1_STR}/openapi.json").json()["components"]["schemas"]

    for name in ("WorldPlaces", "Hotspot", "Feature", "Road", "Bridge", "Ground"):
        assert name in schemas, name


def test_furniture_is_served_in_each_sites_chart(client: TestClient, sim_world: SimWorld) -> None:
    app.dependency_overrides[get_place_index] = lambda: PlaceIndex(sim_world)
    response = client.get(f"{WORLD_URL}/furniture")

    assert response.status_code == 200
    assert [Furniture.model_validate(piece) for piece in response.json()] == furniture_of(sim_world)
    assert set(response.json()[0]) == {"id", "site", "kind", "x", "z", "heading_deg", "seat_m", "span_m"}
