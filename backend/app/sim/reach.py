"""Reach (10-world-v1 §1.1): gathering, fishing, felling, mining and farming happen at a node's work spot.

A node is worked from one of its spots: the actor stands within `REACH_M` of a free spot of a node with stock and
claims it while the action runs (`app.sim.slots`, the one claim registry); walking to a node goes to the nearest free
spot of the nearest such node. When there is none the failure says why, in the world's words: the nearest one is
some way off, someone is already at it, or there's nothing left on it.
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.observability.events import Target
from app.sim import nodes, slots
from app.sim.core import REACH_M, SimCore
from app.sim.items import ITEMS
from app.sim.perception import where_words
from app.sim.slots import Slot
from app.sim.state import Citizen
from app.sim.vec import Vec3, bearing_deg

SPOT_REACH_M = 2.5  # the farthest a kind's spots lie from its node (node_stages.yaml spot_m, a shore's inland step)
RESERVE_TRIES = 40  # nodes tried, nearest first, for a free spot to walk to


@dataclass(frozen=True)
class AtNode:
    node: int
    slot: Slot


def the(one: str) -> str:
    """ "a berry bush" -> "the berry bush" (also "an", "some")."""
    first, _, rest = one.partition(" ")
    return f"the {rest}" if first in ("a", "an", "some") else one


def bare(one: str) -> str:
    first, _, rest = one.partition(" ")
    return rest if first in ("a", "an", "some") else one


def _yields(core: SimCore, node: int, item: str, kinds: Collection[str] | None) -> bool:
    table = core.world.nodes
    return table.kind(node).item == item and (kinds is None or table.kinds[node] in kinds)


def at_node(core: SimCore, citizen: Citizen, item: str, kinds: Collection[str] | None = None) -> AtNode | str:
    """The node to take `item` from and the spot to stand at: the node spot they hold (if its node still has some),
    else the nearest free spot within REACH_M of them of a node with stock; or why there is none."""
    table = core.world.nodes
    near = [
        node
        for _, node in table.near(core.world.grid, citizen.position, REACH_M + SPOT_REACH_M)
        if _yields(core, node, item, kinds)
    ]
    held = slots.held_slot(core, citizen)
    stocked = [node for node in near if nodes.stock(core, node) > 0]
    for node in stocked:
        if held is not None and held.owner == table.ids[node]:
            if core.distance_m(citizen.position, held.position) <= REACH_M:
                return AtNode(node, held)
    free = [
        (core.distance_m(citizen.position, slot.position), node, slot)
        for node in stocked
        if (slot := slots.nearest_free(core, citizen, slots.node_slots(core, node), REACH_M)) is not None
    ]
    if free:
        _, node, slot = min(free, key=lambda option: (option[0], option[1]))
        return AtNode(node, slot)
    open_spots = [node for node in stocked if slots.nearest_free(core, citizen, slots.node_slots(core, node))]
    if stocked and not open_spots:
        return f"Someone is already at {the(table.kind(stocked[0]).one)}; there's no room for you."
    if near and not stocked:
        return f"There's nothing left to take from {the(table.kind(near[0]).one)}."
    seen = nearest_stocked(core, citizen, item, kinds, core.sight_range(citizen))
    if seen is not None:
        node, metres = seen
        where = where_words(metres, bearing_deg(citizen.position, table.unit(node)))
        return f"The nearest {bare(table.kind(node).one)} is {where}; go to it first."
    return f"{none_of(item)} within reach."


def none_of(item: str) -> str:
    """ "There are no berries", "There is no iron sand"."""
    kind = ITEMS[item]
    return f"There is no {kind.name}" if kind.mass else f"There are no {kind.plural or kind.name}"


def nearest_stocked(
    core: SimCore, citizen: Citizen, item: str, kinds: Collection[str] | None, within_m: float
) -> tuple[int, float] | None:
    for metres, node in core.world.nodes.near(core.world.grid, citizen.position, within_m):
        if _yields(core, node, item, kinds) and nodes.stock(core, node) > 0:
            return node, metres
    return None


def node_target(core: SimCore, node: int) -> Target:
    """What an action at a node is about, for spectators (the node renderer marks it worked: a tree shakes)."""
    table = core.world.nodes
    return Target(kind="node", id=table.ids[node], name=bare(table.kind(node).one), position=table.unit(node))


def take_spot(core: SimCore, citizen: Citizen, at: AtNode) -> None:
    """Claim the spot for the action (stepped onto at the tick's end, facing the node)."""
    slots.claim(core, citizen, at.slot, at.slot.position, approach=True)


def reserve(core: SimCore, citizen: Citizen, node: int) -> Vec3 | None:
    """Walking to a node: the nearest free spot of the nearest node like it (same kind) with stock, from this one
    outwards, claimed on the way; None when none within sight has a free spot."""
    table = core.world.nodes
    kind_name = table.kinds[node]
    tried = 0
    for _, other in table.near(core.world.grid, table.unit(node), core.sight_range(citizen)):
        if table.kinds[other] != kind_name or nodes.stock(core, other) == 0:
            continue
        slot = slots.nearest_free(core, citizen, slots.node_slots(core, other))
        if slot is not None:
            return slots.claim(core, citizen, slot, slot.position)
        tried += 1
        if tried >= RESERVE_TRIES:
            break
    return None


def node_held(core: SimCore, citizen: Citizen) -> int | None:
    """The node whose spot the citizen holds, if any."""
    held = slots.held_slot(core, citizen)
    return core.world.nodes.index.get(held.owner) if held is not None else None
