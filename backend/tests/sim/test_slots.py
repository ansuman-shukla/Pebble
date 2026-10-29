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
    crowded,
    held_slot,
    layout,
    load_slots_spec,
    occupancy_words,
    ring_spot,
    step_to,
    walkable,
)
from app.sim.state import Citizen
from app.sim.work import WORK_BY_NAME
from app.sim.world import SimWorld
from app.world.town import load_town
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import GATE, make_spec, skip_to, without_animals

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


def test_rest_takes_a_free_bench_seat_nearby_else_the_ground(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    people = [sim.add_citizen(make_spec(f"r{k}", at=(16.0, 53.5))) for k in range(3)]
    rests = [WorldApi(sim, p.id).rest(5) for p in people]
    sim.step()
    bench = {slot.id for slot in layout(sim.core).owners["market-bench-1"]}
    seated = [p for p in people if held_slot(sim.core, p) is not None]
    assert {_slot(sim, p).id for p in seated} == bench
    for person in seated:
        assert sim.world.distance_m(person.position, _slot(sim, person).position) < 0.01
    assert _apart(sim, people) >= PERSONAL_M  # the third sits on the ground beside them
    texts = sorted(run_until_done(sim, rest, 10).text for rest in rests)
    assert texts == ["You rest a while on the bench."] * 2 + ["You rest a while on the ground."]
    assert occupancy_words(sim.core, "market-bench-1", "seat") == "both taken"


def test_band_sleepers_take_their_lean_tos_mats_then_the_fires_by_their_door(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _sim(new_sim)
    home = sim.world.structures["band_a_camp:shelter-n"]
    band = [
        sim.add_citizen(
            make_spec(f"b{k}", site="band_a_camp", at=home.door_xz, region="band_a", home="band_a_camp:shelter-n")
        )
        for k in range(10)
    ]
    skip_to(sim, band[0].position, night=True)
    for member in band[:3]:
        WorldApi(sim, member.id).sleep()
    sim.step()
    first = sorted(_slot(sim, m).owner for m in band[:3])
    assert first == ["band_a_camp:fire-pit", "band_a_camp:shelter-n", "band_a_camp:shelter-n"]  # the roof first
    for member in band[3:]:
        WorldApi(sim, member.id).sleep()
    sim.step()
    beds = [held_slot(sim.core, m) for m in band]
    owners = sorted(bed.owner for bed in beds if bed is not None)
    assert owners == ["band_a_camp:fire-pit"] * 7 + ["band_a_camp:shelter-n"] * 2  # the fire's mats on their side
    assert all(bed is None or bed.kind == "mat" for bed in beds) and beds.count(None) == 1  # the last lies down
    assert all(sim.world.distance_m(m.position, home.door) <= 6.0 for m in band)
    assert _apart(sim, band) >= PERSONAL_M and crowded(sim.core) == []


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


def test_occupancy_words_tell_how_full_a_thing_is(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    assert occupancy_words(sim.core, "market-bench-2", "seat") == "free"
    sitter = sim.add_citizen(make_spec("solo", at=(24.0, 53.5)))
    WorldApi(sim, sitter.id).rest(30)
    sim.step()
    assert occupancy_words(sim.core, "market-bench-2", "seat") == "one free"


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
