"""Where a walk goes (03 walk_to targets): a place, a person, a thing or a direction, resolved to a spot, or the
in-world reason it can't be walked to; and catching up with the person walked to or followed.
"""

from dataclasses import dataclass

from app.sim import slots
from app.sim.acting import capital
from app.sim.core import SimCore
from app.sim.fauna import SPECIES
from app.sim.perception import Thing, compass, match_animal, match_person, match_thing, normalize, person_label
from app.sim.state import ActionState, Citizen
from app.sim.vec import Vec3, bearing_deg, step_towards
from app.world_api.models import DirectionTarget, PersonTarget, PlaceTarget, Target, ThingTarget

ROUGH_DISTANCE_M: dict[str, float] = {
    "a few steps": 15.0,
    "a short walk": 100.0,
    "a long walk": 500.0,
    "very far": 1500.0,
}
DISTANCE_PHRASE: dict[str, str] = {
    "a few steps": "a few steps",
    "a short walk": "a short way",
    "a long walk": "a long way",
    "very far": "very far",
}
BESIDE_M = 1.2  # walking up to someone ends this far from them
COMPASS_BEARING = {name: index * 45.0 for index, name in enumerate(compass(b * 45.0) for b in range(8))}


@dataclass(frozen=True)
class Destination:
    """Where a walk goes, as the walker names it (`words`, "your home") and as spectators see it (`shown`, "home")."""

    goal: Vec3
    words: str
    person_id: str | None
    arrive: str  # the arrival text, or "rough:<place id>" for a place only guessed at
    shown: str


def resolve(core: SimCore, citizen: Citizen, target: Target) -> Destination | str:
    """Where the target is, or the in-world reason it can't be walked to. A place, home or thing resolves to a free
    slot of it (or a free spot round it), claimed for the walker (`app.sim.slots`), so nobody ends inside anyone."""
    if isinstance(target, PlaceTarget):
        query = normalize(target.name)
        if query == "home":
            if citizen.home is None:
                return "You have no home to go to."
            spot = slots.reserve_home(core, citizen, core.world.structures[citizen.home])
            return Destination(spot, "your home", None, "You arrive home.", shown="home")
        for place_id in sorted(citizen.places):
            place = core.world.places[place_id]
            if normalize(place.name) == query:
                knowledge = citizen.places[place_id]
                if knowledge.level == "visited":
                    spot = slots.reserve_place(core, citizen, place_id)
                    return Destination(spot, place.name, None, f"You arrive at {place.name}.", place.name)
                spot = slots.reserve_near(core, citizen, knowledge.guess, with_centre=True)
                return Destination(spot, place.name, None, f"rough:{place_id}", place.name)
        return f"You don't know a place called {target.name}."
    if isinstance(target, PersonTarget):
        person = match_person(core, citizen, target.who)
        if person is None:
            return "You don't see anyone like that."
        label = person_label(citizen, person)
        # spectators see who it really is; the walker only knows a stranger by their looks
        return Destination(person.position, label, person.id, f"You reach {label}.", shown=person.name)
    if isinstance(target, ThingTarget):
        thing = match_thing(core, citizen, target.what)
        if thing is not None:
            return Destination(
                _thing_spot(core, citizen, thing), thing.label, None, f"You reach {thing.label}.", thing.label
            )
        animal = match_animal(core, citizen, target.what)
        if animal is not None:
            one = SPECIES[animal.kind].one
            spot = slots.reserve_near(core, citizen, animal.position, with_centre=True)
            return Destination(spot, one, None, f"You reach where you saw {one}.", one)
        return f"You don't see any {target.what} around here."
    return _resolve_direction(core, citizen, target)


def _resolve_direction(core: SimCore, citizen: Citizen, target: DirectionTarget) -> Destination | str:
    full = ROUGH_DISTANCE_M[target.distance]
    for share in (1.0, 0.75, 0.5, 0.25):
        goal = step_towards(citizen.position, COMPASS_BEARING[target.direction], full * share, core.world.radius_m)
        town = core.world.town_point(goal)
        if town is not None:
            if core.world.town.walk.is_walkable(*town):
                break
        elif core.planner.outer.allowed[core.world.nearest_cell(goal, citizen.cell)]:
            break
    else:
        return f"You can't go {target.distance} to the {target.direction} from here."
    label = f"to the {target.direction}"
    arrive = f"You walk {DISTANCE_PHRASE[target.distance]} {label} and stop."
    return Destination(
        slots.reserve_near(core, citizen, goal, with_centre=True), f"the {target.direction}", None, arrive, label
    )


def _thing_spot(core: SimCore, citizen: Citizen, thing: Thing) -> Vec3:
    """A structure or hearth: one of its slots; a thing on the ground: a spot beside it; plants, water: the spot told
    (or a free one round it)."""
    if thing.kind == "structure":
        structure = core.world.structures[thing.ref]
        if structure.id == citizen.home:
            return slots.reserve_home(core, citizen, structure)
        return slots.reserve_owner(core, citizen, structure.id, structure.centre, thing.goal)
    if thing.kind == "fire":
        fire = core.state.fires[thing.ref]
        return slots.reserve_owner(core, citizen, fire.id, fire.position, thing.goal)
    return slots.reserve_near(core, citizen, thing.goal, with_centre=thing.kind != "ground")


def beside(core: SimCore, citizen: Citizen, walk: ActionState, person: Citizen) -> None:
    """Caught up with the person walked to: a walk ends; a follow keeps beside them until they stop moving. Whoever
    stops ends a pace from them (BESIDE_M, on the side they came from), facing them (10 §4.3)."""
    moving = person.action is not None and person.action.kind in ("walk_to", "flee", "follow")
    if walk.kind == "follow" and moving:
        walk.route, walk.goal = None, None  # wait at their side; plan again once they pull ahead
        return
    _stand_beside(core, citizen, person)
    if walk.kind != "follow":
        core.end_action(citizen, "done", f"You reach {walk.destination}.")
        return
    core.end_action(citizen, "done", f"{capital(walk.destination)} stops, and you stop beside them.")


def _stand_beside(core: SimCore, citizen: Citizen, person: Citizen) -> None:
    """A pace from them on the side they came from, else the nearest free spot round them at that pace (a group walking
    up to one person stands round them), facing them."""
    stride = core.strides.get(citizen.id)
    came_from = stride.walked[0][0] if stride is not None else citizen.position
    side = citizen.position if core.distance_m(citizen.position, person.position) > 0.01 else came_from
    if core.distance_m(side, person.position) > 0.01:
        spot = slots.free_round(core, citizen, person.position, BESIDE_M, bearing_deg(person.position, side))
        if spot is not None:
            slots.step_to(core, citizen, spot)
    if citizen.id in core.strides:  # facing them (a turn is told with a move)
        citizen.heading_deg = round((180.0 - bearing_deg(citizen.position, person.position)) % 360.0, 2)
