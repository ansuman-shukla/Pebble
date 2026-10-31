"""Animal behaviour and the hunt (10-world-v1 §4.6, A1): alert, herd alarm and flight, the stalk, pounce, race, strike
and feeding, remains and meat, spreading kills over herds, one biter at a time, den defence, feeders and people,
waterholes, and every move streamed along its timed path."""

from collections.abc import Callable
from typing import Any

import pytest

from app.observability.events import AnimalPose, Died, EventDraft, Injured, ItemMoved, TickSummary
from app.sim import animals as animal_life
from app.sim import hunt
from app.sim.animals import WILDLIFE
from app.sim.clock import DAY_MINUTES, SECONDS_PER_TICK
from app.sim.fauna import SPECIES, den_of, terrain, waterhole_of
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, state_hash, take_snapshot
from app.sim.state import Animal, AnimalGroup
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.world_api.facade import WorldApi
from tests.sim_helpers import drawn_on, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

R = 2000.0  # the world's radius (m), for offsets


def _herd(sim: Simulation, kind: str, spots: list[Vec3], **fields: Any) -> list[Animal]:
    """A group of the kind, one member at each spot."""
    world, state = sim.world, sim.state
    group = AnimalGroup(
        id=f"test-group:{len(state.groups) + 1}", kind=kind, home=world.nearest_cell(spots[0]), size=len(spots)
    )
    group.next_move = 10**9
    members = []
    for spot in spots:
        cell = world.nearest_cell(spot)
        animal = Animal(
            id=f"{kind}:{state.next_animal}",
            kind=kind,
            group=group.id,
            position=spot,
            cell=cell,
            height_m=float(terrain(world).surface_m[cell]),
            **fields,
        )
        state.next_animal += 1
        group.members.append(animal.id)
        state.animals[animal.id] = animal
        members.append(animal)
    state.groups[group.id] = group
    return members


def _open_ground(new_sim: Callable[..., Simulation], night: bool) -> tuple[Simulation, Vec3]:
    sim = without_animals(new_sim())
    centre = sim.world.unit(wild_cell(sim, flat_m=15.0))
    skip_to(sim, centre, night=night)
    return sim, centre


def _person(sim: Simulation, at: Vec3, name: str = "walker") -> str:
    citizen = sim.add_citizen(make_spec(name, home=None))
    put_in_the_wild(sim, citizen.id, sim.world.nearest_cell(at))
    sim.core.place_at(citizen, at)
    return citizen.id


def _summary(events: list[EventDraft]) -> TickSummary:
    return [e.payload for e in events if isinstance(e.payload, TickSummary)][-1]


def _step(sim: Simulation) -> list[EventDraft]:
    sim.drain()
    sim.step()
    return sim.drain()


def _speeds(sim: Simulation, pose: AnimalPose) -> list[float]:
    points = pose.route
    return [
        sim.world.distance_m(a.unit, b.unit) / (b.t_s - a.t_s)
        for a, b in zip(points, points[1:], strict=False)
        if a.t_s is not None and b.t_s is not None and b.t_s > a.t_s
    ]


# --- herds: alert, alarm, flight ---


def test_a_person_close_by_sets_the_whole_herd_running_on_one_bearing(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    herd = _herd(sim, "deer", [centre, *(step_towards(centre, b, 12.0, R) for b in (0, 90, 180, 270, 45))],
                 activity="grazing", until=10**9)  # fmt: skip
    _person(sim, step_towards(centre, 90.0, 38.0, R))  # within the nearest deer's 40 m, not the far ones'
    starts = {deer.id: deer.position for deer in herd}
    summary = _summary(_step(sim))
    fled = [deer for deer in herd if summary.animals[deer.id].gait == "run"]
    assert len(fled) == len(herd)  # every member within 60 m bolts in the same tick (≥ 80 % required)
    bearings = [bearing_deg(starts[d.id], d.position) for d in herd]
    assert all(abs((b - bearings[0] + 180) % 360 - 180) <= 2 * animal_life.ALARM_TURN_DEG for b in bearings)
    assert all(abs((b - 270 + 180) % 360 - 180) <= 60 for b in bearings)  # away from the person, to the west
    for deer in herd:
        pose = summary.animals[deer.id]
        assert pose.route[0].unit == starts[deer.id] and pose.route[0].t_s == 0.0
        assert sim.world.distance_m(drawn_on(pose.route, SECONDS_PER_TICK), deer.position) < 0.01
        assert max(_speeds(sim, pose)) <= SPECIES["deer"].run_mps * 1.001
        assert deer.activity == "alert" and pose.goal.startswith("watching Walker")


def test_a_flight_is_a_burst_then_the_sustained_speed(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    (deer,) = _herd(sim, "deer", [centre], activity="grazing", until=10**9)
    _person(sim, step_towards(centre, 0.0, 30.0, R))
    pose = _summary(_step(sim)).animals[deer.id]
    deer_species = SPECIES["deer"]
    assert [p.t_s for p in pose.route] == pytest.approx([0.0, deer_species.burst_s, animal_life.FLIGHT_S])
    assert _speeds(sim, pose) == pytest.approx([deer_species.run_mps, deer_species.trot_mps], rel=1e-3)
    assert sim.world.distance_m(centre, deer.position) == pytest.approx(11 * 20 + 5 * 10, rel=1e-3)
    # winded: a second scare within a few minutes gets only the sustained speed
    _person(sim, step_towards(deer.position, 0.0, 30.0, R), "second")
    deer.until = 0
    again = _summary(_step(sim)).animals[deer.id]
    assert max(_speeds(sim, again)) == pytest.approx(deer_species.trot_mps, rel=1e-3)


def test_a_person_further_off_only_makes_it_alert(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    (deer,) = _herd(sim, "deer", [centre], activity="grazing", until=0)
    walker = _person(sim, step_towards(centre, 180.0, 70.0, R))  # between 40 m and twice that
    summary = _summary(_step(sim))
    assert deer.activity == "alert" and deer.position == centre and not summary.animals[deer.id].route
    assert deer.heading_deg == pytest.approx((180.0 - bearing_deg(centre, sim.citizen(walker).position)) % 360, abs=0.1)


def test_a_rabbit_runs_to_cover_and_freezes(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    (rabbit,) = _herd(sim, "rabbit", [centre], activity="grazing", until=10**9)
    _person(sim, step_towards(centre, 0.0, 10.0, R))
    pose = _summary(_step(sim)).animals[rabbit.id]
    assert pose.route[-1].t_s == pytest.approx(SPECIES["rabbit"].cover_s)  # its burrow, 10 s off
    assert rabbit.activity == "frozen"


def test_a_stalking_hunter_is_not_fled(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    (deer,) = _herd(sim, "deer", [centre], activity="grazing", until=10**9)
    hunter = sim.add_citizen(make_spec("hunter", home=None, skills=["hunting"])).id
    sim.core.place_at(sim.citizen(hunter), step_towards(centre, 90.0, 70.0, R))
    WorldApi(sim, hunter).hunt("the deer")
    _step(sim)
    gap = sim.world.distance_m(sim.citizen(hunter).position, centre)
    assert gap < SPECIES["deer"].flee_people_m  # crept up well inside its flee distance, not yet striking
    assert deer.position == centre and deer.activity == "grazing"


# --- the hunt ---


def _hungry(sim: Simulation, kind: str, at: Vec3, count: int = 1) -> list[Animal]:
    """Hungry predators on the prowl (unseen: not yet fled from)."""
    spots = [step_towards(at, 90.0, 4.0 * n, R) for n in range(count)]
    return _herd(sim, kind, spots, hunger=90.0, activity="prowling")


def test_a_noticed_wolf_races_a_boar_down_and_feeds_then_leaves_meat_and_bones(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    (boar,) = _herd(sim, "boar", [centre], activity="sleeping", until=10**9)
    (wolf,) = _hungry(sim, "wolf", step_towards(centre, 180.0, 50.0, R))
    monkeypatch.setattr(hunt, "sense", lambda *_: "noticed")
    monkeypatch.setattr(hunt, "strike_chance", lambda *_: 1.0)
    events = _step(sim)
    died = [(e.actor_id, e.payload) for e in events if isinstance(e.payload, Died)]
    assert [(actor, d.cause, d.attacker) for actor, d in died] == [(boar.id, "killed by a wolf", wolf.id)]
    summary = _summary(events)
    chase, flight = summary.animals[wolf.id], summary.animals[boar.id]
    assert flight.gait == chase.gait == "run" and wolf.activity == "pouncing" and boar.activity == "dead"
    # the 1-D race: caught where the wolf's run reaches the gap plus the boar's (2 m/s faster for 15 s, then 5.5)
    caught_s = hunt.catch_time(hunt.dash(SPECIES["wolf"]), hunt.dash(SPECIES["boar"]), 50.0, 120.0)
    assert caught_s == pytest.approx(15 + 20 / 5.5)
    assert flight.route[-1].t_s == pytest.approx(caught_s, abs=1e-3)
    assert chase.route[-1].t_s == pytest.approx(caught_s, abs=1e-3)
    assert sim.world.distance_m(wolf.position, boar.position) < 0.5
    assert chase.goal == "feeding on a boar" and chase.target is not None and chase.target.id == boar.id
    sim.step()
    assert str(wolf.activity) == "feeding" and wolf.hunger < 1.0
    sim.run(wolf.until - sim.tick)
    events = sim.drain()
    meat = [e.payload for e in events if isinstance(e.payload, ItemMoved) and e.payload.item == "meat"]
    assert len(meat) == 1 and meat[0].source.kind == "animal" and meat[0].source.id == boar.id
    assert meat[0].count == SPECIES["boar"].meat // 2 and meat[0].destination.kind == "ground"
    stack = sim.state.ground[str(meat[0].destination.id)]
    assert stack.item == "meat" and sim.world.distance_m(stack.position, boar.position) < 0.01  # scavengeable
    assert boar.activity == "dead"
    assert boar.died_tick is not None
    sim.run(boar.died_tick + DAY_MINUTES - sim.tick)
    assert str(boar.activity) == "remains"


def test_an_unseen_wolf_inside_its_pounce_range_pounces_at_once(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    (deer,) = _herd(sim, "deer", [centre], activity="sleeping", until=10**9)
    (wolf,) = _hungry(sim, "wolf", step_towards(centre, 180.0, 25.0, R))
    monkeypatch.setattr(hunt, "strike_chance", lambda *_: 1.0)
    events = _step(sim)
    assert not deer.alive and wolf.activity == "pouncing"
    pounce = _summary(events).animals[wolf.id]
    assert pounce.route[-1].t_s == pytest.approx(animal_life.POUNCE_S)  # the first sub-step: no stalk, no race
    assert sim.world.distance_m(pounce.route[-1].unit, centre) < 0.01


def test_a_wolf_noticed_too_far_off_gives_up_after_two_minutes_and_rests(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    (deer,) = _herd(sim, "deer", [centre], activity="sleeping", until=10**9)
    (wolf,) = _hungry(sim, "wolf", step_towards(centre, 180.0, 50.0, R))  # G* wolf → deer is 30 m
    monkeypatch.setattr(hunt, "sense", lambda *_: "noticed")
    _step(sim)
    catch = WILDLIFE.of(sim.state).catches[wolf.id]
    assert not catch.caught and wolf.activity == "chasing"
    assert WILDLIFE.of(sim.state).tries[wolf.group] == 1  # one of its four hunts tonight
    # a wolf's race spans two ticks: a snapshot taken mid-race resumes it exactly
    copy = Simulation(sim.world, restore(take_snapshot(sim.state)), sim.core.planner)
    for run in (sim, copy):
        run.run(2)
    assert state_hash(copy.state) == state_hash(sim.state)
    assert deer.alive and wolf.target is None and wolf.id not in WILDLIFE.of(sim.state).catches
    assert wolf.until >= sim.tick + animal_life.MISS_REST_TICKS - 2  # a missed hunt rests an hour


def test_a_predator_goes_for_the_herd_with_most_members(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    near = _herd(sim, "deer", [step_towards(centre, 90.0, 150.0 + 6 * n, R) for n in range(2)], activity="sleeping",
                 until=10**9)  # fmt: skip
    far = _herd(sim, "deer", [step_towards(centre, 180.0, 300.0 + 6 * n, R) for n in range(4)], activity="sleeping",
                until=10**9)  # fmt: skip
    (wolf,) = _hungry(sim, "wolf", centre)
    sim.step()
    assert wolf.target in {deer.id for deer in far}
    for deer in far[1:]:
        animal_life.kill(sim.core, deer, "test")
    wolf.target, wolf.until = None, 0
    WILDLIFE.of(sim.state).courses.pop(wolf.id, None)
    WILDLIFE.of(sim.state).catches.pop(wolf.id, None)
    sim.step()
    assert wolf.target in {deer.id for deer in near}  # two against one: the nearer herd has more now


def test_a_pack_hunts_together_and_shares_the_kill(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    (boar,) = _herd(sim, "boar", [centre], activity="sleeping", until=10**9)
    pack = _hungry(sim, "wolf", step_towards(centre, 180.0, 50.0, R), count=3)
    monkeypatch.setattr(hunt, "sense", lambda *_: "noticed")
    monkeypatch.setattr(hunt, "strike_chance", lambda *_: 1.0)
    summary = _summary(_step(sim))
    assert {summary.animals[w.id].gait for w in pack} == {"run"}  # they run together
    assert not boar.alive
    sim.step()
    assert all(w.target == boar.id and w.hunger < 1.0 for w in pack)


# --- predators and people ---


def test_one_wolf_of_a_pack_bites_at_a_time(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    victim = _person(sim, centre)
    pack = _hungry(sim, "wolf", step_towards(centre, 0.0, 30.0, R), count=3)
    biters: set[str] = set()
    for _ in range(10):
        events = _step(sim)
        biters |= {str(e.payload.attacker) for e in events if isinstance(e.payload, Injured) and e.actor_id == victim}
        assert sum(w.target == victim for w in pack) <= 1
    assert len(biters) == 1


def test_one_animal_bites_at_a_time_whatever_its_group(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    victim = _person(sim, centre)
    wolves = [_hungry(sim, "wolf", step_towards(centre, bearing, 30.0, R))[0] for bearing in (0.0, 120.0, 240.0)]
    bites = 0
    for _ in range(10):
        events = _step(sim)
        biters = [str(e.payload.attacker) for e in events if isinstance(e.payload, Injured) and e.actor_id == victim]
        bites += len(biters)
        assert len(biters) <= 1 and sum(w.target == victim for w in wolves) <= 1  # the others hold back
    assert bites >= 1


def test_a_predator_tries_four_hunts_a_night(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    _herd(sim, "deer", [step_towards(centre, 90.0, 150.0, R)], activity="sleeping", until=10**9)
    (wolf,) = _hungry(sim, "wolf", centre)
    WILDLIFE.of(sim.state).tries[wolf.group] = hunt.HUNTS_A_NIGHT
    sim.step()
    assert wolf.target is None  # done for the night
    del WILDLIFE.of(sim.state).tries[wolf.group]  # a new dusk
    wolf.until = 0
    sim.step()
    assert wolf.target is not None


def _den_scene(new_sim: Callable[..., Simulation], friends: int) -> tuple[Simulation, Animal, str]:
    sim = new_sim()
    group = next(g for g in sorted(sim.state.groups.values(), key=lambda g: g.id) if den_of(sim.world, g) is not None)
    den = den_of(sim.world, group)
    assert den is not None
    for animal_id in list(sim.state.animals):
        if sim.state.animals[animal_id].group != group.id:
            del sim.state.animals[animal_id]
    sim.state.groups = {group.id: group}
    skip_to(sim, den, night=False)
    leader = sim.state.animals[group.members[0]]
    for member_id in group.members:
        member = sim.state.animals[member_id]
        member.position, member.cell = den, sim.world.nearest_cell(den)
        member.activity, member.until, member.hunger = "sleeping", 10**9, 0.0
    spot = step_towards(den, 90.0, 20.0, R)
    victim = _person(sim, spot)
    for n in range(friends):
        _person(sim, step_towards(spot, 0.0, 3.0 + n, R), f"friend{n}")
    return sim, leader, victim


def test_a_predator_charges_whoever_comes_near_its_den_by_day(new_sim: Callable[..., Simulation]) -> None:
    sim, leader, victim = _den_scene(new_sim, friends=0)
    events = _step(sim)
    bites = [e for e in events if e.type == "injured" and e.actor_id == victim]
    assert bites and {e.payload.model_dump()["attacker"] for e in bites} == {leader.id}
    assert sim.core.hurt[victim][0] == f"{SPECIES[leader.kind].one} charges you"
    for _ in range(6):
        sim.step()
    assert leader.target is None  # it gave up and went home


def test_a_den_charge_stops_at_the_edge_of_its_ring(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (#109): a wolf chased a forager ~90 m from its den and killed them."""
    sim, leader, victim = _den_scene(new_sim, friends=0)
    monkeypatch.setattr(animal_life, "GIVE_UP_CHANCE", 0.0)  # it would go on biting
    _step(sim)
    assert leader.target == victim
    den = den_of(sim.world, sim.state.groups[leader.group])
    assert den is not None
    person = sim.citizen(victim)
    sim.core.place_at(person, step_towards(den, 90.0, animal_life.DEN_CHASE_M + 5.0, R))  # fled out of the ring
    events = [e for _ in range(5) for e in _step(sim)]
    assert not [e for e in events if e.type == "injured" and e.actor_id == victim]
    assert leader.target is None


def test_a_den_charge_given_up_is_not_taken_up_again_at_once(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, leader, victim = _den_scene(new_sim, friends=0)
    monkeypatch.setattr(animal_life, "GIVE_UP_CHANCE", 1.0)  # one bite, then it lets go
    events = [e for _ in range(10) for e in _step(sim)]  # the forager stays inside the ring
    assert len([e for e in events if e.type == "injured" and e.actor_id == victim]) == 1


def test_company_keeps_a_den_from_charging(new_sim: Callable[..., Simulation]) -> None:
    sim, leader, victim = _den_scene(new_sim, friends=2)
    events = [e for _ in range(5) for e in _step(sim)]
    assert not [e for e in events if e.type == "injured"]
    den = den_of(sim.world, sim.state.groups[leader.group])
    assert den is not None
    loner = _person(sim, step_towards(den, 270.0, 24.0, R), "loner")  # farther from the den, but alone
    leader.until = 0
    events = [e for _ in range(3) for e in _step(sim)]
    assert {e.actor_id for e in events if e.type == "injured"} == {loner}


@pytest.mark.parametrize(("feeders", "leaves"), [(1, True), (2, False)])
def test_a_person_near_a_kill_drives_off_a_lone_feeder_but_not_a_pack(
    new_sim: Callable[..., Simulation], feeders: int, leaves: bool
) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    (deer,) = _herd(sim, "deer", [centre])
    animal_life.kill(sim.core, deer, "killed by a wolf")
    WILDLIFE.of(sim.state).carcasses[deer.id] = SPECIES["deer"].meat // 2
    pack = _herd(sim, "wolf", [step_towards(centre, 90.0 * n, 1.5, R) for n in range(feeders)], hunger=0.0,
                 activity="feeding", target=deer.id, until=sim.tick + 100)  # fmt: skip
    _person(sim, step_towards(centre, 0.0, 10.0, R))
    events = _step(sim)
    dropped = [e for e in events if isinstance(e.payload, ItemMoved) and e.payload.item == "meat"]
    if leaves:
        pose = _summary(events).animals[pack[0].id]
        assert pack[0].target is None and pose.gait == "trot" and len(dropped) == 1
        assert sim.world.distance_m(pack[0].position, centre) > animal_life.CARCASS_THREAT_M
    else:
        assert all(w.target == deer.id for w in pack) and not dropped


# --- waterholes ---


def test_a_herd_drinks_at_its_waterhole_at_dawn(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    group = next(
        g for g in sorted(sim.state.groups.values(), key=lambda g: g.id)
        if not SPECIES[g.kind].predator and waterhole_of(sim.world, g) is not None
    )  # fmt: skip
    hole = waterhole_of(sim.world, group)
    assert hole is not None
    sim.state.animals = {m: sim.state.animals[m] for m in group.members}  # nothing to scare it off
    sim.state.groups = {group.id: group}
    skip_to(sim, hole, night=True)
    drank = False
    for _ in range(14 * 60):
        sim.step()
        members = [sim.state.animals[m] for m in group.members if sim.state.animals[m].alive]
        if any(m.activity == "drinking" and sim.world.distance_m(m.position, hole) <= 20 for m in members):
            drank = True
            break
    assert drank
    assert sim.core.altitude(hole) > -3.0  # at dawn, not in the night


# --- the stream ---


def test_every_animal_move_is_streamed_from_where_it_stood(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=3)
    caps = {kind: s.run_mps * min(s.burst_s, 60) + s.trot_mps * max(0.0, 60 - s.burst_s) for kind, s in SPECIES.items()}
    moves = 0
    for _ in range(600):
        before = {a.id: a.position for a in sim.state.animals.values()}
        summary = _summary(_step(sim))
        for animal_id, start in before.items():
            animal = sim.state.animals.get(animal_id)
            if animal is None or sim.world.distance_m(start, animal.position) < 0.001:
                continue
            moves += 1
            pose = summary.animals[animal_id]
            assert len(pose.route) >= 2 and pose.route[0].unit == start and pose.route[0].t_s == 0.0
            assert sim.world.distance_m(drawn_on(pose.route, SECONDS_PER_TICK), animal.position) < 0.01
            walked = [p for p in pose.route if p.t_s is not None and p.t_s <= SECONDS_PER_TICK + 1e-6]
            metres = sum(sim.world.distance_m(a.unit, b.unit) for a, b in zip(walked, walked[1:], strict=False))
            assert metres <= caps[animal.kind] * 1.01
    assert moves > 1000


# --- where they live ---


def test_every_den_in_the_world_view_has_its_group(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    dens = [f for f in sim.world.features if f.kind == "den"]
    assert len(dens) == 5  # P1's table: two wolf dens, two bear dens, the lions'
    for den in dens:
        groups = [g for g in sim.state.groups.values() if den_of(sim.world, g) == den.position]
        assert len(groups) == 1, den.id
        assert groups[0].kind == den.animal and groups[0].size == SPECIES[str(den.animal)].group_size[1]


# --- kinds ---


def test_a_bear_goes_for_boar_before_deer_and_for_a_carcass_before_either(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    deer = _herd(sim, "deer", [step_towards(centre, 90.0, 80.0 + 6 * n, R) for n in range(5)], activity="sleeping",
                 until=10**9)  # fmt: skip
    (boar,) = _herd(sim, "boar", [step_towards(centre, 180.0, 200.0, R)], activity="sleeping", until=10**9)
    (bear,) = _hungry(sim, "bear", centre)
    sim.step()
    assert bear.target == boar.id  # a bear can't run down deer (G* 0): it lives off boar
    animal_life.kill(sim.core, deer[0], "killed by a wolf")
    bear.target, bear.until = None, 0
    WILDLIFE.of(sim.state).courses.pop(bear.id, None)
    WILDLIFE.of(sim.state).catches.pop(bear.id, None)
    sim.step()
    assert bear.target == deer[0].id and bear.hunger > 50.0  # and off carcasses first: hungry until it eats
    for _ in range(5):
        sim.step()
    assert bear.activity == "feeding" and bear.hunger < 1.0


def test_sharks_and_fish_are_only_drawn_swimming_or_attacking(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=3)
    words: set[str] = set()
    for _ in range(300):
        summary = _summary(_step(sim))
        words |= {pose.activity for aid, pose in summary.animals.items() if aid.split(":")[0] in ("shark", "fish")}
        words |= {a.activity for a in sim.state.animals.values() if a.kind in ("shark", "fish") and a.alive}
    assert words <= {"swimming", "attacking"} and "swimming" in words


def test_a_prowler_after_an_animal_is_said_to_stalk_it(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    _herd(sim, "deer", [step_towards(centre, 90.0, 200.0, R)], activity="sleeping", until=10**9)
    (wolf,) = _hungry(sim, "wolf", centre)
    pose = _summary(_step(sim)).animals[wolf.id]
    assert pose.activity == "prowling" and pose.goal == "stalking a deer"


def test_a_kill_lies_as_bones_before_its_group_replaces_it(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    rabbits = _herd(sim, "rabbit", [centre, step_towards(centre, 90.0, 5.0, R)], activity="grazing", until=10**9)
    animal_life.kill(sim.core, rabbits[0], "killed by a fox")
    sim.run(round(SPECIES["rabbit"].respawn_days * DAY_MINUTES))  # its respawn time: one day, the day it lies dead
    assert sim.state.animals[rabbits[0].id].activity == "remains"
    sim.run(animal_life.REMAINS_SHOWN_TICKS)
    assert rabbits[0].id not in sim.state.animals


def test_a_hunters_kill_is_replaced_on_time(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=False)
    rabbits = _herd(sim, "rabbit", [centre, step_towards(centre, 90.0, 5.0, R)], activity="grazing", until=10**9)
    animal_life.kill(sim.core, rabbits[0], "hunted", attacker="tek", remains=True)  # bones at once
    sim.run(round(SPECIES["rabbit"].respawn_days * DAY_MINUTES))
    assert rabbits[0].id not in sim.state.animals
