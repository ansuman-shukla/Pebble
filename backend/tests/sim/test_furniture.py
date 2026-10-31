"""Furniture (D198, issue #80): a drawn piece under every slot people sit or lie on, where the slot is, at its height,
facing its way; the fire pit's log seats for two; served in each site's chart like placements."""

import math
from collections import Counter

from app.sim.furniture import Furniture, site_furniture
from app.sim.slots import Slot, build_layout, load_slots_spec
from app.sim.vec import Vec3
from app.sim.world import SimWorld, site_unit
from app.world.town import load_town

ON_M = 0.05  # a slot on a piece lies this close to the line of its seats


def furniture_of(sim_world: SimWorld) -> list[Furniture]:
    return site_furniture(load_slots_spec(), load_town(), sim_world.sites)


def _unit(sim_world: SimWorld, piece: Furniture, along_m: float = 0.0) -> Vec3:
    """A point on the piece's line of seats, `along_m` to its right (seen by whoever sits on it), on the globe."""
    turn = math.radians(piece.heading_deg)
    x, z = piece.x - math.cos(turn) * along_m, piece.z + math.sin(turn) * along_m
    if piece.site == "town":
        return sim_world.town.to_unit(x, z)
    return site_unit(sim_world.radius_m, next(s for s in sim_world.sites if s.id == piece.site), x, z)


def _under(sim_world: SimWorld, slot: Slot, pieces: list[Furniture]) -> list[Furniture]:
    """The pieces this slot is on: its spot on the line of seats, at its height, facing its way (within a few
    degrees: a log's two seats face its middle)."""
    return [
        piece
        for piece in pieces
        if piece.seat_m == slot.height_m
        and abs((piece.heading_deg - slot.heading_deg + 180) % 360 - 180) <= 12
        and any(
            sim_world.distance_m(_unit(sim_world, piece, end * piece.span_m / 2), slot.position) <= ON_M
            for end in (-1, 1)
        )
    ]


def test_every_seat_mat_and_seated_work_slot_has_a_piece_under_it(sim_world: SimWorld) -> None:
    lay = build_layout(sim_world, load_town(), load_slots_spec())
    pieces = furniture_of(sim_world)
    benches = {placement.id for placement in load_town().placements if placement.kind == "bench"}
    raised = [
        slot
        for slot in lay.slots.values()
        if slot.posture in ("sitting", "lying") and slot.owner not in benches  # a bench is its own seat
    ]
    assert len(raised) == 2 * (8 + 10 + 3 * 2) + 2  # both camps' logs and mats, the loom's stool, the lord's seat
    for slot in raised:
        assert len(_under(sim_world, slot, pieces)) == 1, slot.id
    seats_on = Counter(piece.id for slot in raised for piece in _under(sim_world, slot, pieces))
    assert sorted(seats_on.values()) == [1] * (2 * 10 + 2 * 6 + 2) + [2] * 8  # every piece carries its slots
    assert len(pieces) == len(seats_on)
    grounded = [slot for slot in lay.slots.values() if slot.posture == "sitting_ground"]
    assert grounded and not any(_under(sim_world, slot, pieces) for slot in grounded)  # the gaol, the prayers


def test_the_fire_pits_seats_are_four_logs_for_two_and_the_mats_lie_round_them(sim_world: SimWorld) -> None:
    pieces = furniture_of(sim_world)
    for camp in ("band_a_camp", "band_b_camp"):
        mine = [piece for piece in pieces if piece.site == camp]
        logs = [piece for piece in mine if piece.kind == "log_seat"]
        assert [piece.id for piece in logs] == [f"{camp}:fire-pit#seat-{k}" for k in (1, 3, 5, 7)]
        assert all(math.isclose(piece.span_m, 0.84, abs_tol=0.01) and piece.seat_m == 0.4 for piece in logs)
        for log in logs:  # on the ring's chord, facing the fire across it
            assert math.isclose(math.hypot(log.x, log.z), 2.2 * math.cos(math.radians(11)), abs_tol=0.01)
            to_fire = math.degrees(math.atan2(-log.x, -log.z)) % 360
            assert abs((log.heading_deg - to_fire + 180) % 360 - 180) < 0.5
        assert Counter(piece.kind for piece in mine) == {"log_seat": 4, "sleeping_mat": 16}
    town = Counter((piece.kind, piece.id) for piece in pieces if piece.site == "town")
    assert town == {("stool", "farmhouse-1-loom#seat"): 1, ("lord_seat", "castle-keep#lord-seat"): 1}
