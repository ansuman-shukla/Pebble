from fastapi import APIRouter

from app.api.routes import admin, citizens, clock, entities, events, health, live, town, world

api_router = APIRouter()
api_router.include_router(admin.router)
api_router.include_router(citizens.router)
api_router.include_router(clock.router)
api_router.include_router(entities.router)
api_router.include_router(events.router)
api_router.include_router(health.router)
api_router.include_router(live.router)
api_router.include_router(town.router)
api_router.include_router(world.router)
