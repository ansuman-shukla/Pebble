"""What `look_around` says: time from the local sun, things grouped and chosen by importance within a word budget,
and never a number or an id."""

import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from app.brains.justice import known_deed
from app.core.rng import Rng
from app.observability.events import BellRang, Judged, Spoiled, Stole, Took, ToolBroke, Trespassed
from app.sim import market, nodes, ownership, perception, senses, society, territory, wear, wild
from app.sim.clock import TIMES
from app.sim.core import Stride
from app.sim.perception import (
    SIGHT_WORDS,
    TIERS,
    Sight,
    fit_to_budget,
    sights,
    things_in_view,
    words,
)
from app.sim.simulation import Simulation
from app.sim.state import ActionState, Citizen
from app.sim.vec import Vec3, step_towards
from app.sim.wear import WEAR
from app.sim.world import WATER_BIOMES
from app.world_api.facade import WorldApi, run_until_done
from app.world_api.models import ChestView, Gesture, Perception, Seen, ThingKind, Work
from tests.sim_helpers import WELL, add_animal, make_spec, put_in_the_wild, skip_to, wild_cell, without_animals

CAMP = "band_a_camp"
ITEM_ORDER = ("berries", "roots", "nuts", "meat", "fish", "rice", "dried meat", "wood", "reeds", "hide", "flint")
NAMES = ("Aiko", "Genzo", "Mio")
LEADS = {"You see ": 2, "Animals: ": 1, "Around you: ": 2}  # words that start the lines of what is seen


def sight_words(seen: Perception) -> int:
    """Words in the lines listing people, animals and things (without their leading words)."""
    return sum(
        len(line.split()) - lead
        for line in seen.text().splitlines()
        for start, lead in LEADS.items()
        if line.startswith(start)
    )


def _near(sim: Simulation, origin: Vec3, bearing: float, metres: float) -> Vec3:
    return step_towards(origin, bearing, metres, sim.world.radius_m)


def _put(sim: Simulation, citizen: Citizen, position: Vec3) -> Citizen:
    sim.core.place_at(citizen, position)
    return citizen


def _stack(sim: Simulation, item: str, count: int, position: Vec3) -> None:
    sim.core.new_stack(item, count, position, sim.world.nearest_cell(position, 0))


def _busy_camp(sim: Simulation) -> Citizen:
    """Band A's camp mid-afternoon (local), its people about and the day's gathering piled up around the fire."""
    band = ["oru", "tek", "lia", "suna"]
    observer = sim.add_citizen(
        make_spec(
            "ama",
            name="Ama",
            site=CAMP,
            at=(1.5, 3.0),
            home=f"{CAMP}:shelter-n",
            region="band_a",
            knows_places=[CAMP],
            knows_people=band,
        )
    )
    for index, member in enumerate(band):
        sim.add_citizen(make_spec(member, name=member.capitalize(), site=CAMP, at=(-6.0 + 3 * index, -4.0)))
    sim.add_citizen(make_spec("visitor", appearance="a stranger in a fur cloak", site=CAMP, at=(8.0, 8.0)))
    centre = sim.world.places[CAMP].centre
    piles = [("wood", 5), ("reeds", 6), ("wood", 5), ("berries", 9), ("nuts", 7), ("reeds", 4), ("wood", 5)]
    for index, (item, count) in enumerate(piles * 3):
        _stack(sim, item, count, _near(sim, centre, 37.0 * index, 2.0 + index % 9))
    return observer


def test_a_busy_camp_still_mentions_the_river(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    observer = _busy_camp(sim)
    river = next(thing for thing in things_in_view(sim.core, observer) if thing.label == "a river")
    nearer = [thing for thing in things_in_view(sim.core, observer) if thing.distance_m < river.distance_m]
    assert len(nearer) >= 12  # the old "nearest twelve" would have left the river out

    seen = WorldApi(sim, observer.id).look_around()
    assert [(t.label, t.kind) for t in seen.things if t.kind == "water"] == [("a river", "water")]
    assert seen.things[0].label == "a river"  # the most important thing is told first
    assert ("the fire pit", "fire") in [(thing.label, thing.kind) for thing in seen.things]
    assert "Around you: a river " in seen.text()


def test_like_things_are_grouped(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    observer = _busy_camp(sim)
    seen = WorldApi(sim, observer.id).look_around()
    labels = [thing.label for thing in seen.things]
    assert "your home" in labels and "two lean-tos" in labels  # the camp's other lean-tos, as one
    grouped = [sight.seen for sight in sights(sim.core, observer, things_in_view(sim.core, observer))]
    on_the_ground = sorted(seen.label for seen in grouped if seen.label.endswith("on the ground"))
    assert on_the_ground == [  # twenty-one piles, one entry per item (wood: nine piles of five)
        "a great deal of wood on the ground",
        "plenty of berries on the ground",
        "plenty of nuts on the ground",
        "plenty of reeds on the ground",
    ]
    assert all(seen.where.startswith("the nearest ") for seen in grouped if seen.label.endswith("on the ground"))
    assert "a stranger in a fur cloak" in seen.text()

    town = new_sim()
    walker = town.add_citizen(make_spec(at=WELL))
    in_town = WorldApi(town, walker.id).look_around()
    houses = [thing for thing in in_town.things if thing.label.endswith(" houses")]
    assert houses and houses[0].label.split()[0] in ("several", "many")
    assert houses[0].where.startswith("the nearest ")
    assert f"{houses[0].label}, {houses[0].where}" in in_town.text()


def test_things_say_what_they_are(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    walker = sim.add_citizen(make_spec(at=WELL))
    _stack(sim, "rice", 5, _near(sim, walker.position, 90.0, 4.0))
    _stack(sim, "wood", 5, _near(sim, walker.position, 270.0, 4.0))
    found = {sight.seen.label: sight for sight in sights(sim.core, walker, things_in_view(sim.core, walker))}
    kinds = {label: (sight.seen.kind, sight.tier) for label, sight in found.items()}
    assert kinds["the well"] == ("water", TIERS["water"])
    assert kinds["some rice on the ground"] == ("item", TIERS["food"])  # food lying about is food
    assert kinds["some wood on the ground"] == ("item", TIERS["item"])
    assert kinds["your home"] == ("home", TIERS["home"])
    assert kinds["the keep"] == ("shelter", TIERS["shelter"])
    assert kinds["the castle gate"] == ("building", TIERS["building"])
    storehouses = next(label for label in kinds if label.endswith("storehouses"))
    assert kinds[storehouses] == ("building", TIERS["food"])  # where the town's food is kept
    nodes = {sight.seen.resource: (sight.seen.kind, sight.tier) for sight in found.values() if sight.seen.resource}
    assert nodes["berries"] == ("node", TIERS["food"]) and nodes["wood"] == ("node", TIERS["material"])  # N1 nodes
    assert {sight.seen.resource for sight in found.values() if sight.seen.kind != "node"} == {None}

    world = sim.world
    oceans = ("shallow_ocean", "deep_ocean")
    coast = next(
        cell
        for cell in range(len(world.biomes))
        if sim.core.planner.outer.allowed[cell] and any(world.biome(n) in oceans for n in world.neighbours[cell])
    )
    _put(sim, walker, world.unit(coast))
    sea = [
        sight.seen
        for sight in sights(sim.core, walker, things_in_view(sim.core, walker))
        if sight.seen.label == "the sea"
    ]
    assert [(seen.kind, seen.resource) for seen in sea] == [("sea", None)]


def test_a_lake_you_can_drink_from_is_right_beside_you(new_sim: Callable[..., Simulation]) -> None:
    """Regression: the lake was told where its nearest cell's centre is ("close by"), so a brain on the shore never
    saw water beside it and kept walking to the lake ("You are already there.") instead of drinking."""
    sim = new_sim()
    world = sim.world
    allowed = sim.core.planner.outer.allowed
    shore = next(
        cell
        for cell in range(len(world.biomes))
        if allowed[cell]
        and world.town_point(world.unit(cell)) is None
        and any(world.biome(n) == "lake" for n in world.neighbours[cell])
    )
    citizen = _put(sim, sim.add_citizen(make_spec()), world.unit(shore))
    citizen.body.thirst = 50.0
    api = WorldApi(sim, citizen.id)
    lake = next(thing for thing in api.look_around().things if thing.label == "a lake")
    assert (lake.kind, lake.nearness, lake.where) == ("water", "right beside you", "right beside you")
    assert run_until_done(sim, api.drink(), 10).text == "You drink from the lake until you are no longer thirsty."

    inland = next(
        n for n in world.neighbours[shore] if allowed[n] and all(world.biome(m) != "lake" for m in world.neighbours[n])
    )
    _put(sim, citizen, world.unit(inland))
    lake = next(thing for thing in api.look_around().things if thing.label == "a lake")
    assert lake.nearness != "right beside you"
    refused = api.drink().result
    assert refused is not None and refused.text == "There's no water within reach."


def test_no_river_is_told_inside_the_town_where_only_the_well_gives_water(
    new_sim: Callable[..., Simulation],
) -> None:
    """Regression (#21): on the world's river cells under the town a look said "a river right beside you" while
    `drink` refused there, as the well is the town's only water."""
    sim = new_sim()
    world = sim.world
    spots = [
        world.unit(cell)
        for cell in range(world.cell_count)
        if world.river[cell] and world.town.walk.is_walkable(*(world.town_point(world.unit(cell)) or (1e9, 1e9)))
    ]
    assert spots  # the town's own walkable ground lies on some of the world's river cells
    citizen = sim.add_citizen(make_spec())
    citizen.body.thirst = 50.0
    api = WorldApi(sim, citizen.id)
    for spot in spots:
        _put(sim, citizen, spot)
        assert not any(
            seen.label == "a river" and seen.nearness == "right beside you" for seen in api.look_around().things
        )
        rivers = [
            int(thing.ref.split(":")[1])
            for thing in things_in_view(sim.core, citizen)
            if thing.ref.startswith("river:")
        ]
        assert not any(world.in_town[cell] for cell in rivers)  # a river told is one you can drink from at its cell
        refused = api.drink().result
        assert refused is not None and refused.text == "There's no water within reach."


def _sight(label: str, kind: ThingKind, tier: int, distance_m: float) -> Sight:
    return Sight(Seen(label=label, where="close by to the west", nearness="close by", kind=kind), tier, distance_m)


def test_the_budget_tells_the_important_things_first_and_stops_at_the_first_that_does_not_fit() -> None:
    found = [
        _sight("the old shed", "building", TIERS["building"], 1.0),
        _sight("plenty of reeds growing along the bank of the slow brown stream", "material", TIERS["material"], 2.0),
        _sight("a fire pit", "fire", TIERS["fire"], 40.0),
        _sight("a far lean-to", "shelter", TIERS["shelter"], 90.0),
        _sight("a near lean-to", "shelter", TIERS["shelter"], 5.0),
        _sight("your home", "home", TIERS["home"], 30.0),
        _sight("berry bushes", "food", TIERS["food"], 60.0),
        _sight("a few roots", "food", TIERS["food"], 20.0),
        _sight("the sea", "sea", TIERS["sea"], 140.0),
        _sight("a lake", "water", TIERS["water"], 120.0),
    ]
    always = ["a lake", "the sea", "a few roots", "your home", "a near lean-to", "a fire pit"]
    crowd = [Seen(label="Someone", where="close by to the east", nearness="close by")] * (SIGHT_WORDS // 6)
    told = fit_to_budget(crowd, [], found)
    assert [seen.label for seen in told] == always  # a crowd fills the budget: only what is always told

    roomy = fit_to_budget([], [], found)
    assert [seen.label for seen in roomy] == [
        "a lake",
        "the sea",
        "a few roots",
        "berry bushes",
        "your home",
        "a near lean-to",
        "a far lean-to",
        "a fire pit",
        "plenty of reeds growing along the bank of the slow brown stream",
        "the old shed",
    ]

    shed, reeds = found[0], found[1]
    used = SIGHT_WORDS - (words(shed.seen) + 1) - sum(words(seen) for seen in told)  # room for the shed, not the reeds
    person = Seen(label=" ".join(["Someone"] * (used - 1)), where="here", nearness="close by")
    assert words(person) == used
    fewer = [sight for sight in found if sight.seen in told or sight in (shed, reeds)]
    assert fit_to_budget([person], [], fewer) == told  # the reeds don't fit, so the shorter shed after them isn't told


def test_people_standing_together_share_a_phrase(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    watcher = sim.add_citizen(make_spec("watcher", at=WELL, knows_people=["aiko", "genzo"]))
    spot = _near(sim, watcher.position, 0.0, 8.0)
    for name in ("aiko", "genzo", "stranger"):
        _put(sim, sim.add_citizen(make_spec(name, name=name.capitalize(), appearance="a man in a fur cloak")), spot)
    text = WorldApi(sim, watcher.id).look_around().text()
    assert "You see Aiko, Genzo and a man in a fur cloak a few paces to the north." in text


def test_people_and_danger_are_never_dropped(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    crowd = [f"p-{chr(ord('a') + i)}{chr(ord('a') + j)}" for i in range(5) for j in range(6)]
    watcher = sim.add_citizen(make_spec("watcher", at=WELL, knows_people=crowd[::2]))
    for index, person in enumerate(crowd):
        position = _near(sim, watcher.position, 12.0 * index, 4.0 + 3 * (index % 10))
        _put(sim, sim.add_citizen(make_spec(person, name=f"Name{person[2:].upper()}")), position)
    seen = WorldApi(sim, watcher.id).look_around()
    assert len(seen.people) == len(crowd)
    assert sum(words(person) for person in seen.people) > SIGHT_WORDS  # the crowd alone fills the budget...
    text = seen.text()
    assert all(f"Name{person[2:].upper()}" in text for person in crowd[::2])
    assert text.count("a person in a p-") == len(crowd) // 2
    found = sights(sim.core, watcher, things_in_view(sim.core, watcher))
    nearest_important = {  # ...yet the nearest water, food, shelter and fire are still told
        min(tier_sights, key=lambda sight: (sight.distance_m, sight.seen.label)).seen
        for tier in {TIERS[kind] for kind in ("water", "food", "home", "shelter", "fire")}
        if (tier_sights := [sight for sight in found if sight.tier == tier])
    }
    assert {seen.kind for seen in nearest_important} >= {"water", "shelter"}
    assert nearest_important <= set(seen.things)
    assert len(seen.things) < len(found)

    danger = [Seen(label=f"a wolf number {i}", where="close by to the north", nearness="close by") for i in range(40)]
    told = fit_to_budget([], danger, found)
    assert set(told) == nearest_important | {sight.seen for sight in found if sight.tier == TIERS["water"]}
    rendered = Perception(
        you=seen.you,
        place=seen.place,
        time=seen.time,
        time_of_day=seen.time_of_day,
        people=[],
        animals=danger,
        things=told,
        heard=[],
    ).text()
    assert all(wolf.label in rendered for wolf in danger)


def _situation(sim: Simulation, rng: Rng, index: int) -> Citizen:
    """A citizen somewhere on the planet (the town, a camp, or anywhere on land) at some time, with a few people and
    piles around: ids carry digits so a leaked one shows."""
    world = sim.world
    sim.state.tick = rng.randint(0, 3 * 24 * 60)
    where = index % 3
    if where == 0:
        origin = world.places["well"].centre
    elif where == 1:
        origin = world.places[("band_a_camp", "band_b_camp")[rng.randint(0, 1)]].centre
    else:
        cells = [cell for cell in range(len(world.biomes)) if sim.core.planner.outer.allowed[cell]]
        origin = world.unit(cells[rng.randint(0, len(cells) - 1)])
    position = _near(sim, origin, rng.random() * 360, rng.random() * 40)
    if world.biome(world.nearest_cell(position)) in WATER_BIOMES:  # off a coast: nobody stands in the sea
        position = origin
    others = [f"c{index}-{n}" for n in range(rng.randint(0, 3))]
    purse = {"coins": rng.randint(1, 300)} if rng.random() < 0.5 else {}
    spec = make_spec(f"o{index}", knows_people=others[::2], home="main-w-3", inventory=purse)
    observer = _put(sim, sim.add_citizen(spec), position)
    for number, other in enumerate(others):
        titled = {"titles": ["leader"], "rank": 4, "region": "band_a", "home": None} if number == 1 else {}
        spec = make_spec(other, name=NAMES[number], appearance="a woman in a grey cloak", **titled)
        person = _put(sim, sim.add_citizen(spec), _near(sim, position, rng.random() * 360, rng.random() * 30))
        person.body.asleep = rng.random() < 0.2
        person.body.alive = rng.random() > 0.1
    if others:  # a theft the observer saw, so what they know of the thief is said too
        theft = Stole(owner="main-w-3", store="main-w-3-chest", item="rice", count=5, witnesses=[observer.id])
        sim.core.emit("stole", theft, actor=sim.citizen(others[0]))
    items = ("wood", "reeds", "berries", "nuts", "roots", "rice", "dried meat")
    for _ in range(rng.randint(0, 25)):
        item = items[rng.randint(0, len(items) - 1)]
        _stack(sim, item, rng.randint(1, 60), _near(sim, position, rng.random() * 360, rng.random() * 60))
    return observer


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def test_perception_is_words_only_deterministic_and_within_budget(new_sim: Callable[..., Simulation]) -> None:
    rng = Rng(20261029)
    digits_or_ids = re.compile(r"[0-9_]|:\S|stack-|main-w|shelter-|band_")
    budgets = []
    for index in range(150):
        sim = new_sim()
        observer = _situation(sim, rng, index)
        seen = perception.perceive(sim.core, observer)
        again = perception.perceive(sim.core, observer)
        assert seen == again  # the same world gives the same words
        text = seen.text()
        assert not digits_or_ids.search(text), text
        assert not any(digits_or_ids.search(words) for words in _strings(seen.model_dump())), seen
        assert sight_words(seen) <= SIGHT_WORDS, text
        budgets.append(sight_words(seen))
    assert max(budgets) > SIGHT_WORDS * 0.8  # some situations were busy enough to need the budget


def test_the_time_reads_naturally_through_a_whole_day(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = WorldApi(sim, sim.add_citizen(make_spec()).id)
    sentences = {when: set[str]() for _, when, _ in TIMES}
    for _ in range(24 * 4):
        seen = api.look_around()
        first_line = seen.text().splitlines()[0]
        assert first_line == f"You are {seen.place}. {seen.time} It is {seen.day_of_week}."
        assert (seen.time_of_day, seen.time) in {(when, sentence) for _, when, sentence in TIMES}
        assert "It is the sun" not in first_line and "It is It" not in first_line
        sentences[seen.time_of_day].add(seen.time)
        sim.run(15)
    assert all(sentences.values())  # every time of day came round


# --- contract v1 (10-world-v1 §6.2): the self, the day, the ground, the stall and chest, people, notices ---


def _v1(new_sim: Callable[..., Simulation], *specs: dict[str, Any]) -> Simulation:
    """A quiet scene (no animals) at the main gate, by day, with these people."""
    sim = without_animals(new_sim(seed=11))
    for fields in specs:
        sim.add_citizen(make_spec(**fields))
    sim.drain()
    return sim


def _look(sim: Simulation, who: str) -> Perception:
    return WorldApi(sim, who).look_around()


def test_the_purse_the_load_and_titles_are_told(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "lord", "titles": ["lord"], "rank": 5, "inventory": {"coins": 7, "rice": 5}},
        {"citizen_id": "ama", "region": "band_a", "titles": ["leader"], "rank": 4, "home": None},
        {"citizen_id": "kenji", "titles": ["samurai"], "rank": 4, "inventory": {"coins": 250}},
        {"citizen_id": "goro", "titles": ["ashigaru"], "rank": 3},
    )
    lord = WorldApi(sim, "lord").check_self()
    assert (lord.purse, lord.carrying, lord.titles) == ("seven coins", ["some rice"], ["the lord of the castle town"])
    assert lord.load is None
    assert "You carry some rice. You are standing still. You have seven coins." in lord.text()
    assert WorldApi(sim, "kenji").check_self().purse == "two strings of coins"
    assert WorldApi(sim, "kenji").check_self().titles == ["a samurai of the castle town"]
    assert WorldApi(sim, "goro").check_self().titles == ["a foot soldier of the castle town"]
    assert WorldApi(sim, "ama").check_self().titles == ["the leader of band A"]
    assert WorldApi(sim, "goro").check_self().purse is None
    goro = sim.citizen("goro")
    carry_kg = goro.traits.carry_kg
    goro.inventory["wood"] = int(carry_kg * 0.5) + 1  # a piece of wood weighs a kilogram
    assert WorldApi(sim, "goro").check_self().load == "carrying a load that slows you"
    goro.inventory["wood"] = int(carry_kg * 0.9) + 1
    assert WorldApi(sim, "goro").check_self().load == "carrying a heavy load, too heavy to run"
    goro.inventory["wood"] = int(carry_kg * 0.5) - 1
    assert WorldApi(sim, "goro").check_self().load is None


def test_how_people_here_regard_you_follows_your_standing_on_their_ground(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(new_sim, {"citizen_id": "genzo"}, {"citizen_id": "kaz", "region": "band_b", "home": None})
    standing = society.SOCIETY.of(sim.state).standing
    assert WorldApi(sim, "genzo").check_self().standing == "People here regard you well."
    assert WorldApi(sim, "kaz").check_self().standing is None  # nothing said of band B in town
    for value, said in ((-30, "People here distrust you."), (-80, "People here shun you as an outcast.")):
        standing["kaz"]["town"] = value
        assert WorldApi(sim, "kaz").check_self().standing == said
    standing["genzo"]["town"] = 75
    assert WorldApi(sim, "genzo").check_self().standing == "People here honour you."
    wild = put_in_the_wild(sim, "genzo", wild_cell(sim))  # nobody's ground
    assert territory.claim_at(sim.world, wild.position) is None
    assert WorldApi(sim, "genzo").check_self().standing is None


def _steal(sim: Simulation, thief: str, witnesses: list[str], store: str = "field-rack-1") -> int:
    owner = "farmhouse-1"
    payload = Stole(owner=owner, store=store, item="rice", count=5, witnesses=witnesses)
    return sim.core.emit("stole", payload, actor=sim.citizen(thief))


def test_you_are_wanted_for_a_deed_the_wronged_know_until_it_is_judged(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "kaz", "region": "band_b", "home": None, "age": 19},
        {"citizen_id": "pip", "region": "band_b", "home": None, "age": 8},
        {"citizen_id": "genzo", "home": "farmhouse-1"},
        {"citizen_id": "nim", "region": "band_b", "home": None},
        {"citizen_id": "masanori", "titles": ["lord"], "rank": 5},
        {"citizen_id": "tek", "region": "band_a", "home": None},
    )
    _steal(sim, "kaz", [])  # nobody saw it
    _steal(sim, "pip", ["genzo"])  # a child can't be judged
    assert WorldApi(sim, "kaz").check_self().wanted is None
    assert WorldApi(sim, "pip").check_self().wanted is None
    _steal(sim, "kaz", ["nim"])  # only his own band saw it
    assert WorldApi(sim, "kaz").check_self().wanted is None
    seen = _steal(sim, "kaz", ["genzo"])
    trespass = Trespassed(kind="ground", owner="band_a", place="band A's ground", took=Took(item="meat", count=4))
    sim.core.emit("trespassed", trespass.model_copy(update={"witnesses": []}), actor=sim.citizen("kaz"))
    assert WorldApi(sim, "kaz").check_self().wanted == "You are wanted in the castle town for theft."
    sim.core.emit("trespassed", trespass.model_copy(update={"witnesses": ["tek"]}), actor=sim.citizen("kaz"))
    assert WorldApi(sim, "kaz").check_self().wanted == (
        "You are wanted in the castle town for theft and by band A for poaching."
    )
    judged = Judged(person="kaz", sentence="fine", fine_mon=10, deeds=[seen])
    sim.core.emit("judged", judged, actor=sim.citizen("masanori"))
    assert WorldApi(sim, "kaz").check_self().wanted == "You are wanted by band A for poaching."
    view = WorldApi(sim, "kaz").check_self()
    assert view.text().endswith("You are wanted by band A for poaching.")


@pytest.mark.parametrize(
    ("day", "words"),
    [
        (0, "the first day of the week, market day"),
        (3, "the fourth day of the week"),
        (6, "the seventh day of the week, court day"),
        (7, "the first day of the week, market day"),
    ],
)
def test_the_day_of_the_week_is_told_with_market_and_court_days(
    new_sim: Callable[..., Simulation], day: int, words: str
) -> None:
    sim = _v1(new_sim, {"citizen_id": "genzo"})
    sim.state.tick = day * 24 * 60
    seen = _look(sim, "genzo")
    assert seen.day_of_week == words
    assert seen.text().splitlines()[0].endswith(f" It is {words}.")
    sim.citizen("genzo").body.asleep = True
    assert perception.perceive(sim.core, sim.citizen("genzo")).day_of_week == words  # sleepers keep the count


def test_a_band_b_hunter_in_the_lords_woods_hears_whose_ground_it_is_and_that_he_is_exposed(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _v1(new_sim, {"citizen_id": "kaz", "region": "band_b", "home": None, "knows_places": []})
    woods = next(h for h in sim.world.hotspots if h.id == "lords_woods")
    put_in_the_wild(sim, "kaz", sim.world.nearest_cell(woods.centre))
    seen = _look(sim, "kaz")
    assert seen.ground == territory.ground_words(sim.core, sim.citizen("kaz"))
    assert seen.ground is not None and "the Lord's woods" in seen.ground
    assert seen.safety == "exposed"
    assert f"This is {seen.ground}. You are exposed." in seen.text().splitlines()
    town = _v1(new_sim, {"citizen_id": "genzo"})
    sim_genzo = _look(town, "genzo")
    assert (sim_genzo.safety, sim_genzo.ground) == ("inside the walls", "the castle town")


def test_at_an_open_stall_the_look_tells_its_prices(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "fumiko", "at": (20.0, 52.2), "home": "main-e-2", "skills": ["trade"]},
        {"citizen_id": "goro", "at": (20.0, 56.0)},
    )
    sim.stock_store("market-stall", "rice", 120)
    assert _look(sim, "goro").market is None  # shut
    sim.start("fumiko", Work(task="trade"))
    seen = _look(sim, "goro")
    assert seen.market == market.market_view(sim.core, sim.citizen("goro"))
    assert seen.market is not None and seen.market.items
    assert "Rice, four coins for two measures; it pays three coins (fair). Sickle, none left;" in seen.text()
    sim.core.place_at(sim.citizen("goro"), sim.world.town.to_unit(20.0, 70.0))
    assert _look(sim, "goro").market is None


def test_at_your_chest_you_see_what_it_holds_and_what_went_missing(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(new_sim, {"citizen_id": "genzo", "home": "farmhouse-1"}, {"citizen_id": "kaz", "region": "band_b"})
    door = sim.world.structures["farmhouse-1"].door
    sim.core.place_at(sim.citizen("genzo"), door)
    assert _look(sim, "genzo").chest == ChestView(holds=[])
    assert "Your chest is empty." in _look(sim, "genzo").text()
    sim.stock_store("farmhouse-1-chest", "rice", 30)
    sim.stock_store("farmhouse-1-chest", "coins", 5)
    assert _look(sim, "genzo").chest == ChestView(holds=["five coins", "plenty of rice"])
    ownership.took(sim.core, sim.citizen("kaz"), "farmhouse-1-chest", "rice", 4)
    seen = _look(sim, "genzo")
    assert "Some of your rice is gone." in seen.noticed
    assert "Some of your rice is gone." not in _look(sim, "genzo").noticed  # noticed once
    assert _look(sim, "kaz").chest is None  # not his
    sim.core.place_at(sim.citizen("genzo"), _near(sim, door, 0.0, 12.0))
    assert _look(sim, "genzo").chest is None  # out of reach


def test_people_you_know_are_told_with_kin_and_titles(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "genzo", "family": {"aiko": "mate"}, "knows_people": ["aiko", "masanori", "ama"]},
        {"citizen_id": "aiko", "family": {"genzo": "mate"}},
        {"citizen_id": "masanori", "titles": ["lord"], "rank": 5},
        {"citizen_id": "ama", "region": "band_a", "titles": ["leader"], "rank": 4, "home": None},
        {"citizen_id": "tek", "region": "band_a", "home": None, "knows_people": ["ama", "genzo"]},
        {"citizen_id": "goro", "titles": ["ashigaru"], "rank": 3},
    )
    for who in ("aiko", "masanori", "ama", "tek", "goro"):
        sim.core.place_at(sim.citizen(who), _near(sim, sim.citizen("genzo").position, 90.0, 6.0))
    seen = {person.label: person for person in _look(sim, "genzo").people}
    assert seen["Aiko"].relation == "your mate"
    assert seen["Masanori"].relation == "your lord"
    assert seen["Ama"].relation == "the leader of band A"
    assert seen["a person in a tek cloak"].relation is None  # a stranger
    assert seen["a person in a goro cloak"].relation is None  # a stranger's title is nothing Genzo knows
    by_tek = {person.label: person for person in _look(sim, "tek").people}
    assert by_tek["Ama"].relation == "your leader"
    assert by_tek["Genzo"].relation is None
    assert "Aiko, your mate, a few paces to the east" in _look(sim, "genzo").text()


def test_what_you_know_of_someone_is_their_standing_of_note_and_their_deeds(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "genzo", "home": "farmhouse-1", "knows_people": ["kaz", "kenji"]},
        {"citizen_id": "kaz", "region": "band_b", "home": None},
        {"citizen_id": "kenji"},
        {"citizen_id": "tek", "region": "band_a", "home": None},
    )
    seen = {person.label: person for person in _look(sim, "genzo").people}
    assert (seen["Kaz"].regard, seen["Kenji"].regard) == (None, None)  # nothing of note
    _steal(sim, "kaz", ["genzo"])
    _steal(sim, "tek", ["genzo"], store="farmhouse-1-chest")
    trespass = Trespassed(kind="walls", owner="town", place="the castle town", witnesses=["genzo"])
    sim.core.emit("trespassed", trespass, actor=sim.citizen("kaz"))
    elsewhere = Took(item="meat", count=2)  # band A's wrong, not the town's: none of Genzo's
    poaching = Trespassed(kind="ground", owner="band_a", place="band A's ground", took=elsewhere, witnesses=["genzo"])
    sim.core.emit("trespassed", poaching, actor=sim.citizen("kaz"))
    society.SOCIETY.of(sim.state).standing["kaz"]["town"] = -40
    society.SOCIETY.of(sim.state).standing["kenji"]["town"] = 80
    society.SOCIETY.of(sim.state).standing["tek"]["town"] = -40  # a stranger's standing is nothing Genzo knows
    seen = {person.label: person for person in _look(sim, "genzo").people}
    assert seen["Kaz"].regard == "distrusted, who stole rice from your rack and was in the castle town at night"
    assert seen["Kenji"].regard == "honoured"
    assert seen["a person in a tek cloak"].regard == "who stole rice from your chest"  # deeds of strangers too
    assert known_deed(seen["Kaz"]) == "stole rice from your rack and was in the castle town at night"
    assert perception.words(seen["Kaz"]) == len(
        "Kaz, distrusted, who stole rice from your rack and was in the castle town at night,"
        f" {seen['Kaz'].where}".split()
    )  # the sight budget counts what is known of people


def test_others_are_seen_working_running_sitting_and_hurt(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(new_sim, {"citizen_id": "genzo", "knows_people": ["aiko"]}, {"citizen_id": "aiko"})
    aiko, genzo = sim.citizen("aiko"), sim.citizen("genzo")
    sim.core.place_at(aiko, _near(sim, genzo.position, 0.0, 5.0))
    action = ActionState(number=1, kind="work", started_tick=0, started_seq=0, args={"task": "farm"}, label="tending")
    aiko.action = action
    assert perception.person_doing(sim.core, genzo, aiko) == "farming"  # what she'd say of herself in full: "tending"
    assert perception.self_view(sim.core, aiko).doing == "You are tending."
    aiko.action = replace(action, kind="gather", label="berries", args={"node_kind": "berry_bush"})
    assert perception.person_doing(sim.core, genzo, aiko) == "gathering berries"
    aiko.action = replace(action, kind="gather", label="wood", args={"node_kind": nodes.TREE_KIND})
    assert perception.person_doing(sim.core, genzo, aiko) == "chopping a tree"
    aiko.action = replace(action, kind="rest", label="", args={"posture": "sitting", "where": "on the bench"})
    assert perception.person_doing(sim.core, genzo, aiko) == "sitting"
    aiko.action = replace(action, kind="walk_to", label="the well", args={})
    assert perception.person_doing(sim.core, genzo, aiko) == "walking"
    aiko.action = replace(action, kind="flee", label="", args={})
    assert perception.person_doing(sim.core, genzo, aiko) == "running"  # fleeing runs, however the last stride went
    aiko.action = replace(action, kind="walk_to", label="the well", args={})
    sim.core.strides[aiko.id] = Stride(action=1, walked=(), gait="run")
    assert perception.person_doing(sim.core, genzo, aiko) == "running"
    del sim.core.strides[aiko.id]
    aiko.inventory["wood"] = int(aiko.traits.carry_kg * 0.6)
    assert perception.person_doing(sim.core, genzo, aiko) == "carrying a load"
    aiko.body.health = 40.0
    assert perception.person_doing(sim.core, genzo, aiko) == "carrying a load, looking hurt"
    aiko.action, aiko.body.health, aiko.body.hunger = None, 100.0, 95.0
    assert perception.person_doing(sim.core, genzo, aiko) == "looking starved"
    aiko.body.health = 10.0
    assert _look(sim, "genzo").people[0].doing == "looking near death"
    aiko.body.asleep = True
    assert perception.person_doing(sim.core, genzo, aiko) == "asleep"


def test_predators_are_seen_after_their_quarry_and_at_their_kills(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(new_sim, {"citizen_id": "kaz", "region": "band_b", "home": None})
    kaz = put_in_the_wild(sim, "kaz", wild_cell(sim))
    deer = add_animal(sim, "deer", _near(sim, kaz.position, 0.0, 120.0), activity="grazing")
    wolf = add_animal(sim, "wolf", _near(sim, kaz.position, 0.0, 110.0), activity="stalking", target=deer.id)
    assert perception.animal_doing(sim.core, kaz, wolf, 110.0) == "stalking a deer"
    wolf.activity = "chasing"
    assert perception.animal_doing(sim.core, kaz, wolf, 110.0) == "chasing a deer"
    deer.alive, wolf.activity = False, "feeding"
    assert perception.animal_doing(sim.core, kaz, wolf, 110.0) == "feeding on remains"
    assert perception.animal_doing(sim.core, kaz, wolf, 40.0) == "watching you"  # close, it watches you first
    wolf.target = kaz.id
    assert perception.animal_doing(sim.core, kaz, wolf, 110.0) == "coming at you"


def test_gestures_seen_since_the_last_look_are_told_once(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "genzo", "knows_people": ["kenji"]},
        {"citizen_id": "kenji", "knows_people": ["genzo", "aiko"]},
        {"citizen_id": "aiko", "appearance": "a woman in a headwrap"},
    )
    for who in ("kenji", "aiko"):
        sim.core.place_at(sim.citizen(who), _near(sim, sim.citizen("genzo").position, 90.0, 4.0))
    assert sim.instant("kenji", Gesture(kind="bow", to="genzo")).outcome == "done"
    sim.instant("kenji", Gesture(kind="wave", to="aiko"))
    sim.instant("aiko", Gesture(kind="laugh"))
    sim.instant("aiko", Gesture(kind="laugh", to="kenji"))  # a laugh isn't aimed: the same sight, told once
    seen = _look(sim, "genzo")
    assert seen.noticed == [
        "Kenji bows to you.",
        "Kenji waves to a woman in a headwrap.",
        "A woman in a headwrap laughs.",
    ]
    assert " ".join(seen.noticed) in seen.text().splitlines()
    assert _look(sim, "genzo").noticed == []
    assert _look(sim, "kenji").noticed == ["Aiko laughs."]  # not his own; he knows her


def test_the_temple_bell_is_heard_awake_within_its_reach(new_sim: Callable[..., Simulation]) -> None:
    tower = (85.0, -71.5)
    sim = _v1(
        new_sim,
        {"citizen_id": "ennen", "home": "temple-hall", "at": tower},
        {"citizen_id": "genzo"},
        {"citizen_id": "aiko"},
        {"citizen_id": "far", "home": None},
    )
    sim.citizen("aiko").body.asleep = True
    heard_m = society.load_laws().bell.heard_m
    ringer = sim.citizen("ennen").position
    assert sim.core.distance_m(sim.citizen("genzo").position, ringer) <= heard_m
    put_in_the_wild(sim, "far", wild_cell(sim))
    assert sim.core.distance_m(sim.citizen("far").position, ringer) > heard_m
    sim.core.emit("bell_rang", BellRang(kind="noon"), actor=sim.citizen("ennen"))
    assert _look(sim, "genzo").noticed == ["The temple bell rings."]
    assert _look(sim, "far").noticed == []
    assert _look(sim, "ennen").noticed == []
    sim.citizen("aiko").body.asleep = False
    assert _look(sim, "aiko").noticed == []  # slept through it


def test_spoiled_food_and_a_worn_out_pack_are_noticed_at_the_next_look(new_sim: Callable[..., Simulation]) -> None:
    inventory = {"berries": 10, "meat": 4, "pack": 1}
    sim = _v1(new_sim, {"citizen_id": "tek", "region": "band_a", "home": None, "inventory": inventory})
    tek = sim.citizen("tek")
    tek.body.asleep = True
    WEAR.of(sim.state).rising = {"tek"}
    wear.spoil_at_dawn(sim.core, lambda _unit: False)
    sim.core.emit("tool_broke", ToolBroke(item="pack", use="carry"), actor=tek)  # the dawn's pack roll came up
    sim.core.emit("tool_broke", ToolBroke(item="flint spear", use="hunt"), actor=tek)  # told in the hunt's result
    assert perception.perceive(sim.core, tek).noticed == []  # asleep: kept for later
    tek.body.asleep = False
    assert _look(sim, "tek").noticed == ["Some of your berries and meat spoiled.", "Your pack wore out."]
    assert _look(sim, "tek").noticed == []


def test_notices_keep_only_the_latest_few_until_the_next_look(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(new_sim, {"citizen_id": "genzo"})
    for kind in ("dawn", "noon", "dusk") * 4:  # nobody rang it: a bell with no ringer is heard by nobody
        sim.core.emit("bell_rang", BellRang(kind=kind))
    assert senses.take(sim.core, "genzo") == []
    for number in range(senses.KEPT + 3):
        sim.core.emit("spoiled", Spoiled(holder="genzo", holder_kind="inventory", items={ITEM_ORDER[number]: 1}))
    sim.core.emit("spoiled", Spoiled(holder="farmhouse-1-chest", holder_kind="store", items={"rice": 2}))
    kept = senses.take(sim.core, "genzo")
    assert [notice.items for notice in kept] == [(item,) for item in ITEM_ORDER[3 : senses.KEPT + 3]]
    assert senses.take(sim.core, "genzo") == []
    assert senses.SENSES.of(sim.state).noticed == {}  # a store's spoiling is nobody's notice


def test_a_bare_tool_word_picks_up_the_best_of_that_tool_within_reach(new_sim: Callable[..., Simulation]) -> None:
    sim = _v1(new_sim, {"citizen_id": "tek", "region": "band_a", "home": None})
    tek = sim.citizen("tek")
    for item in ("flint spear", "obsidian spear", "stone axe"):
        _stack(sim, item, 1, tek.position)
    api = WorldApi(sim, "tek")
    assert api.pick_up("the spear").text == "You pick up an obsidian spear."
    assert api.pick_up("a spear").text == "You pick up a flint spear."
    assert api.pick_up("the spear").text == "There's no the spear within reach."
    assert api.pick_up("an axe").text == "You pick up a stone axe."
    assert tek.inventory == {"flint spear": 1, "obsidian spear": 1, "stone axe": 1}


@pytest.mark.parametrize(("kills", "said"), [(True, "You bring down a deer."), (False, "A deer gets away.")])
def test_a_spear_that_breaks_in_the_hunt_is_told_in_its_result(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch, kills: bool, said: str
) -> None:
    sim = _v1(new_sim, {"citizen_id": "tek", "region": "band_a", "home": None, "inventory": {"flint spear": 1}})
    tek = put_in_the_wild(sim, "tek", wild_cell(sim))
    skip_to(sim, tek.position, night=False)
    add_animal(sim, "deer", _near(sim, tek.position, 90.0, 20.0), activity="grazing", until=10**9)
    monkeypatch.setattr(wild, "hunt_chance", lambda *_: 1.0 if kills else 0.0)
    monkeypatch.setattr(wear, "use_tool", lambda *_args, **_kw: True)
    result = run_until_done(sim, WorldApi(sim, "tek").hunt("the deer"), 30)
    assert result.text.startswith(said) and result.text.endswith(" Your flint spear breaks.")
    monkeypatch.setattr(wear, "use_tool", lambda *_args, **_kw: False)
    add_animal(sim, "deer", _near(sim, tek.position, 90.0, 20.0), activity="grazing", until=10**9)
    assert "breaks" not in run_until_done(sim, WorldApi(sim, "tek").hunt("the deer"), 30).text


@pytest.mark.parametrize(
    ("deed", "words"),
    [
        (
            society.Deed(1, 0, "theft", "kaz", "town", owner="farmhouse-2", item="rice", store="field-rack-2"),
            "stole rice from the rack",
        ),  # fmt: skip
        (
            society.Deed(1, 0, "theft", "kaz", "town", owner="farmhouse-1", item="rice", store="farmhouse-1-chest"),
            "stole rice from your chest",
        ),  # fmt: skip
        (
            society.Deed(1, 0, "poaching", "kaz", "town", item="meat", place="the Lord's woods"),
            "took meat from the Lord's woods",
        ),  # fmt: skip
        (society.Deed(1, 0, "trespass", "kaz", "town", place="the castle"), "was in the castle at night"),
        (society.Deed(1, 0, "assault", "kaz", "town", victim="genzo"), "struck you"),
        (society.Deed(1, 0, "killing", "kaz", "town", victim="aiko"), "killed a woman in a headwrap"),
        # deeds logged before deeds kept their goods and places (an older run resumed)
        (society.Deed(1, 0, "theft", "kaz", "town", owner="farmhouse-2"), "stole from the store"),
        (society.Deed(1, 0, "poaching", "kaz", "town"), "took game from their ground"),
        (society.Deed(1, 0, "trespass", "kaz", "town"), "was in the walls at night"),
    ],
)
def test_a_deed_is_said_as_the_one_who_knows_it_would_say_it(
    new_sim: Callable[..., Simulation], deed: society.Deed, words: str
) -> None:
    sim = _v1(
        new_sim,
        {"citizen_id": "genzo", "home": "farmhouse-1"},
        {"citizen_id": "aiko", "appearance": "a woman in a headwrap"},
    )
    assert perception.deed_words(sim.core, sim.citizen("genzo"), deed) == words
