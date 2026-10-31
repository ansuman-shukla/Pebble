"""Ownership and theft (10-world-v1 §2.6): who owns each store, `stash`, taking and eating from stores in reach, the
granary's grants, and the one `stole` a take from someone else's store emits with its witnesses."""

from collections.abc import Callable
from typing import Any

import pytest

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.engine import citizen_brains
from app.observability.events import EventDraft, ItemMoved, Stole
from app.sim import ownership
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.exchange import store_in_reach
from app.sim.ownership import OWNERSHIP, free_to_take, owner_of
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, take_snapshot
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import GATE, make_spec, without_animals

TOWN = ["town", "well", "main-gate", "storehouses"]


def _door(sim: Simulation, structure: str, dx: float = 0.0) -> tuple[float, float]:
    x, z = sim.world.structures[structure].door_xz
    return (x + dx, z)


def _scene(new_sim: Callable[..., Simulation], *people: tuple[str, str, str], **extra: dict[str, Any]) -> Simulation:
    """(citizen, home, the structure whose door they stand at) for each; the ids say who they are."""
    sim = without_animals(new_sim(seed=5))
    for citizen_id, home, at in people:
        fields = {"home": home, "at": _door(sim, at), "knows_places": TOWN} | extra.get(citizen_id, {})
        sim.add_citizen(make_spec(citizen_id, **fields))
    sim.drain()
    return sim


def _stole(events: list[EventDraft]) -> list[tuple[str | None, Stole]]:
    return [(event.actor_id, event.payload) for event in events if isinstance(event.payload, Stole)]


@pytest.mark.parametrize(
    ("store", "owner"),
    [
        ("farmhouse-1-chest", "farmhouse-1"),
        ("castle-keep-chest", "castle-keep"),  # the treasury
        ("store-2", "castle-keep"),  # the granary
        ("store-5", "castle-keep"),
        ("market-stall", "main-e-2"),
        ("field-rack-1", "farmhouse-1"),
        ("field-rack-2", "farmhouse-2"),
        ("band_a_camp:drying-rack", "band_a"),
        ("band_b_camp:drying-rack", "band_b"),
        ("rice-fields", None),  # the paddies' field store is nobody's
    ],
)
def test_every_store_has_its_owner(new_sim: Callable[..., Simulation], store: str, owner: str | None) -> None:
    assert owner_of(new_sim().world, store) == owner


def test_a_take_from_someone_else_s_chest_is_one_theft_seen_by_those_who_see_the_thief(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(
        new_sim,
        ("goro", "cross-s-1", "farmhouse-1"),
        ("hana", "farmhouse-1", "farmhouse-1"),  # beside him: sees it
        ("fumiko", "main-e-2", "main-e-2"),  # in her house across town: doesn't
    )
    sim.state.citizens["fumiko"].in_view.discard("goro")
    sim.stock_store("farmhouse-1-chest", "rice", 20)
    sim.drain()
    result = WorldApi(sim, "goro").pick_up("5 rice")
    events = sim.drain()
    assert result.outcome == "done" and result.text == "You take some rice from the chest."
    assert _stole(events) == [
        ("goro", Stole(owner="farmhouse-1", store="farmhouse-1-chest", item="rice", count=5, witnesses=["hana"]))
    ]
    moved = [e for e in events if isinstance(e.payload, ItemMoved)]
    assert len(moved) == 1 and moved[0].cause_seq == next(e.seq for e in events if e.type == "stole")
    assert sim.state.stores["farmhouse-1-chest"] == {"rice": 15}
    assert sim.citizen("goro").inventory["rice"] == 5


def test_the_owners_take_freely_and_notice_once_what_went_missing(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("goro", "cross-s-1", "farmhouse-1"), ("genzo", "farmhouse-1", "farmhouse-1"))
    sim.stock_store("farmhouse-1-chest", "rice", 20)
    sim.stock_store("farmhouse-1-chest", "coins", 9)
    WorldApi(sim, "goro").pick_up("3 rice")
    WorldApi(sim, "goro").pick_up("2 coins")
    sim.drain()
    genzo = WorldApi(sim, "genzo")
    first = genzo.pick_up("2 rice")
    assert first.text == "You take a little rice from the chest. Some of your coins and rice are gone."
    assert genzo.pick_up("2 rice").text == "You take a little rice from the chest."  # told once
    assert _stole(sim.drain()) == []


def test_eating_from_the_granary_is_free_to_the_keep_and_within_a_grant_and_theft_beyond(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(
        new_sim,
        ("kenji", "castle-keep", "store-2"),
        ("ennen", "temple-hall", "store-2"),
        ("genzo", "farmhouse-1", "store-2"),
    )
    sim.stock_store("store-2", "rice", 200)
    for who in ("kenji", "ennen", "genzo"):
        sim.citizen(who).body.hunger = 100.0
        run_until_done(sim, WorldApi(sim, who).eat("rice"), 30)
    sim.citizen("ennen").body.hunger = 100.0
    run_until_done(sim, WorldApi(sim, "ennen").eat("rice"), 30)  # 20 measures today: 5 past the temple's 15
    thefts = [(who, stole.count, stole.owner) for who, stole in _stole(sim.drain())]
    assert thefts == [("genzo", 10, "castle-keep"), ("ennen", 5, "castle-keep")]
    assert OWNERSHIP.of(sim.state).granted == {"temple-hall": 15}


def test_a_store_nobody_owns_is_free_to_take_from(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("goro", "cross-s-1", "store-2"))
    assert free_to_take(sim.core, sim.citizen("goro"), "rice-fields", "rice") is None  # the paddies' field store
    assert free_to_take(sim.core, sim.citizen("goro"), "farmhouse-1-chest", "rice") == 0


def test_a_grant_starts_afresh_each_town_day(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("ennen", "temple-hall", "store-2"))
    ennen = sim.citizen("ennen")
    sim.stock_store("store-2", "rice", 100)
    assert free_to_take(sim.core, ennen, "store-2", "rice") == 15
    assert free_to_take(sim.core, ennen, "store-2", "wood") == 0  # the grant is rice
    WorldApi(sim, "ennen").pick_up("12 rice")
    assert free_to_take(sim.core, ennen, "store-2", "rice") == 3
    sim.state.tick += DAY_MINUTES
    assert free_to_take(sim.core, ennen, "store-2", "rice") == 15


def test_a_store_you_may_take_from_comes_before_a_nearer_one_of_someone_else_s(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim = _scene(new_sim, ("tokuji", "farmhouse-2", "farmhouse-2"))
    tokuji = sim.citizen("tokuji")
    sim.core.place_at(tokuji, sim.world.town.to_unit(-65.5, 89.5))  # 3.8 m from the rack, 4.8 m from the door
    monkeypatch.setitem(ownership.PLACED_OWNERS, "farm-rack", "farmhouse-1")  # the rack someone else's
    sim.stock_store("farm-rack", "rice", 5)
    assert store_in_reach(sim.core, tokuji, "rice") == "farm-rack"  # nothing of theirs here: theft
    sim.stock_store("farmhouse-2-chest", "rice", 5)
    assert store_in_reach(sim.core, tokuji, "rice") == "farmhouse-2-chest"
    assert store_in_reach(sim.core, tokuji, "wood") is None
    monkeypatch.setitem(ownership.PLACED_OWNERS, "farm-rack", "farmhouse-2")
    assert store_in_reach(sim.core, tokuji, "rice") == "farm-rack"  # both theirs: the nearest


def test_stash_puts_carried_things_in_your_own_chest_only(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ("genzo", "farmhouse-1", "farmhouse-1"),
        ("goro", "cross-s-1", "farmhouse-1"),
        genzo={"inventory": {"rice": 12, "coins": 7}},
        goro={"inventory": {"rice": 4}},
    )
    genzo, goro = WorldApi(sim, "genzo"), WorldApi(sim, "goro")
    assert genzo.stash("rice", 5).text == "You put some rice in the chest."
    assert genzo.stash("coins", 99).outcome == "done"  # as many as they carry
    assert sim.state.stores["farmhouse-1-chest"] == {"rice": 5, "coins": 7}
    assert sim.citizen("genzo").inventory == {"rice": 7}
    assert genzo.stash("dried meat", 1).text == "You aren't carrying any dried meat."
    assert goro.stash("rice", 4).text == "There's nothing of yours to put it in here."
    assert sim.citizen("goro").inventory == {"rice": 4}


def test_stashing_into_a_robbed_chest_tells_the_owner(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ("genzo", "farmhouse-1", "farmhouse-1"),
        ("goro", "cross-s-1", "farmhouse-1"),
        genzo={"inventory": {"rice": 2}},
    )
    sim.stock_store("farmhouse-1-chest", "rice", 3)
    WorldApi(sim, "goro").pick_up("rice")
    text = WorldApi(sim, "genzo").stash("rice", 2).text
    assert text == "You put a little rice in the chest. Some of your rice is gone."


def test_a_band_takes_freely_from_its_own_camp_rack_and_steals_from_the_other_s(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = without_animals(new_sim(seed=5))
    camp = {"site": "band_a_camp", "at": (3.0, 4.5), "knows_places": ["band_a_camp"]}
    sim.add_citizen(make_spec("tek", region="band_a", home="band_a_camp:shelter-e", **camp))
    sim.add_citizen(make_spec("kaz", region="band_b", home="band_b_camp:shelter-e", **camp))
    sim.stock_store("band_a_camp:drying-rack", "dried meat", 10)
    sim.drain()
    assert WorldApi(sim, "tek").pick_up("2 dried meat").text == "You take a little dried meat from the rack."
    WorldApi(sim, "kaz").pick_up("2 dried meat")
    assert [(who, s.owner, s.count) for who, s in _stole(sim.drain())] == [("kaz", "band_a", 2)]


def test_the_ownership_block_round_trips_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(
        new_sim,
        ("ennen", "temple-hall", "store-2"),
        ("goro", "cross-s-1", "farmhouse-1"),
        ("genzo", "farmhouse-1", "store-2"),  # the robbed household (its chest is far off)
    )
    sim.stock_store("store-2", "rice", 50)
    sim.stock_store("farmhouse-1-chest", "rice", 5)
    WorldApi(sim, "ennen").pick_up("4 rice")
    WorldApi(sim, "goro").pick_up("rice")
    back = restore(take_snapshot(sim.state))
    assert OWNERSHIP.of(back) == OWNERSHIP.of(sim.state)
    assert OWNERSHIP.of(back).missing == {"farmhouse-1-chest": {"rice": 5}}


# --- the scripted brains (§3.6: steal only by need) ---


def _brain(sim: Simulation, citizen_id: str, **profile: Any) -> UtilityBrain:
    citizen = sim.citizen(citizen_id)
    fields = {"citizen_id": citizen_id, "name": citizen.name, "role": "smith", "region": "town"}
    return UtilityBrain(WorldApi(sim, citizen_id), BrainProfile(home_area="The castle town", **fields | profile), 9)


def test_a_starving_townsman_with_no_food_and_no_coins_takes_rice_from_the_storehouse(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _scene(new_sim, ("tetsu", "main-w-3", "store-2"), ("kenji", "castle-keep", "castle-keep"))  # no grant
    sim.stock_store("store-2", "rice", 50)
    sim.citizen("tetsu").body.hunger = 95.0
    sim.drain()
    _brain(sim, "tetsu", honesty=0.0).decide()
    assert [(who, s.store, s.count) for who, s in _stole(sim.drain())] == [("tetsu", "store-2", 5)]


@pytest.mark.parametrize(
    ("inventory", "honesty", "hunger"),
    [
        ({"coins": 3}, 0.0, 95.0),  # coins: buys instead
        ({}, 1.0, 95.0),  # honest
        ({}, 0.0, 85.0),  # hungry, not starving
    ],
)
def test_nobody_else_steals(
    new_sim: Callable[..., Simulation], inventory: dict[str, int], honesty: float, hunger: float
) -> None:
    sim = _scene(new_sim, ("tetsu", "main-w-3", "store-2"), tetsu={"inventory": inventory})
    sim.stock_store("store-2", "rice", 50)
    sim.citizen("tetsu").body.hunger = hunger
    sim.drain()
    brain = _brain(sim, "tetsu", honesty=honesty)
    for _ in range(30):
        brain.tick()
        sim.step()
    assert _stole(sim.drain()) == []


def test_the_granary_feeds_its_eaters_and_the_others_eat_at_home(new_sim: Callable[..., Simulation]) -> None:
    sim = _scene(new_sim, ("goro", "cross-s-1", "store-2"), ("genzo", "farmhouse-1", "store-2"))
    sim.stock_store("store-2", "rice", 50)
    for who in ("goro", "genzo"):
        sim.citizen(who).body.hunger = 70.0
    sim.drain()
    goro, genzo = _brain(sim, "goro", granary=True), _brain(sim, "genzo", role="rice farmer")
    goro.decide()
    genzo.decide()
    eat = sim.citizen("goro").action
    assert eat is not None and eat.kind == "eat"
    walk = sim.citizen("genzo").action
    assert walk is not None and walk.kind == "walk_to" and walk.label == "home"
    assert _stole(sim.drain()) == []


def test_the_engine_tells_each_brain_whether_the_granary_feeds_them_and_how_honest_they_are(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    profiles = {citizen_id: brain.profile for citizen_id, brain in citizen_brains(sim, 1).brains.items()}
    assert {citizen_id for citizen_id, profile in profiles.items() if profile.granary} == {
        "masanori",
        "kenji",
        "ennen",
        "goro",
        "fumiko",
        "tetsu",
        "daisuke",
    }
    kaz = next(spec.traits for spec in load_citizens(CITIZENS).citizens if spec.id == "kaz")
    assert kaz is not None and profiles["kaz"].honesty == kaz.honesty


def test_out_at_the_gate_no_store_is_in_reach(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim(seed=5))
    sim.add_citizen(make_spec("goro", at=GATE))
    assert store_in_reach(sim.core, sim.citizen("goro")) is None
