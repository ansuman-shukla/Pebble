"""With brains on, the world stays deterministic: the same seed gives the same day, and a run resumed from a snapshot
(with brand-new brain objects) continues exactly as if it had never stopped."""

import hashlib
import json
from collections.abc import Callable

from app.engine import citizen_brains
from app.observability.events import EventDraft
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, state_hash, take_snapshot

SEED = 7


def _populate(sim: Simulation) -> None:
    sim.add_cast(load_citizens(CITIZENS))


def _live(sim: Simulation, ticks: int, seed: int = SEED) -> list[EventDraft]:
    brains = citizen_brains(sim, seed)
    events: list[EventDraft] = []
    for _ in range(ticks):
        brains(sim)
        sim.step()
        events += sim.drain()
    return events


def _hash(events: list[EventDraft]) -> str:
    rows = [(e.seq, e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def test_the_same_seed_lives_the_same_day(new_sim: Callable[..., Simulation]) -> None:
    hashes = []
    for _ in range(2):
        sim = new_sim(seed=SEED)
        _populate(sim)
        events = _live(sim, DAY_MINUTES)
        assert sum(e.type == "action_started" for e in events) > 300  # they really lived it
        hashes.append((_hash(events), state_hash(sim.state)))
    assert hashes[0] == hashes[1]
    other = new_sim(seed=SEED)
    _populate(other)
    assert _hash(_live(other, DAY_MINUTES, seed=SEED + 1)) != hashes[0][0]  # brains really draw on the seed


def test_a_resumed_run_with_new_brains_continues_identically(new_sim: Callable[..., Simulation]) -> None:
    straight = new_sim(seed=SEED)
    _populate(straight)
    brains = citizen_brains(straight, SEED)
    for _ in range(6 * 60):
        brains(straight)
        straight.step()
    snapshot = take_snapshot(straight.state)
    straight.drain()
    for _ in range(6 * 60):
        brains(straight)
        straight.step()
    future = _hash(straight.drain())

    resumed = Simulation(straight.world, restore(snapshot), straight.core.planner)
    assert _hash(_live(resumed, 6 * 60)) == future
    assert state_hash(resumed.state) == state_hash(straight.state)
