"""Crafting (10-world-v1 §2.3): each recipe uses up its inputs (and the forge's fuel) and yields its item in one step,
only for someone with the skill, at its station, carrying what it takes; cut short, nothing is used or made."""

from collections.abc import Callable
from typing import get_args

import pytest

from app.observability.events import Crafted, ItemMoved
from app.observability.replay import ReplayEvent, replay
from app.sim.crafting import STATION_M, load_recipes, recipe_named, station_in_reach, stations
from app.sim.simulation import Simulation
from app.sim.slots import held_slot
from app.sim.snapshot import take_snapshot
from app.world_api.models import Craft, Give, RecipeName, Work
from tests.sim_helpers import WELL, make_spec, without_animals

ANVIL = (54.3, 57.3)  # the forge's anvil, before its open front
LOOM = (-87.0, 92.2)  # the weaver's stool before the loom at farmhouse-1
CAMP = "band_a_camp"
# §2.3, one row per recipe: inputs, wood burned besides, yield, skill, station, minutes
BIBLE = {
    "flint spear": ({"wood": 1, "flint": 1}, 0, {"flint spear": 1}, "hunting", "fire_pit", 30),
    "obsidian spear": ({"wood": 1, "obsidian": 1}, 0, {"obsidian spear": 1}, "hunting", "fire_pit", 30),
    "iron spear": ({"iron sand": 2, "wood": 1}, 2, {"iron spear": 1}, "smithing", "forge", 60),
    "stone axe": ({"wood": 1, "flint": 2}, 0, {"stone axe": 1}, "gathering", "fire_pit", 45),
    "iron axe": ({"iron sand": 3, "wood": 2}, 2, {"iron axe": 1}, "smithing", "forge", 120),
    "sickle": ({"iron sand": 3, "wood": 1}, 2, {"sickle": 1}, "smithing", "forge", 120),
    "cloth": ({"reeds": 2}, 0, {"cloth": 1}, "weaving", "loom", 60),
    "pack": ({"hide": 2, "reeds": 2}, 0, {"pack": 1}, "weaving", "loom", 60),
    "dried meat": ({"meat": 1}, 0, {"dried meat": 1}, None, "drying_rack", 30),
}


@pytest.mark.parametrize("name", sorted(BIBLE))
def test_each_recipe_is_the_bible_s(name: str) -> None:
    recipe = load_recipes().recipes[name]
    assert (recipe.inputs, recipe.fuel, recipe.yields, recipe.skill, recipe.station, recipe.minutes) == BIBLE[name]


def test_the_recipes_are_the_contract_s_and_only_dried_meat_comes_in_batches() -> None:
    recipes = load_recipes().recipes
    assert set(recipes) == set(get_args(RecipeName))
    assert {name: recipe.batch for name, recipe in recipes.items() if recipe.batch != 1} == {"dried meat": 5}
    assert {name for name, recipe in recipes.items() if recipe.fuel} == {"iron spear", "iron axe", "sickle"}


def test_a_recipe_is_named_by_its_name_or_what_it_makes() -> None:
    assert recipe_named("sickle") == recipe_named("a sickle") == "sickle"
    assert recipe_named("An Iron Axe") == "iron axe"
    assert recipe_named("a length of cloth") == recipe_named("cloth") == "cloth"
    assert recipe_named("some dried meat") == "dried meat"
    assert recipe_named("a spear") is None and recipe_named("moonstones") is None


def test_every_station_kind_stands_somewhere(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=1)
    found = {kind: [s.id for s in stations(sim.world, kind)] for kind in load_recipes().stations}
    assert found["forge"] == ["forge"] and found["loom"] == ["farmhouse-1-loom"]
    assert {"band_a_camp:fire-pit", "band_b_camp:fire-pit"} <= set(found["fire_pit"])
    assert {"band_a_camp:drying-rack", "band_b_camp:drying-rack"} <= set(found["drying_rack"])


def _smith(new_sim: Callable[..., Simulation], **fields: object) -> Simulation:
    sim = without_animals(new_sim(seed=4))
    fields = {"name": "Tetsu", "at": ANVIL, "skills": ["smithing"], "home": "cross-n-9"} | fields
    sim.add_citizen(make_spec("tetsu", **fields))
    sim.drain()
    return sim


def _run(sim: Simulation, citizen_id: str, number: int, ticks: int) -> str:
    for _ in range(ticks):
        if sim.result(citizen_id, number) is not None:
            break
        sim.step()
    result = sim.result(citizen_id, number)
    assert result is not None
    return f"{result.outcome}: {result.text}"


def test_the_smith_forges_a_sickle_at_the_anvil_burning_wood(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, inventory={"iron sand": 4, "wood": 3, "coins": 9})
    number = sim.start("tetsu", Craft(recipe="sickle"))
    craft = sim.citizen("tetsu").action
    assert craft is not None and craft.kind == "craft" and craft.until_tick == sim.tick + 120
    assert craft.label == "making a sickle"
    assert (craft.args["recipe"], craft.args["station"], craft.args["slot"]) == ("sickle", "forge", "forge#anvil")
    sim.drain()
    sim.run(119)
    assert sim.result("tetsu", number) is None and sim.citizen("tetsu").inventory["iron sand"] == 4  # not yet
    slot = held_slot(sim.core, sim.citizen("tetsu"))
    assert slot is not None and slot.id == "forge#anvil"
    sim.step()
    assert _run(sim, "tetsu", number, 0) == "done: You make a sickle."
    assert sim.citizen("tetsu").inventory == {"iron sand": 1, "sickle": 1, "coins": 9}  # 3 sand, 1 + 2 wood
    events = sim.drain()
    crafted = next(e for e in events if e.type == "crafted")
    assert (crafted.actor_id, crafted.payload) == (
        "tetsu",
        Crafted(recipe="sickle", item="sickle", count=1, station="forge"),
    )
    moves = [e.payload for e in events if isinstance(e.payload, ItemMoved) and e.cause_seq == crafted.seq]
    assert [(m.item, m.count, m.source.kind, m.destination.kind) for m in moves] == [
        ("iron sand", 3, "inventory", "world"),
        ("wood", 3, "inventory", "world"),
        ("sickle", 1, "world", "inventory"),
    ]


def test_crafting_away_from_the_station_or_without_the_skill_refuses(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, at=WELL, inventory={"iron sand": 3, "wood": 3})
    away = sim.start("tetsu", Craft(recipe="iron spear"))
    assert _run(sim, "tetsu", away, 0) == "failed: You need a forge within reach to make an iron spear."
    other = _smith(new_sim, skills=[], inventory={"iron sand": 3, "wood": 3})
    unskilled = other.start("tetsu", Craft(recipe="iron spear"))
    assert _run(other, "tetsu", unskilled, 0) == "failed: You don't know how to make an iron spear."
    unknown = other.start("tetsu", Craft(recipe="a golden crown"))
    assert _run(other, "tetsu", unknown, 0) == "failed: You don't know how to make that."
    assert other.citizen("tetsu").inventory == {"iron sand": 3, "wood": 3} and other.citizen("tetsu").action is None


def test_crafting_needs_the_inputs_and_the_forge_s_fuel(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, inventory={"iron sand": 3, "wood": 2})  # the axe's wood, but none to burn
    number = sim.start("tetsu", Craft(recipe="iron axe"))
    assert _run(sim, "tetsu", number, 0) == (
        "failed: To make an iron axe you need three measures of iron sand and four pieces of wood."
    )
    flint = sim.start("tetsu", Craft(recipe="stone axe"))  # needs gathering and a fire pit: the skill comes first
    assert _run(sim, "tetsu", flint, 0) == "failed: You don't know how to make a stone axe."


def test_the_forge_s_anvil_takes_one_smith(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, inventory={"iron sand": 2, "wood": 3})
    sim.add_citizen(
        make_spec("ito", name="Ito", at=(53.0, 57.3), skills=["smithing"], inventory={"iron sand": 2, "wood": 3})
    )
    sim.start("tetsu", Craft(recipe="iron spear"))
    second = sim.start("ito", Craft(recipe="iron spear"))
    assert _run(sim, "ito", second, 0) == "failed: Someone is working at a forge; there's no room for you."


def test_what_is_given_away_meanwhile_is_not_conjured_back(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, inventory={"iron sand": 2, "wood": 3})
    sim.add_citizen(make_spec("ito", name="Ito", at=(53.0, 57.3)))
    number = sim.start("tetsu", Craft(recipe="iron spear"))
    sim.step()
    sim.instant("tetsu", Give(person="Ito", item="iron sand"))
    sim.drain()
    assert _run(sim, "tetsu", number, 70) == "failed: You no longer have what it takes."
    assert sim.citizen("tetsu").inventory == {"wood": 3}
    assert not [e for e in sim.drain() if e.type == "crafted"]


def test_a_craft_cut_short_uses_nothing_and_makes_nothing(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, inventory={"iron sand": 2, "wood": 3})
    number = sim.start("tetsu", Craft(recipe="iron spear"))
    sim.run(30)
    sim.start("tetsu", Work(task="trade"))  # anything else ends it
    assert _run(sim, "tetsu", number, 0) == "interrupted: You stop crafting to do something else."
    sim.run(40)
    assert sim.citizen("tetsu").inventory == {"iron sand": 2, "wood": 3}


def test_crafting_refuses_what_the_crafter_couldn_t_carry(new_sim: Callable[..., Simulation]) -> None:
    def weaver(inventory: dict[str, int]) -> Simulation:
        sim = without_animals(new_sim(seed=4))
        spec = make_spec("aiko", name="Aiko", at=LOOM, home="farmhouse-1", skills=["weaving"], inventory=inventory)
        sim.add_citizen(spec)
        return sim

    full = weaver({"reeds": 2, "iron sand": 24})  # 24.2 kg; the cloth's 1 kg for 0.2 kg of reeds: 25.0, just fits
    assert full.result("aiko", full.start("aiko", Craft(recipe="cloth"))) is None
    over = weaver({"reeds": 2, "iron sand": 24, "coins": 1})
    too_heavy = over.start("aiko", Craft(recipe="cloth"))
    assert _run(over, "aiko", too_heavy, 0) == "failed: You couldn't carry a length of cloth as well."


def test_weaving_at_the_loom_makes_cloth_from_the_reeds_carried(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim(seed=4))
    sim.add_citizen(make_spec("aiko", name="Aiko", at=LOOM, home="farmhouse-1", skills=["weaving"]))
    bare = sim.start("aiko", Work(task="weave"))  # no reeds: the hour goes on the loom
    assert _run(sim, "aiko", bare, 61) == "done: You mend the loom and set up the warp; there are no reeds to weave."
    assert sim.citizen("aiko").inventory == {} and not [e for e in sim.drain() if e.type == "crafted"]
    sim.citizen("aiko").inventory["reeds"] = 5
    number = sim.start("aiko", Work(task="weave"))
    weaving = sim.citizen("aiko").action
    assert weaving is not None and weaving.kind == "work" and weaving.args["slot"] == "farmhouse-1-loom#seat"
    assert _run(sim, "aiko", number, 61) == "done: You weave a length of cloth."
    assert sim.citizen("aiko").inventory == {"reeds": 3, "cloth": 1}
    crafted = [e.payload for e in sim.drain() if isinstance(e.payload, Crafted)]
    assert crafted == [Crafted(recipe="cloth", item="cloth", count=1, station="farmhouse-1-loom")]
    sim.citizen("aiko").inventory["iron sand"] = 24  # 24.3 + 1 - 0.2 kg is more than she can carry
    full = sim.start("aiko", Work(task="weave"))
    assert _run(sim, "aiko", full, 61) == "done: Your hands are full; you leave the warp on the loom."
    assert sim.citizen("aiko").inventory == {"reeds": 3, "cloth": 1, "iron sand": 24}
    packed = sim.start("aiko", Craft(recipe="pack"))
    assert _run(sim, "aiko", packed, 0) == "failed: To make a pack you need two hides and two reeds."


def _hunter(new_sim: Callable[..., Simulation], at: tuple[float, float], **fields: object) -> Simulation:
    sim = without_animals(new_sim(seed=4))
    fields = {"name": "Bo", "site": CAMP, "at": at, "home": f"{CAMP}:shelter-n", "region": "band_a"} | fields
    sim.add_citizen(make_spec("bo", **fields))
    sim.drain()
    return sim


def test_a_hunter_knaps_a_spear_on_a_log_by_the_fire_pit(new_sim: Callable[..., Simulation]) -> None:
    sim = _hunter(new_sim, (1.5, 1.5), skills=["hunting"], inventory={"wood": 1, "flint": 3})
    number = sim.start("bo", Craft(recipe="flint spear"))
    craft = sim.citizen("bo").action
    assert craft is not None and craft.args["station"] == f"{CAMP}:fire-pit"
    assert str(craft.args["slot"]).startswith(f"{CAMP}:fire-pit#seat-") and craft.args["posture"] == "sitting"
    assert _run(sim, "bo", number, 31) == "done: You make a flint spear."
    assert sim.citizen("bo").inventory == {"flint": 2, "flint spear": 1}
    stone = sim.start("bo", Craft(recipe="stone axe"))
    assert _run(sim, "bo", stone, 0) == "failed: You don't know how to make a stone axe."


def test_meat_dries_on_the_rack_up_to_five_strips_at_a_time(new_sim: Callable[..., Simulation]) -> None:
    sim = _hunter(new_sim, (3.0, 7.2), inventory={"meat": 7})  # anyone may dry meat
    number = sim.start("bo", Craft(recipe="dried meat"))
    craft = sim.citizen("bo").action
    assert craft is not None and craft.label == "making five strips of dried meat" and craft.until_tick == sim.tick + 30
    assert _run(sim, "bo", number, 31) == "done: You make five strips of dried meat."
    assert sim.citizen("bo").inventory == {"meat": 2, "dried meat": 5}
    again = sim.start("bo", Craft(recipe="dried meat"))
    assert _run(sim, "bo", again, 31) == "done: You make two strips of dried meat."
    assert sim.citizen("bo").inventory == {"dried meat": 7}
    far = _hunter(new_sim, (-6.0, -2.0), inventory={"meat": 1})  # 9.2 m from the rack
    assert station_in_reach(far.core, far.citizen("bo"), "drying_rack") is None
    assert STATION_M == 4.0


def test_crafts_replay_exactly(new_sim: Callable[..., Simulation]) -> None:
    sim = _smith(new_sim, inventory={"iron sand": 5, "wood": 5})
    snapshot = take_snapshot(sim.state)
    number = sim.start("tetsu", Craft(recipe="iron spear"))
    events = sim.drain()
    for _ in range(61):
        sim.step()
        events += sim.drain()
    assert _run(sim, "tetsu", number, 0) == "done: You make an iron spear."
    replayed = replay(
        snapshot, [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    )
    assert (
        replayed.citizens["tetsu"].inventory
        == sim.citizen("tetsu").inventory
        == {
            "iron sand": 3,
            "wood": 2,
            "iron spear": 1,
        }
    )
