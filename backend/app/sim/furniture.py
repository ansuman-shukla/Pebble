"""Furniture (10-world-v1 §4.3, D198): the log seats, stools and mats people sit and lie on, laid where their slots
are (`data/slots.yaml`, a slot's `furniture`), so every rest, sleep and seated work is done on a drawn thing.

A slot with furniture gets a piece under it; neighbouring log seats of one owner (closer than `JOIN_M`, at one
height) are one log, as long as the seats on it need (the fire pit's 8 seats are 4 logs for two). Pieces are told in
their site's chart, like placements: the town's metres, or a camp's round its anchor.
"""

import math
from collections.abc import Iterable

from pydantic import BaseModel

from app.sim.slots import FurnitureKind, LocalSlot, SlotsSpec, local_slots, placement_slots
from app.world.town import TownView
from app.world.view import Site

JOIN_M = 1.0  # neighbouring log seats closer than this are one log (seats on a log lie 0.84 m apart, D117)
_JOINED: frozenset[FurnitureKind] = frozenset({"log_seat"})


class Furniture(BaseModel):
    """A piece of furniture as the client draws it (`GET /api/v1/world/furniture`)."""

    id: str  # "<slot owner>#<its first slot's name>"
    site: str  # "town" or a camp's site id: the chart x and z are in
    kind: FurnitureKind
    x: float  # the piece's middle (local metres, x east, z south like placements)
    z: float
    heading_deg: float  # the way whoever sits or lies on it faces (0 = +z, 90 = +x), like its slots'
    seat_m: float  # where the hips rest above the ground (0 for a mat)
    span_m: float = 0.0  # between its outermost seats along it (a log for two: 0.84); 0 for a piece of one slot


def site_furniture(spec: SlotsSpec, town: TownView, sites: Iterable[Site]) -> list[Furniture]:
    """Every piece in the world: under the town's placements, the named places' own slots and the camps'."""
    pieces = [piece for p in town.placements for piece in _pieces("town", p.id, placement_slots(spec, p))]
    for place_id, place in spec.places.items():
        pieces += _pieces("town", place_id, local_slots(place.slots))
    for site in sites:
        if site.kind == "camp":
            for p in site.placements:
                pieces += _pieces(site.id, f"{site.id}:{p.id}", placement_slots(spec, p))
    return pieces


def _pieces(site: str, owner: str, located: list[LocalSlot]) -> list[Furniture]:
    runs: list[list[LocalSlot]] = []
    for at in located:
        kind = at.spec.furniture
        if kind is None:
            continue
        last = runs[-1][-1] if runs else None
        if (
            last is not None
            and kind in _JOINED
            and last.spec.furniture == kind
            and last.spec.height_m == at.spec.height_m
            and math.hypot(at.x - last.x, at.z - last.z) < JOIN_M
        ):
            runs[-1].append(at)
        else:
            runs.append([at])
    return [_piece(site, owner, run) for run in runs]


def _piece(site: str, owner: str, run: list[LocalSlot]) -> Furniture:
    first, last = run[0], run[-1]
    kind = first.spec.furniture
    if kind is None:
        raise ValueError(f"{owner}#{first.spec.name} has no furniture")
    # the run's way, averaged as directions (a log's two seats face its middle from either end of it)
    east = sum(math.sin(math.radians(at.heading_deg)) for at in run)
    south = sum(math.cos(math.radians(at.heading_deg)) for at in run)
    return Furniture(
        id=f"{owner}#{first.spec.name}",
        site=site,
        kind=kind,
        x=round((first.x + last.x) / 2, 3),
        z=round((first.z + last.z) / 2, 3),
        heading_deg=round(math.degrees(math.atan2(east, south)) % 360.0, 2),
        seat_m=first.spec.height_m,
        span_m=round(math.hypot(last.x - first.x, last.z - first.z), 3),
    )
