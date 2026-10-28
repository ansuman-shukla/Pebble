"""Runs for the spectator endpoint tests (citizens, timeline, needs, conversations, stats).

`story` is a scripted dev run (no brains) with a known shape:

```
 tick 2   Haru shouts at the market (Aiko and Genzo hear him; Aiko learns his name and of the temple)
 tick 6   Aiko shouts back from the well                       ─┐ one thread in the castle town
 tick 36  Genzo whispers alone; Aiko sets off for the main gate ─── a thread of its own (30 min of silence)
 tick 65  everyone's state is captured (a snapshot was taken at 60)
 tick 66  Genzo is made parched and nearly dead; he dies of dehydration a tick or two later
 tick 75  the end
```
"""

import copy
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.engine import Clock, EngineLoop, open_loop
from app.sim.citizens import CITIZENS, DEV_CITIZENS
from app.sim.state import Citizen
from app.sim.world import SimWorld
from app.world.store import WorldKey
from app.world_api.facade import WorldApi

API = settings.API_V1_STR
KEY = WorldKey(seed=20261028, generator_version="test", spec_hash="2" * 64)
Bodies = dict[int, dict[str, tuple[float, float, float, float]]]  # tick -> citizen -> needs after that tick


@dataclass
class Story:
    loop: EngineLoop
    at_65: dict[str, Citizen]  # deep copies of everyone at tick 65
    bodies: Bodies


def run_recording(loop: EngineLoop, ticks: int, bodies: Bodies) -> None:
    for _ in range(ticks):
        loop.run_ticks(1, headless=True)
        bodies[loop.sim.tick] = {
            c.id: (c.body.hunger, c.body.thirst, c.body.energy, c.body.health)
            for c in loop.sim.state.citizens.values()
            if c.body.alive
        }


def dev_run(session: Session, world: SimWorld) -> EngineLoop:
    return open_loop(session, world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock(speed=3), brains=False)


def tell_story(session: Session, world: SimWorld) -> Story:
    loop = dev_run(session, world)
    haru, aiko, genzo = (WorldApi(loop.sim, f"dev-{name}") for name in ("haru", "aiko", "genzo"))
    bodies: Bodies = {}
    run_recording(loop, 2, bodies)
    haru.say("Hello there, I am Haru! Have you seen the temple?", "shout")
    run_recording(loop, 4, bodies)
    aiko.say("Good day, Haru!", "shout")
    run_recording(loop, 30, bodies)
    genzo.say("Is anyone there?", "whisper")
    aiko.walk_to_place("the main gate")
    run_recording(loop, 29, bodies)
    at_65 = copy.deepcopy(loop.sim.state.citizens)
    body = loop.sim.citizen("dev-genzo").body
    body.thirst, body.health = 95.0, 0.15
    run_recording(loop, 10, bodies)
    return Story(loop=loop, at_65=at_65, bodies=bodies)


def live_cast(session: Session, world: SimWorld) -> EngineLoop:
    """The real cast of 15 with their brains, for 70 minutes."""
    loop = open_loop(session, world, KEY, new_run=True, citizens=CITIZENS, clock=Clock(speed=1), brains=True)
    loop.run_ticks(70, headless=True)
    return loop


def timeline(client: TestClient, citizen: str, **params: Any) -> list[dict[str, Any]]:
    response = client.get(f"{API}/citizens/{citizen}/timeline", params={"limit": 500, **params})
    assert response.status_code == 200, response.text
    entries: list[dict[str, Any]] = response.json()["entries"]
    return entries
