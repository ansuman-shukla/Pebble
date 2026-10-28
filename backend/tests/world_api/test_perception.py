"""What `look_around` says: time from the local sun, things grouped and chosen by importance within a word budget,
and never a number or an id."""

import re
from collections.abc import Callable

from app.core.rng import Rng
from app.sim import perception
from app.sim.clock import TIMES
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
from app.sim.state import Citizen
from app.sim.vec import Vec3, step_towards
from app.world_api.facade import WorldApi
from app.world_api.models import Perception, Seen, ThingKind
from tests.sim_helpers import WELL, make_spec

CAMP = "band_a_camp"
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
    plants = {sight.seen.resource: sight.seen.kind for sight in found.values() if sight.seen.resource is not None}
    assert plants["berries"] == "food" and plants["wood"] == "material"
    assert {sight.seen.resource for sight in found.values() if sight.seen.kind not in ("food", "material")} == {None}

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
    others = [f"c{index}-{n}" for n in range(rng.randint(0, 3))]
    observer = _put(sim, sim.add_citizen(make_spec(f"o{index}", knows_people=others[::2], home="main-w-3")), position)
    for number, other in enumerate(others):
        spec = make_spec(other, name=NAMES[number], appearance="a woman in a grey cloak")
        person = _put(sim, sim.add_citizen(spec), _near(sim, position, rng.random() * 360, rng.random() * 30))
        person.body.asleep = rng.random() < 0.2
        person.body.alive = rng.random() > 0.1
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
        assert first_line == f"You are {seen.place}. {seen.time}"
        assert (seen.time_of_day, seen.time) in {(when, sentence) for _, when, sentence in TIMES}
        assert "It is the sun" not in first_line and "It is It" not in first_line
        sentences[seen.time_of_day].add(seen.time)
        sim.run(15)
    assert all(sentences.values())  # every time of day came round
