from fastapi import APIRouter, Response

from app.api.deps import SessionDep, WorldGeneratorDep
from app.world.spec import load_site_kinds, load_world_spec
from app.world.store import load_or_generate
from app.world.view import WorldView

router = APIRouter(prefix="/world", tags=["world"])


@router.get("", response_model=WorldView)
def read_world(session: SessionDep, generator: WorldGeneratorDep) -> Response:
    """The planet: grid, heights, biomes, rivers, land loop and sites (stored JSON, generated on first request)."""
    payload = load_or_generate(session, load_world_spec(), load_site_kinds(), generator)
    return Response(content=payload, media_type="application/json")
