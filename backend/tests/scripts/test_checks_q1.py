"""Q1's run checks: each counts what the critic checklist names and fails where it should."""

from collections.abc import Callable
from dataclasses import replace

from app.observability.events import (
    ActionEnded,
    ActionStarted,
    Died,
    EventDraft,
    EventType,
    Injured,
    ItemLocation,
    ItemMoved,
    NodeChanged,
    Payload,
    Said,
    Stole,
    Target,
    TaxChange,
    ToolBroke,
    Traded,
    TreeFelled,
    Trespassed,
)
from app.sim import nodes, slots, society
from app.sim.clock import DAY_MINUTES, START_MINUTE
from app.sim.simulation import Simulation
from app.sim.state import ActionState
from app.world.roads import NONE
from scripts.checks import CHECKS, q1
from scripts.checks.base import Outcome
from tests.sim_helpers import make_spec


def _event(sim: Simulation, kind: EventType, who: str | None, payload: Payload, actor: str = "citizen") -> EventDraft:
    return EventDraft(0, sim.tick, kind, actor, who, None, None, "public", None, payload)  # type: ignore[arg-type]


def _band(sim: Simulation, who: str, region: str = "band_b", shelter: str = "shelter-n") -> str:
    camp = f"{region}_camp"
    return sim.add_citizen(make_spec(who, site=camp, at=(0.0, 6.0), home=f"{camp}:{shelter}", region=region)).id


def test_every_q1_check_is_registered() -> None:
    assert {c.name for c in q1.CHECKS} <= {c.name for c in CHECKS}
    assert len(q1.CHECKS) == 13


def test_the_cast_needs_twenty_two_and_forty_two_of_forty_four_alive(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    for who in ("ann", "bo"):
        sim.add_citizen(make_spec(who))
    check = q1.Cast()
    check.start(sim)
    sim.citizen("bo").body.alive = False
    outcome = check.outcome(sim)
    assert (outcome.value, outcome.ok) == (1, False)  # 2 spawned, not 22
    full, short = Outcome(21, True, ""), Outcome(20, True, "")
    assert q1.Cast.overall({1: full, 7: full}).ok  # 42 of 44
    assert not q1.Cast.overall({1: full, 7: short}).ok  # 41
    assert not q1.Cast.overall({1: Outcome(22, False, ""), 7: Outcome(22, True, "")}).ok  # a seed spawned wrong


def test_a_death_needs_its_cause_and_a_blow_its_striker(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    for who in ("ann", "bo", "cy"):
        sim.add_citizen(make_spec(who))
    check = q1.DeathCauses()
    check.start(sim)
    sim.citizen("ann").body.alive = False
    check.after_step(sim, [_event(sim, "died", "ann", Died(cause="starvation"))])
    assert check.outcome(sim).ok
    sim.citizen("bo").body.alive = False
    check.after_step(sim, [_event(sim, "died", "bo", Died(cause="killed by a wolf"))])  # no attacker named
    assert not check.outcome(sim).ok and "bo" in check.outcome(sim).words
    check = q1.DeathCauses()
    check.start(sim)
    check.after_step(sim, [_event(sim, "died", "bo", Died(cause="killed by a wolf", attacker="wolf:1"))])
    sim.citizen("ann").body.alive = True
    assert check.outcome(sim).ok
    sim.citizen("cy").body.alive = False  # dead without a word
    assert check.outcome(sim).value == 1 and "cy (no died event)" in check.outcome(sim).words


def test_attacking_a_person_or_hurting_one_by_violence_fails_but_a_hunt_doesn_t(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    check = q1.Assaults()
    check.start(sim)
    deer = Target(kind="animal", id="deer:1", name="a deer")
    hunt = ActionStarted(number=1, action="attack", args={}, label="a deer", target=deer)
    check.after_step(sim, [_event(sim, "action_started", "kaz", hunt)])
    check.after_step(sim, [_event(sim, "injured", "kaz", Injured(amount=5, cause="animal attack", attacker="wolf:1"))])
    assert check.outcome(sim).ok
    person = hunt.model_copy(update={"target": Target(kind="person", id="tek", name="Tek")})
    check.after_step(sim, [_event(sim, "action_started", "kaz", person)])
    assert check.outcome(sim).value == 1
    check.after_step(sim, [_event(sim, "injured", "tek", Injured(amount=5, cause="violence", attacker="kaz"))])
    assert check.outcome(sim).value == 2


def test_two_bodies_at_the_exact_same_point_count_unless_one_is_inside(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    for who in ("ann", "bo"):
        sim.add_citizen(make_spec(who))
    check = q1.Overlaps()
    check.start(sim)
    ann, bo = sim.citizen("ann"), sim.citizen("bo")
    bo.position = ann.position
    check.after_step(sim, [])
    assert check.outcome(sim).value == 1
    walk = ActionState(number=1, kind="walk_to", started_tick=0, started_seq=0, args={})
    ann.action, bo.action = walk, replace(walk, number=2)
    check.after_step(sim, [])
    assert check.outcome(sim).value == 1 and check.walking == 1  # two walkers on one route: reported
    bo.action = None
    check.after_step(sim, [])
    assert check.outcome(sim).value == 2
    ann.action = None
    home = sim.world.structures[str(ann.home)]
    inside = slots.layout(sim.core).slots[f"{home.id}#inside"]
    slots.claim(sim.core, ann, inside, inside.position)
    check.after_step(sim, [])
    assert check.outcome(sim).value == 2  # not counted again


def test_a_sleeper_at_home_lies_inside_or_on_a_mat_and_away_on_open_ground(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    nim = sim.citizen(_band(sim, "nim"))
    check = q1.Sleepers()
    check.start(sim)
    home = sim.world.structures[str(nim.home)]
    nim.position, nim.body.asleep = home.door, True
    check.after_step(sim, [])
    assert check.outcome(sim).value == 1  # at the lean-to, on no mat
    mat = next(s for s in slots.layout(sim.core).owners[home.id] if s.kind == "mat")
    nim.position = mat.position
    slots.claim(sim.core, nim, mat, mat.position)
    check.after_step(sim, [])
    assert check.outcome(sim).value == 1
    slots.release(sim.core, nim)
    nim.position = sim.world.places["band_b_camp"].centre  # a camp spot, more than 6 m from the door
    off = sim.core.distance_m(nim.position, home.door) > 6.0 and slots.walkable(sim.core, nim.position)
    check.after_step(sim, [])
    assert check.outcome(sim).value == (1 if off else 2)


def test_standing_about_counts_awake_daytime_ticks_with_nothing_on_or_waiting(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    sim.add_citizen(make_spec("ann"))
    sim.state.tick = 12 * 60 - START_MINUTE  # noon
    check = q1.StandingAbout()
    check.start(sim)
    ann = sim.citizen("ann")
    for _ in range(9):
        check.after_step(sim, [])
    assert check.outcome(sim).value == 1.0
    check.after_step(sim, [_event(sim, "said", "ann", Said(words="Hello.", volume="normal", heard_by=[]))])
    assert check.outcome(sim).value == 0.9  # talking is no standing about
    ann.body.asleep = True
    check.after_step(sim, [])
    assert check.outcome(sim).value == 0.9  # asleep: not counted
    ann.body.asleep = False
    sim.state.tick += 12 * 60  # midnight
    check.after_step(sim, [])
    assert check.outcome(sim).value == 0.9 and not check.outcome(sim).ok
    assert "ann 90.0%" in check.outcome(sim).words


def test_a_raid_is_a_night_band_b_took_from_the_field_racks(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    kaz, nim, genzo = _band(sim, "kaz"), _band(sim, "nim"), sim.add_citizen(make_spec("genzo")).id
    check = q1.Raids()
    check.start(sim)
    rack = Stole(owner="farmhouse-1", store="field-rack-1", item="rice", count=5)
    sim.state.tick = DAY_MINUTES + 22 * 60 - START_MINUTE  # 22:00 on the second day
    check.after_step(sim, [_event(sim, "stole", kaz, rack)])
    sim.state.tick += 3 * 60  # 01:00: the same night
    check.after_step(sim, [_event(sim, "stole", nim, rack.model_copy(update={"count": 2}))])
    check.after_step(sim, [_event(sim, "stole", genzo, rack)])  # a townsman
    check.after_step(sim, [_event(sim, "stole", kaz, rack.model_copy(update={"store": "farmhouse-1-chest"}))])
    assert (check.outcome(sim).value, check.rice) == (1, 7)
    sim.state.tick += DAY_MINUTES
    check.after_step(sim, [_event(sim, "stole", kaz, rack)])
    assert check.outcome(sim).value == 2
    assert q1.Raids.overall({1: Outcome(1, True, ""), 7: Outcome(1, True, "")}).ok
    assert not q1.Raids.overall({1: Outcome(1, True, ""), 7: Outcome(0, True, "")}).ok


def test_band_b_s_obsidian_sales_count_and_nobody_else_s(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    nim, ama = _band(sim, "nim"), _band(sim, "ama", "band_a")
    check = q1.ObsidianSales()
    check.start(sim)
    shard = Traded(item="obsidian", count=4, lots=4, coins=16, stall="market-stall", merchant="fumiko")
    check.after_step(sim, [_event(sim, "sold", nim, shard), _event(sim, "sold", ama, shard)])
    check.after_step(sim, [_event(sim, "bought", nim, shard)])
    check.after_step(sim, [_event(sim, "sold", nim, shard.model_copy(update={"item": "hide"}))])
    assert check.outcome(sim).value == 1
    assert q1.ObsidianSales.overall({1: Outcome(2, True, ""), 7: Outcome(2, True, "")}).ok
    assert not q1.ObsidianSales.overall({1: Outcome(2, True, ""), 7: Outcome(1, True, "")}).ok


def test_band_standings_must_move_the_way_their_deeds_and_trade_say(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    kaz, ama, goro = _band(sim, "kaz"), _band(sim, "ama", "band_a"), sim.add_citizen(make_spec("goro")).id
    check = q1.StandingDirection()
    check.start(sim)
    standing = society.SOCIETY.of(sim.state).standing
    assert check.outcome(sim).ok  # nothing done, nothing moved
    seen = Trespassed(kind="walls", owner="town", place="the castle town", witnesses=[goro])
    check.after_step(sim, [_event(sim, "trespassed", kaz, seen)])
    assert not check.outcome(sim).ok  # seen, yet band B's standing didn't fall
    standing[kaz]["town"] -= 5
    assert check.outcome(sim).ok
    sale = Traded(item="hide", count=1, lots=1, coins=11, stall="market-stall", merchant="fumiko")
    check.after_step(sim, [_event(sim, "sold", ama, sale)])
    assert not check.outcome(sim).ok  # band A traded, yet its standing didn't rise
    standing[ama]["town"] += 3
    assert check.outcome(sim).ok
    standing[kaz]["town"] += 5
    unseen = seen.model_copy(update={"witnesses": [kaz]})
    fresh = q1.StandingDirection()
    fresh.start(sim)
    fresh.after_step(sim, [_event(sim, "trespassed", kaz, unseen)])
    assert fresh.witnessed == 0


def test_tools_broken_add_up_over_the_seeds(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = q1.ToolsBroken()
    check.start(sim)
    check.after_step(sim, [_event(sim, "tool_broke", "tek", ToolBroke(item="flint spear", use="hunt"))])
    assert check.outcome(sim).value == 1 and "flint spear" in check.outcome(sim).words
    assert not q1.ToolsBroken.overall({1: Outcome(0, True, ""), 7: Outcome(0, True, "")}).ok


def test_the_road_share_counts_only_trips_over_four_hundred_metres(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    ann = sim.citizen(sim.add_citizen(make_spec("ann")).id)
    world = sim.world
    road = next(cell for cell in range(len(world.road_kinds)) if world.road_kinds[cell] != NONE)
    off = next(cell for cell in range(len(world.road_kinds)) if world.road_kinds[cell] == NONE)
    check = q1.RoadShare()
    check.start(sim)
    walk = ActionStarted(number=1, action="walk_to", args={}, label="the well")
    ended = ActionEnded(number=1, action="walk_to", outcome="done", text="")

    def step_to(cell: int) -> None:
        check.before_step(sim)
        ann.position, ann.cell = world.unit(cell), cell
        check.after_step(sim, [])

    ann.position, ann.cell = world.unit(off), off
    check.after_step(sim, [_event(sim, "action_started", ann.id, walk)])
    step_to(road)  # off road to the road cell: the metres walked count as on the road where they end
    step_to(off)
    check.after_step(sim, [_event(sim, "action_finished", ann.id, ended)])
    metres = world.distance_m(world.unit(off), world.unit(road))
    if 2 * metres > q1.TRIP_M:
        assert abs(check.outcome(sim).value - 0.5) < 1e-9 and not check.outcome(sim).ok
    else:
        assert check.metres == 0.0 and check.outcome(sim).ok  # a short walk isn't a trip


def test_ecology_faults_a_tree_slow_to_regrow_gold_that_rises_and_a_one_way_flint_seam(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    table = sim.world.nodes
    tree = next(i for i, kind in enumerate(table.kinds) if kind == "tree")
    check = q1.Ecology()
    check.start(sim)
    assert check.flint_a and all(int(table.caps[table.index[n]]) == q1.FLINT_A_CAP for n in check.flint_a)
    nodes.change(sim.core, tree, 0, None)  # felled: a stump
    felled = TreeFelled(node=table.ids[tree], yaw_deg=0.0, logs=10)
    check.after_step(sim, [_event(sim, "tree_felled", "bo", felled)])
    sim.state.tick += int(q1.TREE_REGROW_DAYS * DAY_MINUTES) + 1
    check.after_step(sim, [])
    assert check.outcome(sim).value == 1 and "tree" in check.outcome(sim).words
    flint = next(iter(check.flint_a))
    fell = NodeChanged(node=flint, kind="flint_seam", item="flint", before=30, after=29, stage="")
    check.after_step(sim, [_event(sim, "node_changed", "bo", fell)])
    assert check.outcome(sim).value == 2  # fell, never regrew
    check.after_step(sim, [_event(sim, "node_changed", None, fell.model_copy(update={"before": 29, "after": 30}))])
    assert check.outcome(sim).value == 1
    gold = NodeChanged(node="falls:gold", kind="gold_pool", item="gold", before=3, after=4, stage="")
    check.after_step(sim, [_event(sim, "node_changed", None, gold)])
    assert check.outcome(sim).value == 2


def test_rice_flows_are_measured_a_day_from_day_four_against_the_bible(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    check = q1.RiceFlows()
    check.start(sim)
    harvest = NodeChanged(node="paddy-1", kind="rice_paddy", item="rice", before=60, after=0, stage="")
    sim.state.tick = 3 * DAY_MINUTES  # day 3: not counted
    check.after_step(sim, [_event(sim, "node_changed", "genzo", harvest)])
    assert check.outcome(sim).words.startswith("harvest 0")
    sim.state.tick = 4 * DAY_MINUTES
    rice = Traded(item="rice", count=45, lots=23, coins=90, stall="market-stall", merchant="fumiko")
    events = [
        _event(sim, "node_changed", "genzo", harvest),
        _event(sim, "node_changed", "genzo", harvest.model_copy(update={"before": 60, "after": 0})),
        _event(sim, "tax_paid", "genzo", TaxChange(household="farmhouse-1", rice=48)),
        _event(sim, "sold", "genzo", rice),
        _event(sim, "bought", "goro", rice),
    ]
    check.after_step(sim, events)
    outcome = check.outcome(sim)
    assert outcome.ok and outcome.words.startswith("harvest 120, tax 48, stall in 45, stall out 45")
    fumiko = sim.add_citizen(make_spec("fumiko", home="main-e-2")).id
    own = ItemMoved(
        item="rice",
        count=10,
        source=ItemLocation(kind="store", id="market-stall"),
        destination=ItemLocation(kind="inventory", id=fumiko),
    )
    check.after_step(sim, [_event(sim, "item_moved", fumiko, own)])
    assert not check.outcome(sim).ok and "stall out 55" in check.outcome(sim).words  # the merchant's own rice too
