"""What a citizen senses, in words (03-actions-perception, "Perception"), and resolving what they refer to.

Sight: ~150 m by day, ~20 m at night (linear through twilight), ×0.4 in forest, ×1.3 on hills. No occlusion in v0.
A look around groups like things ("three lean-tos", "plenty of wood on the ground"; D64) and lists them by importance
within a word budget (D63): everyone in view, every water, your home, the nearest food, shelter and fire (and every
fire within a few paces), then the rest nearest first.
"""

import math
import re
from dataclasses import dataclass
from typing import Literal, get_args

import numpy as np

from app.sim import fire as fires
from app.sim.bodies import body_words
from app.sim.clock import local_minute, time_of_day
from app.sim.core import FOREST_BIOMES, SimCore
from app.sim.fauna import DANGEROUS, SPECIES
from app.sim.items import GATHERED, ITEMS, RESOURCE_INDEX, amount_words
from app.sim.state import ActionState, Animal, Citizen
from app.sim.vec import Vec3, bearing_deg, lat_lon_deg
from app.sim.world import CAMP_STRUCTURE_LABELS, HOME_KINDS, STRUCTURE_LABELS, WATER_BIOMES
from app.world_api.models import (
    NEAREST,
    HeardWords,
    Nearness,
    Perception,
    ResourceName,
    Seen,
    SelfView,
    ThingKind,
    phrase,
)

COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
MAX_ANIMALS = 8
FIRE_TOLD_M = 15.0  # every fire within a few paces is told (someone tending a pair of baskets sees both)
WATCHING_M = 60.0  # an awake predator this close is "watching you"
SIGHT_WORDS = 120  # people, animals and things seen are listed in about this many words (D63)
COUNT_WORDS = {2: "two", 3: "three", 4: "four", 5: "five"}  # then "several", and "many" from ten
GROUP_NOUNS: dict[str, str] = {  # structure kinds seen in numbers
    "storehouse": "storehouses",
    "townhouse": "houses",
    "farmhouse": "farmhouses",
    "castle_gatehouse": "gatehouses",
    "lean_to": "lean-tos",
}
FOOD_PLANTS = frozenset({"berries", "roots", "nuts"})
# importance of what's seen; every water and the nearest of each other tier below IMPORTANT are always told
TIERS: dict[ThingKind, int] = {
    "water": 0,
    "sea": 0,
    "food": 1,
    "home": 2,
    "shelter": 3,
    "fire": 4,
    "material": 5,
    "item": 6,
    "building": 7,
}
IMPORTANT = 5
RESOURCE_NAMES: dict[str, ResourceName] = {name: name for name in get_args(ResourceName)}
WATER = frozenset(WATER_BIOMES)
_CELL_MARGIN_M = 25.0  # cells whose centre is this much beyond sight still count (cells are ~40 m across)
_ARTICLES = frozenset({"the", "a", "an", "some", "any", "my", "your"})

BIOME_WORDS: dict[str, str] = {
    "grassland": "open grassland",
    "broadleaf_forest": "a broadleaf forest",
    "taiga": "a pine forest",
    "wetland": "a marsh",
    "hills": "the hills",
    "mountain": "a mountainside",
    "savanna": "dry scrubland",
    "tundra": "cold, bare tundra",
    "snow": "deep snow",
    "ice": "the ice",
    "beach": "a beach",
    "volcanic": "black volcanic rock",
}
DOING: dict[str, str] = {
    "walk_to": "walking",
    "follow": "walking",
    "gather": "gathering",
    "eat": "eating",
    "drink": "drinking",
    "rest": "resting",
    "sleep": "asleep",
    "wait": "standing about",
    "flee": "running",
    "work": "working",
    "hunt": "hunting",
    "fish": "fishing",
    "make_fire": "making a fire",
    "feed_fire": "tending a fire",
    "attack": "fighting",
}
ANIMAL_DOING: dict[str, str] = {
    "grazing": "grazing",
    "walking": "on the move",
    "running": "running",
    "hunting": "hunting",
    "sleeping": "asleep",
}
RESOURCE_KEYWORDS: dict[str, frozenset[str]] = {
    "berries": frozenset({"berries", "berry", "bush", "bushes"}),
    "roots": frozenset({"roots", "root"}),
    "nuts": frozenset({"nuts", "nut"}),
    "reeds": frozenset({"reeds", "reed"}),
    "wood": frozenset({"wood", "branches", "deadwood", "firewood"}),
}
STRUCTURE_KEYWORDS: dict[str, frozenset[str]] = {
    "well": frozenset({"well", "water"}),
    "storehouse": frozenset({"storehouse", "store"}),
    "townhouse": frozenset({"house"}),
    "farmhouse": frozenset({"farmhouse", "house"}),
    "castle_gatehouse": frozenset({"gate", "gatehouse"}),
    "castle_keep": frozenset({"keep", "castle"}),
    "lean_to": frozenset({"lean-to", "shelter"}),
    "fire_pit": frozenset({"fire", "pit", "firepit"}),
}


def normalize(text: str) -> str:
    words = re.sub(r"[^a-z0-9' -]", " ", text.lower()).split()
    return " ".join(word for word in words if word not in _ARTICLES)


def compass(bearing: float) -> str:
    return COMPASS[int((bearing + 22.5) // 45) % 8]


def nearness(distance_m: float) -> Nearness:
    if distance_m < 3:
        return "right beside you"
    if distance_m < 15:
        return "a few paces"
    if distance_m < 50:
        return "close by"
    if distance_m < 150:
        return "some way off"
    if distance_m < 500:
        return "in the distance"
    return "far away"


def where_words(distance_m: float, bearing: float) -> str:
    near = nearness(distance_m)
    return near if near == "right beside you" else f"{near} to the {compass(bearing)}"


@dataclass(frozen=True)
class Thing:
    label: str
    keywords: frozenset[str]
    goal: Vec3  # where to walk to reach it
    distance_m: float
    bearing: float
    kind: Literal["structure", "ground", "resource", "water", "fire"]
    ref: str
    water: Literal["fresh", "salt"] | None = None
    item: str | None = None  # the resource of a plant, the item of a ground stack
    state: str | None = None  # how a fire burns ("burning low"), told as what it is doing


def person_label(observer: Citizen, other: Citizen) -> str:
    return other.name if other.id in observer.people else other.appearance


def visible_people(core: SimCore, citizen: Citizen) -> list[tuple[Citizen, float]]:
    """Everyone (living or dead) within sight, nearest first."""
    sight = core.sight_range(citizen)
    seen: list[tuple[float, str, Citizen]] = []
    for other in core.citizens():
        if other.id == citizen.id:
            continue
        distance = core.distance_m(citizen.position, other.position)
        if distance <= sight:
            seen.append((distance, other.id, other))
    seen.sort()
    return [(other, distance) for distance, _, other in seen]


def match_person(core: SimCore, citizen: Citizen, who: str) -> Citizen | None:
    """The nearest living person in view whose name (if known) or appearance matches the words."""
    query = normalize(who)
    for other, _ in visible_people(core, citizen):
        if not other.body.alive:
            continue
        names = {normalize(other.appearance)}
        if other.id in citizen.people:
            names.add(normalize(other.name))
        if query and any(query == name or query in name for name in names):
            return other
    return None


def _resource_label(resource: str, count: int) -> str:
    if resource == "berries":
        return (
            "bushes heavy with berries"
            if count >= 20
            else "berry bushes"
            if count >= 5
            else "a few berries on the bushes"
        )
    if resource == "roots":
        return "plenty of edible roots" if count >= 10 else "a few edible roots"
    if resource == "nuts":
        return "nut trees heavy with nuts" if count >= 10 else "a few nuts on the trees"
    if resource == "reeds":
        return "thick reeds" if count >= 10 else "a few reeds"
    return "plenty of fallen wood" if count >= 10 else "a little fallen wood"


def things_in_view(core: SimCore, citizen: Citizen) -> list[Thing]:
    world, state = core.world, core.state
    position = citizen.position
    sight = core.sight_range(citizen)
    things: list[Thing] = []

    def add(
        label: str,
        keywords: frozenset[str],
        goal: Vec3,
        kind: Literal["structure", "ground", "resource", "water", "fire"],
        ref: str,
        water: Literal["fresh", "salt"] | None = None,
        at: Vec3 | None = None,
        item: str | None = None,
        burning: str | None = None,
    ) -> None:
        target = goal if at is None else at
        distance = core.distance_m(position, target)
        bearing = bearing_deg(position, target)
        things.append(Thing(label, keywords, goal, distance, bearing, kind, ref, water, item, burning))

    # everyone of a band has their own seat round its fire
    seat = [other.id for other in core.citizens() if other.region == citizen.region].index(citizen.id)
    for structure in world.structures.values():
        distance = core.distance_m(position, structure.centre)
        if distance > sight:
            continue
        if structure.id == citizen.home:
            add(
                "your home",
                frozenset({"home", "house"}),
                structure.door,
                "structure",
                structure.id,
                at=structure.centre,
            )
        else:
            water: Literal["fresh"] | None = "fresh" if structure.kind == "well" else None
            pit_fire = state.fires.get(structure.id)
            burning = fires.state_words(pit_fire) if pit_fire is not None else None
            keywords = STRUCTURE_KEYWORDS[structure.kind] | frozenset((burning or "").split())
            add(
                structure.label,
                keywords,
                structure.spot(seat),
                "structure",
                structure.id,
                water,
                structure.centre,
                burning=burning,
            )

    for fire in sorted(state.fires.values(), key=lambda f: f.id):
        if fire.kind == "pit":
            continue  # told as the fire pit (a structure), burning or cold
        if core.distance_m(position, fire.position) <= sight:
            hearth = world.hearths.get(fire.id)
            goal = hearth.stand if hearth is not None else fire.position
            burning = fires.state_words(fire)
            keywords = fires.KEYWORDS | frozenset(burning.split())
            add(fires.label(fire), keywords, goal, "fire", fire.id, at=fire.position, burning=burning)

    for stack in sorted(state.ground.values(), key=lambda s: s.id):
        if core.distance_m(position, stack.position) <= sight:
            item = ITEMS[stack.item]
            keywords = frozenset({item.name, item.one.split()[-1]})
            label = f"{amount_words(stack.count, item)} on the ground"
            add(label, keywords, stack.position, "ground", stack.id, item=stack.item)

    cos_limit = math.cos(min(math.pi, (sight + _CELL_MARGIN_M) / world.radius_m))
    cells = np.flatnonzero(world.grid.positions @ np.array(position) >= cos_limit)
    cells = cells[np.argsort(world.grid.positions[cells] @ np.array(position))[::-1]]  # nearest first
    here = citizen.cell
    resources = state.resources
    found_resource: set[str] = set()
    found_water: set[str] = set()
    # a lake or the sea next to your cell is right beside you: you can drink from it there (`water_within_reach`)
    beside = {_water_kind(world.biome(other)) for other in world.neighbours[here] if world.biome(other) in WATER}
    for cell in [here, *[int(c) for c in cells if c != here]]:
        unit = world.unit(cell)
        biome = world.biome(cell)
        for resource, column in RESOURCE_INDEX.items():
            if resource not in GATHERED:
                continue  # fish are seen as shoals (animals) and caught with fish()
            count = int(resources[cell, column])
            if count > 0 and resource not in found_resource:
                found_resource.add(resource)
                at = position if cell == here else unit
                add(
                    _resource_label(resource, count),
                    RESOURCE_KEYWORDS[resource],
                    unit,
                    "resource",
                    f"{cell}:{resource}",
                    at=at,
                    item=resource,
                )
        if world.river[cell] and "river" not in found_water:
            found_water.add("river")
            add(
                "a river",
                frozenset({"river", "stream", "water"}),
                unit,
                "water",
                f"river:{cell}",
                "fresh",
                at=position if cell == here else unit,
            )
        if biome in WATER:
            water_kind = _water_kind(biome)
            if water_kind in found_water:
                continue
            shore = _shore_cell(core, cell, citizen)
            if shore is None:
                continue
            found_water.add(water_kind)
            if water_kind == "lake":
                add(
                    "a lake",
                    frozenset({"lake", "pond", "water"}),
                    world.unit(shore),
                    "water",
                    f"lake:{cell}",
                    "fresh",
                    at=position if water_kind in beside else unit,
                )
            else:
                add(
                    "the sea",
                    frozenset({"sea", "ocean", "water"}),
                    world.unit(shore),
                    "water",
                    f"sea:{cell}",
                    "salt",
                    at=position if water_kind in beside else unit,
                )
    things.sort(key=lambda thing: (thing.distance_m, thing.ref))
    return things


def _water_kind(biome: str) -> Literal["lake", "sea"]:
    return "lake" if biome == "lake" else "sea"


def _shore_cell(core: SimCore, water_cell: int, citizen: Citizen) -> int | None:
    """The walkable neighbour of a water cell nearest to the citizen."""
    options = [
        (core.distance_m(citizen.position, core.world.unit(other)), other)
        for other in core.world.neighbours[water_cell]
        if core.planner.outer.allowed[other]
    ]
    return min(options)[1] if options else None


def match_thing(core: SimCore, citizen: Citizen, what: str) -> Thing | None:
    query = normalize(what)
    words = set(query.split())
    matches = [
        thing for thing in things_in_view(core, citizen) if thing.keywords & words or normalize(thing.label) == query
    ]
    if "water" in words:
        fresh = [thing for thing in matches if thing.water == "fresh"]
        matches = fresh or matches
    exact = [thing for thing in matches if normalize(thing.label) == query]  # "the fire pit", not any fire
    matches = exact or matches
    # the best fit first ("the cold fire basket" over a burning one), then the nearest
    return (
        min(matches, key=lambda thing: (-len(thing.keywords & words), thing.distance_m, thing.ref)) if matches else None
    )


HOME_RADIUS_M = 6.0


def animal_sightings(core: SimCore, citizens: list[Citizen]) -> dict[str, list[tuple[Animal, float]]]:
    """For each citizen: the animals (living, and remains) within sight, nearest first."""
    animals = [core.state.animals[aid] for aid in sorted(core.state.animals)]
    if not animals or not citizens:
        return {citizen.id: [] for citizen in citizens}
    where = np.array([animal.position for animal in animals])
    eyes = np.array([citizen.position for citizen in citizens])
    distances = np.arccos(np.clip(where @ eyes.T, -1.0, 1.0)) * core.world.radius_m
    sightings: dict[str, list[tuple[Animal, float]]] = {}
    for column, citizen in enumerate(citizens):
        rows = np.flatnonzero(distances[:, column] <= core.sight_range(citizen)).tolist()
        seen = sorted((float(distances[row, column]), animals[row].id, animals[row]) for row in rows)
        sightings[citizen.id] = [(animal, distance) for distance, _, animal in seen]
    return sightings


def visible_animals(core: SimCore, citizen: Citizen) -> list[tuple[Animal, float]]:
    return animal_sightings(core, [citizen])[citizen.id]


def animal_names(kind: str) -> set[str]:
    species = SPECIES[kind]
    return {kind.replace("_", " "), species.many, normalize(species.one), "animal", "animals"}


def match_animal(core: SimCore, citizen: Citizen, words: str) -> Animal | None:
    """The nearest living animal in view the words name ("the deer", "a wolf", "wolves", "that herd of elk")."""
    query = normalize(words)
    if not query:
        return None
    for animal, _ in visible_animals(core, citizen):
        if not animal.alive:
            continue
        names = animal_names(animal.kind)
        if query in names or any(name in query.split() or query.endswith(name) for name in names - {"animal"}):
            return animal
    return None


def nearest_danger(core: SimCore, citizen: Citizen) -> tuple[Animal, float] | None:
    """The nearest living animal in view that attacks people."""
    return next(
        ((animal, distance) for animal, distance in visible_animals(core, citizen)
         if animal.alive and animal.kind in DANGEROUS),
        None,
    )  # fmt: skip


def animal_doing(citizen: Citizen, animal: Animal, distance_m: float) -> str | None:
    if animal.target == citizen.id:
        return "coming at you"
    if animal.kind in DANGEROUS and animal.activity not in ("sleeping", "dead") and distance_m <= WATCHING_M:
        return "watching you"
    return ANIMAL_DOING.get(animal.activity)


def from_where(core: SimCore, citizen: Citizen, distance_m: float, bearing: float) -> str:
    where = where_words(distance_m, bearing)
    return f"from the trees, {where}" if core.world.biome(citizen.cell) in FOREST_BIOMES else where


def seen_animals(citizen: Citizen, sightings: list[tuple[Animal, float]]) -> list[Seen]:
    """Animals in view as a person would name them: each group once (nearest member), remains one by one."""
    groups: dict[str, list[tuple[Animal, float]]] = {}
    remains: list[Seen] = []
    for animal, distance in sightings:
        if animal.alive:
            groups.setdefault(animal.group, []).append((animal, distance))
        else:
            where = where_words(distance, bearing_deg(citizen.position, animal.position))
            remains.append(
                Seen(label=f"the remains of {SPECIES[animal.kind].one}", where=where, nearness=nearness(distance))
            )
    seen: list[tuple[float, Seen]] = []
    for members in groups.values():
        nearest, distance = members[0]
        species = SPECIES[nearest.kind]
        where = where_words(distance, bearing_deg(citizen.position, nearest.position))
        label = species.count_words(len(members))
        doing = animal_doing(citizen, nearest, distance)
        seen.append((distance, Seen(label=label, where=where, nearness=nearness(distance), doing=doing)))
    seen.sort(key=lambda entry: (entry[0], entry[1].label))
    return ([entry[1] for entry in seen] + remains)[:MAX_ANIMALS]


def place_words(core: SimCore, citizen: Citizen) -> str:
    """Where the citizen is: the smallest known place they stand in, else the ground described."""
    world = core.world
    inside = [
        place
        for place_id, place in world.places.items()
        if place_id in citizen.places
        and citizen.places[place_id].level == "visited"
        and core.distance_m(citizen.position, place.centre) <= place.radius_m
    ]
    inside.sort(key=lambda place: (place.radius_m, place.id))
    parts: list[str] = []
    home = world.structures.get(citizen.home) if citizen.home is not None else None
    if home is not None and core.distance_m(citizen.position, home.door) <= HOME_RADIUS_M:
        parts.append("at your home")
    parts += [
        f"in {place.name}" if place.kind == "site" and place.id == "town" else f"at {place.name}" for place in inside
    ]
    if parts:
        return ", ".join(parts[:2])
    if world.town_point(citizen.position) is not None:
        return "in an unfamiliar walled town"
    ground = BIOME_WORDS[world.biome(citizen.cell)]
    if world.river[citizen.cell]:
        ground += " by a river"
    near = [
        (core.distance_m(citizen.position, world.places[place_id].centre), world.places[place_id].name)
        for place_id, knowledge in sorted(citizen.places.items())
        if knowledge.level == "visited"
    ]
    near = [entry for entry in near if entry[0] <= 400]
    if near:
        return f"in {ground}, not far from {min(near)[1]}"
    if ground.startswith("a "):
        return f"in an unfamiliar {ground[2:]}"
    if ground.startswith("the "):
        return f"in {ground}, somewhere unfamiliar"
    return f"in unfamiliar {ground}"


def doing_words(action: ActionState | None, asleep: bool) -> str:
    if asleep:
        return "You are asleep."
    if action is None:
        return "You are standing still."
    if action.kind == "walk_to":
        return f"You are walking to {action.destination}." if action.destination else "You are walking."
    if action.kind == "follow":
        return f"You are following {action.destination}."
    return f"You are {DOING.get(action.kind, 'busy')}."


def self_view(core: SimCore, citizen: Citizen) -> SelfView:  # noqa: ARG001  # same signature as the other senses
    carrying = [amount_words(count, ITEMS[item]) for item, count in sorted(citizen.inventory.items()) if count > 0]
    return SelfView(
        feeling=body_words(citizen.body), carrying=carrying, doing=doing_words(citizen.action, citizen.body.asleep)
    )


def perceive(core: SimCore, citizen: Citizen) -> Perception:
    """Everything the citizen senses now; heard speech is reported once."""
    you = self_view(core, citizen)
    _, lon = lat_lon_deg(citizen.position)
    when, time = time_of_day(local_minute(core.state.tick, core.world.town_lon_deg, lon))
    if citizen.body.asleep:
        return Perception(
            you=you, place="asleep", time=time, time_of_day=when, people=[], animals=[], things=[], heard=[]
        )
    people = [
        Seen(
            label=person_label(citizen, other)
            if other.body.alive
            else f"the still body of {person_label(citizen, other)}",
            where=where_words(distance, bearing_deg(citizen.position, other.position)),
            nearness=nearness(distance),
            doing=_doing(other) if other.body.alive else None,
        )
        for other, distance in visible_people(core, citizen)
    ]
    animals = seen_animals(citizen, visible_animals(core, citizen))
    things = fit_to_budget(people, animals, sights(core, citizen, things_in_view(core, citizen)))
    heard = [HeardWords(who=entry.who, words=entry.words, volume=entry.volume) for entry in citizen.heard]
    citizen.heard.clear()
    return Perception(
        you=you,
        place=place_words(core, citizen),
        time=time,
        time_of_day=when,
        people=people,
        animals=animals,
        things=things,
        heard=heard,
    )


@dataclass(frozen=True)
class Sight:
    """A thing or a group of like things in view, before the word budget picks what is said."""

    seen: Seen
    tier: int  # importance (TIERS), lower first
    distance_m: float  # to the nearest member


def _group_key(core: SimCore, citizen: Citizen, thing: Thing) -> str:
    if thing.kind == "structure":
        structure = core.world.structures[thing.ref]
        if structure.id == citizen.home or structure.label.startswith("the "):  # your home, named ones: on their own
            return thing.ref
        return f"structure:{structure.kind}"
    if thing.kind == "ground":
        return f"ground:{thing.item}"
    if thing.kind == "fire":
        return f"fire:{thing.ref}"  # a fire on its own (a pit's fire shares the pit's id)
    return thing.ref  # each kind of plant and of water is already only its nearest


def _kind(core: SimCore, citizen: Citizen, thing: Thing) -> ThingKind:
    if thing.water is not None:
        return "water" if thing.water == "fresh" else "sea"
    if thing.kind == "resource":
        return "food" if thing.item in FOOD_PLANTS else "material"
    if thing.kind == "ground":
        return "item"
    if thing.kind == "fire":
        return "fire"
    structure = core.world.structures[thing.ref]
    if structure.id == citizen.home:
        return "home"
    if structure.kind in HOME_KINDS:
        return "shelter"
    return "fire" if structure.kind == "fire_pit" else "building"


def _tier(core: SimCore, thing: Thing, kind: ThingKind) -> int:
    """How important it is to mention; food on the ground and the storehouses count as food."""
    if thing.kind == "ground" and thing.item is not None and ITEMS[thing.item].food > 0:
        return TIERS["food"]
    if thing.kind == "structure" and core.world.structures[thing.ref].kind == "storehouse":
        return TIERS["food"]
    return TIERS[kind]


def _count_words(count: int) -> str:
    return COUNT_WORDS.get(count, "several" if count < 10 else "many")


def sights(core: SimCore, citizen: Citizen, things: list[Thing]) -> list[Sight]:
    """Things in view (nearest first) with like ones grouped: one entry per kind of unnamed structure ("three
    lean-tos") and per item on the ground (stacks added up), said where the nearest one is."""
    groups: dict[str, list[Thing]] = {}
    for thing in things:
        groups.setdefault(_group_key(core, citizen, thing), []).append(thing)
    found: list[Sight] = []
    for members in groups.values():
        nearest = members[0]
        kind = _kind(core, citizen, nearest)
        where = where_words(nearest.distance_m, nearest.bearing)
        label = nearest.label
        if nearest.kind == "ground" and nearest.item is not None:
            total = sum(core.state.ground[member.ref].count for member in members)
            label = f"{amount_words(total, ITEMS[nearest.item])} on the ground"
        if len(members) > 1 and nearest.kind == "structure":
            label = f"{_count_words(len(members))} {GROUP_NOUNS[core.world.structures[nearest.ref].kind]}"
        if any(where_words(member.distance_m, member.bearing) != where for member in members[1:]):
            where = NEAREST + where
        resource = RESOURCE_NAMES[nearest.item] if nearest.kind == "resource" and nearest.item is not None else None
        seen = Seen(
            label=label,
            where=where,
            nearness=nearness(nearest.distance_m),
            doing=nearest.state,
            kind=kind,
            resource=resource,
        )
        found.append(Sight(seen, _tier(core, nearest, kind), nearest.distance_m))
    return found


def words(seen: Seen) -> int:
    return len(phrase(seen).split())


def fit_to_budget(people: list[Seen], animals: list[Seen], found: list[Sight]) -> list[Seen]:
    """The things to tell, most important first. People and animals are always told and spend the budget first;
    every water, your home, the nearest food and shelter and every fire within a few paces are always told; the
    rest follow by importance,
    nearest first, while SIGHT_WORDS last (the first that doesn't fit ends the list)."""
    ranked = sorted(found, key=lambda sight: (sight.tier, sight.distance_m, sight.seen.label))
    must = {
        index
        for index, sight in enumerate(ranked)
        if sight.tier == TIERS["water"]
        or (sight.tier < IMPORTANT and (index == 0 or ranked[index - 1].tier != sight.tier))
        or (sight.seen.kind == "fire" and sight.distance_m < FIRE_TOLD_M)
    }
    spare = SIGHT_WORDS - sum(words(seen) for seen in [*people, *animals]) - sum(words(ranked[i].seen) for i in must)
    chosen = set(must)
    for index, sight in enumerate(ranked):
        if index in chosen:
            continue
        cost = words(sight.seen)
        if cost > spare:
            break
        chosen.add(index)
        spare -= cost
    return [sight.seen for index, sight in enumerate(ranked) if index in chosen]


if set(RESOURCE_NAMES) != set(GATHERED):
    raise ValueError("the contract's resource names must be the simulation's resources")
_LABELS = {**STRUCTURE_LABELS, **CAMP_STRUCTURE_LABELS}
_UNGROUPED = {kind for kind, label in _LABELS.items() if label.startswith("a ")} - set(GROUP_NOUNS)
if _UNGROUPED:
    raise ValueError(f"structure kinds seen in numbers need a plural: {sorted(_UNGROUPED)}")


def _doing(other: Citizen) -> str | None:
    if other.body.asleep:
        return "asleep"
    return DOING.get(other.action.kind) if other.action is not None else None
