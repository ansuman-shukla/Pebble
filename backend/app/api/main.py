from fastapi import APIRouter

from app.api.routes import health, town, world

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(town.router)
api_router.include_router(world.router)
