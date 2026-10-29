"""A thirsty town brain standing at the well but out of its reach walks up to it instead of trying to drink forever.

Regression: "at the well" (the place) let a town brain choose `drink` however far from the well itself it stood; the
drink failed ("There's no water within reach.") and the brain chose it again, waiting in between, until it died of
thirst a few paces from the well (seed 7, Hana, once walking speeds changed who stood where).
"""

from collections.abc import Callable

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.sim.doing import water_within_reach
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec

SEED = 7
BY_THE_WELL = (-25.9, 52.75)  # where Hana stood: "at the well", out of its reach


def test_a_thirsty_brain_out_of_reach_of_the_well_walks_up_to_it_and_drinks(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    hana = sim.add_citizen(make_spec("hana", name="Hana", at=BY_THE_WELL, home=None))
    hana.body.thirst = 70.0
    assert water_within_reach(sim.core, hana) is None
    assert "at the well" in WorldApi(sim, hana.id).look_around().place
    profile = BrainProfile(citizen_id=hana.id, name=hana.name, role="child", region="town", home_area="the town")
    brain = UtilityBrain(WorldApi(sim, hana.id), profile, SEED)
    for _ in range(30):
        brain.tick()
        sim.step()
        if hana.body.thirst < 10:
            break
    assert hana.body.thirst < 10
    assert water_within_reach(sim.core, hana) == ("fresh", "the well")
