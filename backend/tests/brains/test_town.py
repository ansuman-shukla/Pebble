"""BR1's town brains (10-world-v1 §3.1, §2): who they know holds a title, buying and selling at the stall, dues on
court day, the smith's forge, the weaver's reeds, the digger's trips and the night watch."""

from collections.abc import Callable

from app.engine import citizen_brains
from app.sim.simulation import Simulation
from tests.sim_helpers import make_spec


def test_brains_know_titles_from_what_people_hold_not_from_their_role_words(
    new_sim: Callable[..., Simulation],
) -> None:
    """A title held (spawned with it) is known whatever the role says; role words alone give none (D165 note)."""
    sim = new_sim()
    sim.add_citizen(
        make_spec("kenji", name="Kenji", role="retainer", rank=4, titles=["samurai"], knows_people=["aiko"])
    )
    sim.add_citizen(make_spec("aiko", name="Aiko", role="weaver", knows_people=["kenji", "ashi"]))
    sim.add_citizen(make_spec("ashi", name="Ashi", role="lord of nothing", knows_people=["aiko"]))
    profiles = {brain.profile.citizen_id: brain.profile for brain in citizen_brains(sim, 1).brains.values()}
    assert profiles["aiko"].titled == (("Kenji", "samurai"),)
    assert profiles["kenji"].titles == ("samurai",) and profiles["aiko"].titles == ()
    assert profiles["aiko"].bows_to("Kenji") and not profiles["kenji"].bows_to("Aiko")
