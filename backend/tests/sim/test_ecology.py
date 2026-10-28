"""Wild plants grow back after gathering on the 02 schedule (berries ~3 days, roots ~5, nuts ~7), one event a piece."""

from collections.abc import Callable

import pytest

from app.observability.replay import ReplayEvent, from_snapshot, replay
from app.sim.clock import DAY_MINUTES
from app.sim.ecology import schedule_regrowth
from app.sim.items import RESOURCE_INDEX
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, state_hash, take_snapshot
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import make_spec


def _bare_cell(sim: Simulation, resource: str) -> tuple[int, int]:
    """A cell that can hold the resource, emptied as if gathered bare (and growing back); returns (cell, cap)."""
    column = RESOURCE_INDEX[resource]
    caps = sim.world.resource_caps[:, column]
    cell = int(caps.argmax())
    sim.state.resources[cell, column] = 0
    schedule_regrowth(sim.core, cell, resource)
    return cell, int(caps[cell])


@pytest.mark.parametrize(("resource", "days"), [("berries", 3.0), ("roots", 5.0), ("nuts", 7.0)])
def test_a_bare_cell_is_full_again_on_schedule(new_sim: Callable[..., Simulation], resource: str, days: float) -> None:
    sim = new_sim()
    cell, cap = _bare_cell(sim, resource)
    column = RESOURCE_INDEX[resource]
    start = take_snapshot(sim.state)
    sim.run(round(days * DAY_MINUTES * 0.5))
    assert abs(int(sim.state.resources[cell, column]) - cap / 2) <= 1  # steady growth
    sim.run(round(days * DAY_MINUTES * 0.45))
    assert int(sim.state.resources[cell, column]) < cap  # not early
    sim.run(round(days * DAY_MINUTES * 0.06))
    assert int(sim.state.resources[cell, column]) == cap
    assert f"{cell}:{resource}" not in sim.state.regrow  # full: nothing left to grow
    events = sim.drain()
    grown = [e for e in events if e.type == "resource_changed"]
    assert len(grown) == cap and all(e.actor_id is None for e in grown)
    replayable = [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    assert replay(start, replayable).same_as(from_snapshot(take_snapshot(sim.state)))
    sim.run(DAY_MINUTES)
    assert int(sim.state.resources[cell, column]) == cap  # never beyond the cap


def test_gathering_starts_regrowth_and_it_survives_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    gatherer = sim.add_citizen(make_spec("gatherer", site="band_b_camp", at=(0.0, 10.0), home=None, knows_places=[]))
    api = WorldApi(sim, gatherer.id)
    cell = gatherer.cell
    column = RESOURCE_INDEX["berries"]
    before = int(sim.state.resources[cell, column])
    assert run_until_done(sim, api.gather("berries"), 30).outcome == "done"
    after = int(sim.state.resources[cell, column])
    assert after < before
    due = sim.state.regrow[f"{cell}:berries"]
    assert sim.tick < due <= sim.tick + 3 * DAY_MINUTES / int(sim.world.resource_caps[cell, column]) + 1
    resumed = Simulation(sim.world, restore(take_snapshot(sim.state)), sim.core.planner)
    assert state_hash(resumed.state) == state_hash(sim.state)
    resumed.run(due - resumed.tick)
    assert int(resumed.state.resources[cell, column]) == after + 1
