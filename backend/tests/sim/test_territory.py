"""Territory (10-world-v1 §1.5, 1.6, 3.3): whose ground a spot is, the night law of the walls and the castle,
poaching, the safety words, the dens people learn, and the wolf pack's lone quarry. Every `trespassed` comes from
`sim/territory.py`; the scenes here put the doer, the witnesses and the ground in place and run the simulation."""

from collections.abc import Callable
from typing import Any

import pytest

from app.observability.events import ActionEnded, EventDraft, Injured, ItemLocation, Took, Trespassed
from app.sim import animals as animal_life
from app.sim import society, territory, wild
from app.sim.animals import WILDLIFE
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.fauna import SPECIES, den_of, pin_of, terrain
from app.sim.fire import add_fuel
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.sim.state import Animal, AnimalGroup, Fire
from app.sim.territory import TERRITORY, Claim, claim_at, ground_words, safety
from app.sim.vec import Vec3, step_towards
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

R = 2000.0  # the world's radius (m), for offsets
TOWN = ["town", "well", "main-gate"]
OUTSIDER = {"region": "band_b", "home": None, "look": "band-b-hunter"}
HUNTER = {"home": None, "skills": ["hunting"], "inventory": {"flint spear": 1}}


def _at(minute: int, day: int = 1) -> int:
    """The tick at this minute of the town's clock on that day."""
    return day * DAY_MINUTES + minute - START_MINUTE


def _scene(new_sim: Callable[..., Simulation]) -> Simulation:
    return without_animals(new_sim(seed=11))


def _person(sim: Simulation, citizen_id: str, at: Vec3, **fields: Any) -> str:
    citizen = sim.add_citizen(make_spec(citizen_id, **({"home": None, "knows_places": TOWN} | fields)))
    sim.core.place_at(citizen, at)
    return citizen.id


def _town(sim: Simulation, x: float, z: float) -> Vec3:
    return sim.world.town.to_unit(x, z)


def _trespasses(events: list[EventDraft]) -> list[tuple[str | None, Trespassed]]:
    return [(event.actor_id, event.payload) for event in events if isinstance(event.payload, Trespassed)]


def _run(sim: Simulation, ticks: int) -> list[EventDraft]:
    events: list[EventDraft] = []
    for _ in range(ticks):
        sim.step()
        events += sim.drain()
    return events


def _night(sim: Simulation, minute: int = 23 * 60) -> None:
    sim.state.tick = _at(minute)
    sim.drain()


def _hotspot(sim: Simulation, hotspot_id: str) -> Vec3:
    return next(h.centre for h in sim.world.hotspots if h.id == hotspot_id)


def _east_of_chart(sim: Simulation, metres: float) -> Vec3:
    """A spot `metres` east of the town chart's east edge, level with its middle."""
    return _town(sim, sim.world.town.extent.max_x + metres, 0.0)


# --- grounds ---


def test_each_spot_says_whose_ground_it_is(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim)
    world = sim.world
    assert claim_at(world, _town(sim, 0.0, 60.0)) == Claim("town", "the castle town")
    assert claim_at(world, _east_of_chart(sim, 395.0)) == Claim("town", "the castle town's ground")
    assert claim_at(world, _east_of_chart(sim, 405.0)) is None
    assert claim_at(world, _hotspot(sim, "lords_woods")) == Claim("town", "the Lord's woods", "lords_woods")
    assert claim_at(world, _hotspot(sim, "eastern_wall_scar")) == Claim(
        "band_a", "the Eastern wall scar", "eastern_wall_scar"
    )
    assert claim_at(world, _hotspot(sim, "b_wood")) == Claim("band_b", "B wood", "b_wood")
    camp_a, camp_b = world.places["band_a_camp"].centre, world.places["band_b_camp"].centre
    assert claim_at(world, step_towards(camp_a, 200.0, 395.0, R)) == Claim("band_a", "band A's ground")
    assert claim_at(world, step_towards(camp_a, 200.0, 405.0, R)) is None
    assert claim_at(world, step_towards(camp_b, 20.0, 395.0, R)) == Claim("band_b", "band B's ground")
    for unclaimed in ("elder_grove", "falls_pool", "obsidian_field", "river_marsh"):
        assert claim_at(world, _hotspot(sim, unclaimed)) is None, unclaimed


def test_the_ground_words_name_the_ground_the_road_or_the_hotspot(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim)
    world = sim.world
    walker = sim.citizen(_person(sim, "walker", _town(sim, 0.0, 60.0)))
    assert ground_words(sim.core, walker) == "the castle town"
    falls_road = next(road for road in world.roads if road.id == "falls_road")
    on_ground = next(
        c for c in falls_road.cells if claim_at(world, world.unit(c)) == Claim("town", territory.GROUND_WORDS["town"])
    )
    off_ground = next(c for c in falls_road.cells if claim_at(world, world.unit(c)) is None)
    sim.core.place_at(walker, world.unit(on_ground))
    assert ground_words(sim.core, walker) == f"{falls_road.name}, on the castle town's ground"
    sim.core.place_at(walker, world.unit(off_ground))
    assert ground_words(sim.core, walker) == falls_road.name
    grove = next(h for h in world.hotspots if h.id == "elder_grove")
    road_cells = {cell for road in world.roads for cell in road.cells}
    off_road = next(
        spot
        for bearing in range(0, 360, 30)
        if world.nearest_cell(spot := step_towards(grove.centre, bearing, grove.radius_m * 0.6, R)) not in road_cells
    )
    sim.core.place_at(walker, off_road)
    assert ground_words(sim.core, walker) == "the Elder grove"
    sim.core.place_at(walker, world.unit(wild_cell(sim)))
    assert ground_words(sim.core, walker) is None


def test_a_road_through_a_claimed_hotspot_is_in_it_and_a_road_beats_a_path(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(new_sim)
    world = sim.world
    walker = sim.citizen(_person(sim, "walker", _town(sim, 0.0, 60.0)))
    west_road = next(road for road in world.roads if road.id == "west_road")
    in_woods = next(c for c in west_road.cells if (claim_at(world, world.unit(c)) or Claim("town", "")).hotspot)
    sim.core.place_at(walker, world.unit(in_woods))
    assert ground_words(sim.core, walker) == f"{west_road.name}, in the Lord's woods"
    kinds: dict[int, set[str]] = {}
    for road in world.roads:
        for cell in road.cells:
            kinds.setdefault(cell, set()).add(road.kind)
    shared = next(c for c, k in sorted(kinds.items()) if k == {"road", "path"})
    first_road = next(road for road in world.roads if road.kind == "road" and shared in road.cells)
    sim.core.place_at(walker, world.unit(shared))
    assert str(ground_words(sim.core, walker)).startswith(first_road.name)


# --- the night law ---


def test_an_outsider_inside_the_walls_after_dusk_trespasses_once_per_entry(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(new_sim)
    _night(sim)
    kaz = _person(sim, "kaz", _town(sim, -20.0, 60.0), **OUTSIDER)
    goro = _person(sim, "goro", _town(sim, -24.0, 60.0))  # a town man beside him: no deed of his own
    sim.citizen(goro).in_view.add(kaz)
    sim.drain()
    events = _run(sim, 5)
    assert _trespasses(events) == [
        ("kaz", Trespassed(kind="walls", owner="town", place="the castle town", witnesses=["goro"]))
    ]
    sim.core.place_at(sim.citizen(kaz), _east_of_chart(sim, 30.0))  # out through the gate ...
    assert _trespasses(_run(sim, 2)) == []
    sim.core.place_at(sim.citizen(kaz), _town(sim, -20.0, 60.0))  # ... and back in: a new entry
    assert [t.kind for _, t in _trespasses(_run(sim, 3))] == ["walls"]


def test_the_walls_are_open_by_day_and_a_new_night_is_a_new_entry(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim)
    sim.state.tick = _at(10 * 60)
    kaz = _person(sim, "kaz", _town(sim, -20.0, 60.0), **OUTSIDER)
    sim.drain()
    assert _trespasses(_run(sim, 3)) == []
    _night(sim, 22 * 60)
    assert [actor for actor, _ in _trespasses(_run(sim, 3))] == [kaz]
    sim.state.tick = _at(12 * 60, day=2)
    assert _trespasses(_run(sim, 3)) == []
    sim.state.tick = _at(22 * 60, day=2)
    assert [actor for actor, _ in _trespasses(_run(sim, 3))] == [kaz]


def test_only_the_lord_samurai_and_ashigaru_may_be_in_the_castle_at_night(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim)
    _night(sim)
    court = [_town(sim, x, 10.0) for x in (-12.0, -6.0, 0.0, 6.0, 12.0)]
    _person(sim, "masanori", court[0], titles=["lord"], rank=5)
    _person(sim, "kenji", court[1], titles=["samurai"], rank=4)
    _person(sim, "goro", court[2], titles=["ashigaru"], rank=3)
    _person(sim, "genzo", court[3])
    _person(sim, "kaz", court[4], **OUTSIDER)
    _person(sim, "aiko", _town(sim, 0.0, 34.0))  # outside the castle gate, inside the town walls
    sim.drain()
    told = {(actor, t.kind, t.place) for actor, t in _trespasses(_run(sim, 3))}
    assert told == {
        ("genzo", "castle", "the castle"),
        ("kaz", "castle", "the castle"),
        ("kaz", "walls", "the castle town"),
    }


# --- poaching ---


def _woods_hunter(new_sim: Callable[..., Simulation], **fields: Any) -> tuple[Simulation, str, Animal]:
    """A hunter in the middle of the Lord's woods by day with a deer close by, every hunt a kill."""
    sim = _scene(new_sim)
    centre = _hotspot(sim, "lords_woods")
    hunter = sim.add_citizen(make_spec("hunter", **(HUNTER | fields)))
    put_in_the_wild(sim, hunter.id, sim.world.nearest_cell(centre))
    skip_to(sim, hunter.position, night=False)
    deer = _animal(sim, "deer", step_towards(hunter.position, 90.0, 30.0, R), activity="grazing", until=10**9)
    sim.drain()
    return sim, hunter.id, deer


def _animal(sim: Simulation, kind: str, at: Vec3, **fields: Any) -> Animal:
    world, state = sim.world, sim.state
    cell = world.nearest_cell(at)
    group = AnimalGroup(id=f"test-group:{len(state.groups) + 1}", kind=kind, home=cell, size=1)
    group.next_move = 10**9
    animal = Animal(
        id=f"{kind}:{state.next_animal}",
        kind=kind,
        group=group.id,
        position=at,
        cell=cell,
        height_m=float(terrain(world).surface_m[cell]),
        **fields,
    )
    state.next_animal += 1
    group.members.append(animal.id)
    state.animals[animal.id] = animal
    state.groups[group.id] = group
    return animal


def test_kaz_hunting_in_the_lords_woods_is_one_poaching_deed_with_his_take(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, kaz, deer = _woods_hunter(new_sim, region="band_b")
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 1.0)
    result = run_until_done(sim, WorldApi(sim, kaz).hunt("the deer"), 10)
    assert result.outcome == "done" and not deer.alive
    events = sim.drain()
    told = _trespasses(events)
    meat = SPECIES["deer"].meat
    assert told == [
        (kaz, Trespassed(kind="ground", owner="town", place="the Lord's woods", took=Took(item="meat", count=meat)))
    ]
    deed = next(e for e in events if isinstance(e.payload, Trespassed))
    moved = next(e for e in events if e.seq == deed.cause_seq)
    assert moved.type == "item_moved" and moved.payload.model_dump()["source"]["id"] == deer.id
    assert [d.kind for d in society.deeds_by(sim.core, kaz)] == ["poaching"]


@pytest.mark.parametrize(
    ("fields", "poaches"),
    [
        ({}, True),  # a town man without the title
        ({"titles": ["ashigaru"], "rank": 3}, True),
        ({"titles": ["samurai"], "rank": 4}, False),
        ({"titles": ["lord"], "rank": 5}, False),
    ],
)
def test_only_the_lord_and_samurai_hunt_the_lords_woods(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any], poaches: bool
) -> None:
    sim, hunter, _ = _woods_hunter(new_sim, **fields)
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 1.0)
    assert run_until_done(sim, WorldApi(sim, hunter).hunt("the deer"), 10).outcome == "done"
    assert [t.owner for _, t in _trespasses(sim.drain())] == (["town"] if poaches else [])


def _take(sim: Simulation, citizen_id: str, source: ItemLocation, item: str = "berries", count: int = 3) -> None:
    """A take from the wild as the gathering and fishing actions record it: the goods into the taker's hands."""
    citizen = sim.citizen(citizen_id)
    citizen.inventory[item] = citizen.inventory.get(item, 0) + count
    cause = sim.core.emit(
        "action_finished", ActionEnded(action="gather", number=1, outcome="done", text=""), actor=citizen
    )
    sim.core.item_moved(citizen, item, count, source, ItemLocation(kind="inventory", id=citizen.id), cause_seq=cause)


@pytest.mark.parametrize(
    ("region", "where", "owner"),
    [
        ("town", "lords_woods", None),  # town folk may gather in the Lord's woods
        ("band_b", "lords_woods", "town"),
        ("band_b", "b_wood", None),
        ("band_a", "b_wood", "band_b"),
        ("town", "eastern_wall_scar", "band_a"),
        ("band_a", "elder_grove", None),  # nobody's
    ],
)
def test_taking_from_the_wild_on_another_groups_ground_is_poaching(
    new_sim: Callable[..., Simulation], region: str, where: str, owner: str | None
) -> None:
    sim = _scene(new_sim)
    centre = _hotspot(sim, where)
    forager = _person(sim, "forager", centre, region=region)
    sim.drain()
    _take(sim, forager, ItemLocation(kind="resource", cell=sim.world.nearest_cell(centre)))
    assert [t.owner for _, t in _trespasses(sim.drain())] == ([owner] if owner else [])


def test_takes_from_stores_the_ground_or_the_world_are_never_poaching(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim)
    kaz = _person(sim, "kaz", _hotspot(sim, "lords_woods"), region="band_b")
    sim.drain()
    for kind in ("store", "ground", "world", "inventory"):
        _take(sim, kaz, ItemLocation(kind=kind, id="somewhere"))
    citizen = sim.citizen(kaz)  # the wild's goods dropped beside him, not taken into his hands
    wild = ItemLocation(kind="animal", id="deer:1")
    sim.core.item_moved(citizen, "meat", 2, wild, ItemLocation(kind="ground", id="stack-9", position=citizen.position))
    sim.core.item_moved(citizen, "meat", 2, wild, ItemLocation(kind="inventory", id="someone-else"))
    assert _trespasses(sim.drain()) == []


def test_band_a_hunting_on_band_b_ground_poaches_and_on_its_own_does_not(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(new_sim)
    camp_a, camp_b = sim.world.places["band_a_camp"].centre, sim.world.places["band_b_camp"].centre
    tek = _person(sim, "tek", step_towards(camp_a, 0.0, 300.0, R), region="band_a")
    sim.drain()
    _take(sim, tek, ItemLocation(kind="animal", id="deer:1"), "meat", 8)
    assert _trespasses(sim.drain()) == []
    sim.core.place_at(sim.citizen(tek), step_towards(camp_b, 0.0, 300.0, R))
    _take(sim, tek, ItemLocation(kind="animal", id="deer:1"), "meat", 8)
    assert [(t.owner, t.place, t.took) for _, t in _trespasses(sim.drain())] == [
        ("band_b", "band B's ground", Took(item="meat", count=8))
    ]


# --- safety ---


def test_the_safety_words_and_where_predators_may_attack_agree(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim)
    wild_spot = sim.world.unit(wild_cell(sim))
    camp_b = sim.world.places["band_b_camp"].centre
    kaz = sim.citizen(_person(sim, "kaz", _town(sim, 0.0, 60.0), region="band_b"))
    seen: dict[str, bool] = {}

    def check(expected: str) -> None:
        assert safety(sim.core, kaz) == expected
        seen[expected] = animal_life.exposed(sim.core, kaz)

    check("inside the walls")
    sim.core.place_at(kaz, wild_spot)
    check("exposed")
    fire = Fire(id="fire:99", kind="campfire", position=wild_spot, cell=kaz.cell, height_m=0.0)
    add_fuel(fire, 600)
    sim.state.fires[fire.id] = fire
    check("by the fire")
    del sim.state.fires[fire.id]
    _person(sim, "one", step_towards(wild_spot, 0.0, 5.0, R))
    check("exposed")  # one other isn't company
    _person(sim, "two", step_towards(wild_spot, 180.0, 9.0, R))
    check("in company")
    sim.core.place_at(kaz, step_towards(camp_b, 90.0, 300.0, R))  # band B's ground, nobody about
    check("on home ground")
    sim.core.place_at(kaz, step_towards(sim.world.places["band_a_camp"].centre, 90.0, 300.0, R))
    check("exposed")  # band A's ground is not his
    assert seen == {
        "inside the walls": False,
        "by the fire": False,
        "in company": False,
        "on home ground": True,
        "exposed": True,
    }


# --- dens ---


def _den_scene(new_sim: Callable[..., Simulation], kind: str, friends: int = 0) -> tuple[Simulation, Animal, str]:
    """The den of the kind by day with its group asleep at it and someone walking 20 m from it."""
    sim = new_sim()
    group = next(
        g
        for g in sorted(sim.state.groups.values(), key=lambda g: g.id)
        if g.kind == kind and den_of(sim.world, g) is not None
    )
    den = den_of(sim.world, group)
    assert den is not None
    sim.state.animals = {a: animal for a, animal in sim.state.animals.items() if animal.group == group.id}
    sim.state.groups = {group.id: group}
    skip_to(sim, den, night=False)
    for member_id in group.members:
        member = sim.state.animals[member_id]
        member.position, member.cell = den, sim.world.nearest_cell(den)
        member.activity, member.until, member.hunger = "sleeping", 10**9, 0.0
    spot = step_towards(den, 90.0, 20.0, R)
    victim = _person(sim, "walker", spot)
    for n in range(friends):
        _person(sim, f"friend{n}", step_towards(spot, 0.0, 3.0 + n, R))
    sim.drain()
    return sim, sim.state.animals[group.members[0]], victim


def test_someone_charged_at_a_den_by_day_learns_it(new_sim: Callable[..., Simulation]) -> None:
    sim, leader, victim = _den_scene(new_sim, "wolf")
    assert territory.known_dens(sim.core, victim) == []
    events = _run(sim, 3)
    assert any(isinstance(e.payload, Injured) and e.actor_id == victim for e in events)  # charged
    pin = pin_of(sim.world, sim.state.groups[leader.group])
    assert pin is not None
    (den,) = territory.known_dens(sim.core, victim)
    assert den.id == pin.place and den.kind == "den" and den.animal == "wolf"
    assert territory.den_words(sim.world, den) == f"the wolves' den in {_called(sim, den.hotspot)}"


def _called(sim: Simulation, hotspot_id: str | None) -> str:
    return next(h.called for h in sim.world.hotspots if h.id == hotspot_id)


def test_nobody_learns_a_den_they_were_not_charged_at(new_sim: Callable[..., Simulation]) -> None:
    sim, _, victim = _den_scene(new_sim, "bear", friends=2)  # in company: no charge
    _run(sim, 3)
    assert TERRITORY.of(sim.state).dens == {}


def test_a_charge_under_way_teaches_the_den_before_any_bite(new_sim: Callable[..., Simulation]) -> None:
    sim, leader, victim = _den_scene(new_sim, "bear")
    WILDLIFE.of(sim.state).charges[leader.id] = "hunt"
    leader.target = victim
    territory.learn_dens(sim.core)
    assert territory.known_dens(sim.core, victim) == []  # a hunt teaches no den
    WILDLIFE.of(sim.state).charges[leader.id] = "den"
    territory.learn_dens(sim.core)
    assert [d.animal for d in territory.known_dens(sim.core, victim)] == ["bear"]


@pytest.mark.parametrize(("why", "learns"), [("den", True), ("hunt", False)])
def test_a_bite_from_a_den_charge_teaches_the_den_at_once(
    new_sim: Callable[..., Simulation], why: str, learns: bool
) -> None:
    """Charge, bite and giving up can fall in one tick: the bite itself teaches it."""
    sim, leader, victim = _den_scene(new_sim, "bear")
    WILDLIFE.of(sim.state).charges[leader.id] = why
    sim.core.injure(sim.citizen(victim), 5.0, "animal attack", "a bear charges you", attacker=leader.id)
    assert bool(territory.known_dens(sim.core, victim)) is learns


def test_known_dens_and_told_entries_survive_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim, leader, victim = _den_scene(new_sim, "wolf")
    _run(sim, 3)
    _night(sim)
    _person(sim, "kaz", _town(sim, -20.0, 60.0), **OUTSIDER)
    _run(sim, 2)
    before = TERRITORY.of(sim.state)
    assert before.dens and before.inside == {"kaz": ["walls"]}
    restored = restore(take_snapshot(sim.state))
    assert TERRITORY.of(restored) == before


# --- the wolf pack's quarry ---


def _open_ground(new_sim: Callable[..., Simulation], night: bool) -> tuple[Simulation, Vec3]:
    sim = without_animals(new_sim())
    centre = sim.world.unit(wild_cell(sim, flat_m=15.0))
    skip_to(sim, centre, night=night)
    return sim, centre


@pytest.mark.parametrize(
    ("kind", "company", "goes"),
    [("wolf", 0, True), ("wolf", 1, False), ("bear", 1, True), ("lion", 1, True)],
)
def test_wolves_go_only_for_a_person_alone_other_predators_for_a_pair_too(
    new_sim: Callable[..., Simulation], kind: str, company: int, goes: bool
) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    victim = _person(sim, "walker", centre)
    for n in range(company):
        _person(sim, f"mate{n}", step_towards(centre, 0.0, 8.0, R))
    predators = [
        _animal(sim, kind, step_towards(centre, 90.0, 60.0 + 4.0 * n, R), hunger=90.0, activity="prowling")
        for n in range(3 if kind == "wolf" else 1)
    ]
    sim.drain()
    went: set[str | None] = set()
    for _ in range(3):
        bitten = {e.actor_id for e in _run(sim, 1) if isinstance(e.payload, Injured)}
        went |= {p.target for p in predators} | bitten
    assert went - {None} == ({victim} if goes else set())


def test_a_wolf_gives_up_once_its_quarry_has_company(new_sim: Callable[..., Simulation]) -> None:
    sim, centre = _open_ground(new_sim, night=True)
    victim = _person(sim, "walker", centre)
    (wolf,) = [_animal(sim, "wolf", step_towards(centre, 90.0, 110.0, R), hunger=90.0, activity="prowling")]
    sim.drain()
    _run(sim, 1)
    assert wolf.target == victim  # still far off: coming at them
    mate = sim.citizen(_person(sim, "mate", step_towards(sim.citizen(victim).position, 0.0, 5.0, R)))
    assert mate.body.alive
    _run(sim, 1)
    assert wolf.target is None
