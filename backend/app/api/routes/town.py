from fastapi import APIRouter

from app.world.town import TownView, load_town

router = APIRouter(prefix="/town", tags=["town"])


@router.get("", response_model=TownView)
def read_town() -> TownView:
    return load_town()
