"""A band's food grounds (10 §1.2): the land its scripted brains know from the start, read off the world once.

The home ring about a camp runs thin by day 3-4, so foragers walk out a long way (`routines._forage_trip`) towards the
ways from camp where food lies 450-1 000 m out. The band knows its dens too: food by a den doesn't count towards a
way, and a trip's stops keep clear of every den. A mind would learn all this by walking the land; BR2's band brains
replace the compass ways with known hotspots.
"""

from collections.abc import Sequence
from typing import get_args

from app.brains.profile import Ground
from app.brains.routines import TRIP_LEGS
from app.sim.destinations import COMPASS_BEARING, ROUGH_DISTANCE_M
from app.sim.vec import Vec3, step_towards
from app.sim.world import SimWorld
from app.world_api.models import Compass

GROUNDS_M = (450.0, 1000.0)  # a band's food grounds: past the thin home ring, the middle ring (10 §1.2)
GROUND_FOOD = frozenset({"berries", "roots", "nuts"})
GROUNDS_KEPT = 3
GROUND_LEAST = 100  # food (pieces when full) a way must hold to be worth the walk
DEN_CLEAR_M = 150.0  # forage trips keep this far from the dens (a bold hunter walked into a wolf's den on one)
GATHER_SPREAD_M = 150.0  # how far from where a walk ends foragers go for the food they see ("some way off")
STOP_CLEAR_M = DEN_CLEAR_M + GATHER_SPREAD_M  # so a trip's stops keep this far from the dens
WAYS: tuple[Compass, ...] = get_args(Compass)  # north first, clockwise: the order of `food_by_bearing`'s sectors


def forage_grounds(world: SimWorld, camp_id: str) -> tuple[Ground, ...]:
    """The ways from a band's camp its food lies beyond the home ring, most first. Food within DEN_CLEAR_M of a den
    doesn't count, and a trip's stops (the long walk out, then each short walk on) keep STOP_CLEAR_M from every den
    (the food a forager walks to from there then lies DEN_CLEAR_M clear), so a way whose first stop is too near one
    isn't taken and the walks on stop short of one."""
    camp = world.places[camp_id].centre
    dens = [feature.position for feature in world.features if feature.kind == "den"]
    totals = world.nodes.food_by_bearing(world.grid, camp, *GROUNDS_M, GROUND_FOOD, avoid=dens, clear_m=DEN_CLEAR_M)
    ranked = sorted(range(len(totals)), key=lambda sector: (-totals[sector], sector))
    grounds: list[Ground] = []
    for sector in ranked:
        if totals[sector] < GROUND_LEAST or len(grounds) == GROUNDS_KEPT:
            break
        legs = clear_legs(world, camp, WAYS[sector], dens)
        if legs >= 0:
            grounds.append(Ground(WAYS[sector], legs))
    return tuple(grounds)


def clear_legs(world: SimWorld, camp: Vec3, way: Compass, dens: Sequence[Vec3]) -> int:
    """How many short walks on past the long walk out keep every stop STOP_CLEAR_M from the dens (-1: not even the
    long walk's end)."""
    for leg in range(TRIP_LEGS + 1):
        metres = ROUGH_DISTANCE_M["a long walk"] + leg * ROUGH_DISTANCE_M["a short walk"]
        stop = step_towards(camp, COMPASS_BEARING[way], metres, world.radius_m)
        if any(world.distance_m(stop, den) < STOP_CLEAR_M for den in dens):
            return leg - 1
    return TRIP_LEGS
