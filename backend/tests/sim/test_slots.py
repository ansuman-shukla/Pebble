"""Slots (10-world-v1 §4.3, D117-D119): walks end on free slots of where they go, rest takes a seat, sleep goes
inside or onto a mat, work is done at its task's slot, claims let go when they should, and at every tick's end no two
bodies that stand, sit or lie are within 0.8 m of each other."""

from collections import Counter
from collections.abc import Callable

import pytest

from app.observability.events import JsonScalar, TickSummary
from app.sim.core import Stride
from app.sim.doing import water_within_reach
from app.sim.ground_speed import ground_mps
from app.sim.motion import BodyMotion, body_motion
from app.sim.simulation import Simulation
from app.sim.slots import (
    LEGS_M,
    PERSONAL_M,
    SLOTS,
    STEP_MAX_M,
    Slot,
    build_layout,
    claim,
    claim_of,
    crowded,
    held_slot,
    layout,
    legs,
    load_slots_spec,
    reserve_owner,
    ring_bearings,
    ring_spot,
    settle,
    step_to,
    take_seat,
    walkable,
)
from app.sim.snapshot import restore, state_hash, take_snapshot
from app.sim.state import Citizen
from app.sim.vec import bearing_deg, slerp, step_towards
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
    down = [slot for slot in spots if slot.posture in ("sitting", "sitting_ground", "lying")]
    on_legs = [
        (sitter.id, other.id)
        for sitter in down
        for other in spots
        if other is not sitter
        and sim_world.distance_m(legs(sim_world, sitter.position, sitter.heading_deg), other.position) < PERSONAL_M
    ]
    assert on_legs == []  # no stand, seat or mat on a sitter's or lier's legs (the fire's stands sat on them)
    for camp in ("band_a_camp", "band_b_camp"):  # nobody sleeps across the way from a lean-to to the fire
        fire = sim_world.structures[f"{camp}:fire-pit"].centre
        for structure in sim_world.structures.values():
            if structure.kind != "lean_to" or structure.site != camp:
                continue
            way = [slerp(structure.door, fire, k / 20) for k in range(21)]
            for mat in (slot for slot in lay.owners[f"{camp}:fire-pit"] if slot.kind == "mat"):
                assert min(sim_world.distance_m(mat.position, p) for p in way) >= 0.9, (structure.id, mat.id)
    for slot in spots:
        if slot.kind in ("stand", "queue", "work") and sim_world.town_point(slot.position) is not None:
            assert sim_world.town.walk.is_walkable(*sim_world.town_point(slot.position) or (0, 0)), slot.id
    assert SLOTTED_TASKS <= lay.tasks <= set(WORK_BY_NAME) | FUTURE_TASKS
    assert "farmhouse-1-loom#seat" in {slot.id for slot in lay.homes["farmhouse-1"]}  # the weaver's loom is at home
    assert "farmhouse-2-loom#seat" not in lay.slots
    assert {slot.kind for slot in lay.owners["castle-keep"]} >= {"inside", "stand", "queue", "work"}
    assert [slot.id for slot in lay.places["storehouses"]][:2] == ["store-2#door-1", "store-2#door-2"]  # granary


def test_walkers_to_one_place_take_separate_stands_then_a_queue_in_reach(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    people = [sim.add_citizen(make_spec(f"p{k}", at=GATE)) for k in range(5)]
    walks = [WorldApi(sim, p.id).walk_to_place("the well") for p in people]
    for walk in walks:
        assert run_until_done(sim, walk, 30).text == "You arrive at the well."
    sim.step()
    well = sim.world.structures["well"].centre
    reach = sorted(round(sim.world.distance_m(p.position, well), 1) for p in people)
    assert reach == [WELL_STAND_M] * 3 + [WELL_QUEUE_M] * 2
    assert _apart(sim, people) >= PERSONAL_M
    assert all(water_within_reach(sim.core, p) == ("fresh", "the well") for p in people)
    assert crowded(sim.core) == []

    stander = next(p for p in people if round(sim.world.distance_m(p.position, well), 1) == WELL_STAND_M)
    first, second = sorted(
        (p for p in people if round(sim.world.distance_m(p.position, well), 1) == WELL_QUEUE_M),
        key=lambda p: _slot(sim, p).id,
    )
    assert [_slot(sim, first).id, _slot(sim, second).id] == ["well#queue-1", "well#queue-2"]  # in order, not nearest
    waiting = [WorldApi(sim, p.id).wait(30) for p in (first, second)]
    freed = held_slot(sim.core, stander)
    assert freed is not None
    WorldApi(sim, stander.id).walk_to_place("the main gate")  # the stand is free from now...
    late = sim.add_citizen(make_spec("late", at=GATE))
    late_walk = WorldApi(sim, late.id).walk_to_place("the well")
    assert _slot(sim, late).id == "well#queue-3"  # ...but kept for those queueing: the newcomer joins the end
    sim.drain()
    sim.step()
    assert held_slot(sim.core, first) == freed  # the first in line moves up...
    assert sim.world.distance_m(first.position, freed.position) < 0.01
    assert _summary(sim).moved[first.id].route  # ...drawn walking there
    assert _slot(sim, second).id == "well#queue-1"  # and the next one up behind them
    assert all(w.result is None for w in waiting)  # still waiting, now at the well itself
    assert run_until_done(sim, late_walk, 30).text == "You arrive at the well."
    WorldApi(sim, late.id).wait(30)
    sim.step()
    assert _slot(sim, late).id == "well#queue-2" and crowded(sim.core) == []


def test_a_weaver_walks_home_to_the_loom_and_weaves_there(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    weaver = sim.add_citizen(make_spec("aiko", at=(-80.0, 80.0), home="farmhouse-1", skills=["weaving"]))
    farmer = sim.add_citizen(make_spec("genzo", at=(-80.0, 80.0), home="farmhouse-1", skills=["farming"]))
    for citizen in (farmer, weaver):  # the farmer first: the loom is the weaver's, free or not
        assert run_until_done(sim, WorldApi(sim, citizen.id).walk_to_place("home"), 10).text == "You arrive home."
    loom = layout(sim.core).slots["farmhouse-1-loom#seat"]
    assert sim.world.distance_m(weaver.position, loom.position) < 0.01
    assert weaver.heading_deg == loom.heading_deg  # facing the loom
    assert held_slot(sim.core, farmer) == layout(sim.core).slots["farmhouse-1#door"]
    work = WorldApi(sim, weaver.id).work("weave")
    started = [e.payload.model_dump() for e in sim.drain() if e.type == "action_started" and e.actor_id == "aiko"]
    assert started[-1]["args"] == {
        "task": "weave",
        "slot": loom.id,
        "where": "at the loom",
        "posture": "sitting",
        "facing": loom.heading_deg,
        "seat_m": 0.3,
    }
    sim.step()
    action = weaver.action
    assert action is not None
    body = body_motion(alive=True, asleep=False, action="work", args=action.args, gait=None, load=0, talking=False)
    assert body == BodyMotion("craft", "sitting", loom.heading_deg, 0.3)  # on the loom's stool, facing it
    assert run_until_done(sim, work, 61).text == "You weave a length of cloth."
    assert WorldApi(sim, farmer.id).look_around().place.startswith("at your home")


def test_work_needs_a_free_slot_of_its_task_in_the_place(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    seller = sim.add_citizen(make_spec("fumiko", at=(20.0, 56.0), skills=["trade"], knows_places=["market"]))
    rival = sim.add_citizen(make_spec("rival", at=(22.0, 58.0), skills=["trade"], knows_places=["market"]))
    stall = layout(sim.core).slots["market-stall#seller"]
    work = WorldApi(sim, seller.id).work("trade")  # in the market, 3.7 m before the stall: walks round behind it
    sim.drain()
    sim.step()
    route = _summary(sim).moved[seller.id].route
    assert sim.world.distance_m(seller.position, stall.position) < 0.01 and work.result is None
    assert route[-1].t_s is not None and route[-1].t_s <= 60.0
    assert len(route) > 2  # round the stall, not through it
    assert all(sim.world.town.walk.is_walkable(*(sim.world.town_point(p.unit) or (0, 0))) for p in route[1:-1])
    second = run_until_done(sim, WorldApi(sim, rival.id).work("trade"), 1)
    assert second.text == "Others are working there; there's no room for you."
    homeless = sim.add_citizen(make_spec("tkd", at=(-80.0, 80.0), home="main-w-3", skills=["weaving"]))
    assert run_until_done(sim, WorldApi(sim, homeless.id).walk_to_place("home"), 10).outcome == "done"
    assert run_until_done(sim, WorldApi(sim, homeless.id).work("weave"), 1).text == "Your loom is at home."


def test_farmers_tend_separate_rows_inside_the_paddies(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    fields = ["town", "rice-fields"]
    farmers = [
        sim.add_citizen(make_spec(f"f{k}", at=(-90.0, 61.0), skills=["farming"], knows_places=fields)) for k in range(3)
    ]
    for farmer in farmers:
        run_until_done(sim, WorldApi(sim, farmer.id).walk_to_place("the rice fields"), 10)
    works = [WorldApi(sim, f.id).work("farm") for f in farmers]
    sim.step()
    assert all(w.result is None for w in works)
    for farmer in farmers:
        x, z = sim.world.town_point(farmer.position) or (0.0, 0.0)
        assert -126 < x < -114 and 46 < z < 66, (x, z)  # in paddy-5, not on the grass beside (audit F4)
    assert _apart(sim, farmers) >= 4.0  # a row of tiles apart


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
    sim.step()  # they sit still on the bench now: drawn on its seats at its height, facing its way
    bodies = Counter(
        body_motion(alive=True, asleep=False, action="rest", args=p.action.args, gait=None, load=0, talking=False)
        for p in people
        if p.action is not None
    )
    on_bench = [BodyMotion("sit", "sitting", _slot(sim, p).heading_deg, 0.45) for p in seated]
    assert bodies == Counter([*on_bench, BodyMotion("sit_ground", "sitting_ground")])
    texts = sorted(run_until_done(sim, rest, 10).text for rest in rests)
    assert texts == ["You rest a while on the bench."] * 2 + ["You rest a while on the ground."]


def test_a_family_sleeps_inside_and_steps_out_apart_in_the_morning(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    door = sim.world.structures["farmhouse-1"].door_xz
    family = [sim.add_citizen(make_spec(f"k{k}", at=door, home="farmhouse-1")) for k in range(3)]
    skip_to(sim, family[0].position, night=True)
    sleeps = [WorldApi(sim, member.id).sleep() for member in family]
    started = [e.payload.model_dump()["args"] for e in sim.drain() if e.type == "action_started"]
    inside: dict[str, JsonScalar] = {
        "slot": "farmhouse-1#inside",
        "where": "inside",
        "posture": "inside",
        "facing": 0.0,
        "seat_m": 0.0,
    }
    assert started == [inside] * 3
    body = body_motion(alive=True, asleep=True, action="sleep", args=inside, gait="walk", load=0, talking=False)
    assert body == BodyMotion("inside", "inside")  # hidden after the door, even while still stepping in
    sim.step()
    assert all(claim_of(sim.core, m) is not None for m in family) and crowded(sim.core) == []  # inside, out of sight
    middle = sim.world.structures["farmhouse-1"].centre
    assert all(sim.world.distance_m(m.position, middle) < 0.01 for m in family)  # in through the door, out of sight
    assert _summary(sim).moved["k0"].route  # drawn walking in
    late = sim.add_citizen(make_spec("late", at=(-80.0, 80.0), home="farmhouse-1"))
    run_until_done(sim, WorldApi(sim, late.id).walk_to_place("home"), 10)
    assert _slot(sim, late).id == "farmhouse-1#door"  # those inside are out of the doorway
    late_sleep = WorldApi(sim, late.id).sleep()
    far = sim.add_citizen(make_spec("far", at=(-40.0, 61.0), home="farmhouse-1"))
    WorldApi(sim, far.id).sleep()
    started = [e.payload.model_dump()["args"] for e in sim.drain() if e.type == "action_started"]
    assert started[-1] == {"slot": None, "where": "on the ground"}  # away from home: lies down in the street
    sleeps.append(late_sleep)
    for sleep in sleeps:
        assert run_until_done(sim, sleep, 18 * 60).text == "You wake up; it is morning."
    sim.step()
    assert _apart(sim, [*family, late]) >= PERSONAL_M and crowded(sim.core) == []  # out of the door, side by side
    assert all(walkable(sim.core, m.position) for m in family)
    assert all(sim.world.distance_m(m.position, sim.world.structures["farmhouse-1"].door) < 6.0 for m in family)


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
    assert owners.count("band_a_camp:shelter-n") == 2 and owners.count("band_a_camp:fire-pit") >= 6
    assert all(bed is None or bed.kind == "mat" for bed in beds) and beds.count(None) == 10 - len(owners)
    fire_mats = [
        slot
        for slot in layout(sim.core).owners["band_a_camp:fire-pit"]
        if slot.kind == "mat" and sim.world.distance_m(slot.position, home.door) <= 6.0
    ]
    lying = [spot for m in band for spot in (m.position, legs(sim.world, m.position, m.heading_deg))]
    for mat in fire_mats:  # the fire's mats on their side are all taken, or someone lies by them already
        assert mat in beds or any(sim.world.distance_m(spot, mat.position) < PERSONAL_M for spot in lying)
    assert all(sim.world.distance_m(m.position, home.door) <= 6.0 for m in band)
    assert _apart(sim, band) >= PERSONAL_M and crowded(sim.core) == []


def test_claims_let_go_when_a_walk_is_cut_short_or_the_walker_dies(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    sim.add_citizen(make_spec("caller", name="Caller", at=(0.0, 96.0)))
    walker = sim.add_citizen(make_spec("walker", age=70, at=(0.0, 150.0), knows_people=["caller"]))
    walk = WorldApi(sim, "walker").walk_to_place("the well")
    sim.step()
    claimed = held_slot(sim.core, walker)
    assert claimed is not None and claimed.owner == "well"
    WorldApi(sim, "caller").say("Wait for me!")
    assert run_until_done(sim, walk, 5).outcome == "interrupted"
    assert claim_of(sim.core, walker) is None  # the stand is free for others again

    sitter = sim.add_citizen(make_spec("sitter", at=(16.0, 53.5)))
    WorldApi(sim, sitter.id).rest(30)
    sim.step()
    assert held_slot(sim.core, sitter) is not None
    sim.core.injure(sitter, 200.0, "violence", "a blow fells you")
    sim.step()
    assert claim_of(sim.core, sitter) is None

    idler = sim.add_citizen(make_spec("idler", at=(-40.0, 61.0)))
    WorldApi(sim, idler.id).walk_to_place("the well")
    WorldApi(sim, idler.id).wait(10)  # changed their mind before setting off
    spot = idler.position
    sim.step()
    assert claim_of(sim.core, idler) is None and idler.position == spot

    rester = sim.add_citizen(make_spec("rester", at=(24.0, 53.5), knows_people=["idler"]))
    WorldApi(sim, rester.id).rest(30)
    sim.step()
    assert _slot(sim, rester).owner == "market-bench-2"
    WorldApi(sim, idler.id).walk_towards("west", "a long walk")
    WorldApi(sim, rester.id).follow("idler")  # gets up and goes after them: the seat is free again
    sim.step()
    assert rester.action is not None and rester.action.kind == "follow"
    assert claim_of(sim.core, rester) is None


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


def test_the_claims_round_trip_through_a_snapshot_and_runs_repeat(new_sim: Callable[..., Simulation]) -> None:
    def run() -> Simulation:
        sim = _sim(new_sim)
        for k in range(4):
            sim.add_citizen(make_spec(f"s{k}", at=GATE))
            WorldApi(sim, f"s{k}").walk_to_place("the well")
        sim.run(3)
        return sim

    sim, again = run(), run()
    assert len(SLOTS.of(sim.state).claims) == 4
    assert state_hash(sim.state) == state_hash(again.state)
    restored = restore(take_snapshot(sim.state))
    assert SLOTS.of(restored) == SLOTS.of(sim.state) and SLOTS.of(restored) is not SLOTS.of(sim.state)


def test_bodies_closer_than_personal_space_step_apart(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    first = sim.add_citizen(make_spec("ana", at=(-40.0, 61.0)))
    second = sim.add_citizen(make_spec("bo", at=(-40.0, 61.6)))  # 0.6 m apart: too close
    sim.step()
    assert sim.world.distance_m(first.position, second.position) >= 0.8


def test_a_walk_ends_on_a_slot_beside_the_walker_without_walking(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    stand = layout(sim.core).slots["well#stand-2"]
    x, z = sim.world.town_point(stand.position) or (0.0, 0.0)
    near = sim.add_citizen(make_spec("near", at=(x, z + 0.5)))
    walk = WorldApi(sim, near.id).walk_to_place("the well")
    assert run_until_done(sim, walk, 1).text == "You are already there."
    sim.step()
    assert sim.world.distance_m(near.position, stand.position) < 0.01  # stepped onto the stand


def test_a_walker_passing_a_stand_doesnt_take_it_and_things_are_walked_up_to(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _sim(new_sim)
    stand = layout(sim.core).slots["well#stand-2"]
    passer = sim.add_citizen(make_spec("passer", at=GATE))
    sim.core.place_at(passer, stand.position)
    WorldApi(sim, passer.id).walk_to_place("the main gate")  # on the stand, but walking on
    visitor = sim.add_citizen(make_spec("visitor", at=(-20.0, 58.0)))
    WorldApi(sim, visitor.id).walk_to_thing("the well")
    assert _slot(sim, visitor) == stand  # the nearest stand, though someone walks across it
    caller = sim.add_citizen(make_spec("caller", at=(-30.0, 61.0)))
    walker = sim.add_citizen(make_spec("walker", at=(-45.0, 61.0)))
    run_until_done(sim, WorldApi(sim, walker.id).walk_to_person("a person in a caller cloak"), 5)
    to_caller = (180.0 - bearing_deg(walker.position, caller.position)) % 360.0
    assert abs((walker.heading_deg - to_caller + 180) % 360 - 180) < 1.0  # facing whom they walked up to
    assert 1.1 < sim.world.distance_m(walker.position, caller.position) < 1.3  # a pace off, not inside them


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
    sim.core.strides[someone.id] = Stride(1, ((start, 0.0), (middle, 30.0), (end, 60.0)), gait="run")
    aside = sim.world.town.to_unit(-36.0, 62.0)
    assert step_to(sim.core, someone, aside)
    stepped = sim.core.strides[someone.id]
    assert stepped.walked == ((start, 0.0), (middle, 30.0), (aside, 60.0))
    assert stepped.gait == "run"  # a runner stepped aside still ran there (B1's endurance reads the gait)
    sim.core.strides.clear()
    far = sim.world.town.to_unit(60.0, 61.0)  # 100 m: more than a minute's walk
    assert not step_to(sim.core, someone, far) and someone.position == aside
    across = sim.world.town.to_unit(-26.0, 62.0)  # 10 m: within a minute's walk, but no step at a tick's end
    assert not step_to(sim.core, someone, across) and someone.position == aside and STEP_MAX_M == 8.0
    assert step_to(sim.core, someone, across, far=True) and someone.position == across  # a work slot in the place


def test_steps_to_a_spot_take_the_time_the_person_walks_it_in(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    young = sim.add_citizen(make_spec("young", at=(-40.0, 61.0)))
    elder = sim.add_citizen(make_spec("elder", age=75, at=(-34.0, 61.0)))
    times = {}
    for person, (x, z) in ((young, (-38.8, 61.0)), (elder, (-32.8, 61.0))):  # a straight step of 1.2 m
        spot = sim.world.town.to_unit(x, z)
        metres = sim.world.distance_m(person.position, spot)
        assert step_to(sim.core, person, spot)
        times[person.id] = sim.core.strides[person.id].walked[-1][1]
        assert times[person.id] == pytest.approx(metres / ground_mps(sim.core, person, "walk"), rel=1e-3)
    assert times["elder"] > times["young"] * 1.2  # at their own pace, not one walking pace for all
    stall = layout(sim.core).slots["market-stall#seller"]
    trader = sim.add_citizen(make_spec("trader", at=(20.0, 56.0)))
    assert step_to(sim.core, trader, stall.position)  # round the stall: corners timed by the metres walked
    walked = sim.core.strides[trader.id].walked
    metres = sum(sim.world.distance_m(a[0], b[0]) for a, b in zip(walked, walked[1:], strict=False))
    assert len(walked) > 2
    assert walked[-1][1] == pytest.approx(metres / ground_mps(sim.core, trader, "walk"), rel=1e-3)


def test_a_crowd_round_one_point_spreads_a_metre_apart_from_a_pace_off(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    crowd = [
        sim.add_citizen(make_spec(f"c{k}", site="band_a_camp", at=(12.0, 12.0), region="band_a")) for k in range(10)
    ]
    point = crowd[0].position
    spots = []
    for person in crowd:
        spot = ring_spot(sim.core, person, point, with_centre=False)
        assert spot is not None
        claim(sim.core, person, None, spot)
        spots.append(spot)
    radii = [round(sim.world.distance_m(spot, point), 2) for spot in spots]
    assert radii == [1.2] * 7 + [2.0] * 3  # a pace off first: the first ring holds 7
    for ring in (spots[:7], spots[7:]):
        gaps = [sim.world.distance_m(a, b) for index, a in enumerate(ring) for b in ring[index + 1 :]]
        assert min(gaps) >= 0.99  # a metre apart on a ring, not 0.77 m (8 round 1 m) as a scrum
    assert all(sim.world.distance_m(a, b) >= PERSONAL_M for index, a in enumerate(spots) for b in spots[index + 1 :])
    assert [ring_bearings(r) for r in (1.2, 2.0, 2.8, 3.6)] == [7, 12, 17, 22]


def test_nobody_stays_standing_on_a_sitters_legs(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    sitter = sim.add_citizen(make_spec("sitter", at=(16.0, 53.5)))
    WorldApi(sim, sitter.id).rest(30)
    sim.step()
    seat = _slot(sim, sitter)
    feet = legs(sim.world, seat.position, seat.heading_deg)
    assert sim.world.distance_m(feet, seat.position) == pytest.approx(LEGS_M, abs=0.01)
    ahead = step_towards(seat.position, (180.0 - seat.heading_deg) % 360.0, 1.0, sim.world.radius_m)
    x, z = sim.world.town_point(ahead) or (0.0, 0.0)
    comer = sim.add_citizen(make_spec("comer", at=(x, z)))  # a metre before the sitter: clear of them, on their legs
    assert sim.world.distance_m(comer.position, sitter.position) > PERSONAL_M
    start = comer.position
    sim.step()
    assert comer.position != start and sim.world.distance_m(comer.position, feet) >= PERSONAL_M  # stepped off them
    assert sitter.position == seat.position
    assert ring_spot(sim.core, comer, sitter.position, with_centre=False) is not None
    spot = ring_spot(sim.core, comer, sitter.position, with_centre=False)
    assert spot is not None and sim.world.distance_m(spot, feet) >= PERSONAL_M  # ring spots keep off them too


def test_whoever_just_arrived_steps_aside_not_whoever_stood_there(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    stander = sim.add_citizen(make_spec("zed", at=(-40.0, 61.0)))  # stood there first (its id sorts last)
    comer = sim.add_citizen(make_spec("amy", at=(-37.0, 61.0)))
    spot, start = stander.position, comer.position
    sim.core.strides[comer.id] = Stride(1, ((start, 0.0), (spot, 2.2)))  # walked onto them this tick
    sim.core.place_at(comer, spot)
    settle(sim.core)
    assert stander.position == spot and stander.id not in sim.core.strides  # stays put, doesn't move
    assert sim.world.distance_m(comer.position, spot) >= PERSONAL_M  # the newcomer steps aside...
    walked = sim.core.strides[comer.id].walked
    assert walked[0] == (start, 0.0) and walked[-1][0] == comer.position  # ...drawn walking on to there
    assert crowded(sim.core) == []


def test_a_step_aside_after_a_walk_keeps_to_the_tick_and_the_walkers_speed(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    walker = sim.add_citizen(make_spec("walker", at=(-40.0, 61.0)))
    start, to_unit = walker.position, sim.world.town.to_unit
    middle, end = to_unit(-39.0, 61.0), to_unit(-38.0, 61.0)
    sim.core.strides[walker.id] = Stride(1, ((start, 0.0), (middle, 20.0), (end, 40.0)))  # stopped early
    sim.core.place_at(walker, end)
    aside = to_unit(-38.0, 62.0)
    assert step_to(sim.core, walker, aside)
    walked = sim.core.strides[walker.id].walked
    pace = ground_mps(sim.core, walker, "walk")
    assert walked[:3] == ((start, 0.0), (middle, 20.0), (end, 40.0))  # on from where they stopped...
    assert walked[3][0] == aside and walked[3][1] == pytest.approx(40.0 + 1.0 / pace, rel=0.02)  # ...at their pace

    budget = ground_mps(sim.core, walker, "walk") * 60.0  # a walk round a corner using the whole tick at full speed
    leg = budget / 2
    corner = [to_unit(-40.0, 61.0), to_unit(-40.0 + leg, 61.0), to_unit(-40.0 + leg, 61.0 + leg)]
    sim.core.strides[walker.id] = Stride(1, ((corner[0], 0.0), (corner[1], 30.0), (corner[2], 60.0)))
    sim.core.place_at(walker, corner[2])
    assert step_to(sim.core, walker, to_unit(-40.0 + leg, 62.0 + leg))  # on past the end: farther than the walk
    walked = sim.core.strides[walker.id].walked
    metres = sum(sim.world.distance_m(a[0], b[0]) for a, b in zip(walked, walked[1:], strict=False))
    assert metres <= budget * 1.001 and walked[-1][1] == 60.0  # cut the corner: no faster than they walk


def _on_slot(sim: Simulation, citizen_id: str, slot_id: str, waits_for: str | None = None) -> Citizen:
    """Someone standing on a slot they hold (in a queue: waiting for the owner's stands)."""
    slot = layout(sim.core).slots[slot_id]
    citizen = sim.add_citizen(make_spec(citizen_id, at=GATE))
    sim.core.place_at(citizen, slot.position)
    claim(sim.core, citizen, slot, slot.position, waits_for=waits_for)
    return citizen


def test_a_queue_is_first_come_first_served_from_the_ring_to_the_stands(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    for k in (1, 2, 3):
        _on_slot(sim, f"s{k}", f"well#stand-{k}")
    second = _on_slot(sim, "second", "well#queue-2", waits_for="well")  # the first in line has just left
    late = sim.add_citizen(make_spec("late", at=(0.0, 150.0)))  # a few minutes' walk off
    late_walk = WorldApi(sim, late.id).walk_to_place("the well")
    assert _slot(sim, late).id == "well#queue-3"  # behind the one queueing, not the free place before them
    first = _on_slot(sim, "first", "well#queue-1", waits_for="well")
    ringer = sim.add_citizen(make_spec("ringer", at=GATE))
    well = sim.world.structures["well"].centre
    assert reserve_owner(sim.core, ringer, "well", well, well) != layout(sim.core).slots["well#queue-3"].position
    ring_claim = claim_of(sim.core, ringer)
    assert ring_claim is not None and ring_claim.slot is None and ring_claim.waits_for == "well"  # round about
    sim.core.place_at(ringer, ring_claim.position)  # already there, waiting
    WorldApi(sim, "s1").walk_to_place("the main gate")  # a stand frees while the late one is still on the way
    sim.step()
    assert _slot(sim, first).id == "well#stand-1" and _slot(sim, second).id == "well#queue-1"
    assert claim_of(sim.core, ringer) == ring_claim  # can't pass the late one, still walking to queue-3
    assert late.action is not None and late.action.kind == "walk_to"
    assert run_until_done(sim, late_walk, 40).text == "You arrive at the well."
    sim.step()
    assert _slot(sim, late).id == "well#queue-2" and _slot(sim, ringer).id == "well#queue-3"  # in their order
    assert crowded(sim.core) == []


def test_only_those_waiting_their_turn_hold_the_line(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    for k in (1, 2, 3):
        _on_slot(sim, f"s{k}", f"well#stand-{k}")
    sitter = _on_slot(sim, "sitter", "well#queue-1", waits_for="well")
    WorldApi(sim, sitter.id).rest(30)  # sits down in the queue: out of the line, stays put
    leaver = _on_slot(sim, "leaver", "well#queue-2", waits_for="well")
    sim.add_citizen(make_spec("friend", at=(-40.0, 61.0)))
    WorldApi(sim, leaver.id).follow("a person in a friend cloak")  # off after someone: out of the line too
    WorldApi(sim, "friend").walk_towards("west", "a long walk")
    WorldApi(sim, "s1").walk_to_place("the main gate")
    newcomer = sim.add_citizen(make_spec("newcomer", at=GATE))
    WorldApi(sim, newcomer.id).walk_to_place("the well")
    assert _slot(sim, newcomer).id == "well#stand-1"  # nobody waits for it
    spot = sitter.position
    sim.step()
    assert sitter.position == spot and sitter.id not in sim.core.strides  # not moved up while resting


def test_a_crowd_waits_by_a_seat_taken_or_a_sitter_on_the_ground(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    taker = sim.add_citizen(make_spec("taker", at=(14.0, 53.5)))
    assert take_seat(sim.core, taker) is not None  # taken, not sat on yet: its legs are kept clear already
    seat = _slot(sim, taker)
    other = sim.add_citizen(make_spec("other", at=(-40.0, 61.0)))
    feet = legs(sim.world, seat.position, seat.heading_deg)
    before = step_towards(seat.position, (180.0 - seat.heading_deg) % 360.0, 1.0, sim.world.radius_m)
    spot = ring_spot(sim.core, other, before, with_centre=True)  # a metre before the seat: on the legs, not there
    assert spot is not None and spot != before and sim.world.distance_m(spot, feet) >= PERSONAL_M
    lone = sim.add_citizen(make_spec("lone", at=(-40.0, 61.0)))
    WorldApi(sim, lone.id).rest(30)  # no seat near: on the ground, legs out before them
    sim.step()
    assert claim_of(sim.core, lone) is None  # sitting on the ground holds no slot: only the body keeps its legs clear
    ground_feet = legs(sim.world, lone.position, lone.heading_deg)
    before = step_towards(lone.position, (180.0 - lone.heading_deg) % 360.0, 1.0, sim.world.radius_m)
    spot = ring_spot(sim.core, other, before, with_centre=True)
    assert spot is not None and spot != before and sim.world.distance_m(spot, ground_feet) >= PERSONAL_M
    centre = ring_spot(sim.core, other, sim.world.town.to_unit(-30.0, 61.0), with_centre=True)
    assert centre == sim.world.town.to_unit(-30.0, 61.0)  # a free point itself first, when asked
    aside = ring_spot(sim.core, other, sim.world.town.to_unit(-30.0, 61.0), with_centre=False)
    assert aside is not None and round(sim.world.distance_m(aside, centre), 2) == 1.2


def test_work_far_across_its_place_is_walked_to_but_beds_beyond_a_few_steps_arent(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _sim(new_sim)
    fields = ["town", "rice-fields"]
    farmer = sim.add_citizen(make_spec("farmer", at=(-110.0, 36.0), skills=["farming"], knows_places=fields))
    work = WorldApi(sim, farmer.id).work("farm")
    slot = _slot(sim, farmer)
    assert sim.world.distance_m(farmer.position, slot.position) > STEP_MAX_M  # across the fields
    sim.step()
    assert work.result is None and sim.world.distance_m(farmer.position, slot.position) < 0.01
    home = sim.world.structures["band_a_camp:shelter-n"]
    x, z = home.door_xz
    stray = sim.add_citizen(
        make_spec("stray", site="band_a_camp", at=(x, z - 14.0), region="band_a", home="band_a_camp:shelter-n")
    )
    skip_to(sim, stray.position, night=True)
    WorldApi(sim, stray.id).sleep()
    started = [e.payload.model_dump()["args"] for e in sim.drain() if e.type == "action_started"]
    assert started[-1] == {"slot": None, "where": "on the ground"}  # every mat too far: lies down where they are


def test_the_first_in_line_still_on_the_way_keeps_the_freed_stand(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    for k in (1, 2, 3):
        _on_slot(sim, f"s{k}", f"well#stand-{k}")
    walker = sim.add_citizen(make_spec("walker", at=(0.0, 150.0)))
    WorldApi(sim, walker.id).walk_to_place("the well")
    assert _slot(sim, walker).id == "well#queue-1"
    idle = _on_slot(sim, "idle", "well#queue-2", waits_for="well")
    WorldApi(sim, "s1").walk_to_place("the main gate")
    sim.step()
    assert walker.action is not None and walker.action.kind == "walk_to"  # still on the way...
    assert _slot(sim, idle).id == "well#queue-2"  # ...so the one behind them doesn't take the stand
