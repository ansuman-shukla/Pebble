"""The v0 cast (`data/citizens/citizens.yaml`): 15 identities per the 04 roster that all spawn into the real world."""

import re
from collections import Counter
from collections.abc import Callable

from app.core.config import REPO_ROOT
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.simulation import Simulation
from app.sim.state import age_group

LOOKS = REPO_ROOT / "frontend" / "src" / "lib" / "world" / "citizen-looks.ts"
FIGURE_SEX = {"masculine": "male", "feminine": "female"}
ROSTER_AGES = [55, 34, 40, 28, 26, 9, 44, 63, 24, 15, 30, 38, 29, 19, 7]  # 04-minds, in roster order


def _looks() -> dict[str, tuple[str, str]]:
    """look id -> (region, sex) from the frontend's look configs."""
    pattern = re.compile(r"id: '([^']+)',\s*region: '([^']+)',[\s\S]*?figure: '([^']+)'")
    return {look: (region, FIGURE_SEX[figure]) for look, region, figure in pattern.findall(LOOKS.read_text())}


def test_the_cast_follows_the_roster() -> None:
    cast = load_citizens(CITIZENS)
    citizens = cast.citizens
    assert len(citizens) == 15
    assert Counter(c.region for c in citizens) == {"town": 6, "band_a": 5, "band_b": 4}
    assert [c.age for c in citizens] == ROSTER_AGES
    assert len({c.id for c in citizens}) == len({c.name for c in citizens}) == 15
    looks = _looks()
    assert len(looks) == 15
    assert sorted(c.look for c in citizens) == sorted(looks)
    for citizen in citizens:
        assert looks[citizen.look] == (citizen.region, citizen.sex), citizen.id
        assert citizen.role and citizen.personality and citizen.appearance, citizen.id
    ids = {c.id for c in citizens}
    for citizen in citizens:
        assert set(citizen.knows_people) <= ids - {citizen.id}, citizen.id
        mates = {c.id for c in citizens if c.region == citizen.region} - {citizen.id}
        assert mates <= set(citizen.knows_people), f"{citizen.id} should know everyone in their region"
    bands = [c for c in citizens if c.region != "town"]
    assert all(c.inventory.get("dried meat", 0) > 0 and c.home and c.home.startswith(c.site) for c in bands)
    assert all(c.site == "town" and c.home for c in citizens if c.region == "town")
    assert cast.stores["store-2"]["rice"] >= 300  # the town has food for some days


def test_everyone_spawns_at_home_ground_and_knows_their_way_home(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    cast = load_citizens(CITIZENS)
    for spec in cast.citizens:
        citizen = sim.add_citizen(spec)
        assert (citizen.role, citizen.region, citizen.group) == (spec.role, spec.region, age_group(spec.age))
        home = sim.world.structures[str(citizen.home)]
        assert home.is_home and home.site == spec.site
        assert sim.world.distance_m(citizen.position, home.door) < 140, spec.id
    assert {c.inventory.get("dried meat", 0) > 0 for c in sim.state.citizens.values() if c.region != "town"} == {True}
