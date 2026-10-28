from collections.abc import Mapping

import pytest
from sqlmodel import Session, func, select

from app.db.models import World
from app.world.spec import WorldSpec, load_site_kinds, load_world_spec
from app.world.store import WorldGenerator, find_payload, load_or_generate, save_payload, world_key
from app.world.town import KindSpec
from app.world.view import WorldView


class CountingGenerator:
    """Stands in for the real generator: a tiny view, and a count of how often it ran."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, spec: WorldSpec, kinds: Mapping[str, KindSpec]) -> WorldView:
        self.calls += 1
        return WorldView(
            seed=spec.seed,
            generator_version="test",
            radius_m=spec.radius_m,
            frequency=spec.frequency,
            cell_count=len(kinds),
            biome_names=[],
            positions="",
            heights="",
            biomes="",
            triangles="",
            rivers=[],
            land_loop=[],
            sites=[],
        )


@pytest.fixture
def counting() -> CountingGenerator:
    return CountingGenerator()


def _rows(session: Session) -> int:
    return session.exec(select(func.count()).select_from(World)).one()


def test_first_load_generates_and_stores_then_reads_back(db_session: Session, counting: CountingGenerator) -> None:
    spec, kinds = load_world_spec(), load_site_kinds()
    generator = WorldGenerator(version="test-1", generate=counting)
    before = _rows(db_session)

    first = load_or_generate(db_session, spec, kinds, generator)
    second = load_or_generate(db_session, spec, kinds, generator)

    assert counting.calls == 1
    assert first == second
    assert WorldView.model_validate_json(first).seed == spec.seed
    assert _rows(db_session) == before + 1


def test_a_new_seed_or_generator_version_is_another_world(db_session: Session, counting: CountingGenerator) -> None:
    spec, kinds = load_world_spec(), load_site_kinds()

    load_or_generate(db_session, spec, kinds, WorldGenerator(version="test-1", generate=counting))
    load_or_generate(db_session, spec, kinds, WorldGenerator(version="test-2", generate=counting))
    load_or_generate(
        db_session, spec.model_copy(update={"seed": 7}), kinds, WorldGenerator(version="test-2", generate=counting)
    )

    assert counting.calls == 3


def test_saving_a_stored_world_keeps_the_first_payload(db_session: Session) -> None:
    key = world_key(load_world_spec(), load_site_kinds(), "test-1")

    assert find_payload(db_session, key) is None
    assert save_payload(db_session, key, b'{"first": 1}') == b'{"first": 1}'
    assert save_payload(db_session, key, b'{"second": 2}') == b'{"first": 1}'
    assert find_payload(db_session, key) == b'{"first": 1}'
