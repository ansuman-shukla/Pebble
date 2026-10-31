"""Nodes (10-world-v1 §1.1): every usable wild thing is a node with an id, worked only from its spots, its stock drops
visibly and grows back on its kind's schedule; felled trees stand as stumps, then saplings; minerals are nodes too."""

import math
from collections.abc import Callable

import pytest

from app.observability.events import NodeChanged, TreeFelled
from app.observability.replay import ReplayEvent, from_snapshot, replay
from app.sim import nodes, reach, slots, wear
from app.sim.clock import DAY_MINUTES
from app.sim.core import REACH_M
from app.sim.node_table import load_node_kinds, stage_of, stage_words
from app.sim.simulation import Simulation
from app.sim.snapshot import restore, state_hash, take_snapshot
from app.sim.vec import bearing_deg, step_towards
from app.sim.world import SimWorld
from app.world.flora import YAW_STEP_DEG
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import make_spec, stand_at_node, wild_node, without_animals

KINDS = load_node_kinds()


def _wild(new_sim: Callable[..., Simulation], **spec: object) -> tuple[Simulation, WorldApi]:
    sim = without_animals(new_sim())
    fields: dict[str, object] = {"home": None, "knows_places": []}
    fields.update(spec)
    citizen = sim.add_citizen(make_spec("tess", **fields))
    return sim, WorldApi(sim, citizen.id)


def _replayable(sim: Simulation) -> list[ReplayEvent]:
    return [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in sim.drain()]


def _alone(sim: Simulation, kind: str, clear_m: float) -> int:
    """A wild node of the kind with no other node yielding the same item within `clear_m`."""
    table = sim.world.nodes
    item = KINDS[kind].item
    for node, name in enumerate(table.kinds):
        if name != kind or not sim.core.planner.outer.allowed[int(table.cells[node])]:
            continue
        near = table.near(sim.world.grid, table.unit(node), clear_m)
        if all(other == node or table.kind(other).item != item for _, other in near):
            if all(sim.world.distance_m(table.unit(node), p.centre) > 800 for p in sim.world.places.values()):
                return node
    raise LookupError(kind)


# --- the table ---


def test_the_table_holds_the_flora_the_node_features_and_the_paddies(sim_world: SimWorld) -> None:
    table = sim_world.nodes
    flora = [node_id for node_id in table.ids if node_id.startswith("flora:")]
    assert flora == [f"flora:{index}" for index in range(len(flora))] and len(flora) > 40_000
    assert table.ids[: len(flora)] == tuple(flora)  # the flora's id is its index in GET /world/flora
    features = {node_id: table.kinds[table.index[node_id]] for node_id in table.ids[len(flora) :]}
    assert [node_id for node_id, kind in features.items() if kind == "rice_paddy"] == [
        f"paddy-{n}" for n in range(1, 7)
    ]
    assert features["falls_pool:gold_pool"] == "gold_pool" and features["south_marsh:iron_sand_bar"] == "iron_sand_bar"
    assert sorted(kind for kind in features.values() if kind != "rice_paddy") == sorted(
        ["fishing_spot"] * 11 + ["flint_seam"] * 3 + ["obsidian_field"] * 3 + ["iron_sand_bar", "gold_pool"]
    )
    caps = {node_id: int(table.caps[table.index[node_id]]) for node_id in features}
    assert caps["gulf_shore:fishing_spot-1"] == 30 and caps["falls_pool:fishing_spot-1"] == 20  # the sea holds more
    assert caps["river_marsh:fishing_spot-2"] == 20 and caps["falls_pool:gold_pool"] == 40
    assert (
        caps["painted_cave_flint:flint_seam"],
        caps["eastern_wall_scar:flint_seam"],
        caps["b_shore:flint_seam"],
    ) == (
        30,
        40,
        10,
    )
    assert {int(table.caps[node]) for node, kind in enumerate(table.kinds) if kind == "berry_bush"} == {12}
    assert {int(table.caps[node]) for node, kind in enumerate(table.kinds) if kind == "tree"} == {10}


def test_no_wild_node_grows_in_the_town_and_every_paddy_lies_in_it(sim_world: SimWorld) -> None:
    table = sim_world.nodes
    inside = [table.kinds[node] for node in range(len(table)) if sim_world.town_point(table.unit(node)) is not None]
    assert sorted(inside) == ["rice_paddy"] * 6


def test_hotspot_nodes_know_their_hotspot(sim_world: SimWorld) -> None:
    table = sim_world.nodes
    grove = [table.kinds[node] for node in range(len(table)) if table.hotspots[node] == "elder_grove"]
    assert grove.count("berry_bush") == 25 and grove.count("nut_tree") == 10  # hotspots.yaml's exact counts
    assert table.hotspots[table.index["falls_pool:gold_pool"]] == "falls_pool"
    assert table.hotspots[table.index["paddy-1"]] is None


def test_spots_stand_round_a_node_facing_it(sim_world: SimWorld) -> None:
    table = sim_world.nodes
    tree = table.kinds.index("tree")
    (spot,) = table.spots(tree)  # one feller at 0.9 m, on the side away from where it falls
    assert sim_world.distance_m(spot.position, table.unit(tree)) == pytest.approx(0.9, abs=1e-3)
    fall = float(table.yaw_deg[tree])
    assert fall == float(int(fall / YAW_STEP_DEG)) * YAW_STEP_DEG
    away = bearing_deg(table.unit(tree), spot.position)
    assert abs((away - fall) % 360.0 - 180.0) < 0.5
    for kind, count, metres in (("berry_bush", 2, 1.2), ("reed_bed", 3, 1.5), ("flint_seam", 2, 1.5)):
        node = table.kinds.index(kind)
        spots = table.spots(node)
        assert len(spots) == count
        for at in spots:
            assert sim_world.distance_m(at.position, table.unit(node)) == pytest.approx(metres, abs=1e-3)
            facing = (180.0 - bearing_deg(at.position, table.unit(node))) % 360.0  # yaw 0 = south
            assert at.heading_deg == pytest.approx(facing, abs=0.01)
        gaps = [sim_world.distance_m(a.position, b.position) for a in spots for b in spots if a is not b]
        assert min(gaps) >= slots.PERSONAL_M  # two can work one bush side by side


def test_shore_spots_lie_a_metre_inland_three_metres_apart(sim_world: SimWorld) -> None:
    table = sim_world.nodes
    node = table.index["gulf_shore:fishing_spot-1"]
    spots = table.spots(node)
    assert len(spots) == 3
    gaps = sorted(sim_world.distance_m(a.position, b.position) for a in spots for b in spots if a is not b)
    assert gaps[0] == pytest.approx(3.0, abs=0.01) and gaps[-1] == pytest.approx(6.0, abs=0.01)
    middle = spots[0].position
    assert sim_world.distance_m(middle, table.unit(node)) == pytest.approx(1.0, abs=0.01)
    land = step_towards(table.unit(node), float(table.shore[node]), 20.0, sim_world.radius_m)
    assert sim_world.distance_m(middle, land) < sim_world.distance_m(table.unit(node), land) - 0.9  # inland
    assert not sim_world.is_water(sim_world.nearest_cell(step_towards(middle, float(table.shore[node]), 15.0, 2000.0)))


def test_paddy_spots_lie_inside_their_rects(sim_world: SimWorld) -> None:
    table = sim_world.nodes
    for paddy_id, rect in table.paddy_rects.items():
        spots = table.spots(table.index[paddy_id])
        assert len(spots) == 4
        for spot in spots:
            local = sim_world.town_point(spot.position)
            assert local is not None
            x, z = local
            assert rect.x0 + 1 < x < rect.x1 - 1 and rect.z0 + 1 < z < rect.z1 - 1


# --- stages and words ---


def test_drawn_stages_follow_the_stock_as_the_bible_says() -> None:
    berry, reeds, nuts, fishing = (KINDS[k] for k in ("berry_bush", "reed_bed", "nut_tree", "fishing_spot"))
    assert [stage_of(berry, stock, 12) for stock in range(13)] == [
        f"fruit-{math.floor(8 * stock / 12 + 0.5)}" for stock in range(13)
    ]
    assert [stage_of(reeds, stock, 20) for stock in range(21)] == [f"reeds-{math.ceil(5 * s / 20)}" for s in range(21)]
    assert [stage_of(nuts, stock, 15) for stock in range(16)] == [f"nuts-{math.ceil(s / 3)}" for s in range(16)]
    assert [stage_of(fishing, stock, 30) for stock in (30, 6, 5, 0)] == ["ripples", "ripples", "still", "still"]
    seam = KINDS["flint_seam"]
    assert [stage_of(seam, stock, 40) for stock in (40, 30, 29, 20, 19, 1, 0)] == [
        "heap-4",
        "heap-4",
        "heap-3",
        "heap-3",
        "heap-2",
        "heap-2",
        "rubble",
    ]


def test_what_is_said_is_what_is_drawn() -> None:
    berry = KINDS["berry_bush"]
    assert stage_words(berry, "fruit-8") == "a berry bush heavy with fruit"
    assert stage_words(berry, "fruit-6", 3) == "three berry bushes heavy with fruit"
    assert stage_words(berry, "fruit-5") == "a berry bush with berries"
    assert stage_words(berry, "fruit-1") == "a berry bush with a few berries left"
    assert stage_words(berry, "fruit-0", 12) == "many berry bushes stripped bare"
    for name, kind in KINDS.items():  # every stage a node can show has its words
        if kind.stage is None:
            continue
        for stock in range(kind.sea_cap or kind.cap + 1):
            assert stage_words(kind, stage_of(kind, min(stock, kind.cap), kind.cap)), name


# --- regrowth ---


@pytest.mark.parametrize(("kind", "days"), [("berry_bush", 3.0), ("root_patch", 5.0), ("deadwood", 2.0)])
def test_a_bare_node_is_full_again_on_schedule(new_sim: Callable[..., Simulation], kind: str, days: float) -> None:
    sim = without_animals(new_sim())
    node = sim.world.nodes.kinds.index(kind)
    cap = int(sim.world.nodes.caps[node])
    start = take_snapshot(sim.state)
    interval = KINDS[kind].regrow_minutes(cap)
    assert interval is not None
    nodes.change(sim.core, node, cap - 1, None)
    first_due = sim.tick + interval
    sim.run(5)
    nodes.change(sim.core, node, 0, None)  # taken again before it grew: the piece already growing keeps its time
    entry = nodes.entry(sim.core, node)
    assert entry is not None and entry.regrow_at == first_due
    assert nodes.below_cap(sim.core) == []  # it grows back: nothing short of its cap is stuck
    sim.run(round(days * DAY_MINUTES * 0.5))
    assert abs(nodes.stock(sim.core, node) - cap / 2) <= 1  # steady growth
    sim.run(round(days * DAY_MINUTES * 0.45))
    assert nodes.stock(sim.core, node) < cap  # not early
    sim.run(round(days * DAY_MINUTES * 0.06))
    assert nodes.stock(sim.core, node) == cap and nodes.entry(sim.core, node) is None  # full: nothing left to grow
    events = sim.drain()
    changed = [e for e in events if isinstance(e.payload, NodeChanged) and e.payload.node == f"flora:{node}"]
    grown = [e.payload for e in changed[2:] if isinstance(e.payload, NodeChanged)]  # after the two takes
    assert len(grown) == cap and all(e.actor_id is None for e in changed)
    assert [(g.before, g.after) for g in grown] == [(n, n + 1) for n in range(cap)]
    grown_at = [e.tick for e in changed[2:]]
    assert grown_at == [first_due + k * interval for k in range(cap)]  # one piece every interval, on the minute
    assert grown[-1].stage == nodes.stage(sim.core, node)
    replayable = [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in events]
    assert replay(start, replayable).same_as(from_snapshot(take_snapshot(sim.state)))
    sim.run(DAY_MINUTES)
    assert nodes.stock(sim.core, node) == cap  # never beyond the cap


def test_minerals_grow_back_by_their_seam_and_gold_never(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    table = sim.world.nodes
    expected = {
        "painted_cave_flint:flint_seam": 20 * DAY_MINUTES // 30,
        "eastern_wall_scar:flint_seam": 15 * DAY_MINUTES // 40,  # the rich wall scar is full in 15 days
        "obsidian_field:obsidian_field-1": 30 * DAY_MINUTES // 40,
        "south_marsh:iron_sand_bar": 10 * DAY_MINUTES // 60,
    }
    for node_id, interval in expected.items():
        node = table.index[node_id]
        nodes.change(sim.core, node, int(table.caps[node]) - 1, None)
        entry = nodes.entry(sim.core, node)
        assert entry is not None and entry.regrow_at == sim.tick + interval, node_id
    gold = table.index["falls_pool:gold_pool"]
    nodes.change(sim.core, gold, 39, None)
    entry = nodes.entry(sim.core, gold)
    assert entry is not None and entry.regrow_at is None
    sim.run(3 * DAY_MINUTES)
    assert nodes.stock(sim.core, gold) == 39
    assert nodes.below_cap(sim.core) == []  # gold is finite by design, not stuck


# --- gathering at a spot ---


def test_gathering_needs_a_free_spot_within_reach(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    bush = _alone(sim, "berry_bush", 20.0)
    table = sim.world.nodes
    sim.core.place_at(tess, step_towards(table.unit(bush), 0.0, 8.0, sim.world.radius_m))
    result = run_until_done(sim, api.gather("berries"), 1)
    assert result.text == "The nearest berry bush is a few paces to the south; go to it first."
    spots = [spot.position for spot in table.spots(bush)]
    away = next(
        point
        for bearing in range(0, 360, 10)
        if min(
            sim.world.distance_m(point := step_towards(table.unit(bush), bearing, 4.5, sim.world.radius_m), s)
            for s in spots
        )
        > REACH_M
    )
    sim.core.place_at(tess, away)  # the bush within 4.5 m, both its spots over 3 m off
    result = run_until_done(sim, api.gather("berries"), 1)
    assert result.text.startswith("The nearest berry bush is right beside you") or result.text.startswith(
        "The nearest berry bush is a few paces"
    )
    assert result.text.endswith("go to it first.")
    stand_at_node(sim, tess.id, bush)
    for index, other in enumerate(("ova", "pim")):  # both spots taken by others picking it
        sim.add_citizen(make_spec(other, home=None, knows_places=[]))
        stand_at_node(sim, other, bush, index)
        slot = slots.node_slots(sim.core, bush)[index]
        slots.claim(sim.core, sim.citizen(other), slot, slot.position)
    sim.core.place_at(tess, step_towards(table.unit(bush), 0.0, 2.0, sim.world.radius_m))
    result = run_until_done(sim, api.gather("berries"), 1)
    assert result.text == "Someone is already at the berry bush; there's no room for you."
    assert nodes.stock(sim.core, bush) == 12 and "berries" not in tess.inventory


def test_a_gatherer_takes_the_spot_picks_the_bush_and_it_shows(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    bush = _alone(sim, "berry_bush", 20.0)
    table = sim.world.nodes
    near = step_towards(table.unit(bush), 45.0, 2.5, sim.world.radius_m)  # within reach of a spot, not on it
    sim.core.place_at(tess, near)
    handle = api.gather("berries")
    sim.run(1)
    held = slots.held_slot(sim.core, tess)
    assert held is not None and held.owner == f"flora:{bush}"
    assert sim.world.distance_m(tess.position, held.position) < 0.01 and tess.heading_deg == held.heading_deg
    assert tess.action is not None and tess.action.args["node"] == f"flora:{bush}"
    result = run_until_done(sim, handle, 20)
    assert result.outcome == "done" and result.text.startswith("You gather")
    taken = tess.inventory["berries"]
    assert 4 <= taken <= 6 and nodes.stock(sim.core, bush) == 12 - taken
    assert sim.world.distance_m(tess.position, table.unit(bush)) <= REACH_M
    changed = [e for e in sim.drain() if e.type == "node_changed"]
    assert len(changed) == 1 and changed[0].actor_id == tess.id
    payload = changed[0].payload
    assert isinstance(payload, NodeChanged)
    assert (payload.node, payload.kind, payload.item, payload.before, payload.after) == (
        f"flora:{bush}",
        "berry_bush",
        "berries",
        12,
        12 - taken,
    )
    assert payload.stage == f"fruit-{round(8 * (12 - taken) / 12)}"
    entry = nodes.entry(sim.core, bush)
    assert entry is not None and entry.regrow_at == changed[0].tick + 6 * 60  # +1 every 6 hours


def test_walking_to_berries_goes_to_a_free_spot_of_a_bush_with_some_left(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    table = sim.world.nodes
    bush = wild_node(sim, "berry_bush")
    nodes.change(sim.core, bush, 0, None)  # the nearest bush is stripped bare
    sim.core.place_at(tess, step_towards(table.unit(bush), 90.0, 6.0, sim.world.radius_m))
    seen = [t for t in api.look_around().things if t.resource == "berries"]
    assert seen and "stripped" not in seen[0].label  # only bushes with berries on them are told
    spot = reach.reserve(sim.core, tess, bush)  # asked for the stripped one: the nearest like it with berries
    claimed = slots.held_slot(sim.core, tess)
    assert spot is not None and claimed is not None and claimed.owner != f"flora:{bush}"
    assert nodes.stock(sim.core, sim.world.nodes.index[claimed.owner]) > 0
    slots.release(sim.core, tess)
    result = run_until_done(sim, api.walk_to_thing("berries"), 120)
    assert result.outcome == "done"
    held = slots.held_slot(sim.core, tess)
    assert held is not None and held.owner != f"flora:{bush}"
    other = table.index[held.owner]
    assert table.kinds[other] == "berry_bush" and nodes.stock(sim.core, other) > 0
    assert sim.world.distance_m(tess.position, held.position) < 0.01
    assert run_until_done(sim, api.gather("berries"), 21).outcome == "done"


def test_wood_comes_from_fallen_wood_and_trees_only_fall_to_an_axe(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    table = sim.world.nodes
    tree = _alone(sim, "tree", 0.1)
    near_wood = [o for _, o in table.near(sim.world.grid, table.unit(tree), 8.0) if table.kinds[o] == "deadwood"]
    assert near_wood == []
    stand_at_node(sim, tess.id, tree)
    result = run_until_done(sim, api.gather("wood"), 1)
    assert result.outcome == "failed" and result.text.endswith(", and felling a tree takes an axe.")
    used: list[str] = []
    monkeypatch.setattr(wear, "use_tool", _recorder(used))
    tess.inventory["stone axe"] = 1
    sim.drain()
    handle = api.gather("wood")
    sim.run(60)
    assert handle.result is None  # a stone axe takes an hour and a half
    result = run_until_done(sim, handle, 31)
    assert result.outcome == "done" and result.text.startswith("The tree falls")
    events = sim.drain()
    (felled,) = [e.payload for e in events if isinstance(e.payload, TreeFelled)]
    assert felled.node == f"flora:{tree}" and felled.logs == 10
    assert felled.yaw_deg == pytest.approx((180.0 - float(table.yaw_deg[tree])) % 360.0, abs=0.01)
    stack = sim.state.ground[str(felled.stack)]
    assert (stack.item, stack.count) == ("wood", 10) and sim.world.distance_m(stack.position, table.unit(tree)) < 0.01
    assert used == ["stone axe"]  # the felling wears the axe
    assert nodes.stage(sim.core, tree) == "stump" and nodes.stock(sim.core, tree) == 0
    assert run_until_done(sim, api.gather("wood"), 1).outcome == "failed"  # a stump gives no more
    felled_at = next(e.tick for e in events if isinstance(e.payload, TreeFelled))
    for days, stage in ((5, "sapling"), (10, "standing")):
        sim.state.tick = felled_at + days * DAY_MINUTES - 1  # jump the clock (between ticks) to the day it grows
        assert nodes.stage(sim.core, tree) != stage
        sim.step()
        assert nodes.stage(sim.core, tree) == stage
    assert nodes.entry(sim.core, tree) is None
    grown = [e.payload for e in sim.drain() if isinstance(e.payload, NodeChanged) and e.payload.node == felled.node]
    assert [(g.before, g.after, g.stage) for g in grown] == [(0, 0, "sapling"), (0, 10, "standing")]


def test_an_axe_takes_fallen_wood_first_when_a_tree_is_in_reach_too(
    new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch
) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    tess.inventory["stone axe"] = 1
    table = sim.world.nodes
    tree, wood = next(
        (tree, at.node)
        for tree, name in enumerate(table.kinds)
        if name == "tree"
        and any(table.kinds[o] == "deadwood" for _, o in table.near(sim.world.grid, table.unit(tree), 4.0))
        and stand_at_node(sim, tess.id, tree)
        and not isinstance(at := reach.at_node(sim.core, tess, "wood", {"deadwood"}), str)
    )  # standing at a tree's spot with fallen wood within reach too
    assert not isinstance(reach.at_node(sim.core, tess, "wood", {"tree"}), str)
    used: list[str] = []
    monkeypatch.setattr(wear, "use_tool", _recorder(used))
    sim.drain()
    result = run_until_done(sim, api.gather("wood"), 21)  # the fallen wood's 20 minutes, not the axe's 90
    assert result.outcome == "done" and not result.text.startswith("The tree falls")
    events = sim.drain()
    assert not [e for e in events if isinstance(e.payload, TreeFelled)] and used == []
    assert nodes.stock(sim.core, tree) == int(table.caps[tree]) and nodes.stage(sim.core, tree) == "standing"
    assert nodes.stock(sim.core, wood) < int(table.caps[wood])
    (changed,) = [e.payload for e in events if isinstance(e.payload, NodeChanged)]
    assert changed.node == table.ids[wood]


def test_minerals_are_mined_and_gold_panned_at_their_spots(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    table = sim.world.nodes
    seam = table.index["painted_cave_flint:flint_seam"]
    stand_at_node(sim, tess.id, seam)
    handle = api.gather("flint")
    sim.run(9)
    assert handle.result is None
    assert run_until_done(sim, handle, 2).text == "You mine a flint nodule."
    assert tess.inventory == {"flint": 1} and nodes.stock(sim.core, seam) == 29
    gold = table.index["falls_pool:gold_pool"]
    stand_at_node(sim, tess.id, gold)
    texts = [run_until_done(sim, api.gather("gold"), 31).text for _ in range(12)]
    panned = texts.count("You pan a grain of gold.")
    assert 0 < panned < 12 and texts.count("You work a long while but find no gold.") == 12 - panned  # 50 %
    assert tess.inventory["gold"] == panned and nodes.stock(sim.core, gold) == 40 - panned


def test_the_nodes_block_holds_only_what_differs_and_survives_a_snapshot(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    state = nodes.node_state(sim.core)
    assert sorted(state.entries) == ["paddy-1", "paddy-2", "paddy-3", "paddy-4"]  # every other node starts full
    bush = sim.world.nodes.kinds.index("berry_bush")
    nodes.change(sim.core, bush, 5, None)
    block = nodes.dump_state(sim.core)
    assert isinstance(block, dict) and isinstance(block["entries"], dict)
    assert block["entries"][f"flora:{bush}"] == {
        "kind": "berry_bush",
        "item": "berries",
        "cap": 12,
        "stock": 5,
        "stage": "fruit-3",
        "regrow_at": sim.tick + 360,
        "growth": None,
        "sapling": False,
    }
    resumed = Simulation(sim.world, restore(take_snapshot(sim.state)), sim.core.planner)
    assert state_hash(resumed.state) == state_hash(sim.state)
    resumed.run(360)
    assert nodes.stock(resumed.core, bush) == 6


def test_perception_tells_nodes_in_their_stage_words(new_sim: Callable[..., Simulation]) -> None:
    sim, api = _wild(new_sim)
    tess = sim.citizen(api.citizen_id)
    table = sim.world.nodes
    stand_at_node(sim, tess.id, table.index["river_marsh:fishing_spot-1"])
    things = {t.label: t for t in api.look_around().things}
    spot = next(t for label, t in things.items() if label.startswith("a good fishing spot"))
    assert spot.label == "a good fishing spot, fish jumping" and spot.kind == "node" and spot.resource is None
    assert not any("tall tree" in label for label in things)  # trees are wood only to someone with an axe
    tess.inventory["iron axe"] = 1
    assert any("tall tree" in t.label for t in api.look_around().things)
    assert reach.the("an oak dropping nuts") == "the oak dropping nuts"


def _recorder(used: list[str]) -> Callable[..., bool]:
    """A stand-in for `wear.use_tool` that notes each tool used and never breaks it."""

    def use(_core: object, _citizen: object, item: str, **_cause: object) -> bool:
        used.append(item)
        return False

    return use
