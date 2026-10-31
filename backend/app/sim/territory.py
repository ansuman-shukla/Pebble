"""Territory (10-world-v1 §1.5, 1.6, 3.3): whose ground each spot is, the law of the walls at night, poaching, how
safe a spot is, and the dens people learned to fear.

- **Grounds.** Each group owns its home ground: the town its chart and HOME_GROUND_M around it, each band
  HOME_GROUND_M around its camp. A claimed hotspot (the Lord's woods: the town; the Eastern wall scar: band A; B wood:
  band B) is its claimant's too, and is said before any home ground it overlaps.
- **Trespass** (`trespassed`, every one emitted here): while the town's night law holds (`society.night_law`, the
  dusk bell to the dawn bell), an outsider (group ≠ town) inside the walls (the town chart) is a `walls` deed and
  anyone but the lord, samurai and ashigaru inside the castle walls a `castle` deed, once per entry: again only after
  they left, or on a later night.
- **Poaching** (`trespassed {kind: ground, took}`): taking from the wild (a node, a fishing water, a hunted animal:
  any `item_moved` from a `resource` or an `animal` into the taker's hands) on another group's ground, or hunting in
  the Lord's woods without the lord's or a samurai's title. One deed per take (a hunt's meat and hide are one take).
  Learned from the events as they are emitted, so no action calls in here.
- **Safety** (`you.safety`): inside the walls, by a lit fire, in company (two others close), on home ground, else
  exposed; the first three are where predators don't attack (D68, `animals.exposed`).
- **Dens.** Someone a predator charges at its den learns that den and keeps DEN_KEEP_AWAY_M from it after (brains
  read `known_dens`).

The system `territory` keeps who is inside the walls or the castle with their entry already told, the last take
told, and the dens each citizen knows.
"""

import math
from dataclasses import dataclass, field
from functools import cache
from typing import Literal, cast

from pydantic import JsonValue, TypeAdapter

from app.observability.events import EventDraft, Injured, ItemMoved, Took, Trespassed
from app.sim import society
from app.sim.animals import GROUP_M, GROUP_SAFE, WILDLIFE
from app.sim.citizens import Title
from app.sim.core import SimCore
from app.sim.fauna import SPECIES, pin_of, world_cache
from app.sim.fire import SAFE_M, near_lit_fire
from app.sim.state import Citizen, Region, System
from app.sim.vec import Vec3
from app.sim.world import SimWorld
from app.world.town import load_town
from app.world.view import Feature
from app.world_api.models import Safety

HOME_GROUND_M = 400.0  # a group's home ground reaches this far round its camp (the town: round its chart)
DEN_KEEP_AWAY_M = 60.0  # someone who knows a den keeps this far from it
CAMPS: dict[str, Region] = {"band_a_camp": "band_a", "band_b_camp": "band_b"}
GROUND_WORDS: dict[Region, str] = {
    "town": "the castle town's ground",
    "band_a": "band A's ground",
    "band_b": "band B's ground",
}
TOWN_WORDS = "the castle town"  # inside its walls
CASTLE_WORDS = "the castle"
CASTLE_AREA = "castle-courtyard"  # the town area inside the castle walls
CASTLE_TITLES: frozenset[Title] = frozenset({"lord", "samurai", "ashigaru"})  # at home in the castle at night
RESERVED_HUNTS: dict[str, frozenset[Title]] = {"lords_woods": frozenset({"lord", "samurai"})}  # hotspot -> who hunts
WILD_SOURCES = frozenset({"resource", "animal"})  # where a take from the wild comes from
NightKind = Literal["walls", "castle"]


@dataclass(frozen=True)
class Claim:
    """Whose ground a spot is."""

    owner: Region
    place: str  # in words: "the Lord's woods", "band A's ground", "the castle town"
    hotspot: str | None = None  # the claimed hotspot's id; None on a home ground


@dataclass
class Territory:
    inside: dict[str, list[NightKind]] = field(default_factory=dict)  # citizen -> walls/castle, entry already told
    last_take: int | None = None  # cause seq of the last take told as poaching (one deed per take)
    dens: dict[str, list[str]] = field(default_factory=dict)  # citizen -> den feature ids they know (sorted)


_BLOCK = TypeAdapter(Territory)


def _dump(territory: Territory) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(territory, mode="json"))


def _load(data: JsonValue) -> Territory:
    return _BLOCK.validate_python(data)


TERRITORY = System[Territory]("territory", 1, new=lambda _world: Territory(), dump=_dump, load=_load)


# --- grounds ---


def claim_at(world: SimWorld, unit: Vec3) -> Claim | None:
    """Whose ground this spot is: a claimed hotspot's claimant, else the group whose home ground it lies on."""
    for hotspot in world.hotspots:
        if hotspot.claim is not None and world.distance_m(unit, hotspot.centre) <= hotspot.radius_m:
            return Claim(hotspot.claim, hotspot.called, hotspot.id)
    if world.town_point(unit) is not None:
        return Claim("town", TOWN_WORDS)
    if _from_town_chart_m(world, unit) <= HOME_GROUND_M:
        return Claim("town", GROUND_WORDS["town"])
    for site, group in CAMPS.items():
        if world.distance_m(unit, world.places[site].centre) <= HOME_GROUND_M:
            return Claim(group, GROUND_WORDS[group])
    return None


def _from_town_chart_m(world: SimWorld, unit: Vec3) -> float:
    """How far a spot outside the town chart lies from its edge (the chart's local metres; 0 inside)."""
    x, z = world.town.to_local(unit)
    if not math.isfinite(x):
        return math.inf
    extent = world.town.extent
    dx = max(extent.min_x - x, 0.0, x - extent.max_x)
    dz = max(extent.min_z - z, 0.0, z - extent.max_z)
    return math.hypot(dx, dz)


def ground_words(core: SimCore, citizen: Citizen) -> str | None:
    """Whose ground or which way this is (`Perception.ground`): "the Lord's woods", "band A's ground", "the road
    from the castle town to the Falls pool, on the castle town's ground", an unclaimed hotspot ("the Elder grove");
    None out in the wild off every road."""
    world = core.world
    claim = claim_at(world, citizen.position)
    road = _road_names(world).get(citizen.cell) if world.town_point(citizen.position) is None else None
    if road is not None and claim is not None:
        return f"{road}, {'in' if claim.hotspot else 'on'} {claim.place}"
    if road is not None or claim is not None:
        return road or (claim.place if claim is not None else None)
    hotspot = next((h for h in world.hotspots if world.distance_m(citizen.position, h.centre) <= h.radius_m), None)
    return hotspot.called if hotspot is not None else None


def _road_names(world: SimWorld) -> dict[int, str]:
    """Cell -> the name of the road (else path) through it; the first listed wins where several cross."""
    cache = world_cache(world)
    found: dict[int, str] | None = cache.get("road names")
    if found is not None:
        return found
    names: dict[int, str] = {}
    for kind in ("road", "path"):
        for road in world.roads:
            if road.kind == kind:
                for cell in road.cells:
                    names.setdefault(cell, road.name)
    cache["road names"] = names
    return names


def safety(core: SimCore, citizen: Citizen) -> Safety:
    """How safe the citizen is where they stand (`you.safety`, 10 §1.6): the first that holds of inside the walls, by
    a lit fire, in company, on home ground (their own group's, claimed hotspots too), else exposed."""
    position = citizen.position
    if core.world.town_point(position) is not None:
        return "inside the walls"
    if near_lit_fire(core, position, SAFE_M):
        return "by the fire"
    others = sum(
        1 for other in core.living() if other.id != citizen.id and core.distance_m(other.position, position) <= GROUP_M
    )
    if others >= GROUP_SAFE - 1:
        return "in company"
    claim = claim_at(core.world, position)
    if claim is not None and claim.owner == citizen.region:
        return "on home ground"
    return "exposed"


# --- the night law: walls and castle ---


def keep_the_law(core: SimCore) -> None:
    """Every-tick hook (after the night law is set): one `trespassed` for each entry into the walls or the castle
    while the law holds."""
    territory = TERRITORY.of(core.state)
    if not society.night_law(core):
        territory.inside.clear()
        return
    inside: dict[str, list[NightKind]] = {}
    for citizen in core.living():
        kinds = _breaking(core, citizen)
        told = territory.inside.get(citizen.id, [])
        for kind in kinds:
            if kind not in told:
                _trespassed(core, citizen, kind, "town", CASTLE_WORDS if kind == "castle" else TOWN_WORDS)
        if kinds:
            inside[citizen.id] = kinds
    territory.inside = inside


def _breaking(core: SimCore, citizen: Citizen) -> list[NightKind]:
    point = core.world.town_point(citizen.position)
    if point is None:
        return []
    kinds: list[NightKind] = ["walls"] if citizen.region != "town" else []
    if _in_castle(*point) and not CASTLE_TITLES & set(society.titles(core, citizen.id)):
        kinds.append("castle")
    return kinds


def _in_castle(x: float, z: float) -> bool:
    x0, z0, x1, z1 = _castle_rect()
    return x0 <= x <= x1 and z0 <= z <= z1


@cache
def _castle_rect() -> tuple[float, float, float, float]:
    area = next(area for area in load_town().areas if area.id == CASTLE_AREA)
    xs, zs = [x for x, _ in area.polygon], [z for _, z in area.polygon]
    return (min(xs), min(zs), max(xs), max(zs))


def _trespassed(
    core: SimCore,
    citizen: Citizen,
    kind: Literal["walls", "castle", "ground"],
    owner: Region,
    place: str,
    took: Took | None = None,
    cause_seq: int | None = None,
) -> int:
    payload = Trespassed(kind=kind, owner=owner, place=place, took=took, witnesses=society.witnesses(core, citizen.id))
    return core.emit("trespassed", payload, actor=citizen, cause_seq=cause_seq)


# --- poaching ---


def poached(core: SimCore, citizen: Citizen, unit: Vec3, hunting: bool) -> Claim | None:
    """The ground a take from the wild here wrongs, if any: another group's, or the Lord's woods for a hunter
    without the title."""
    claim = claim_at(core.world, unit)
    if claim is None:
        return None
    if claim.owner != citizen.region:
        return claim
    allowed = RESERVED_HUNTS.get(claim.hotspot or "")
    if hunting and allowed is not None and not allowed & set(society.titles(core, citizen.id)):
        return claim
    return None


def on_event(core: SimCore, event: EventDraft) -> None:
    """Event hook: a take from the wild may be poaching; a predator's charge at its den teaches the one it charged."""
    if isinstance(event.payload, ItemMoved):
        _took(core, event, event.payload)
    elif isinstance(event.payload, Injured):
        _charged(core, event, event.payload)


def _took(core: SimCore, event: EventDraft, moved: ItemMoved) -> None:
    taker = core.state.citizens.get(event.actor_id or "") if event.actor_kind == "citizen" else None
    destination = moved.destination
    if taker is None or moved.source.kind not in WILD_SOURCES:
        return
    if destination.kind != "inventory" or destination.id != taker.id:
        return
    territory = TERRITORY.of(core.state)
    if event.cause_seq is not None and event.cause_seq == territory.last_take:
        return  # the same take's other goods (a hunt's hide after its meat)
    claim = poached(core, taker, taker.position, hunting=moved.source.kind == "animal")
    if claim is None:
        return
    territory.last_take = event.cause_seq
    took = Took(item=moved.item, count=moved.count)
    _trespassed(core, taker, "ground", claim.owner, claim.place, took=took, cause_seq=event.seq)


# --- dens ---


def learn_dens(core: SimCore) -> None:
    """Every-tick hook (after the animals moved): whoever a predator is charging at its den learns the den."""
    life = WILDLIFE.of(core.state)
    for animal_id, why in sorted(life.charges.items()):
        animal = core.state.animals[animal_id]
        if why == "den" and animal.target in core.state.citizens:
            _learn_den(core, animal.target, animal.group)


def _charged(core: SimCore, event: EventDraft, injured: Injured) -> None:
    """A bite from a den charge (charge, bite and giving up can all fall in one tick, before `learn_dens` runs)."""
    animal = core.state.animals.get(injured.attacker or "")
    if animal is None or event.actor_id not in core.state.citizens:
        return
    if WILDLIFE.of(core.state).charges.get(animal.id) == "den":
        _learn_den(core, event.actor_id, animal.group)


def _learn_den(core: SimCore, citizen_id: str, group_id: str) -> None:
    pin = pin_of(core.world, core.state.groups[group_id])
    if pin is None:
        return
    known = TERRITORY.of(core.state).dens.setdefault(citizen_id, [])
    if pin.place not in known:
        known.append(pin.place)
        known.sort()


def known_dens(core: SimCore, citizen_id: str) -> list[Feature]:
    """The dens this citizen learned (charged at them), in id order."""
    ids = TERRITORY.of(core.state).dens.get(citizen_id, [])
    return [feature for feature in core.world.features if feature.id in ids]


def den_words(world: SimWorld, den: Feature) -> str:
    """ "the wolves' den in the Lord's woods"."""
    many = SPECIES[str(den.animal)].many
    hotspot = next((h for h in world.hotspots if h.id == den.hotspot), None)
    where = f" in {hotspot.called}" if hotspot is not None else ""
    return f"the {many}' den{where}"
