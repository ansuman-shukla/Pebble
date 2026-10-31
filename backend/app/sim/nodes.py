"""Nodes as a system (10-world-v1 §1.1): what every usable wild thing holds now, how it grows back and how it looks.

The node table (`app.sim.node_table`, part of the static world) says where each node is and what it can hold; this
system keeps only the nodes that differ from full (a picked bush, a felled tree, a paddy short of ripe), so a new run
starts with every node full and the paddies at their start growth (§1.4). Every change of a node's stock or stage is
one `node_changed` (a felling also `tree_felled`), told with the citizen who did it or by the world when it grows:

```
 take ─▶ stock − n ─▶ below the cap: +1 every `regrow` until full (gold never)
 fell a tree ─▶ stump (stump_days) ─▶ sapling (sapling_days) ─▶ a tree again, full
 paddies (app.sim.paddies) ─▶ growth by tending; ripe = 60 rice; harvested to stubble, replanted by tending
```

Stages come from the kind's row in `data/world/node_stages.yaml` (pieces or levels of the stock; trees and paddies
from their own state), the same stage the renderer draws and the words perception says.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.observability.events import ItemLocation, NodeChanged, TreeFelled
from app.sim.clock import DAY_MINUTES
from app.sim.core import SimCore
from app.sim.node_table import PADDY_KIND, NodeTable, load_node_kinds, stage_of, stage_words
from app.sim.state import Citizen, System
from app.sim.world import SimWorld

TREE_KIND = "tree"
RIPE = 100  # paddy growth at which it bears its rice


@dataclass
class NodeEntry:
    """A node that differs from full."""

    kind: str
    cap: int
    stock: int
    regrow_at: int | None = None  # the tick it grows one more (a felled tree: its next stage); None: it doesn't
    growth: int | None = None  # paddies: 0 replanted, + a day's tending (paddies.TEND_GROWTH), RIPE bears rice
    sapling: bool = False  # a felled tree grown back as far as a sapling


@dataclass
class NodeState:
    entries: dict[str, NodeEntry] = field(default_factory=dict)  # by node id
    tended: dict[str, int] = field(default_factory=dict)  # paddy id -> the town day it was last tended
    tended_growth: dict[str, int] = field(default_factory=dict)  # paddy id -> growth its tending added that day


def entry_stage(entry: NodeEntry | None, kind_name: str, cap: int) -> str:
    """The drawn stage of a node (None: it is full)."""
    if kind_name == TREE_KIND:
        return "standing" if entry is None else "sapling" if entry.sapling else "stump"
    if kind_name == PADDY_KIND:
        growth = RIPE if entry is None or entry.growth is None else entry.growth
        stock = cap if entry is None else entry.stock
        if growth >= RIPE:
            return "gold" if stock > 0 else "stubble"
        return "green" if growth >= RIPE // 2 else "seedlings"
    return stage_of(load_node_kinds()[kind_name], cap if entry is None else entry.stock, cap)


class _EntrySnap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    item: str  # dumped for spectators (replay, the live feed): not read back
    cap: int
    stock: int
    stage: str  # dumped for spectators: not read back
    regrow_at: int | None = None
    growth: int | None = None
    sapling: bool = False


class _NodesSnap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: dict[str, _EntrySnap]
    tended: dict[str, int]
    tended_growth: dict[str, int]


_SNAP = TypeAdapter(_NodesSnap)


class NodeView(BaseModel):
    """A node that differs from full, as spectators see it (replay, the live feed's snapshot)."""

    kind: str
    item: str
    cap: int
    stock: int
    stage: str  # drawn stage (node_stages.yaml): "fruit-3", "stump", "gold", ...


def node_views(block: JsonValue) -> dict[str, NodeView]:
    """Every node a `nodes` snapshot block holds (those that differ from full), by id."""
    return {
        node_id: NodeView(kind=e.kind, item=e.item, cap=e.cap, stock=e.stock, stage=e.stage)
        for node_id, e in _SNAP.validate_python(block).entries.items()
    }


def _dump(state: NodeState) -> JsonValue:
    kinds = load_node_kinds()
    snap = _NodesSnap(
        entries={
            node_id: _EntrySnap(
                kind=entry.kind,
                item=kinds[entry.kind].item,
                cap=entry.cap,
                stock=entry.stock,
                stage=entry_stage(entry, entry.kind, entry.cap),
                regrow_at=entry.regrow_at,
                growth=entry.growth,
                sapling=entry.sapling,
            )
            for node_id, entry in sorted(state.entries.items())
        },
        tended=dict(sorted(state.tended.items())),
        tended_growth=dict(sorted(state.tended_growth.items())),
    )
    dumped: JsonValue = _SNAP.dump_python(snap, mode="json")
    return dumped


def _load(data: JsonValue) -> NodeState:
    snap = _SNAP.validate_python(data)
    return NodeState(
        entries={
            node_id: NodeEntry(e.kind, e.cap, e.stock, e.regrow_at, e.growth, e.sapling)
            for node_id, e in snap.entries.items()
        },
        tended=dict(snap.tended),
        tended_growth=dict(snap.tended_growth),
    )


def _new(world: SimWorld) -> NodeState:
    """Every node full but the paddies short of ripe (§1.4: growth 0, 0, 50, 50, 100, 100)."""
    table = world.nodes
    paddies = [index for index, kind in enumerate(table.kinds) if kind == PADDY_KIND]
    start = load_node_kinds()[PADDY_KIND].start_growth
    if start and len(start) != len(paddies):
        raise ValueError(f"{len(paddies)} paddies but {len(start)} start growths")
    state = NodeState()
    for index, growth in zip(paddies, start, strict=False):
        if growth < RIPE:
            state.entries[table.ids[index]] = NodeEntry(PADDY_KIND, int(table.caps[index]), 0, growth=growth)
    return state


NODES = System[NodeState]("nodes", 1, new=_new, dump=_dump, load=_load)


def dump_state(core: SimCore) -> JsonValue:
    """The system's snapshot block now (for comparing states)."""
    return _dump(node_state(core))


def node_state(core: SimCore) -> NodeState:
    return NODES.of(core.state)


def table(core: SimCore) -> NodeTable:
    return core.world.nodes


def entry(core: SimCore, node: int) -> NodeEntry | None:
    return node_state(core).entries.get(table(core).ids[node])


def stock(core: SimCore, node: int) -> int:
    found = entry(core, node)
    return int(table(core).caps[node]) if found is None else found.stock


def stage(core: SimCore, node: int) -> str:
    nodes = table(core)
    return entry_stage(entry(core, node), nodes.kinds[node], int(nodes.caps[node]))


def words(core: SimCore, node: int, count: int = 1) -> str:
    """What a person sees ("a berry bush heavy with fruit"; `count` like it: "three berry bushes heavy with ...")."""
    return stage_words(table(core).kind(node), stage(core, node), count)


def growth(core: SimCore, node: int) -> int:
    """A paddy's growth (a full paddy is ripe)."""
    found = entry(core, node)
    return RIPE if found is None or found.growth is None else found.growth


def change(
    core: SimCore,
    node: int,
    after: int,
    actor: Citizen | None,
    growth: int | None = None,
    cause_seq: int | None = None,
) -> int:
    """Set a node's stock (a paddy's growth too) and tell it (`node_changed`); a node short of its cap starts growing
    back if its kind does and it isn't already. Returns the event's seq."""
    nodes, state = table(core), node_state(core)
    node_id, kind_name, cap = nodes.ids[node], nodes.kinds[node], int(nodes.caps[node])
    if not 0 <= after <= cap:
        raise ValueError(f"{node_id}: stock {after} outside 0..{cap}")
    found = state.entries.get(node_id)
    before = cap if found is None else found.stock
    paddy_growth = growth if growth is not None else found.growth if found is not None else None
    if kind_name == PADDY_KIND and paddy_growth is None:
        paddy_growth = RIPE
    if after == cap and (kind_name != PADDY_KIND or (paddy_growth or 0) >= RIPE):
        state.entries.pop(node_id, None)
    else:
        if found is None:
            found = state.entries[node_id] = NodeEntry(kind_name, cap, before)
        found.stock, found.growth = after, paddy_growth
        interval = nodes.kind(node).regrow_minutes(cap)
        if found.regrow_at is None and interval is not None and kind_name not in (TREE_KIND, PADDY_KIND):
            found.regrow_at = core.state.tick + interval
    kind = nodes.kind(node)
    payload = NodeChanged(
        node=node_id, kind=kind_name, item=kind.item, before=before, after=after, stage=stage(core, node)
    )
    return core.emit("node_changed", payload, actor=actor, cause_seq=cause_seq)


def take_into(core: SimCore, citizen: Citizen, node: int, item: str, count: int, cause_seq: int) -> int:
    """Items taken from a node go into the taker's hands (told as moved from the node, after its `node_changed`);
    returns the `item_moved` seq."""
    nodes = table(core)
    citizen.inventory[item] = citizen.inventory.get(item, 0) + count
    return core.item_moved(
        citizen,
        item,
        count,
        ItemLocation(kind="resource", id=nodes.ids[node], cell=int(nodes.cells[node])),
        ItemLocation(kind="inventory", id=citizen.id),
        cause_seq=cause_seq,
    )


def fell(core: SimCore, citizen: Citizen, node: int, stack: str | None) -> int:
    """A standing tree comes down (its logs go to `stack`): a stump for `stump_days`, then a sapling. Returns the
    `tree_felled` seq; the `node_changed` follows it."""
    nodes = table(core)
    kind = nodes.kind(node)
    if nodes.kinds[node] != TREE_KIND or entry(core, node) is not None:
        raise ValueError(f"{nodes.ids[node]} is not a standing tree")
    yaw = round((180.0 - float(nodes.yaw_deg[node])) % 360.0, 2)  # the fall's bearing as a heading
    felled = TreeFelled(node=nodes.ids[node], yaw_deg=yaw, logs=int(nodes.caps[node]), stack=stack)
    seq = core.emit("tree_felled", felled, actor=citizen)
    node_state(core).entries[nodes.ids[node]] = NodeEntry(
        TREE_KIND, int(nodes.caps[node]), int(nodes.caps[node]), regrow_at=core.state.tick + _days(kind.stump_days)
    )
    change(core, node, 0, citizen, cause_seq=seq)
    return seq


def grow(core: SimCore) -> None:
    """Every-tick hook: nodes due grow one more (felled trees reach their next stage), each told as it happens."""
    nodes, state = table(core), node_state(core)
    tick = core.state.tick
    due = sorted(
        (found.regrow_at, node_id)
        for node_id, found in state.entries.items()
        if found.regrow_at is not None and found.regrow_at <= tick
    )
    for _, node_id in due:
        node = nodes.index[node_id]
        found = state.entries[node_id]
        kind = nodes.kind(node)
        if found.kind == TREE_KIND:
            if found.sapling:
                found.regrow_at = None
                change(core, node, found.cap, None)
            else:
                found.sapling = True
                found.regrow_at = tick + _days(kind.sapling_days)
                change(core, node, 0, None)
            continue
        interval = kind.regrow_minutes(found.cap)
        if interval is None or found.regrow_at is None:
            found.regrow_at = None
            continue
        found.regrow_at += interval
        change(core, node, found.stock + 1, None)


def _days(days: float | None) -> int:
    if days is None:
        raise ValueError("trees need stump_days and sapling_days")
    return round(days * DAY_MINUTES)


def below_cap(core: SimCore) -> list[str]:
    """Nodes short of their cap with nothing growing them back (gold never does; paddies grow by tending)."""
    return sorted(
        node_id
        for node_id, found in node_state(core).entries.items()
        if found.regrow_at is None and found.kind not in (PADDY_KIND, "gold_pool")
    )
