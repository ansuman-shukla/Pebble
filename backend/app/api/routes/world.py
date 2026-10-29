from fastapi import APIRouter, Request, Response

from app.api.deps import SessionDep, WorldGeneratorDep
from app.services.places import world_layout
from app.world.spec import load_site_kinds, load_world_spec
from app.world.store import load_or_generate
from app.world.view import WorldPlaces, WorldView

router = APIRouter(prefix="/world", tags=["world"])

_CACHE = "public, max-age=3600"


@router.get("", response_model=WorldView)
def read_world(session: SessionDep, generator: WorldGeneratorDep) -> Response:
    """The planet: grid, heights, biomes, rivers, land loop, sites and places (stored, generated on first request)."""
    payload = load_or_generate(session, load_world_spec(), load_site_kinds(), generator)
    return Response(content=payload, media_type="application/json")


@router.get("/places", response_model=WorldPlaces)
def read_places(session: SessionDep, generator: WorldGeneratorDep) -> WorldPlaces:
    """Hotspots, hunting grounds, fixed features (nodes, dens, signposts, markers), roads, bridges and flora kinds."""
    return world_layout(session, generator).places


@router.get(
    "/flora",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The packed flora table."}},
)
def read_flora(request: Request, session: SessionDep, generator: WorldGeneratorDep) -> Response:
    """Every usable tree, bush, root patch, reed bed and deadwood pile, packed (layout in `app.world.flora`):
    `cell u32[n] | east i8[n] | north i8[n] | kind u8[n] | scale u8[n] | yaw u8[n]`, little-endian, n = bytes / 9."""
    layout = world_layout(session, generator)
    etag = f'"{layout.key.generator_version}-{layout.key.spec_hash[:16]}"'
    headers = {"Cache-Control": _CACHE, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=layout.flora, media_type="application/octet-stream", headers=headers)
