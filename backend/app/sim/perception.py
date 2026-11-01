"""What a citizen senses, in words (03-actions-perception, "Perception"), and resolving what they refer to.

Sight: ~150 m by day, ~20 m at night (linear through twilight), ×0.4 in forest, ×1.3 on hills. No occlusion in v0.
A look around groups like things ("three lean-tos", "plenty of wood on the ground"; D64) and lists them by importance
within a word budget (D63): everyone in view, every water, your home, the nearest food, shelter and fire (and every
fire within a few paces), then the rest nearest first.

Contract v1 (10-world-v1 §6.2, D177-D179) adds, all in words: your purse, load, titles, how people on this ground
regard you and whether you are wanted; the day of the week, whose ground this is and how safe; your chest at hand;
who the people you know are to you (kin, their titles) and what you know of them (their standing with your group if
it is of note, their deeds you know); and what you noticed since your last look (`senses`). The market stall's
prices come from `market.market_view` (passed in: the market imports this module).
"""

import math
import re
from dataclasses import dataclass
from typing import Literal, cast, get_args

import numpy as np

from app.sim import fire as fires
from app.sim import nodes, ownership, senses, society, territory
from app.sim.bodies import THRESHOLDS, body_words
from app.sim.citizens import Kin, Title, store_ids
from app.sim.clock import local_minute, time_of_day
from app.sim.coins import coin_words
from app.sim.core import FOREST_BIOMES, SimCore
from app.sim.custody import custody_of
from app.sim.fauna import DANGEROUS, SPECIES
from app.sim.ground_speed import load_share
from app.sim.items import ITEMS, amount_words, tool_in
from app.sim.locomotion import load_bodies
from app.sim.node_table import GATHERED
from app.sim.state import ActionState, Animal, Body, Citizen, Region
from app.sim.vec import Vec3, bearing_deg, lat_lon_deg
from app.sim.world import CAMP_STRUCTURE_LABELS, HOME_KINDS, STRUCTURE_LABELS, WATER_BIOMES
from app.world_api.models import (
    ChestView,
    GestureKind,
    HeardWords,
    MarketView,
    Nearness,
    Perception,
    ResourceName,
    Seen,
    SelfView,
    ThingKind,
    WorkTask,
)
from app.world_api.phrases import NEAREST, join, phrase

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
FOOD_PLANTS = frozenset({"berries", "roots", "nuts", "rice", "fish"})
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
RESOURCE_NAMES: dict[str, ResourceName] = {name: name for name in get_args(ResourceName)}  # what gather() names
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
    "craft": "making something",
    "seize": "seizing someone",
    "judge": "passing judgement",
    "tend": "tending someone",
}
ANIMAL_DOING: dict[str, str] = {
    "grazing": "grazing",
    "walking": "on the move",
    "sleeping": "asleep",
    # the finer words of 10-world-v1 §4.6 (A1)
    "alert": "on the alert",
    "trotting": "on the move",
    "fleeing": "running away",
    "frozen": "keeping still",
    "prowling": "prowling",
    "stalking": "stalking",
    "chasing": "giving chase",
    "pouncing": "pouncing",
    "attacking": "attacking",
    "feeding": "feeding",
    "drinking": "drinking",
    "floating": "floating",
    "swimming": "swimming",
}
RESOURCE_KEYWORDS: dict[str, frozenset[str]] = {  # the words that name a node by what it yields
    "berries": frozenset({"berries", "berry", "bush", "bushes"}),
    "roots": frozenset({"roots", "root"}),
    "nuts": frozenset({"nuts", "nut", "oak", "oaks"}),
    "reeds": frozenset({"reeds", "reed"}),
    "wood": frozenset({"wood", "branches", "deadwood", "firewood"}),
    "rice": frozenset({"rice", "paddy", "paddies"}),
    "fish": frozenset({"fish", "fishing"}),
    "flint": frozenset({"flint", "seam"}),
    "obsidian": frozenset({"obsidian", "glass", "shards"}),
    "iron sand": frozenset({"iron", "sand"}),
    "gold": frozenset({"gold", "pool"}),
}
TREE_KEYWORDS = frozenset({"tree", "trees", "timber"})
STRUCTURE_KEYWORDS: dict[str, frozenset[str]] = {
    "well": frozenset({"well", "water"}),
    "storehouse": frozenset({"storehouse", "store"}),
    "townhouse": frozenset({"house"}),
    "farmhouse": frozenset({"farmhouse", "house"}),
    "castle_gatehouse": frozenset({"gate", "gatehouse"}),
    "castle_keep": frozenset({"keep", "castle"}),
    "temple_hall": frozenset({"temple", "hall"}),
    "lean_to": frozenset({"lean-to", "shelter"}),
    "fire_pit": frozenset({"fire", "pit", "firepit"}),
}
DAY_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
GROUP_WORDS: dict[Region, str] = {"town": "the castle town", "band_a": "band A", "band_b": "band B"}
WANTED_BY: dict[Region, str] = {"town": "in the castle town", "band_a": "by band A", "band_b": "by band B"}
# how the people whose ground you stand on regard you, by your standing word with them (laws.yaml); unsaid: nothing
STANDING_SAID: dict[str, str | None] = {
    "honoured": "People here honour you.",
    "well regarded": "People here regard you well.",
    "nothing said": None,
    "distrusted": "People here distrust you.",
    "outcast": "People here shun you as an outcast.",
}
# someone's standing with your group as `regard` tells it: only when it is of note (most of a group stand well with
# it, and strangers have nothing said of them)
REGARD_SAID: dict[str, str] = {"honoured": "honoured", "distrusted": "distrusted", "outcast": "an outcast"}
KIN_WORDS: dict[Kin, str] = {
    "mate": "your mate",
    "parent": "your parent",
    "child": "your child",
    "sibling": "your sibling",
    "grandparent": "your grandparent",
    "grandchild": "your grandchild",
    "parent's sibling": "your parent's sibling",
    "sibling's child": "your sibling's child",
}
TOLD_DEEDS = 2  # the latest deeds of someone that their regard tells
# a gesture as a seer says it: alone, and made to someone (laughing and jumping aren't aimed)
GESTURE_SAID: dict[GestureKind, tuple[str, str]] = {
    "wave": ("waves", "waves to"),
    "bow": ("bows", "bows to"),
    "nod": ("nods", "nods to"),
    "shake_head": ("shakes their head", "shakes their head at"),
    "point": ("points", "points at"),
    "laugh": ("laughs", ""),
    "jump": ("jumps", ""),
}
RUNNING_GAITS = frozenset({"run", "jog"})
WORK_SEEN: dict[WorkTask, str] = {  # someone seen at work, briefly (they say it in full of themselves: "keeping watch")
    "farm": "farming",
    "store food": "storing food",
    "guard": "guarding",
    "trade": "trading",
    "weave": "weaving",
    "govern": "holding court",
    "ring bell": "ringing the bell",
    "pray": "praying",
}
QUARRY_DOING: dict[str, str] = {"stalking": "stalking", "chasing": "chasing"}  # said with whom they are after
COINS = "coins"  # carried as the purse


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
    kind: Literal["structure", "ground", "node", "water", "fire"]
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


NODE_LINE_M = 50.0  # like nodes this close to the nearest one are told with it ("three berry bushes ...")


def node_things(core: SimCore, citizen: Citizen, sight: float) -> list[Thing]:
    """For each thing a node yields, the nearest node in view with some left, told with the like ones (same kind and
    stage) near it as one line (10 §6.2); standing trees only to someone carrying an axe (they fell them for wood)."""
    table = core.world.nodes
    axe = tool_in(citizen.inventory, "axe") is not None
    nearest: dict[str, tuple[float, int]] = {}
    stocked: list[tuple[float, int]] = []
    for metres, node in table.near(core.world.grid, citizen.position, sight):
        kind_name = table.kinds[node]
        if (kind_name == nodes.TREE_KIND and not axe) or nodes.stock(core, node) == 0:
            continue
        stocked.append((metres, node))
        key = f"{table.kind(node).item}:{kind_name}" if kind_name == nodes.TREE_KIND else table.kind(node).item
        nearest.setdefault(key, (metres, node))
    things: list[Thing] = []
    for metres, node in nearest.values():
        kind_name, stage = table.kinds[node], nodes.stage(core, node)
        like = sum(
            1
            for _, other in stocked
            if table.kinds[other] == kind_name
            and nodes.stage(core, other) == stage
            and core.distance_m(table.unit(other), table.unit(node)) <= NODE_LINE_M
        )
        item = table.kind(node).item
        unit = table.unit(node)
        keywords = RESOURCE_KEYWORDS[item] | (TREE_KEYWORDS if kind_name == nodes.TREE_KIND else frozenset())
        label = nodes.words(core, node, like)
        things.append(
            Thing(
                label, keywords, unit, metres, bearing_deg(citizen.position, unit), "node", table.ids[node], item=item
            )
        )
    return things


def things_in_view(core: SimCore, citizen: Citizen) -> list[Thing]:
    world, state = core.world, core.state
    position = citizen.position
    sight = core.sight_range(citizen)
    things: list[Thing] = []

    def add(
        label: str,
        keywords: frozenset[str],
        goal: Vec3,
        kind: Literal["structure", "ground", "node", "water", "fire"],
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
    things.extend(node_things(core, citizen, sight))
    here = citizen.cell
    found_water: set[str] = set()
    # a lake or the sea next to your cell is right beside you: you can drink from it there (`water_within_reach`)
    beside = {_water_kind(world.biome(other)) for other in world.neighbours[here] if world.biome(other) in WATER}
    # in the town chart the well is the only water (D73): rivers are told only where `water_within_reach` drinks them
    river_here = bool(world.river[here]) and world.town_point(position) is None
    for cell in [here, *[int(c) for c in cells if c != here]]:
        unit = world.unit(cell)
        biome = world.biome(cell)
        river = river_here if cell == here else bool(world.river[cell] and not world.in_town[cell])
        if river and "river" not in found_water:
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


def animal_doing(core: SimCore, citizen: Citizen, animal: Animal, distance_m: float) -> str | None:
    """What an animal is seen doing: coming at you or watching you (a predator near), else its activity, naming its
    quarry ("stalking a deer", "chasing Kenji", "feeding on remains")."""
    if animal.target == citizen.id:
        return "coming at you"
    if animal.kind in DANGEROUS and animal.activity not in ("sleeping", "dead") and distance_m <= WATCHING_M:
        return "watching you"
    doing = ANIMAL_DOING.get(animal.activity)
    quarry = core.state.animals.get(animal.target or "")
    if quarry is not None and not quarry.alive:
        return "feeding on remains" if animal.activity == "feeding" else doing
    prey = SPECIES[quarry.kind].one if quarry is not None else None
    if animal.target in core.state.citizens:
        prey = person_label(citizen, core.state.citizens[animal.target])
    verb = QUARRY_DOING.get(animal.activity)
    return f"{verb} {prey}" if verb is not None and prey is not None else doing


def from_where(core: SimCore, citizen: Citizen, distance_m: float, bearing: float) -> str:
    where = where_words(distance_m, bearing)
    return f"from the trees, {where}" if core.world.biome(citizen.cell) in FOREST_BIOMES else where


def seen_animals(core: SimCore, citizen: Citizen, sightings: list[tuple[Animal, float]]) -> list[Seen]:
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
        doing = animal_doing(core, citizen, nearest, distance)
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
    return f"You are {action_words(action)}."


def action_words(action: ActionState) -> str:
    """What someone is doing ("tending the rice paddies", "chopping a tree", "sitting" on a seat)."""
    if action.kind in ("work", "craft") and action.label:  # "keeping watch", "making a flint spear"
        return action.label
    if action.kind == "gather":
        return "chopping a tree" if action.args.get("node_kind") == nodes.TREE_KIND else f"gathering {action.label}"
    if action.kind == "rest" and action.args.get("posture") == "sitting":
        return "sitting"
    return DOING.get(action.kind, "busy")


def title_words(title: Title, group: Region, yours: bool) -> str:
    """A title as said of its holder of `group`: to their own people ("your lord", "your leader") or anyone else."""
    if title == "lord":
        return "your lord" if yours else "the lord of the castle town"
    if title == "leader":
        return "your leader" if yours else f"the leader of {GROUP_WORDS[group]}"
    rank = "samurai" if title == "samurai" else "foot soldier"
    return f"your lord's {rank}" if yours else f"a {rank} of the castle town"


def load_words(core: SimCore, citizen: Citizen) -> str | None:
    """How laden someone is, by the load bands that slow them (bodies.yaml): None when they go unhindered."""
    share = load_share(core, citizen)
    bands = [band for band in load_bodies().load if share >= band.share]
    if not bands:
        return None
    heavy = any(band.no_run for band in bands)
    return "carrying a heavy load, too heavy to run" if heavy else "carrying a load that slows you"


def standing_words(core: SimCore, citizen: Citizen) -> str | None:
    """How the group whose ground the citizen stands on regards them, if anything is said of them."""
    claim = territory.claim_at(core.world, citizen.position)
    if claim is None:
        return None
    return STANDING_SAID[society.standing_word(society.standing(core, citizen.id, claim.owner))]


def wanted_words(core: SimCore, citizen: Citizen) -> str | None:
    """ "You are wanted in the castle town for theft." (each group that wants them, for what)."""
    wanted: dict[Region, list[str]] = {}
    for deed in society.wanted_for(core, citizen.id):
        kinds = wanted.setdefault(deed.group, [])
        if deed.kind not in kinds:
            kinds.append(deed.kind)
    if not wanted:
        return None
    return "You are wanted " + " and ".join(f"{WANTED_BY[g]} for {join(kinds)}" for g, kinds in wanted.items()) + "."


def self_view(core: SimCore, citizen: Citizen) -> SelfView:
    """How the citizen is: body, what they carry (coins as their purse), what they do, how laden, their titles, how
    people here regard them and whether they are wanted."""
    inventory = citizen.inventory
    goods = sorted((item, count) for item, count in inventory.items() if count > 0 and item != COINS)
    coins = inventory.get(COINS, 0)
    return SelfView(
        feeling=body_words(citizen.body),
        carrying=[amount_words(count, ITEMS[item]) for item, count in goods],
        doing=doing_words(citizen.action, citizen.body.asleep),
        purse=coin_words(coins) if coins > 0 else None,
        load=load_words(core, citizen),
        titles=[title_words(title, citizen.region, yours=False) for title in society.titles(core, citizen.id)],
        standing=standing_words(core, citizen),
        wanted=wanted_words(core, citizen),
        held=held_words(core, citizen),
        confined=confined_words(core, citizen),
    )


def held_words(core: SimCore, citizen: Citizen) -> str | None:
    """ "Goro holds you fast." while someone holds them (`custody`)."""
    custody = custody_of(core, citizen.id)
    if custody is None or custody.keeper is None:
        return None
    keeper = person_label(citizen, core.state.citizens[custody.keeper])
    return f"{keeper[:1].upper()}{keeper[1:]} holds you fast."


def confined_words(core: SimCore, citizen: Citizen) -> str | None:
    """ "You are confined in the gaol." / "You are tied at the fire." once confined (`custody`)."""
    custody = custody_of(core, citizen.id)
    if custody is None or custody.keeper is not None:
        return None
    return "You are confined in the gaol." if custody.place == "gaol" else "You are tied at the fire."


def day_words(tick: int) -> str:
    """ "the first day of the week, market day"."""
    week, day = society.load_laws().week, society.day_of_week(tick)
    named = {week.market_day: "market day", week.court_day: "court day"}.get(day)
    return f"the {DAY_WORDS[day - 1]} day of the week" + (f", {named}" if named else "")


def chest_view(core: SimCore, citizen: Citizen) -> ChestView | None:
    """What the household chest holds, when it is within reach of the citizen."""
    if citizen.home is None or f"{citizen.home}{ownership.CHEST}" not in store_ids():
        return None
    chest = f"{citizen.home}{ownership.CHEST}"
    if core.distance_m(citizen.position, ownership.reach_point(core, chest)) > ownership.REACH_M:
        return None
    stock = core.state.stores.get(chest, {})
    return ChestView(holds=[amount_words(count, ITEMS[item]) for item, count in sorted(stock.items()) if count > 0])


def perceive(core: SimCore, citizen: Citizen, market: MarketView | None = None) -> Perception:
    """Everything the citizen senses now (`market`: the stall at hand's prices, `market.market_view`); heard speech
    and what they noticed are told once."""
    you = self_view(core, citizen)
    _, lon = lat_lon_deg(citizen.position)
    when, time = time_of_day(local_minute(core.state.tick, core.world.town_lon_deg, lon))
    day = day_words(core.state.tick)
    if citizen.body.asleep:
        return Perception(
            you=you,
            place="asleep",
            time=time,
            time_of_day=when,
            people=[],
            animals=[],
            things=[],
            heard=[],
            day_of_week=day,
        )
    people = [
        Seen(
            label=person_label(citizen, other)
            if other.body.alive
            else f"the still body of {person_label(citizen, other)}",
            where=where_words(distance, bearing_deg(citizen.position, other.position)),
            nearness=nearness(distance),
            doing=person_doing(core, citizen, other) if other.body.alive else None,
            relation=relation_words(core, citizen, other),
            regard=regard_words(core, citizen, other) if other.body.alive else None,
        )
        for other, distance in visible_people(core, citizen)
    ]
    animals = seen_animals(core, citizen, visible_animals(core, citizen))
    things = fit_to_budget(people, animals, sights(core, citizen, things_in_view(core, citizen)))
    heard = [HeardWords(who=entry.who, words=entry.words, volume=entry.volume) for entry in citizen.heard]
    citizen.heard.clear()
    chest = chest_view(core, citizen)
    noticed = [notice_words(core, citizen, notice) for notice in senses.take(core, citizen.id)]
    if chest is not None:
        noticed.append(ownership.notice(core, citizen, f"{citizen.home}{ownership.CHEST}").strip())
    return Perception(
        you=you,
        place=place_words(core, citizen),
        time=time,
        time_of_day=when,
        people=people,
        animals=animals,
        things=things,
        heard=heard,
        day_of_week=day,
        ground=territory.ground_words(core, citizen),
        safety=territory.safety(core, citizen),
        market=market,
        chest=chest,
        noticed=list(dict.fromkeys(words for words in noticed if words)),
    )


def person_doing(core: SimCore, observer: Citizen, other: Citizen) -> str | None:
    """What someone is seen doing by the observer ("running", "carrying a load", "farming", "held by Kenji", "confined
    in the gaol") and how they look if it shows ("looking hurt")."""
    if other.body.asleep:
        return "asleep"
    action, doing = other.action, None
    custody = custody_of(core, other.id)
    if custody is not None and custody.keeper is not None:
        doing = f"held by {person_label(observer, core.state.citizens[custody.keeper])}"
    elif custody is not None:
        doing = "confined in the gaol" if custody.place == "gaol" else "tied at the fire"
    elif action is not None and action.kind in ("walk_to", "follow", "flee"):
        stride = core.strides.get(other.id)
        if action.kind == "flee" or (stride is not None and stride.gait in RUNNING_GAITS):
            doing = "running"
        else:
            doing = "carrying a load" if load_words(core, other) else "walking"
    elif action is not None and action.kind == "work":
        doing = WORK_SEEN.get(cast(WorkTask, action.args.get("task")), DOING["work"])
    elif action is not None:
        doing = action_words(action)
    looks = looks_words(other.body)
    return ", ".join(words for words in (doing, looks) if words) or None


def looks_words(body: Body) -> str | None:
    """What anyone sees of a body's plight: badly hurt, else starving."""
    if body.health <= THRESHOLDS["health"][1]:
        return "looking near death"
    if body.health <= THRESHOLDS["health"][0]:
        return "looking hurt"
    if body.hunger >= THRESHOLDS["hunger"][1]:
        return "looking starved"
    return None


def relation_words(core: SimCore, observer: Citizen, other: Citizen) -> str | None:
    """Who someone the observer knows is to them: kin ("your mate"), then titles ("your lord", "the leader of band
    A"); None for strangers and people with neither."""
    if other.id not in observer.people:
        return None
    members = society.SOCIETY.of(core.state).members
    mine, theirs = members[observer.id], members[other.id]
    kin = mine.family.get(other.id)
    parts = [KIN_WORDS[kin]] if kin is not None else []
    parts += [title_words(title, theirs.group, yours=theirs.group == mine.group) for title in theirs.titles]
    return ", ".join(parts) or None


def regard_words(core: SimCore, observer: Citizen, other: Citizen) -> str | None:
    """What the observer holds of someone: their standing with the observer's group when it is of note ("honoured",
    "distrusted"), and the latest deeds of theirs against the observer's group the observer knows ("who stole rice
    from the rack"); a wrong done to another group is none of theirs (a band's own poaching elsewhere)."""
    parts = []
    if other.id in observer.people:
        word = society.standing_word(society.standing(core, other.id, observer.region))
        parts += [REGARD_SAID[word]] if word in REGARD_SAID else []
    known = society.known_deeds(core, observer.id)
    deeds = [deed_words(core, observer, d) for d in known if d.doer == other.id and d.group == observer.region]
    told = list(dict.fromkeys(reversed(deeds)))[:TOLD_DEEDS]
    parts += ["who " + join(told[::-1])] if told else []
    return ", ".join(parts) or None


def deed_words(core: SimCore, observer: Citizen, deed: society.Deed) -> str:
    """A deed as the observer knows it ("stole rice from your chest", "took meat from the Lord's woods", "was in the
    castle at night", "struck you"). Deeds logged before deeds kept their goods and place are said without them."""
    goods = f"{ITEMS[deed.item].name} " if deed.item is not None else ""
    if deed.kind == "theft":
        store = ownership.store_words(str(deed.store))
        if deed.owner in (observer.home, observer.region):
            store = store.replace("the ", "your ", 1)
        return f"stole {goods}from {store}"
    if deed.kind == "poaching":
        return f"took {goods or 'game '}from {deed.place or 'their ground'}"
    if deed.kind == "trespass":
        return f"was in {deed.place or 'the walls'} at night"
    victim = core.state.citizens[str(deed.victim)]
    whom = "you" if victim.id == observer.id else person_label(observer, victim)
    return f"{'struck' if deed.kind == 'assault' else 'killed'} {whom}"


def notice_words(core: SimCore, citizen: Citizen, notice: senses.Notice) -> str:
    """ "Kenji bows to you.", "The temple bell rings.", "Some of your berries spoiled.", "Your pack wore out."."""
    if notice.kind == "bell":
        return "The temple bell rings."
    if notice.kind == "spoiled":
        return f"Some of your {join([ITEMS[item].name for item in notice.items])} spoiled."
    if notice.kind == "worn":
        return f"Your {ITEMS[notice.items[0]].name} wore out."
    if notice.gesture is None or notice.who is None:
        raise ValueError(f"a gesture noticed needs who made it and how: {notice}")
    who = person_label(citizen, core.state.citizens[notice.who])
    alone, aimed = GESTURE_SAID[notice.gesture]
    if notice.to is None or not aimed:
        return f"{who[0].upper()}{who[1:]} {alone}."
    whom = "you" if notice.to == citizen.id else person_label(citizen, core.state.citizens[notice.to])
    return f"{who[0].upper()}{who[1:]} {aimed} {whom}."


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
    return thing.ref  # each yield of the nodes and each kind of water is already only its nearest


def _kind(core: SimCore, citizen: Citizen, thing: Thing) -> ThingKind:
    if thing.water is not None:
        return "water" if thing.water == "fresh" else "sea"
    if thing.kind == "node":
        return "node"
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
    if thing.kind == "node":  # a node that feeds you is told like food, the rest like materials
        return TIERS["food"] if thing.item in FOOD_PLANTS else TIERS["material"]
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
        resource = RESOURCE_NAMES.get(str(nearest.item)) if nearest.kind == "node" else None
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
    """Words an entry takes, with what is known of a person ("Genzo, your mate, well regarded, ...")."""
    known = [part for part in (seen.relation, seen.regard) if part]
    return len(phrase(", ".join([seen.label, *known]), seen.where, seen.doing).split())


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


if set(RESOURCE_NAMES) != GATHERED:
    raise ValueError("the contract's resource names must be what nodes yield to gather()")
if set(RESOURCE_KEYWORDS) != GATHERED | {"fish"}:
    raise ValueError("every node yield needs the words that name it")
_LABELS = {**STRUCTURE_LABELS, **CAMP_STRUCTURE_LABELS}
_UNGROUPED = {kind for kind, label in _LABELS.items() if label.startswith("a ")} - set(GROUP_NOUNS)
if _UNGROUPED:
    raise ValueError(f"structure kinds seen in numbers need a plural: {sorted(_UNGROUPED)}")
