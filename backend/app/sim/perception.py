"""What a citizen senses, in words (03-actions-perception, "Perception"), and resolving what they refer to.

Sight: ~150 m by day, ~20 m at night (linear through twilight), ×0.4 in forest, ×1.3 on hills. No occlusion in v0.
"""

import math
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.sim import fire as fires
from app.sim.bodies import body_words
from app.sim.clock import local_minute, time_words
from app.sim.core import FOREST_BIOMES, SimCore
from app.sim.fauna import DANGEROUS, SPECIES
from app.sim.items import GATHERED, ITEMS, RESOURCE_INDEX, amount_words
from app.sim.state import ActionState, Animal, Citizen, GroundStack
from app.sim.vec import Vec3, bearing_deg, lat_lon_deg
from app.world_api.models import HeardWords, Perception, Seen, SelfView

COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
MAX_THINGS = 12
MAX_ANIMALS = 8
HEAP_M = 5.0  # stacks of one item this close to the nearest one are one heap to the eye
WATCHING_M = 60.0  # an awake predator this close is "watching you"
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


def where_words(distance_m: float, bearing: float) -> str:
    if distance_m < 3:
        return "right beside you"
    if distance_m < 15:
        near = "a few paces"
    elif distance_m < 50:
        near = "close by"
    elif distance_m < 150:
        near = "some way off"
    elif distance_m < 500:
        near = "in the distance"
    else:
        near = "far away"
    return f"{near} to the {compass(bearing)}"


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
    ) -> None:  # noqa: E501
        target = goal if at is None else at
        distance = core.distance_m(position, target)
        things.append(Thing(label, keywords, goal, distance, bearing_deg(position, target), kind, ref, water))

    # everyone of a band has their own seat round its fire
    seat = [other.id for other in core.citizens() if other.region == citizen.region].index(citizen.id)
    nearest_of: dict[str, tuple[float, str]] = {}
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
        elif structure.label.startswith("the "):  # named ones (the well, the main gate) are listed one by one
            water: Literal["fresh"] | None = "fresh" if structure.kind == "well" else None
            add(
                structure.label,
                STRUCTURE_KEYWORDS[structure.kind],
                structure.spot(seat),
                "structure",
                structure.id,
                water,
                structure.centre,
            )
        elif (distance, structure.id) < nearest_of.get(structure.kind, (math.inf, "")):
            nearest_of[structure.kind] = (distance, structure.id)
    for kind, (_, structure_id) in sorted(nearest_of.items()):
        structure = world.structures[structure_id]
        add(
            structure.label,
            STRUCTURE_KEYWORDS[kind],
            structure.spot(seat),
            "structure",
            structure.id,
            at=structure.centre,
        )

    for fire in sorted(state.fires.values(), key=lambda f: f.id):
        if fire.kind == "pit" and not fire.lit:
            continue  # a cold fire pit is just the fire pit
        if core.distance_m(position, fire.position) <= sight:
            hearth = world.hearths.get(fire.id)
            goal = hearth.stand if hearth is not None else fire.position
            add(fires.label(fire), fires.KEYWORDS, goal, "fire", fire.id, at=fire.position)

    # stacks of one item lying together (a woodpile of many drops) are seen as one heap, at its nearest stack
    heaps: list[tuple[GroundStack, int]] = []
    seen_stacks = sorted(
        (core.distance_m(position, stack.position), stack.id, stack)
        for stack in state.ground.values()
        if core.distance_m(position, stack.position) <= sight
    )
    for _, _, stack in seen_stacks:
        heap = next(
            (i for i, (first, _) in enumerate(heaps)
             if first.item == stack.item and core.distance_m(first.position, stack.position) <= HEAP_M),
            None,
        )  # fmt: skip
        if heap is None:
            heaps.append((stack, stack.count))
        else:
            heaps[heap] = (heaps[heap][0], heaps[heap][1] + stack.count)
    for stack, count in heaps:
        item = ITEMS[stack.item]
        keywords = frozenset({item.name, item.one.split()[-1]})
        add(f"{amount_words(count, item)} on the ground", keywords, stack.position, "ground", stack.id)

    cos_limit = math.cos(min(math.pi, (sight + _CELL_MARGIN_M) / world.radius_m))
    cells = np.flatnonzero(world.grid.positions @ np.array(position) >= cos_limit)
    cells = cells[np.argsort(world.grid.positions[cells] @ np.array(position))[::-1]]  # nearest first
    here = citizen.cell
    resources = state.resources
    found_resource: set[str] = set()
    found_water: set[str] = set()
    for cell in [here, *[int(c) for c in cells if c != here]]:
        unit = world.unit(cell)
        biome = world.biome(cell)
        for resource, column in RESOURCE_INDEX.items():
            if resource not in GATHERED:
                continue  # fish are seen as shoals (animals), caught with fish()
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
        if biome in ("lake", "shallow_ocean", "deep_ocean"):
            water_kind = "lake" if biome == "lake" else "sea"
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
                    at=unit,
                )
            else:
                add(
                    "the sea",
                    frozenset({"sea", "ocean", "water"}),
                    world.unit(shore),
                    "water",
                    f"sea:{cell}",
                    "salt",
                    at=unit,
                )
    things.sort(key=lambda thing: (thing.distance_m, thing.ref))
    return things


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
    return min(matches, key=lambda thing: (thing.distance_m, thing.ref)) if matches else None


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
            remains.append(Seen(label=f"the remains of {SPECIES[animal.kind].one}", where=where))
    seen: list[tuple[float, Seen]] = []
    for members in groups.values():
        nearest, distance = members[0]
        species = SPECIES[nearest.kind]
        where = where_words(distance, bearing_deg(citizen.position, nearest.position))
        label = species.count_words(len(members))
        seen.append((distance, Seen(label=label, where=where, doing=animal_doing(citizen, nearest, distance))))
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
    time = time_words(local_minute(core.state.tick, core.world.town_lon_deg, lon))
    if citizen.body.asleep:
        return Perception(you=you, place="asleep", time=time, people=[], animals=[], things=[], heard=[])
    people = [
        Seen(
            label=person_label(citizen, other)
            if other.body.alive
            else f"the still body of {person_label(citizen, other)}",
            where=where_words(distance, bearing_deg(citizen.position, other.position)),
            doing=_doing(other) if other.body.alive else None,
        )
        for other, distance in visible_people(core, citizen)
    ]
    things = [
        Seen(label=thing.label, where=where_words(thing.distance_m, thing.bearing))
        for thing in things_in_view(core, citizen)
    ]
    heard = [HeardWords(who=entry.who, words=entry.words, volume=entry.volume) for entry in citizen.heard]
    citizen.heard.clear()
    return Perception(
        you=you,
        place=place_words(core, citizen),
        time=time,
        people=people,
        animals=seen_animals(citizen, visible_animals(core, citizen)),
        things=things[:MAX_THINGS],
        heard=heard,
    )


def _doing(other: Citizen) -> str | None:
    if other.body.asleep:
        return "asleep"
    return DOING.get(other.action.kind) if other.action is not None else None
