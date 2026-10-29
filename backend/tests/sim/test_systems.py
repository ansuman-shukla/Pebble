"""The system seam (10-world-v1 §6.5): registered systems keep their own state in a versioned snapshot block, and
their hooks run every tick and at each spot's local dawn and midnight, after bodies and before interrupts."""

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from pydantic import JsonValue

from app.sim.clock import local_minute
from app.sim.core import SimCore
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.snapshot import SNAPSHOT_VERSION, canonical_json, restore, resumable, state_hash, take_snapshot
from app.sim.state import Citizen, System
from app.sim.systems import LocalTest, Registry
from app.sim.vec import lat_lon_deg
from app.sim.world import SimWorld
from app.world_api.facade import WorldApi
from tests.sim_helpers import GATE, make_spec, put_in_the_wild, without_animals

SEED = 31


@dataclass
class Tally:
    """A fake system's state: per citizen, ticks lived and the ticks of their local dawns and midnights."""

    ticks: dict[str, int] = field(default_factory=dict)
    dawns: dict[str, list[int]] = field(default_factory=dict)
    midnights: dict[str, list[int]] = field(default_factory=dict)


def _dump(tally: Tally) -> JsonValue:
    dawns: dict[str, JsonValue] = {key: list[JsonValue](ticks) for key, ticks in sorted(tally.dawns.items())}
    midnights: dict[str, JsonValue] = {key: list[JsonValue](ticks) for key, ticks in sorted(tally.midnights.items())}
    return {"ticks": dict(sorted(tally.ticks.items())), "dawns": dawns, "midnights": midnights}


def _load(data: JsonValue) -> Tally:
    assert isinstance(data, dict)
    ticks, dawns, midnights = data["ticks"], data["dawns"], data["midnights"]
    assert isinstance(ticks, dict) and isinstance(dawns, dict) and isinstance(midnights, dict)
    return Tally(
        ticks={k: int(str(v)) for k, v in ticks.items()},
        dawns={k: [int(str(t)) for t in v] for k, v in dawns.items() if isinstance(v, list)},
        midnights={k: [int(str(t)) for t in v] for k, v in midnights.items() if isinstance(v, list)},
    )


TALLY = System[Tally]("tally", 1, new=lambda _world: Tally(), dump=_dump, load=_load)


def _count(core: SimCore) -> None:
    tally = TALLY.of(core.state)
    for citizen in core.living():
        tally.ticks[citizen.id] = tally.ticks.get(citizen.id, 0) + 1


def _dawn(core: SimCore, now: LocalTest) -> None:
    tally = TALLY.of(core.state)
    for citizen in core.living():
        if now(citizen.position):
            tally.dawns.setdefault(citizen.id, []).append(core.state.tick)


def _midnight(core: SimCore, now: LocalTest) -> None:
    tally = TALLY.of(core.state)
    for citizen in core.living():
        if now(citizen.position):
            tally.midnights.setdefault(citizen.id, []).append(core.state.tick)


FAKE = Registry(systems=(TALLY,), every_tick=(_count,), at_dawn=(_dawn,), at_midnight=(_midnight,))


def _sim(sim_world: SimWorld, planner: Planner, registry: Registry = FAKE) -> Simulation:
    sim = without_animals(Simulation.new(sim_world, seed=SEED, planner=planner, registry=registry))
    sim.add_citizen(make_spec("ann", name="Ann", at=GATE))
    return sim


def _far_east_cell(sim: Simulation, citizen: Citizen) -> tuple[int, float]:
    """A walkable cell 20-40 degrees of longitude east of the citizen, and how many degrees east it is."""
    _, home_lon = lat_lon_deg(citizen.position)
    for cell in range(sim.world.cell_count):
        lat, lon = lat_lon_deg(sim.world.unit(cell))
        east = (lon - home_lon) % 360
        if 20 <= east <= 40 and abs(lat) < 40 and sim.core.planner.outer.allowed[cell]:
            return cell, east
    raise LookupError("no land 20-40 degrees east")


def test_a_new_run_holds_the_state_of_each_registered_system(sim_world: SimWorld, planner: Planner) -> None:
    assert isinstance(_sim(sim_world, planner).state.systems["tally"], Tally)
    plain = _sim(sim_world, planner, Registry())
    assert plain.state.systems == {}
    snapshot = take_snapshot(plain.state, ())
    assert snapshot.systems == {} and snapshot.seed == SEED and snapshot.version == SNAPSHOT_VERSION
    assert state_hash(restore(snapshot, ()), ()) == state_hash(plain.state, ())


def test_hooks_run_every_tick_and_at_each_spots_own_dawn_and_midnight(sim_world: SimWorld, planner: Planner) -> None:
    sim = _sim(sim_world, planner)
    sim.add_citizen(make_spec("bob", name="Bob", at=GATE))
    cell, east = _far_east_cell(sim, sim.citizen("bob"))
    put_in_the_wild(sim, "bob", cell)
    for _ in range(2 * 24 * 60):
        for citizen in sim.state.citizens.values():  # kept fed and rested: nobody here has a brain
            citizen.body.hunger, citizen.body.thirst, citizen.body.energy = 0.0, 0.0, 100.0
        sim.step()
    tally = TALLY.of(sim.state)
    assert tally.ticks == {"ann": 2880, "bob": 2880}
    # tick 0 is 08:00 town time, so the town's midnights are ticks 960 and 2400; local time runs 4 min a degree east
    assert tally.midnights["ann"] == [960, 2400]
    shift = round(east * 4)
    assert [t + shift for t in tally.midnights["bob"]] == pytest.approx([960, 2400], abs=1)
    for citizen_id in ("ann", "bob"):
        _, lon = lat_lon_deg(sim.citizen(citizen_id).position)
        assert len(tally.dawns[citizen_id]) == 2
        for tick in tally.dawns[citizen_id]:
            assert 5 * 60 <= local_minute(tick, sim.world.town_lon_deg, lon) <= 7 * 60
    assert [t + shift for t in tally.dawns["bob"]] == pytest.approx(tally.dawns["ann"], abs=3)


def test_hooks_run_after_bodies_and_before_interrupts_in_list_order(sim_world: SimWorld, planner: Planner) -> None:
    calls: list[str] = []

    def bite(core: SimCore) -> None:
        calls.append("tick")
        if core.state.tick == 5:
            core.injure(core.state.citizens["ann"], 1.0, "violence", "something bites you")

    def local(name: str) -> Callable[[SimCore, LocalTest], None]:
        return lambda _core, _now: calls.append(name)

    sim = _sim(sim_world, planner, Registry(every_tick=(bite,), at_dawn=(local("dawn"),), at_midnight=(local("mid"),)))
    api = WorldApi(sim, "ann")
    number = api.rest(60).number
    sim.run(5)
    result = sim.result("ann", number)
    assert result is not None and result.outcome == "interrupted"  # the same tick: interrupts came after the hook
    assert result.text == "You stop resting: something bites you!"
    assert calls == ["tick", "dawn", "mid"] * 5


def test_a_systems_block_round_trips_through_a_snapshot(sim_world: SimWorld, planner: Planner) -> None:
    straight = _sim(sim_world, planner)
    straight.run(900)
    snapshot = take_snapshot(straight.state, FAKE.systems)
    assert snapshot.systems["tally"].version == 1
    assert snapshot.systems["tally"].data == {"ticks": {"ann": 900}, "dawns": {}, "midnights": {}}
    again = type(snapshot).model_validate_json(snapshot.model_dump_json())
    assert canonical_json(again) == canonical_json(snapshot)
    resumed = Simulation(straight.world, restore(again, FAKE.systems), planner, registry=FAKE)
    assert TALLY.of(resumed.state) == TALLY.of(straight.state)
    assert TALLY.of(resumed.state) is not TALLY.of(straight.state)
    straight.run(900)
    resumed.run(900)
    assert TALLY.of(resumed.state) == TALLY.of(straight.state)
    assert TALLY.of(straight.state).midnights == {"ann": [960]}
    assert state_hash(resumed.state, FAKE.systems) == state_hash(straight.state, FAKE.systems)
    assert snapshot.systems["tally"].data == {"ticks": {"ann": 900}, "dawns": {}, "midnights": {}}  # untouched


def test_a_snapshot_resumes_only_with_the_same_versions_and_systems(sim_world: SimWorld, planner: Planner) -> None:
    sim = _sim(sim_world, planner)
    snapshot = take_snapshot(sim.state, FAKE.systems)
    stored = snapshot.model_dump(mode="json")
    newer = System[Tally]("tally", 2, new=TALLY.new, dump=TALLY.dump, load=TALLY.load)
    other = System[Tally]("other", 1, new=TALLY.new, dump=TALLY.dump, load=TALLY.load)
    assert resumable(stored, FAKE.systems)
    for systems in ((), (newer,), (TALLY, other)):
        assert not resumable(stored, systems)
        with pytest.raises(ValueError):
            restore(snapshot, systems)
    older = {key: value for key, value in stored.items() if key not in ("systems", "seed")} | {"version": 3}
    assert not resumable(older, ())
    assert not resumable(stored | {"version": SNAPSHOT_VERSION - 1}, FAKE.systems)
    with pytest.raises(ValueError):
        take_snapshot(sim.state, ())


def test_two_systems_cannot_share_a_name() -> None:
    with pytest.raises(ValueError):
        Registry(systems=(TALLY, System[Tally]("tally", 3, new=TALLY.new, dump=TALLY.dump, load=TALLY.load)))
