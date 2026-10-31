"""Dying ends whatever the citizen is doing exactly once, whatever kills them and whatever they are doing (03)."""

from collections.abc import Callable

import pytest

from app.observability.events import EventDraft
from app.sim import doing
from app.sim.simulation import Simulation
from app.sim.vec import step_towards
from app.world_api.models import (
    Action,
    Attack,
    DirectionTarget,
    Eat,
    Gather,
    MakeFire,
    Rest,
    Sleep,
    Wait,
    WalkTo,
)
from tests.sim_helpers import add_animal, make_spec, skip_to, stand_at_node, wild_node, without_animals

ENDED = ("action_finished", "action_interrupted")
DARK = "Everything goes dark."

RUNNING: dict[str, Action] = {
    "eat": Eat(item="meat"),
    "rest": Rest(minutes=60),
    "wait": Wait(minutes=60),
    "sleep": Sleep(),
    "walk_to": WalkTo(target=DirectionTarget(direction="north", distance="a long walk")),
    "gather": Gather(resource="berries"),
    "make_fire": MakeFire(),
}


def _scene(new_sim: Callable[..., Simulation]) -> tuple[Simulation, str]:
    """A lone camper out in the wild at night with raw meat, berries at hand and wood for a fire; a brute far off."""
    sim = without_animals(new_sim())
    brute = sim.add_citizen(make_spec("brute", home=None))  # added first, so each tick they move before the camper
    camper = sim.add_citizen(make_spec("camper", home=None, skills=["fire"], inventory={"meat": 5, "wood": 3}))
    stand_at_node(sim, camper.id, wild_node(sim, "berry_bush"))
    sim.core.place_at(brute, step_towards(camper.position, 0.0, 500.0, sim.world.radius_m))
    skip_to(sim, camper.position, night=True)
    camper.body.hunger = 60.0
    return sim, camper.id


def _wolf_at(sim: Simulation, victim_id: str) -> None:
    """A hungry wolf already at the victim's side and going for them: it bites in this tick's ecology step."""
    victim = sim.citizen(victim_id)
    beside = step_towards(victim.position, 90.0, 1.0, sim.world.radius_m)
    add_animal(sim, "wolf", beside, hunger=80.0, activity="chasing", target=victim_id, until=sim.tick + 30)


def _starve(sim: Simulation, victim_id: str) -> None:
    body = sim.citizen(victim_id).body
    body.hunger, body.thirst, body.health = 100.0, 0.0, 0.01


def _parch(sim: Simulation, victim_id: str) -> None:
    body = sim.citizen(victim_id).body
    body.hunger, body.thirst, body.health = 0.0, 100.0, 0.01


def _maul(sim: Simulation, victim_id: str) -> None:
    sim.citizen(victim_id).body.health = 0.5
    _wolf_at(sim, victim_id)


def _strike(sim: Simulation, victim_id: str) -> None:
    """The brute steps up beside the victim and attacks them (striking before the victim moves this tick)."""
    victim = sim.citizen(victim_id)
    victim.body.health = 0.01
    brute = sim.citizen("brute")
    sim.core.place_at(brute, step_towards(victim.position, 0.0, 1.0, sim.world.radius_m))
    assert sim.result(brute.id, sim.start(brute.id, Attack(target=victim.appearance))) is None


DEATHS: dict[str, tuple[str, Callable[[Simulation, str], None]]] = {
    "starvation": ("starvation", _starve),
    "dehydration": ("dehydration", _parch),
    "animal attack": ("animal attack", _maul),
    "violence": ("violence", _strike),
}


def _ends(events: list[EventDraft], citizen_id: str, number: int) -> list[EventDraft]:
    return [
        e for e in events if e.type in ENDED and e.actor_id == citizen_id and e.payload.model_dump()["number"] == number
    ]


def _assert_died_once_ending(
    sim: Simulation, events: list[EventDraft], victim_id: str, cause: str, number: int
) -> None:
    """Dead of the cause with one `died`, the running action ended once by the death, and nothing done after it."""
    victim = sim.citizen(victim_id)
    assert (victim.body.alive, victim.body.cause_of_death, victim.action) == (False, cause, None)
    died = [e for e in events if e.type == "died" and e.actor_id == victim_id]
    assert [e.payload.model_dump()["cause"] for e in died] == [cause]
    ends = _ends(events, victim_id, number)
    assert [(e.type, e.payload.model_dump()["text"], e.cause_seq) for e in ends] == [
        ("action_interrupted", DARK, died[0].seq)
    ]
    assert not [e for e in events if e.actor_id == victim_id and e.seq > died[0].seq and e.type == "action_started"]
    result = sim.result(victim_id, number)
    assert result is not None and (result.outcome, result.text) == ("interrupted", DARK)


def _run_until_dead(sim: Simulation, victim_id: str, ticks: int) -> list[EventDraft]:
    events: list[EventDraft] = []
    for _ in range(ticks):
        sim.step()
        events += sim.drain()
        if not sim.citizen(victim_id).body.alive:
            return events
    raise AssertionError(f"{victim_id} is still alive after {ticks} ticks")


@pytest.mark.parametrize("death", list(DEATHS))
@pytest.mark.parametrize("running", list(RUNNING))
def test_every_death_ends_every_running_action_once(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch, running: str, death: str
) -> None:
    monkeypatch.setattr(doing, "RAW_SICK_CHANCE", 0.0)
    sim, victim_id = _scene(new_sim)
    number = sim.start(victim_id, RUNNING[running])
    assert sim.citizen(victim_id).action is not None and sim.citizen(victim_id).action.kind == running  # type: ignore[union-attr]
    cause, kill = DEATHS[death]
    kill(sim, victim_id)
    events = sim.drain() + _run_until_dead(sim, victim_id, 1)
    _assert_died_once_ending(sim, events, victim_id, cause, number)


def _eat_then_collapse(sim: Simulation, victim_id: str) -> None:
    sim.citizen(victim_id).body.energy = 0.0
    sim.step()


def _eat_then_get_bitten(sim: Simulation, victim_id: str) -> None:
    _wolf_at(sim, victim_id)  # a bite only hurts; the interrupt stops the meal and what was eaten so far makes sick
    sim.step()


def _eat_then_do_something_else(sim: Simulation, victim_id: str) -> None:
    number = sim.start(victim_id, Wait(minutes=10))
    result = sim.result(victim_id, number)
    assert result is not None and (result.action, result.outcome, result.text) == ("wait", "failed", DARK)


def _eat_to_the_end(sim: Simulation, _victim_id: str) -> None:
    sim.run(10)


@pytest.mark.parametrize(
    "ending",
    [_eat_to_the_end, _eat_then_get_bitten, _eat_then_do_something_else, _eat_then_collapse],
    ids=["finishes", "is bitten", "starts something else", "collapses"],
)
def test_raw_food_that_kills_ends_the_meal_once(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch, ending: Callable[[Simulation, str], None]
) -> None:
    """Bad food kills from inside the meal (via `injure`), so whoever stops the meal must not end it again (#60)."""
    monkeypatch.setattr(doing, "RAW_SICK_CHANCE", 1.0)
    monkeypatch.setattr(doing, "RAW_SICKNESS", (500.0, 500.0))
    sim, victim_id = _scene(new_sim)
    number = sim.start(victim_id, Eat(item="meat"))
    sim.step()  # a minute into the meal
    assert sim.citizen(victim_id).body.alive
    ending(sim, victim_id)
    events = sim.drain()
    _assert_died_once_ending(sim, events, victim_id, "bad food", number)
    assert sim.citizen(victim_id).inventory.get("meat", 0) < 5  # some was eaten: that is what made them sick
