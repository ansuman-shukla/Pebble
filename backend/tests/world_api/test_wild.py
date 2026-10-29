"""Living off the wild through the contract (03): hunt, fish, make_fire, feed_fire, attack, flee, cooking by the fire,
animals and fires in perception, and the interrupts animals cause."""

from collections.abc import Callable

import pytest

from app.sim import doing, movement, wild
from app.sim import fire as fires
from app.sim.clock import NIGHT_ALTITUDE_DEG
from app.sim.core import SIGHT_FIRE_M, SIGHT_NIGHT_M
from app.sim.fauna import SPECIES
from app.sim.simulation import Simulation
from app.sim.state import Fire
from app.sim.vec import step_towards
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import (
    add_animal,
    make_spec,
    move_animal,
    put_in_the_wild,
    skip_to,
    wild_cell,
    without_animals,
)

IN_WORLD = ("You", "There", "The", "A", "An", "Fish")


def _hunter(new_sim: Callable[..., Simulation], **spec: object) -> tuple[Simulation, WorldApi]:
    sim = without_animals(new_sim())
    fields: dict[str, object] = {"home": None, "skills": ["hunting", "fire"], "inventory": {"spear": 1}}
    fields.update(spec)
    citizen = sim.add_citizen(make_spec("hunter", **fields))
    put_in_the_wild(sim, citizen.id, wild_cell(sim))
    skip_to(sim, citizen.position, night=False)
    return sim, WorldApi(sim, citizen.id)


def _beside(sim: Simulation, metres: float, bearing: float = 90.0) -> tuple[float, float, float]:
    return step_towards(sim.citizen("hunter").position, bearing, metres, sim.world.radius_m)


# --- hunting ---


def test_a_hunter_stalks_a_deer_and_brings_it_down(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _hunter(new_sim)
    deer = add_animal(sim, "deer", _beside(sim, 80.0), activity="grazing", until=10**9)
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 1.0)
    sim.drain()
    result = run_until_done(sim, api.hunt("the deer"), 10)
    assert result.outcome == "done"
    assert result.text == "You bring down a deer. You take some meat and a hide."
    assert not deer.alive and deer.activity == "dead"
    hunter = sim.citizen("hunter")
    assert hunter.inventory == {"spear": 1, "meat": SPECIES["deer"].meat, "hide": SPECIES["deer"].hide}
    events = sim.drain()
    died = [e for e in events if e.type == "died"]
    assert [(e.actor_id, e.payload.model_dump()["cause"]) for e in died] == [(deer.id, "hunted")]
    moved = [e.payload.model_dump() for e in events if e.type == "item_moved"]
    assert {(m["item"], m["source"]["kind"], m["source"]["id"]) for m in moved} == {
        ("meat", "animal", deer.id),
        ("hide", "animal", deer.id),
    }
    assert sim.world.distance_m(hunter.position, deer.position) <= wild.HUNT_STRIKE_M  # crept up first


def test_a_missed_animal_bolts_and_a_boar_can_turn_on_you(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _hunter(new_sim)
    boar = add_animal(sim, "boar", _beside(sim, 10.0), activity="grazing", until=10**9)
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 0.0)
    monkeypatch.setitem(SPECIES, "boar", SPECIES["boar"].__class__(**{**SPECIES["boar"].__dict__, "fights_back": 1.0}))
    handle = api.hunt("boar")
    sim.step()
    result = handle.result
    assert result is not None and result.outcome == "failed"
    assert result.text == "A boar turns on you and gets away."
    assert boar.alive and boar.activity == "running"
    hurt = 100.0 - sim.citizen("hunter").body.health
    assert SPECIES["boar"].hurts[0] <= hurt <= SPECIES["boar"].hurts[1]
    injured = [e for e in sim.drain() if e.type == "injured"]
    assert [(e.actor_id, e.payload.model_dump()["attacker"]) for e in injured] == [("hunter", boar.id)]


def test_hunting_odds_follow_skill_tool_strength_and_company(new_sim: Callable[..., Simulation]) -> None:
    sim, _ = _hunter(new_sim)
    deer = add_animal(sim, "deer", _beside(sim, 60.0), activity="grazing", until=10**9)
    hunter = sim.citizen("hunter")
    skilled = wild.hunt_chance(sim.core, hunter, deer)
    assert skilled == pytest.approx(SPECIES["deer"].catch * wild.SPEAR)
    hunter.inventory.pop("spear")
    assert wild.hunt_chance(sim.core, hunter, deer) == pytest.approx(SPECIES["deer"].catch)
    hunter.skills = ()
    assert wild.hunt_chance(sim.core, hunter, deer) == pytest.approx(SPECIES["deer"].catch * wild.UNSKILLED)
    hunter.skills = ("hunting",)
    helper = sim.add_citizen(make_spec("helper", home=None, skills=["hunting"]))
    sim.core.place_at(helper, _beside(sim, 5.0, 0.0))
    WorldApi(sim, "helper").hunt("deer")
    assert wild.hunt_chance(sim.core, hunter, deer) == pytest.approx(SPECIES["deer"].catch * (1 + wild.HELPER_BONUS))
    child = sim.add_citizen(make_spec("child", age=8, home=None, skills=["hunting"]))
    sim.core.place_at(child, _beside(sim, 200.0, 180.0))
    assert wild.hunt_chance(sim.core, child, deer) < SPECIES["deer"].catch * 0.6  # a child is weak


def test_you_can_only_hunt_what_you_see(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _hunter(new_sim)
    add_animal(sim, "fish", _beside(sim, 30.0))
    far = add_animal(sim, "deer", _beside(sim, 400.0))
    texts = [run_until_done(sim, api.hunt(words), 1).text for words in ("deer", "fish")]
    assert texts == ["You don't see any deer around here.", "You can't hunt in the water; try fishing."]
    assert far.alive


# --- fighting ---


def test_attacking_a_wolf_drives_it_off_and_attacking_a_person_hurts_them(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _hunter(new_sim)
    wolf = add_animal(sim, "wolf", _beside(sim, 2.0), target="hunter")
    monkeypatch.setattr(wild, "FIGHT_BACK", 0.0)
    result = run_until_done(sim, api.attack("the wolf"), 5)
    assert result.text == "You strike a wolf and it runs off."
    assert wolf.target is None and wolf.health < 100.0
    injured = [e for e in sim.drain() if e.type == "injured"]
    assert [e.actor_id for e in injured] == [wolf.id]

    other = sim.add_citizen(make_spec("other", name="Other", home=None))
    sim.core.place_at(other, _beside(sim, 1.0, 0.0))
    hit = run_until_done(sim, api.attack("a person in a other cloak"), 3)
    assert hit.text == "You strike a person in a other cloak."
    assert other.body.health < 100.0
    hurt = [e.payload.model_dump() for e in sim.drain() if e.type == "injured"]
    assert [(h["cause"], h["attacker"]) for h in hurt] == [("violence", "hunter")]


def test_a_struck_wolf_can_bite_back(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> None:
    sim, api = _hunter(new_sim)
    wolf = add_animal(sim, "wolf", _beside(sim, 2.0), target="hunter")
    monkeypatch.setattr(wild, "FIGHT_BACK", 1.0)
    result = run_until_done(sim, api.attack("the wolf"), 5)
    assert result.text == "You strike a wolf; it bites back and runs off."
    bitten = [e for e in sim.drain() if e.type == "injured" and e.actor_id == "hunter"]
    assert [(e.payload.model_dump()["cause"], e.payload.model_dump()["attacker"]) for e in bitten] == [
        ("animal attack", wolf.id)
    ]
    low, high = SPECIES["wolf"].bite
    assert low <= 100.0 - sim.citizen("hunter").body.health <= high


# --- fleeing ---


def test_flee_runs_away_from_the_nearest_danger(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _hunter(new_sim)
    assert run_until_done(sim, api.flee(), 1).text == "You see nothing to run from."
    wolf = add_animal(sim, "wolf", _beside(sim, 40.0), activity="sleeping", until=10**9)
    hunter = sim.citizen("hunter")
    start = hunter.position
    result = run_until_done(sim, api.flee(), 10)
    assert result.text == "You run until you feel safer."
    assert sim.world.distance_m(hunter.position, wolf.position) > sim.world.distance_m(start, wolf.position) + 100
    assert sim.world.distance_m(start, hunter.position) == pytest.approx(movement.FLEE_M, abs=25)


# --- fishing ---


def test_fishing_at_a_river_takes_from_its_stock(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _hunter(new_sim)
    hunter = sim.citizen("hunter")
    world = sim.world
    river = next(c for c in range(world.cell_count) if world.river[c] and sim.core.planner.outer.allowed[c])
    sim.core.place_at(hunter, world.unit(river))
    column = 5
    before = int(sim.state.resources[river, column])
    assert before > 0
    monkeypatch.setattr(wild, "FISH_CHANCE", 1.0)
    result = run_until_done(sim, api.fish(), wild.FISH_MINUTES + 1)
    assert result.outcome == "done" and result.text.startswith("You catch")
    caught = hunter.inventory["fish"]
    assert 1 <= caught <= 3
    assert int(sim.state.resources[river, column]) == before - caught
    assert f"{river}:fish" in sim.state.regrow
    monkeypatch.setattr(wild, "FISH_CHANCE", 0.0)
    assert run_until_done(sim, api.fish(), wild.FISH_MINUTES + 1).text == "The fish slip away from you."
    deep = next(
        c
        for c in range(world.cell_count)
        if sim.core.planner.outer.allowed[c]
        and all(world.biome(o) in ("deep_ocean",) or sim.core.planner.outer.allowed[o] for o in world.neighbours[c])
        and any(world.biome(o) == "deep_ocean" for o in world.neighbours[c])
        and not world.river[c]
    )
    sim.core.place_at(hunter, world.unit(deep))
    assert run_until_done(sim, api.fish(), 1).text == "The water here is too deep to fish without a boat."


# --- fire ---


def test_making_and_feeding_a_fire(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _hunter(new_sim, skills=["hunting"])
    hunter = sim.citizen("hunter")
    assert run_until_done(sim, api.make_fire(), 1).text == "You don't know how to make fire."
    hunter.skills = ("fire",)
    assert run_until_done(sim, api.make_fire(), 1).text == "You have no wood to burn."
    hunter.inventory["wood"] = 10
    sim.drain()
    made = run_until_done(sim, api.make_fire(), wild.MAKE_FIRE_MINUTES + 1)
    assert made.text == "You get a fire going."
    camp = next(f for f in sim.state.fires.values() if f.kind == "campfire")
    assert camp.lit and camp.fuel == fires.KINDLING_WOOD * fires.WOOD_MINUTES - 1
    assert hunter.inventory["wood"] == 10 - fires.KINDLING_WOOD
    fed = run_until_done(sim, api.feed_fire(), wild.FEED_FIRE_MINUTES + 1)
    assert fed.text == "You feed the fire; it burns brightly."
    assert "wood" not in hunter.inventory and camp.fuel > 9 * fires.WOOD_MINUTES
    hunter.inventory["wood"] = 10
    assert run_until_done(sim, api.feed_fire(), 3).text == "You feed the fire; it burns brightly."
    assert camp.fuel <= fires.MAX_FUEL
    assert run_until_done(sim, api.feed_fire(), 3).text == "The fire is burning well; it needs no more wood."
    assert run_until_done(sim, api.make_fire(), 1).text == "The fire is already burning."
    events = sim.drain()
    burned = [e.payload.model_dump() for e in events if e.type == "item_moved"]
    assert all(m["destination"] == {"kind": "fire", "id": camp.id, "cell": None, "position": None} for m in burned)
    changes = [e.payload.model_dump() for e in events if e.type == "fire_changed"]
    assert changes[0]["lit"] and changes[0]["id"] == camp.id


def test_a_fire_burns_down_level_by_level_and_goes_out(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    pit = sim.state.fires["band_a_camp:fire-pit"]
    pit.fuel, pit.level = 200, fires.fuel_level(200)
    sim.drain()
    sim.run(201)
    changes = [
        e.payload.model_dump()
        for e in sim.drain()
        if e.type == "fire_changed" and e.payload.model_dump()["id"] == pit.id
    ]
    assert [(c["lit"], c["strength"]) for c in changes] == [(True, 0.667), (True, 0.333), (False, 0.0)]
    assert not pit.lit and pit.fuel == 0


def test_fire_feeds_off_the_woodpile_beside_it(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    keeper = sim.add_citizen(make_spec("keeper", site="band_a_camp", at=(-1.5, 0.0), home=None, skills=["fire"]))
    pit = sim.state.fires["band_a_camp:fire-pit"]
    pile = next(s for s in sim.state.ground.values() if sim.world.distance_m(s.position, pit.position) < 5)
    pit.fuel, pit.level = 100, fires.fuel_level(100)
    assert sim.world.distance_m(keeper.position, pile.position) > 3.0  # out of reach, but the fire's woodpile
    assert sim.world.distance_m(pit.position, pile.position) <= wild.WOODPILE_M
    result = run_until_done(sim, WorldApi(sim, keeper.id).feed_fire(), 3)
    assert result.text == "You feed the fire; it burns brightly."
    assert pile.count < 12 or pile.id not in sim.state.ground


def test_a_fire_lights_the_night_and_cooks_meat(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _hunter(new_sim)
    hunter = sim.citizen("hunter")
    skip_to(sim, hunter.position, night=True)
    assert sim.core.altitude(hunter.position) < NIGHT_ALTITUDE_DEG
    assert sim.core.sight_range(hunter) == pytest.approx(SIGHT_NIGHT_M)
    camp = Fire(id="fire:7", kind="campfire", position=hunter.position, cell=hunter.cell, height_m=hunter.height_m)
    fires.add_fuel(camp, 300)
    sim.state.fires[camp.id] = camp
    assert sim.core.sight_range(hunter) == pytest.approx(SIGHT_FIRE_M)
    assert any((t.label, t.doing, t.kind) == ("a campfire", "burning", "fire") for t in api.look_around().things)

    monkeypatch.setattr(doing, "RAW_SICK_CHANCE", 1.0)
    hunter.inventory["meat"] = 3
    hunter.body.hunger = 60.0
    cooked = run_until_done(sim, api.eat("meat"), 10)
    assert cooked.text.startswith("You roast")
    assert hunter.body.health == 100.0
    eaten = 3 - hunter.inventory.get("meat", 0)
    assert hunter.body.hunger == pytest.approx(max(0.0, 60.0 - eaten * 10.0 * doing.COOKED), abs=0.5)

    camp.fuel, camp.lit, camp.level = 0, False, 0
    hunter.inventory["meat"] = 2
    hunter.body.hunger = 30.0
    raw = run_until_done(sim, api.eat("meat"), 10)
    assert "raw" in raw.text and "sick" in raw.text
    assert hunter.body.health < 100.0
    assert any(e.type == "injured" and e.payload.model_dump()["cause"] == "bad food" for e in sim.drain())


def test_town_folk_take_wood_from_the_storehouse(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.stock_store("store-2", "wood", 30)
    porter = sim.add_citizen(make_spec("porter", at=(70.0, 85.0)))
    result = WorldApi(sim, porter.id).pick_up("wood")
    assert result.text == "You take plenty of wood from the storehouse."
    assert porter.inventory == {"wood": 25} and sim.state.stores["store-2"] == {"wood": 5}
    porter.inventory.clear()
    assert WorldApi(sim, porter.id).pick_up("two pieces of wood").text == "You take a little wood from the storehouse."
    assert porter.inventory == {"wood": 2} and sim.state.stores["store-2"] == {"wood": 3}


# --- perception and interrupts ---


def test_animals_are_seen_by_kind_and_group(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _hunter(new_sim)
    for n in range(4):
        add_animal(sim, "deer", _beside(sim, 60.0 + n), activity="grazing", until=10**9)
    for group in list(sim.state.groups.values())[1:]:  # one herd of four
        sim.state.animals[group.members[0]].group = next(iter(sim.state.groups))
    wolf = add_animal(sim, "wolf", _beside(sim, 30.0, 270.0), activity="idle", until=10**9)
    seen = api.look_around().animals
    assert [(s.label, s.doing) for s in seen] == [("a wolf", "watching you"), ("a herd of deer", "grazing")]
    assert seen[0].where == "close by to the west"
    wolf.activity = "sleeping"
    assert api.look_around().animals[0].doing == "asleep"
    wolf.target, wolf.activity = "hunter", "hunting"
    assert api.look_around().animals[0].doing == "coming at you"
    text = api.look_around().text()
    assert "Animals: a wolf close by to the west (coming at you)" in text


def test_animals_coming_into_view_interrupt_and_being_hurt_wakes_you(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _hunter(new_sim)
    waiting = api.wait(30)
    add_animal(sim, "deer", _beside(sim, 100.0), activity="grazing", until=10**9)
    sim.step()
    assert waiting.result is not None
    assert waiting.result.text == "You stop waiting: a deer comes into view some way off to the east."

    wolf = add_animal(sim, "wolf", _beside(sim, 30.0, 0.0), activity="idle", until=10**9)
    resting = api.rest(30)
    sim.step()
    assert resting.result is not None
    assert resting.result.text == "You stop resting: a wolf is watching you close by to the north."

    hunter = sim.citizen("hunter")
    hunter.body.energy = 20.0
    skip_to(sim, hunter.position, night=True)
    sleeping = api.sleep()
    wolf.hunger, wolf.until = 90.0, 0
    move_animal(sim, wolf, _beside(sim, 2.0, 0.0))
    for _ in range(3):
        sim.step()
        if sleeping.result is not None:
            break
    assert sleeping.result is not None
    assert sleeping.result.text == "You wake: a wolf attacks you!"


def test_wild_failures_are_in_world(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _hunter(new_sim)
    texts = [
        run_until_done(sim, api.hunt("bears"), 1).text,
        run_until_done(sim, api.attack("a dragon"), 1).text,
        run_until_done(sim, api.feed_fire(), 1).text,
        run_until_done(sim, api.gather("fish"), 1).text,
    ]
    assert texts == [
        "You don't see any bears around here.",
        "You don't see anyone or anything like that.",
        "There's no fire within reach.",
        "Fish have to be caught; try fishing.",
    ]
    assert all(text.startswith(IN_WORLD) for text in texts)
