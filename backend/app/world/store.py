"""Generated worlds in Postgres: one row per (seed, generator version, spec hash), generated on first use."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.db.models import World
from app.world.spec import WorldSpec, spec_hash
from app.world.town import KindSpec
from app.world.view import WorldView


@dataclass(frozen=True)
class WorldGenerator:
    version: str
    generate: Callable[[WorldSpec, Mapping[str, KindSpec]], WorldView]


@dataclass(frozen=True)
class WorldKey:
    seed: int
    generator_version: str
    spec_hash: str


def world_key(spec: WorldSpec, kinds: Mapping[str, KindSpec], generator_version: str) -> WorldKey:
    return WorldKey(seed=spec.seed, generator_version=generator_version, spec_hash=spec_hash(spec, kinds))


def find_payload(session: Session, key: WorldKey) -> bytes | None:
    statement = select(World.payload).where(
        World.seed == key.seed,
        World.generator_version == key.generator_version,
        World.spec_hash == key.spec_hash,
    )
    return session.exec(statement).first()


def save_payload(session: Session, key: WorldKey, payload: bytes) -> bytes:
    """Store the payload unless that world is already stored; returns the stored payload either way."""
    statement = (
        insert(World)
        .values(seed=key.seed, generator_version=key.generator_version, spec_hash=key.spec_hash, payload=payload)
        .on_conflict_do_nothing(index_elements=["seed", "generator_version", "spec_hash"])
    )
    session.execute(statement)
    session.commit()
    stored = find_payload(session, key)
    if stored is None:
        raise RuntimeError(f"world {key} vanished right after it was stored")
    return stored


def load_or_generate(
    session: Session, spec: WorldSpec, kinds: Mapping[str, KindSpec], generator: WorldGenerator
) -> bytes:
    """The stored WorldView JSON for this spec, generating and storing it first if needed."""
    key = world_key(spec, kinds, generator.version)
    stored = find_payload(session, key)
    if stored is not None:
        return stored
    return save_payload(session, key, generator.generate(spec, kinds).model_dump_json().encode())
