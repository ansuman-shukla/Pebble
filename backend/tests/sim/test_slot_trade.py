"""A walk to a place lands on the work slot of the walker's own trade first (D166): the lord, who also bears arms,
walks to the castle onto his seat, not onto the nearer guard stand at its gate, so he doesn't set to governing 27 m
from his seat and get walked there at the tick's end (issue #89)."""

from collections.abc import Callable

import pytest

from app.sim.simulation import Simulation
from app.sim.slots import claim_of
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec

INSIDE_THE_GATE = (0.0, 98.0)


@pytest.mark.parametrize(
    ("skills", "slot"),
    [
        (["governing", "arms"], "castle-keep#lord-seat"),
        (["arms", "governing"], "castle-gate#guard-2"),  # arms first: the nearest guard stand
        (["arms"], "castle-gate#guard-2"),
    ],
)
def test_a_walk_to_the_castle_ends_on_the_slot_of_the_walkers_first_trade(
    new_sim: Callable[..., Simulation], skills: list[str], slot: str
) -> None:
    sim = new_sim()
    walker = sim.add_citizen(make_spec("walker", at=INSIDE_THE_GATE, skills=skills, knows_places=["town", "castle"]))
    WorldApi(sim, walker.id).walk_to_place("the castle")
    claimed = claim_of(sim.core, walker)
    assert claimed is not None and claimed.slot == slot
