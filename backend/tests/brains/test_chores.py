"""A band's daily chores count only when their action ran to its end.

Regression: every word said cuts short the action of everyone awake in earshot (03, interrupts), and the dusk fire
feeding and the wood chore were counted done when their option *started*: a feeding or a gather cut short by talk was
never done again that day, the woodpile ran short and band B's fire died before dawn (73-86 % of the night on three
seeds, D165).
"""

from collections.abc import Callable

import pytest
from pydantic import JsonValue

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.sim import fire as fires
from app.sim.doing import GATHER_MINUTES
from app.sim.items import RESOURCE_INDEX
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec, skip_to, without_animals

HOME_A = "band_a_camp:shelter-n"


def _band(sim: Simulation, citizen_id: str, monkeypatch: pytest.MonkeyPatch) -> UtilityBrain:
    citizen = sim.citizen(citizen_id)
    home_area = sim.world.places["band_a_camp"].name
    profile = BrainProfile(citizen_id, citizen.name, "gatherer", "band_a", home_area, citizen.skills)
    brain = UtilityBrain(WorldApi(sim, citizen_id), profile, seed=1)
    brain.api.notes["greeted"] = ["Talker"]  # greeted already: the brain goes on with its chores
    monkeypatch.setattr(brain, "chance", lambda _odds: False)  # no small talk, no fishing
    return brain


def _talker(sim: Simulation, near: tuple[float, float]) -> WorldApi:
    talker = sim.add_citizen(
        make_spec("talker", site="band_a_camp", at=near, home=None, region="band_a", knows_people=["keeper"])
    )
    return WorldApi(sim, talker.id)


def _chores(brain: UtilityBrain) -> list[JsonValue]:
    chores = brain.api.notes.get("chores", [])
    assert isinstance(chores, list)
    return chores


def _cut_short(sim: Simulation, brain: UtilityBrain, talker: WorldApi, action: str) -> None:
    citizen = sim.citizen(brain.profile.citizen_id)
    running = citizen.action
    assert running is not None and running.kind == action
    talker.say("The geese are flying south.")
    sim.step()
    result = brain.api.handle(running.number).result
    assert result is not None and result.outcome == "interrupted"


def test_a_fire_feeding_cut_short_by_talk_is_fed_again_and_counts_once_done(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = without_animals(new_sim())
    keeper = sim.add_citizen(
        make_spec("keeper", site="band_a_camp", at=(0.0, 1.5), home=None, region="band_a", knows_people=["talker"])
    )
    talker = _talker(sim, (1.5, 1.5))
    pit = sim.state.fires["band_a_camp:fire-pit"]
    pit.fuel, pit.level = 100, fires.fuel_level(100)
    skip_to(sim, keeper.position, night=False)
    while sim.core.altitude(keeper.position) > -1:  # on to just after the local sunset: dusk
        sim.state.tick += 1
    brain = _band(sim, keeper.id, monkeypatch)
    brain.decide()
    _cut_short(sim, brain, talker, "feed_fire")
    brain.decide()
    assert "fed fire" not in _chores(brain)
    feeding = keeper.action
    assert feeding is not None and feeding.kind == "feed_fire"  # fed again
    sim.run(3)
    assert brain.api.handle(feeding.number).result is not None
    brain.decide()
    assert "fed fire" in _chores(brain)


def test_a_wood_gather_cut_short_by_talk_is_gathered_again_and_counts_once_done(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = without_animals(new_sim())
    keeper = sim.add_citizen(
        make_spec(
            "keeper", site="band_a_camp", at=(0.0, 30.0), home=HOME_A, region="band_a", inventory={"meat": 3},
            knows_people=["talker"],
        )
    )  # fmt: skip
    sim.state.resources[keeper.cell, RESOURCE_INDEX["wood"]] = 40  # fallen wood right here
    talker = _talker(sim, (1.5, 30.0))
    skip_to(sim, keeper.position, night=False)
    brain = _band(sim, keeper.id, monkeypatch)
    brain.decide()
    assert brain.api.notes["last"] == "gather wood"
    _cut_short(sim, brain, talker, "gather")
    brain.decide()
    assert "wood" not in _chores(brain)
    assert brain.api.notes["last"] == "gather wood"  # the chore again
    gather = keeper.action
    assert gather is not None
    sim.run(GATHER_MINUTES + 1)
    result = brain.api.handle(gather.number).result
    assert result is not None and result.outcome == "done"
    brain.decide()
    assert "wood" in _chores(brain)
