"""Wear and spoilage (10-world-v1 §2.4): food goes off at each holder's local dawn by its share, rounded up; tools
break per use and packs per dawn carried, at their chances; whatever is lost replays exactly."""

import math
from collections.abc import Callable

import pytest

from app.observability.events import EventDraft, ItemMoved, Spoiled, ToolBroke
from app.observability.replay import ReplayEvent, replay
from app.sim.economy import load_economy
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.sim.systems import REGISTRY, dawn_at
from app.sim.vec import Vec3, step_towards
from app.sim.wear import (
    DAWN_GAP,
    WEAR,
    spoil_at_dawn,
    spoilage,
    store_spot,
    use_tool,
    watch_sun,
    wear_packs_at_dawn,
)
from app.sim.world import SimWorld
from tests.sim_helpers import GATE, make_spec, without_animals

USES = 10_000
STORE = "store-2"


@pytest.mark.parametrize(
    ("stock", "lost"),
    [
        ({"meat": 3, "fish": 1, "berries": 10, "roots": 10}, {"meat": 2, "fish": 1, "berries": 3, "roots": 1}),
        ({"meat": 4, "berries": 1, "roots": 11}, {"meat": 2, "berries": 1, "roots": 2}),  # a part rounds up
        ({"rice": 50, "nuts": 9, "dried meat": 4, "cloth": 2, "iron sand": 3, "flint spear": 1}, {}),  # keep
        ({"meat": 0}, {}),
    ],
)
def test_spoilage_takes_each_food_s_share_rounded_up(stock: dict[str, int], lost: dict[str, int]) -> None:
    assert spoilage(stock) == lost


def test_spoilage_shares_are_the_bible_s() -> None:
    assert load_economy().spoilage == {"meat": 0.5, "fish": 0.5, "berries": 0.3, "roots": 0.1}


def _sim(new_sim: Callable[..., Simulation], **fields: object) -> Simulation:
    sim = without_animals(new_sim(seed=5))
    sim.add_citizen(make_spec("tek", name="Tek", at=GATE, **fields))
    sim.drain()
    return sim


def _dawn_tick(sim: Simulation, position: Vec3) -> int:
    """The next tick in which the sun rises at this spot."""
    tick = sim.tick + 1
    while True:
        sim.state.tick = tick
        if dawn_at(sim.core, position):
            return tick
        tick += 1


def _dawn_for(sim: Simulation, *citizen_ids: str) -> None:
    """Make it these citizens' dawn this tick, as `watch_sun` would, for calling a dawn hook directly."""
    WEAR.of(sim.state).rising = set(citizen_ids)


def _run_over(sim: Simulation, dawn: int, before: int = 3, after: int = 3) -> list[EventDraft]:
    sim.state.tick = dawn - before - 1  # jump the clock (between ticks) to just before that dawn
    events: list[EventDraft] = []
    while sim.tick < dawn + after:
        sim.step()
        events += sim.drain()
    return events


def test_a_holder_s_food_spoils_once_at_their_local_dawn(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim, inventory={"meat": 5, "berries": 4, "rice": 6})
    sim.stock_store(STORE, "fish", 3)
    sim.stock_store(STORE, "rice", 30)
    sim.drain()
    tek = sim.citizen("tek")
    snapshot = take_snapshot(sim.state)
    start = sim.tick
    dawn = _dawn_tick(sim, tek.position)
    sim.state.tick = start
    store_dawn = _dawn_tick(sim, store_spot(sim.world, STORE))  # the storehouses lie east of the gate: earlier
    assert store_dawn < dawn
    events = _run_over(sim, dawn, before=dawn - store_dawn + 3)

    spoiled = [e for e in events if isinstance(e.payload, Spoiled)]
    by_holder = {e.payload.holder: e for e in spoiled if isinstance(e.payload, Spoiled)}
    assert len(spoiled) == 2 and set(by_holder) == {"tek", STORE}  # one each, at dawn
    mine, store = by_holder["tek"], by_holder[STORE]
    assert (mine.tick, mine.actor_id, mine.payload) == (
        dawn,
        "tek",
        Spoiled(holder="tek", holder_kind="inventory", items={"berries": 2, "meat": 3}),
    )
    assert (store.tick, store.actor_kind) == (store_dawn, "world")
    assert store.payload == Spoiled(holder=STORE, holder_kind="store", items={"fish": 2})
    assert tek.inventory == {"meat": 2, "berries": 2, "rice": 6}
    assert sim.state.stores[STORE] == {"fish": 1, "rice": 30}

    gone = [(e.cause_seq, e.payload) for e in events if isinstance(e.payload, ItemMoved)]
    assert {(seq, moved.item, moved.count) for seq, moved in gone if moved.destination.kind == "world"} == {
        (mine.seq, "meat", 3),
        (mine.seq, "berries", 2),
        (store.seq, "fish", 2),
    }
    replayed = replay(
        snapshot, [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    )
    assert replayed.citizens["tek"].inventory == tek.inventory
    assert replayed.stores == sim.state.stores


def test_nothing_spoils_away_from_dawn_and_nothing_twice_a_day(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim, inventory={"meat": 40})
    tek = sim.citizen("tek")
    dawn = _dawn_tick(sim, tek.position)
    assert not [e for e in _run_over(sim, dawn, before=60, after=-2) if e.type == "spoiled"]  # the hour before
    assert len([e for e in _run_over(sim, dawn, before=1, after=120) if e.type == "spoiled"]) == 1
    assert tek.inventory == {"meat": 20}


def test_a_citizen_s_dawn_is_stepping_from_the_dark_into_the_light_once_in_half_a_day(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _sim(new_sim)
    sky = {"altitude": -1.0}
    monkeypatch.setattr(sim.core, "altitude", lambda _unit: sky["altitude"])
    dawns = []
    for tick, altitude in (
        (1000, 5.0),  # never seen in the dark: no dawn
        (1001, -1.0),
        (1002, 0.0),  # the sun on the horizon is still down
        (1003, 2.0),  # dawn
        (1004, 3.0),
        (1100, -1.0),
        (1101, 1.0),  # the sun set and rose again: too soon
        (1003 + DAWN_GAP - 2, -1.0),
        (1003 + DAWN_GAP - 1, 1.0),  # a minute short of half a day
        (1003 + DAWN_GAP + 4, -1.0),
        (1003 + DAWN_GAP + 5, 1.0),  # dawn
    ):
        sim.state.tick, sky["altitude"] = tick, altitude
        watch_sun(sim.core)
        dawns += [tick] * len(WEAR.of(sim.state).rising)
    assert dawns == [1003, 1003 + DAWN_GAP + 5]
    assert WEAR.of(sim.state).last == {"tek": 1003 + DAWN_GAP + 5}
    sim.citizen("tek").body.alive = False  # the dead see no sun
    sim.state.tick, sky["altitude"] = sim.state.tick + DAWN_GAP, -1.0
    watch_sun(sim.core)
    assert not WEAR.of(sim.state).dark


@pytest.mark.parametrize(
    ("start_m", "bearing", "speed", "start", "spoils"),
    [
        (-1000.0, 90.0, 84.0, -30, 1),  # east at a walk (sunrise moves 7 m a minute), out of the night
        (0.0, 0.0, 0.0, -30, 1),  # standing still
        (0.0, 270.0, 2.0, -30, 1),  # west, slower than the sunrise: it catches them
        (0.0, 270.0, 84.0, 5, 0),  # west at a walk after sunrise: into the night, no dawn
    ],
)
def test_a_walker_s_food_spoils_at_the_dawn_they_walk_into(
    new_sim: Callable[..., Simulation], start_m: float, bearing: float, speed: float, start: int, spoils: int
) -> None:
    sim = _sim(new_sim, inventory={"meat": 16})
    tek = sim.citizen("tek")
    gate = tek.position
    dawn = _dawn_tick(sim, gate)
    radius = sim.world.radius_m
    position = step_towards(gate, 90.0, start_m, radius) if start_m else gate
    sim.state.tick = dawn + start - 1
    spoiled, seam_dawns = [], 0
    while sim.tick < dawn + 60:
        position = step_towards(position, bearing, speed, radius) if speed else position
        sim.core.place_at(tek, position)
        sim.step()
        spoiled += [e.tick for e in sim.drain() if e.type == "spoiled"]
        seam_dawns += dawn_at(sim.core, position)
    assert len(spoiled) == spoils and tek.inventory["meat"] == 16 // 2**spoils
    if speed == 84.0 and spoils:
        assert seam_dawns == 0  # the sun never rose at their spot within a tick: why it watches their sun instead


def test_a_dawn_with_nothing_to_spoil_still_counts(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    tek = sim.citizen("tek")
    dawn = _dawn_tick(sim, tek.position)
    assert not [e for e in _run_over(sim, dawn, before=2, after=2) if e.type == "spoiled"]
    assert WEAR.of(sim.state).last == {"tek": dawn}
    tek.inventory["meat"] = 6
    west = sim.world.structures["band_b_camp:fire-pit"].door  # still night there: a second sunrise this morning
    sim.core.place_at(tek, west)
    second = _dawn_tick(sim, west)
    assert not [e for e in _run_over(sim, second, before=second - dawn - 2, after=2) if e.type == "spoiled"]
    assert tek.inventory == {"meat": 6}


def test_a_walker_heading_west_into_the_night_doesn_t_spoil_at_the_second_sunrise(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _sim(new_sim, inventory={"meat": 16})
    tek = sim.citizen("tek")
    dawn = _dawn_tick(sim, tek.position)
    assert len([e for e in _run_over(sim, dawn, before=1, after=1) if e.type == "spoiled"]) == 1
    west = sim.world.structures["band_b_camp:fire-pit"].door  # hours behind the town: still night there
    assert sim.core.altitude(west) < 0
    sim.core.place_at(tek, west)
    second = _dawn_tick(sim, west)
    assert second - dawn < 6 * 60
    events = _run_over(sim, second, before=second - dawn - 2, after=2)
    assert not [e for e in events if e.type == "spoiled"] and tek.inventory["meat"] == 8
    assert WEAR.of(sim.state).last == {"tek": dawn}


def test_the_wear_block_round_trips_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim, inventory={"meat": 4})
    wear = WEAR.of(sim.state)
    wear.last, wear.dark, wear.rising = {"tek": 77}, {"tek", "ora"}, {"tek"}
    snapshot = take_snapshot(sim.state)
    restored = WEAR.of(restore(snapshot))
    assert (restored.last, restored.dark, restored.rising) == ({"tek": 77}, {"tek", "ora"}, set())
    assert (snapshot.systems["wear"].version, snapshot.systems["wear"].data) == (
        1,
        {"last": {"tek": 77}, "dark": ["ora", "tek"]},
    )


def test_the_dead_keep_what_they_carried(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim, inventory={"meat": 4})
    sim.citizen("tek").body.alive = False
    _dawn_for(sim, "tek")
    spoil_at_dawn(sim.core, lambda _unit: True)
    assert not sim.drain() and sim.citizen("tek").inventory == {"meat": 4}


def test_stores_spoil_at_their_own_dawn(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    sim.stock_store(STORE, "berries", 10)
    sim.stock_store("band_a_camp:drying-rack", "meat", 6)
    sim.drain()
    camp = store_spot(sim.world, "band_a_camp:drying-rack")
    _dawn_for(sim)
    spoil_at_dawn(sim.core, lambda unit: unit == camp)
    events = sim.drain()
    assert [e.payload for e in events if isinstance(e.payload, Spoiled)] == [
        Spoiled(holder="band_a_camp:drying-rack", holder_kind="store", items={"meat": 3})
    ]
    assert sim.state.stores[STORE] == {"berries": 10}


def test_every_store_stands_somewhere(sim_world: SimWorld) -> None:
    for store_id in ("store-2", "castle-keep-chest", "farmhouse-1-chest", "band_b_camp:drying-rack", "rice-fields"):
        assert sim_world.distance_m(store_spot(sim_world, store_id), sim_world.town.to_unit(0, 0)) < 2500, store_id
    for home in ("castle-keep", "farmhouse-1", "cross-n-9"):  # chests stand by their home's door
        assert sim_world.distance_m(store_spot(sim_world, f"{home}-chest"), sim_world.structures[home].door) < 6
    with pytest.raises(ValueError, match="stands nowhere"):
        store_spot(sim_world, "nowhere-chest")


def test_wear_hooks_are_registered_at_dawn() -> None:
    assert spoil_at_dawn in REGISTRY.at_dawn and wear_packs_at_dawn in REGISTRY.at_dawn
    assert watch_sun in REGISTRY.every_tick
    assert WEAR in REGISTRY.systems


@pytest.mark.parametrize(
    ("item", "chance"),
    [
        ("flint spear", 0.08),  # 4 % a strike, stone × 2
        ("obsidian spear", 0.08),
        ("iron spear", 0.02),  # iron × 0.5
        ("stone axe", 0.02),
        ("iron axe", 0.02),
        ("sickle", 0.015),
    ],
)
def test_tools_break_per_use_at_their_chance(new_sim: Callable[..., Simulation], item: str, chance: float) -> None:
    sim = _sim(new_sim)
    tek = sim.citizen("tek")
    broke = 0
    for _ in range(USES):
        tek.inventory[item] = 1
        broke += use_tool(sim.core, tek, item)
    mean, sd = USES * chance, math.sqrt(USES * chance * (1 - chance))
    assert abs(broke - mean) <= 4 * sd, (broke, mean)
    events = sim.drain()
    broken = [e.payload for e in events if isinstance(e.payload, ToolBroke)]
    assert len(broken) == broke and set(broken) == {ToolBroke(item=item, use=load_economy().breakage[item].use)}


def test_a_broken_tool_is_gone_and_replays(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim, inventory={"flint spear": 2})
    tek = sim.citizen("tek")
    snapshot = take_snapshot(sim.state)
    while not use_tool(sim.core, tek, "flint spear", cause_seq=7):
        pass
    events = sim.drain()
    assert tek.inventory == {"flint spear": 1}
    broke, moved = events[-2], events[-1]
    assert (broke.type, broke.actor_id, broke.cause_seq) == ("tool_broke", "tek", 7)
    assert broke.payload == ToolBroke(item="flint spear", use="hunt")
    assert isinstance(moved.payload, ItemMoved) and moved.cause_seq == broke.seq
    assert (moved.payload.item, moved.payload.count, moved.payload.destination.kind) == ("flint spear", 1, "world")
    replayed = replay(
        snapshot, [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    )
    assert replayed.citizens["tek"].inventory == {"flint spear": 1}


def test_a_tool_must_be_carried_to_be_used(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    with pytest.raises(ValueError, match="no iron axe"):
        use_tool(sim.core, sim.citizen("tek"), "iron axe")


def test_a_carried_pack_wears_out_at_dawn(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    tek = sim.citizen("tek")
    broke = 0
    _dawn_for(sim, "tek")
    for _ in range(USES // 2):
        tek.inventory["pack"] = 2  # each pack carried rolls
        wear_packs_at_dawn(sim.core, lambda _unit: False)  # a citizen's dawn is watch_sun's, not the spot's
        broke += 2 - tek.inventory.get("pack", 0)
    mean, sd = USES * 0.03, math.sqrt(USES * 0.03 * 0.97)
    assert abs(broke - mean) <= 4 * sd, (broke, mean)
    assert {e.payload for e in sim.drain() if isinstance(e.payload, ToolBroke)} == {ToolBroke(item="pack", use="carry")}
    tek.inventory["pack"] = 1
    _dawn_for(sim)
    for _ in range(200):
        wear_packs_at_dawn(sim.core, lambda _unit: True)  # not their dawn: no wear
    assert tek.inventory["pack"] == 1 and not sim.drain()
