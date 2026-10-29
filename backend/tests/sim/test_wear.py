"""Spoilage (10-world-v1 §2.4): food goes off at each holder's local dawn by its share, rounded up, and what is lost
replays exactly."""

from collections.abc import Callable

import pytest

from app.observability.events import EventDraft, ItemMoved, Spoiled
from app.observability.replay import ReplayEvent, replay
from app.sim.economy import load_economy
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot
from app.sim.systems import REGISTRY, dawn_at
from app.sim.vec import Vec3
from app.sim.wear import spoil_at_dawn, spoilage, store_spot
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


def test_the_dead_keep_what_they_carried(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim, inventory={"meat": 4})
    sim.citizen("tek").body.alive = False
    spoil_at_dawn(sim.core, lambda _unit: True)
    assert not sim.drain() and sim.citizen("tek").inventory == {"meat": 4}


def test_stores_spoil_at_their_own_dawn(new_sim: Callable[..., Simulation]) -> None:
    sim = _sim(new_sim)
    sim.stock_store(STORE, "berries", 10)
    sim.stock_store("band_a_camp:drying-rack", "meat", 6)
    sim.drain()
    camp = store_spot(sim.world, "band_a_camp:drying-rack")
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
    assert spoil_at_dawn in REGISTRY.at_dawn
