"""A band's land (10 §1.2): what its scripted brains know of it from the start, read off the world once (the engine
hands it over as `BrainProfile.grounds`, `spots` and `hunting_grounds`; brains themselves see only the world
contract). A mind would learn all this by walking the land.

- **Spots:** the hotspots a band member knows (places they can walk to by name), with what can be taken there and
  the game whose hunting ground each is.
- **Hunting grounds:** a hunter's known game spots, nearest first, rotated by the hunter's place among the band's
  hunters so each starts at a different one (the herds aren't all hunted by everyone, 10 §4.6). Another group's
  claimed grounds (the Lord's woods: the town's) are left out.
- **Ring ways:** the ways from camp the home ring's food lies (100-400 m out), most first: foragers look the ring
  over those ways first (its food lies beyond a camp's sight).
- **Food ways:** where no named spot holds the food, foragers walk out a long way (`bands._forage_trip`) towards the
  ways from camp where food lies 450-1 000 m out. Food by a den doesn't count towards a way, and a trip's stops keep
  clear of every den.
"""

from collections.abc import Collection, Sequence
from typing import get_args

from app.sim.destinations import COMPASS_BEARING, ROUGH_DISTANCE_M
from app.sim.vec import Vec3, step_towards
from app.sim.world import SimWorld
from app.world.view import Hotspot
from app.world_api.models import Compass

GROUNDS_M = (450.0, 1000.0)  # a band's food grounds: past the thin home ring, the middle ring (10 §1.2)
RING_M = (100.0, 400.0)  # the home ring's food beyond what is seen from camp
GROUND_FOOD = frozenset({"berries", "roots", "nuts"})
GROUNDS_KEPT = 3
GROUND_LEAST = 100  # food (pieces when full) a way must hold to be worth the walk
DEN_CLEAR_M = 150.0  # forage trips keep this far from the dens (a bold hunter walked into a wolf's den on one)
GATHER_SPREAD_M = 150.0  # how far from where a walk ends foragers go for the food they see ("some way off")
STOP_CLEAR_M = DEN_CLEAR_M + GATHER_SPREAD_M  # so a trip's stops keep this far from the dens
WAYS: tuple[Compass, ...] = get_args(Compass)  # north first, clockwise: the order of `food_by_bearing`'s sectors


def ring_ways(world: SimWorld, camp_id: str) -> tuple[Compass, ...]:
    """The ways from camp the home ring's food lies, the most (when full) first."""
    camp = world.places[camp_id].centre
    totals = world.nodes.food_by_bearing(world.grid, camp, *RING_M, GROUND_FOOD)
    ranked = sorted(range(len(totals)), key=lambda sector: (-totals[sector], sector))
    return tuple(WAYS[sector] for sector in ranked if totals[sector] > 0)


def known_spots(world: SimWorld, camp_id: str, known: Collection[str]) -> tuple[Hotspot, ...]:
    """The hotspots someone knows (place ids), nearest to their camp first."""
    camp = world.places[camp_id].centre
    spots = [hotspot for hotspot in world.hotspots if hotspot.id in known]
    return tuple(sorted(spots, key=lambda spot: (world.distance_m(camp, spot.centre), spot.id)))


def spot_stock(world: SimWorld, hotspot_id: str) -> dict[str, int]:
    """What can be taken at a hotspot without an axe when its nodes are full, by item, the most first."""
    table = world.nodes
    totals: dict[str, int] = {}
    for node, owner in enumerate(table.hotspots):
        kind = table.kind(node)
        if owner == hotspot_id and not kind.axe_minutes:
            totals[kind.item] = totals.get(kind.item, 0) + int(table.caps[node])
    return dict(sorted(totals.items(), key=lambda entry: (-entry[1], entry[0])))


def hunting_grounds(
    world: SimWorld, camp_id: str, group: str, known: Collection[str], rank: int
) -> tuple[Hotspot, ...]:
    """The game spots a hunter of `group` knows and may hunt on, nearest first, rotated by `rank` (their place among
    the band's hunters)."""
    grounds = [spot for spot in known_spots(world, camp_id, known) if spot.hunting and spot.claim in (None, group)]
    if not grounds:
        return ()
    turn = rank % len(grounds)
    return tuple(grounds[turn:] + grounds[:turn])


def forage_grounds(world: SimWorld, camp_id: str, trip_legs: int) -> tuple[tuple[Compass, int], ...]:
    """The ways from a band's camp its food lies beyond the home ring, most first, each with how many of a trip's
    `trip_legs` short walks on it stays clear of the dens. Food within DEN_CLEAR_M of a den
    doesn't count, and a trip's stops (the long walk out, then each short walk on) keep STOP_CLEAR_M from every den
    (the food a forager walks to from there then lies DEN_CLEAR_M clear), so a way whose first stop is too near one
    isn't taken and the walks on stop short of one."""
    camp = world.places[camp_id].centre
    dens = [feature.position for feature in world.features if feature.kind == "den"]
    totals = world.nodes.food_by_bearing(world.grid, camp, *GROUNDS_M, GROUND_FOOD, avoid=dens, clear_m=DEN_CLEAR_M)
    ranked = sorted(range(len(totals)), key=lambda sector: (-totals[sector], sector))
    grounds: list[tuple[Compass, int]] = []
    for sector in ranked:
        if totals[sector] < GROUND_LEAST or len(grounds) == GROUNDS_KEPT:
            break
        legs = clear_legs(world, camp, WAYS[sector], dens, trip_legs)
        if legs >= 0:
            grounds.append((WAYS[sector], legs))
    return tuple(grounds)


def clear_legs(world: SimWorld, camp: Vec3, way: Compass, dens: Sequence[Vec3], trip_legs: int) -> int:
    """How many short walks on past the long walk out keep every stop STOP_CLEAR_M from the dens (-1: not even the
    long walk's end)."""
    for leg in range(trip_legs + 1):
        metres = ROUGH_DISTANCE_M["a long walk"] + leg * ROUGH_DISTANCE_M["a short walk"]
        stop = step_towards(camp, COMPASS_BEARING[way], metres, world.radius_m)
        if any(world.distance_m(stop, den) < STOP_CLEAR_M for den in dens):
            return leg - 1
    return trip_legs
