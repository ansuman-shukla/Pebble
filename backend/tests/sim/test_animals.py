"""Animals (02-simulation "Ecology"): who lives where, how herds and predators behave, when predators attack people,
respawning up to the soft caps, and that every animal change is an event the replay can rebuild."""

from collections import Counter
from collections.abc import Callable

import pytest

from app.observability.events import EventDraft
from app.observability.replay import ReplayEvent, from_snapshot, replay
from app.sim import animals as animal_life
from app.sim.clock import DAY_MINUTES
from app.sim.fauna import DANGEROUS, HERBIVORES, LIVING_SITES, PREDATORS, SPECIES, can_stand, in_town_walls
from app.sim.fire import add_fuel
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, state_hash, take_snapshot
from app.sim.state import Fire
from app.sim.vec import step_towards
from app.sim.world import SimWorld
from app.world_api.models import Wait
from tests.sim_helpers import (
    add_animal,
    make_spec,
    move_animal,
    put_in_the_wild,
    skip_to,
    wild_cell,
    without_animals,
)


def _replayable(events: list[EventDraft]) -> list[ReplayEvent]:
    return [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]


def _caps(sim: Simulation) -> Counter[str]:
    caps: Counter[str] = Counter()
    for group in sim.state.groups.values():
        caps[group.kind] += group.size
    return caps


# --- the starting population ---


def test_every_kind_lives_in_its_habitat_and_some_near_the_people(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    world = sim.world
    animals = list(sim.state.animals.values())
    assert 150 < len(animals) < 400  # modest enough to send them all to spectators
    assert {a.kind for a in animals} == set(SPECIES)
    for group in sim.state.groups.values():
        assert len(group.members) == group.size
        assert SPECIES[group.kind].group_size[0] <= group.size <= SPECIES[group.kind].group_size[1]
        assert world.biome(group.home) in SPECIES[group.kind].habitat
    for animal in animals:
        assert can_stand(world, SPECIES[animal.kind], animal.cell)
        assert not in_town_walls(world, animal.cell, animal.position)
    for site in LIVING_SITES:
        centre = world.places[site].centre
        near = {g.kind for g in sim.state.groups.values() if world.distance_m(centre, world.unit(g.home)) < 1000}
        assert near & HERBIVORES, f"no game near {site}"
    again = new_sim()
    assert state_hash(again.state) == state_hash(sim.state)  # placed from the seed


# --- ten game days of ecology on its own ---


@pytest.fixture(scope="module")
def ten_days(sim_world: SimWorld, planner: Planner) -> tuple[Simulation, list[Counter[str]], list[EventDraft]]:
    sim = Simulation.new(sim_world, seed=4, planner=planner)
    daily: list[Counter[str]] = []
    events: list[EventDraft] = []
    for _ in range(10):
        for minute in range(DAY_MINUTES):
            sim.step()
            if minute % 5 == 0:
                for animal in sim.state.animals.values():
                    assert not in_town_walls(sim_world, animal.cell, animal.position), animal.id
        events += [e for e in sim.drain() if e.type != "tick_summary"]
        daily.append(Counter(a.kind for a in sim.state.animals.values() if a.alive))
    return sim, daily, events


def test_populations_stay_within_their_caps_and_herbivores_never_die_out(
    ten_days: tuple[Simulation, list[Counter[str]], list[EventDraft]],
) -> None:
    sim, daily, events = ten_days
    caps = _caps(sim)
    for day, living in enumerate(daily, start=1):
        for kind, cap in caps.items():
            assert living[kind] <= cap, f"day {day}: {living[kind]} {kind} over the cap {cap}"
        for kind in HERBIVORES:
            assert living[kind] >= caps[kind] // 2, f"day {day}: {kind} down to {living[kind]} of {caps[kind]}"
        assert sum(living[k] for k in HERBIVORES) >= 0.75 * sum(caps[k] for k in HERBIVORES)
        assert all(living[kind] == caps[kind] for kind in PREDATORS)  # nobody hunts the predators yet
    kills = Counter(e.payload.model_dump()["cause"] for e in events if e.type == "died")
    assert sum(kills.values()) > 50  # predators really hunt (population pressure)
    assert all(cause.startswith("killed by") for cause in kills)
    spawned = [e for e in events if e.type == "animal_spawned"]
    assert len(spawned) > 30 and all(e.payload.model_dump()["replaces"] for e in spawned)
    for group in sim.state.groups.values():
        assert len(group.members) == group.size  # slots stay; remains are replaced, never added to
    for animal in sim.state.animals.values():
        assert can_stand(sim.world, SPECIES[animal.kind], animal.cell)


def test_herbivores_sleep_at_night_and_predators_by_day(
    ten_days: tuple[Simulation, list[Counter[str]], list[EventDraft]],
) -> None:
    sim = Simulation(ten_days[0].world, restore(take_snapshot(ten_days[0].state)), ten_days[0].core.planner)
    asleep = Counter[tuple[str, bool]]()
    awake = Counter[tuple[str, bool]]()
    for _ in range(DAY_MINUTES):
        sim.step()
        for animal in sim.state.animals.values():
            if not animal.alive or SPECIES[animal.kind].swims:
                continue
            night = sim.core.is_night_at(animal.position)
            role = "predator" if SPECIES[animal.kind].predator else "herbivore"
            (asleep if animal.activity == "sleeping" else awake)[(role, night)] += 1

    def share(role: str, night: bool) -> float:
        return asleep[(role, night)] / (asleep[(role, night)] + awake[(role, night)])

    assert share("herbivore", True) > 0.6 > 0.1 > share("herbivore", False)  # a few sleep on past dawn
    assert share("predator", False) > 0.5 > 0.2 > share("predator", True)


# --- herds run from people and predators ---


def test_a_deer_runs_from_a_person_and_from_a_wolf(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    cell = wild_cell(sim)
    walker = put_in_the_wild(sim, sim.add_citizen(make_spec(home=None)).id, cell)
    skip_to(sim, walker.position, night=False)
    deer = add_animal(sim, "deer", step_towards(walker.position, 90.0, 25.0, sim.world.radius_m))
    sim.step()
    assert deer.activity == "running"
    sim.step()
    assert sim.world.distance_m(deer.position, walker.position) > 100

    far = add_animal(sim, "deer", step_towards(walker.position, 270.0, 120.0, sim.world.radius_m))
    sim.step()
    assert far.activity != "running"  # people far off don't bother it
    add_animal(sim, "wolf", step_towards(far.position, 0.0, 30.0, sim.world.radius_m), activity="idle", until=10**9)
    sim.step()
    assert sim.state.animals[far.id].activity == "running"


# --- predators and people ---


def _wolf_scene(new_sim: Callable[..., Simulation], night: bool = True, people: int = 1) -> tuple[Simulation, str]:
    sim = without_animals(new_sim())
    cell = wild_cell(sim)
    ids = [sim.add_citizen(make_spec(f"camper-{n}", home=None)).id for n in range(people)]
    for n, citizen_id in enumerate(ids):
        citizen = put_in_the_wild(sim, citizen_id, cell)
        if n:
            sim.core.place_at(citizen, step_towards(citizen.position, 60.0 * n, 2.0, sim.world.radius_m))
    first = sim.citizen(ids[0])
    skip_to(sim, first.position, night=night)
    add_animal(sim, "wolf", step_towards(first.position, 180.0, 30.0, sim.world.radius_m), hunger=80.0)
    return sim, ids[0]


def _injuries(events: list[EventDraft]) -> list[EventDraft]:
    return [e for e in events if e.type == "injured" and e.actor_kind == "citizen"]


def test_a_hungry_wolf_attacks_a_lone_person_at_night(new_sim: Callable[..., Simulation]) -> None:
    sim, victim_id = _wolf_scene(new_sim)
    victim = sim.citizen(victim_id)
    wait = sim.start(victim_id, Wait(minutes=60))
    sim.drain()
    sim.run(5)
    events = sim.drain()
    bites = _injuries(events)
    assert bites and bites[0].actor_id == victim_id
    wolf = next(a for a in sim.state.animals.values() if a.kind == "wolf")
    assert {(e.payload.model_dump()["cause"], e.payload.model_dump()["attacker"]) for e in bites} == {
        ("animal attack", wolf.id)
    }
    low, high = SPECIES["wolf"].bite
    assert all(low <= e.payload.model_dump()["amount"] <= high for e in bites)
    assert victim.body.health == pytest.approx(100.0 - sum(e.payload.model_dump()["amount"] for e in bites), abs=0.1)
    result = sim.result(victim_id, wait)
    assert result is not None and result.text.startswith("You stop waiting: ")
    assert "a wolf is coming at you" in result.text or "a wolf attacks you!" in result.text


def test_repeated_attacks_can_kill(new_sim: Callable[..., Simulation]) -> None:
    sim, victim_id = _wolf_scene(new_sim)
    victim = sim.citizen(victim_id)
    victim.body.health = 5.0
    sim.run(5)
    assert not victim.body.alive and victim.body.cause_of_death == "animal attack"
    died = [e for e in sim.drain() if e.type == "died" and e.actor_id == victim_id]
    wolf = next(a for a in sim.state.animals.values() if a.kind == "wolf")
    assert len(died) == 1 and died[0].payload.model_dump() == {"cause": "animal attack", "attacker": wolf.id}
    assert wolf.hunger < 1.0 and wolf.target is None  # it has eaten


@pytest.mark.parametrize("safety", ["day", "fire", "group", "town", "fed"])
def test_predators_leave_people_alone_by_day_near_fire_in_groups_in_town_and_when_fed(
    new_sim: Callable[..., Simulation], safety: str
) -> None:
    sim, victim_id = _wolf_scene(new_sim, night=safety != "day", people=3 if safety == "group" else 1)
    victim = sim.citizen(victim_id)
    wolf = next(a for a in sim.state.animals.values() if a.kind == "wolf")
    if safety == "fire":
        camp = Fire(id="fire:99", kind="campfire", position=victim.position, cell=victim.cell, height_m=0.0)
        add_fuel(camp, 600)
        sim.state.fires[camp.id] = camp
    if safety == "fed":
        wolf.hunger = 10.0
    if safety == "town":
        sim.core.place_at(victim, sim.world.town.to_unit(0.0, 96.0))  # just inside the main gate
        skip_to(sim, victim.position, night=True)
        move_animal(sim, wolf, step_towards(victim.position, 180.0, 20.0, sim.world.radius_m))
    sim.run(60)
    assert _injuries(sim.drain()) == []
    assert victim.body.health == 100.0


def test_a_lone_person_is_exposed_only_away_from_fire_walls_and_company(new_sim: Callable[..., Simulation]) -> None:
    sim, victim_id = _wolf_scene(new_sim)
    victim = sim.citizen(victim_id)
    assert animal_life.exposed(sim.core, victim)
    friends = [sim.add_citizen(make_spec(f"friend-{n}", home=None)) for n in range(2)]
    sim.core.place_at(friends[0], step_towards(victim.position, 0.0, 5.0, sim.world.radius_m))
    assert animal_life.exposed(sim.core, victim)  # two aren't a group
    sim.core.place_at(friends[1], step_towards(victim.position, 180.0, 9.0, sim.world.radius_m))
    assert not animal_life.exposed(sim.core, victim)
    sim.core.place_at(friends[1], step_towards(victim.position, 180.0, 11.0, sim.world.radius_m))
    assert animal_life.exposed(sim.core, victim)


def test_animals_keep_away_from_a_lit_fire(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    centre = sim.world.unit(wild_cell(sim))
    camp = Fire(id="fire:1", kind="campfire", position=centre, cell=sim.world.nearest_cell(centre), height_m=0.0)
    add_fuel(camp, 600)
    sim.state.fires[camp.id] = camp
    deer = add_animal(sim, "deer", step_towards(centre, 90.0, 60.0, sim.world.radius_m))
    deer.goal, deer.pace_m = step_towards(centre, 270.0, 60.0, sim.world.radius_m), 40.0  # straight through it
    for _ in range(5):
        sim.step()
        assert sim.world.distance_m(deer.position, centre) > 25.0 - 1e-6
        deer.until = sim.tick + 100
    camp.fuel, camp.lit = 0, False
    deer.goal, deer.pace_m = step_towards(centre, 270.0, 60.0, sim.world.radius_m), 40.0
    sim.run(4)
    assert sim.world.distance_m(deer.position, centre) > 50  # walked past once the fire was out


# --- respawning and events ---


def test_dead_members_are_replaced_after_their_respawn_time(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    group = next(g for g in sim.state.groups.values() if g.kind == "deer")
    victim = sim.state.animals[group.members[0]]
    animal_life.kill(sim.core, victim, "test")
    start = take_snapshot(sim.state)
    sim.drain()
    days = SPECIES["deer"].respawn_days
    sim.run(round(days * DAY_MINUTES) - 1)
    assert victim.id in sim.state.animals and not sim.state.animals[victim.id].alive  # the remains stay until then
    sim.run(1)
    assert victim.id not in sim.state.animals
    events = sim.drain()
    spawned = [e for e in events if e.type == "animal_spawned" and e.payload.model_dump()["replaces"] == victim.id]
    assert len(spawned) == 1 and spawned[0].actor_kind == "animal"
    assert len(group.members) == group.size and spawned[0].actor_id in group.members
    assert replay(start, _replayable(events)).same_as(from_snapshot(take_snapshot(sim.state)))


def test_every_animal_and_fire_change_is_an_event(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=8)
    start = take_snapshot(sim.state)
    sim.run(2 * DAY_MINUTES)
    events = sim.drain()
    final = from_snapshot(take_snapshot(sim.state))
    assert replay(start, _replayable(events)).same_as(final)
    types = Counter(e.type for e in events)
    assert types["animal_spawned"] and types["died"] and types["fire_changed"]
    for kind in ("animal_spawned", "died", "fire_changed"):  # the last one: fire_changed carries absolute values
        index = max(i for i, e in enumerate(events) if e.type == kind)
        dropped = events[:index] + events[index + 1 :]
        try:
            same = replay(start, _replayable(dropped)).same_as(final)
        except KeyError:
            same = False
        assert not same, f"{kind} is redundant"
    summaries = [e for e in events if e.type == "tick_summary"]
    moved = [len(e.payload.model_dump()["animals"]) for e in summaries]
    assert max(moved) < len(sim.state.animals)  # only animals that changed are in a summary
    assert sum(moved) / len(moved) < 60


def test_danger_kinds_are_the_predators_that_bite() -> None:
    assert frozenset({"wolf", "bear", "lion", "polar_bear", "shark"}) == DANGEROUS
    assert "fox" in PREDATORS and "fox" not in DANGEROUS
