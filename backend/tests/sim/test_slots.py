"""Slots (10-world-v1 §4.3, D117-D119): walks end on free slots of where they go, rest takes a seat, sleep goes
inside or onto a mat, work is done at its task's slot, claims let go when they should, and at every tick's end no two
bodies that stand, sit or lie are within 0.8 m of each other."""

from collections.abc import Callable

from app.observability.events import TickSummary
from app.sim.core import Stride
from app.sim.simulation import Simulation
from app.sim.slots import (
    PERSONAL_M,
    Slot,
    build_layout,
    held_slot,
    load_slots_spec,
    ring_spot,
    step_to,
    walkable,
)
from app.sim.state import Citizen
from app.sim.work import WORK_BY_NAME
from app.sim.world import SimWorld
from app.world.town import load_town
from tests.sim_helpers import GATE, make_spec, without_animals

FUTURE_TASKS = {"forge", "dry", "ring bell", "confined"}  # slots laid out for tasks their streams bring later
SLOTTED_TASKS = {"farm", "weave", "trade", "guard", "govern", "pray"}  # every v0 task done at a thing
WELL_STAND_M = 2.3
WELL_QUEUE_M = 3.5


def _sim(new_sim: Callable[..., Simulation]) -> Simulation:
    return without_animals(new_sim(seed=4))  # game coming into view would stop walks


def _apart(sim: Simulation, people: list[Citizen]) -> float:
    return min(
        sim.world.distance_m(a.position, b.position) for index, a in enumerate(people) for b in people[index + 1 :]
    )


def _slot(sim: Simulation, citizen: Citizen) -> Slot:
    slot = held_slot(sim.core, citizen)
    assert slot is not None, f"{citizen.id} holds no slot"
    return slot


def _summary(sim: Simulation) -> TickSummary:
    summaries = [e.payload for e in sim.drain() if e.type == "tick_summary"]
    assert isinstance(summaries[-1], TickSummary)
    return summaries[-1]


def test_the_layout_keeps_personal_space_and_stands_on_walkable_ground(sim_world: SimWorld) -> None:
    lay = build_layout(sim_world, load_town(), load_slots_spec())
    spots = [slot for slot in lay.slots.values() if slot.kind != "inside"]
    close = [
        (a.id, b.id)
        for index, a in enumerate(spots)
        for b in spots[index + 1 :]
        if sim_world.distance_m(a.position, b.position) < 0.8  # a body's personal space (10 §4.3)
    ]
    assert close == [] and PERSONAL_M == 0.8
    for slot in spots:
        if slot.kind in ("stand", "queue", "work") and sim_world.town_point(slot.position) is not None:
            assert sim_world.town.walk.is_walkable(*sim_world.town_point(slot.position) or (0, 0)), slot.id
    assert SLOTTED_TASKS <= lay.tasks <= set(WORK_BY_NAME) | FUTURE_TASKS
    assert "farmhouse-1-loom#seat" in {slot.id for slot in lay.homes["farmhouse-1"]}  # the weaver's loom is at home
    assert "farmhouse-2-loom#seat" not in lay.slots
    assert {slot.kind for slot in lay.owners["castle-keep"]} >= {"inside", "stand", "queue", "work"}
    assert [slot.id for slot in lay.places["storehouses"]][:2] == ["store-2#door-1", "store-2#door-2"]  # granary


def test_bodies_on_one_spot_step_apart_the_later_comer_drawn_walking(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    first = sim.add_citizen(make_spec("ana", at=(-40.0, 61.0)))
    second = sim.add_citizen(make_spec("bo", at=(-40.0, 61.0)))
    spot = first.position
    sim.drain()
    sim.step()
    assert first.position == spot  # who was there first (ties by id) keeps the spot
    assert sim.world.distance_m(second.position, spot) >= PERSONAL_M
    route = _summary(sim).moved["bo"].route
    assert route[0].unit == spot and route[-1].unit == second.position
    assert walkable(sim.core, second.position)


def test_bodies_closer_than_personal_space_step_apart(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    first = sim.add_citizen(make_spec("ana", at=(-40.0, 61.0)))
    second = sim.add_citizen(make_spec("bo", at=(-40.0, 61.6)))  # 0.6 m apart: too close
    sim.step()
    assert sim.world.distance_m(first.position, second.position) >= 0.8


def test_ring_spots_are_walkable_and_clear_of_camp_props(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    someone = sim.add_citizen(make_spec("someone", at=GATE))
    house = sim.world.structures["main-w-3"].centre
    spot = ring_spot(sim.core, someone, house, with_centre=True)
    assert spot is not None and spot != house and walkable(sim.core, spot)
    assert sim.world.town.walk.is_walkable(*(sim.world.town_point(spot) or (0.0, 0.0)))
    pit = sim.world.structures["band_a_camp:fire-pit"].centre
    camp_spot = ring_spot(sim.core, someone, pit, with_centre=True)
    assert camp_spot is not None and sim.world.distance_m(camp_spot, pit) >= 0.9  # off the pit's stones


def test_a_step_aside_keeps_within_the_tick_and_far_spots_are_not_stepped_to(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _sim(new_sim)
    someone = sim.add_citizen(make_spec("someone", at=(-40.0, 61.0)))
    start = someone.position
    middle = sim.world.town.to_unit(-38.0, 61.0)
    end = sim.world.town.to_unit(-36.0, 61.0)
    sim.core.strides[someone.id] = Stride(1, ((start, 0.0), (middle, 30.0), (end, 60.0)))
    aside = sim.world.town.to_unit(-36.0, 62.0)
    assert step_to(sim.core, someone, aside)
    assert sim.core.strides[someone.id].walked == ((start, 0.0), (middle, 30.0), (aside, 60.0))
    sim.core.strides.clear()
    far = sim.world.town.to_unit(60.0, 61.0)  # 100 m: more than a minute's walk
    assert not step_to(sim.core, someone, far) and someone.position == aside
