"""Rice paddies (10-world-v1 §1.4): the six drawn paddies, each a node, run a three-day cycle by hand.

```
 work("farm") at a paddy spot (the farmer goes to the paddy that needs it most: ripe, then stubble, then growing):
   work goes in 20-minute sessions (an elder tends 30), so a cut-short session loses no more than itself:
   ripe ─▶ harvest: ≤ 10 rice a session (15 with a sickle)
   stubble ─▶ replant: seedlings, growth 0 (the day's tending)        ┐ a day's tending of a paddy adds 50:
   growing ─▶ tend: +17 a session, at most +50 a day; 100 = ripe, 60  ┘ three sessions, an hour (an elder's 1.5 h)
 gather("rice") at a ripe paddy's spot ─▶ one 20-minute harvest session
 local midnight ─▶ a ripe paddy left standing loses 2
```

So each paddy runs harvest and replant, tend, tend: 60 measures every three days, 120 a day from the six. The
paddies' state (stock, growth) lives in the `nodes` system; the day each paddy was last tended in its `tended`.
"""

from collections.abc import Callable

from app.sim import nodes, reach, slots, tax, wear
from app.sim.clock import town_clock
from app.sim.core import SimCore
from app.sim.items import ITEMS, amount_words, tool_in
from app.sim.node_table import PADDY_KIND
from app.sim.slots import Slot
from app.sim.state import ActionState, Citizen
from app.sim.vec import Vec3

FIELDS = "rice-fields"  # the place the paddies lie in
TEND_GROWTH = 50  # a day's tending of a paddy: an hour's work (10 §1.4)
TEND_SESSION = 17  # a 20-minute session's share of it (the last one of a day tops it up to 50)
SESSION_MINUTES = 20
ELDER_SESSION_MINUTES = 30
HARVEST = 10  # a session's rice by hand
SICKLE_HARVEST = 15
UNTENDED_LOSS = 2  # rice a ripe paddy left standing loses each night


def paddies(core: SimCore) -> list[int]:
    table = core.world.nodes
    return [node for node, kind in enumerate(table.kinds) if kind == PADDY_KIND]


def paddy_at(core: SimCore, unit: Vec3) -> int | None:
    """The paddy whose rect holds the point, if any."""
    local = core.world.town_point(unit)
    if local is None:
        return None
    table = core.world.nodes
    x, z = local
    for node in paddies(core):
        rect = table.paddy_rects[table.ids[node]]
        if rect.x0 <= x <= rect.x1 and rect.z0 <= z <= rect.z1:
            return node
    return None


def day(core: SimCore) -> int:
    return town_clock(core.state.tick)[0]


def is_ripe(core: SimCore, node: int) -> bool:
    return nodes.growth(core, node) >= nodes.RIPE and nodes.stock(core, node) > 0


def grown_today(core: SimCore, node: int) -> int:
    """The growth tending has added to a paddy today (a replanting counts as a whole day's tending)."""
    state, paddy = nodes.node_state(core), core.world.nodes.ids[node]
    return state.tended_growth.get(paddy, 0) if state.tended.get(paddy) == day(core) else 0


def tended_today(core: SimCore, node: int) -> bool:
    """It has had its day's tending (+50, or a replanting)."""
    return grown_today(core, node) >= TEND_GROWTH


def need(core: SimCore, node: int) -> int:
    """How much a paddy needs a farmer now (lower first): ripe, stubble to replant, growing, done for the day."""
    if is_ripe(core, node):
        return 0
    if tended_today(core, node):
        return 3
    return 1 if nodes.growth(core, node) >= nodes.RIPE else 2


def _by_need(core: SimCore, citizen: Citizen) -> list[Slot]:
    """Every paddy spot, the paddy that needs work most first (nearest first among equals)."""
    options = sorted(
        (need(core, node), core.distance_m(citizen.position, slot.position), slot.id, slot)
        for node in paddies(core)
        for slot in slots.node_slots(core, node)
    )
    return [option[3] for option in options]


def reserve(core: SimCore, citizen: Citizen) -> Vec3 | None:
    """A farmer walking to the rice fields goes to a free spot of the paddy that needs them most, claimed on the
    way (so the hour's work starts where the walk ends); None when every spot is taken."""
    for slot in _by_need(core, citizen):
        if slots.nearest_free(core, citizen, [slot]) is not None:
            return slots.claim(core, citizen, slot, slot.position)
    return None


def take_spot(core: SimCore, citizen: Citizen) -> Slot | str:
    """The farm task's spot: the paddy spot they stand on (the walk there chose it), else a free spot of the paddy
    that needs work most they can walk to within the tick, claimed; or why there is none."""
    held = slots.held_slot(core, citizen)
    if held is not None and held.task == slots.PADDY_TASK:
        if core.distance_m(citizen.position, held.position) <= slots.OCCUPY_M:
            here = core.world.nodes.index[held.owner]
            better = next((slot for slot in _by_need(core, citizen) if slots.nearest_free(core, citizen, [slot])), None)
            if better is None or need(core, core.world.nodes.index[better.owner]) >= need(core, here):
                return held
            return "Another paddy needs you more than this one; walk over to it first."  # the walk there takes it
    slot = slots.take_first_free(core, citizen, _by_need(core, citizen))
    return slot if slot is not None else "Others are working in the paddies; there's no room for you."


def minutes(core: SimCore, citizen: Citizen) -> int:
    """Farm work goes in sessions, so talk or a passer-by cuts short no more than one: a ripe paddy is harvested
    20 minutes at a time, tended 20 minutes at a time (an elder's 30: the bible's hour and a half a day)."""
    node = reach.node_held(core, citizen)
    if citizen.group == "elder" and node is not None and not is_ripe(core, node):
        return ELDER_SESSION_MINUTES
    return SESSION_MINUTES


def farm(core: SimCore, citizen: Citizen, _action: ActionState) -> str:
    """The farm task's finisher: harvest a ripe paddy, else tend it (replant stubble, grow the rice)."""
    node = reach.node_held(core, citizen)
    held = slots.held_slot(core, citizen)
    if node is None or held is None or core.world.nodes.kinds[node] != PADDY_KIND:
        return "You find no paddy at your feet to tend."
    if core.distance_m(citizen.position, held.position) > slots.OCCUPY_M:
        return "You never reached the paddy; the rice goes untended."
    if is_ripe(core, node):
        return harvest(core, citizen, node, sessions=1)
    if tended_today(core, node):
        return "You tend the paddy, but it needs nothing more today."
    state, paddy, so_far = nodes.node_state(core), core.world.nodes.ids[node], grown_today(core, node)
    state.tended[paddy] = day(core)
    growth = nodes.growth(core, node)
    if growth >= nodes.RIPE:  # stubble
        state.tended_growth[paddy] = TEND_GROWTH  # the day's tending
        nodes.change(core, node, 0, citizen, growth=0)
        return "You plant the stubbled paddy with young seedlings."
    added = min(TEND_SESSION, TEND_GROWTH - so_far)
    state.tended_growth[paddy] = so_far + added
    grown = min(nodes.RIPE, growth + added)
    if grown >= nodes.RIPE:
        state.tended_growth[paddy] = TEND_GROWTH  # ripe: that was the day's tending (replanted tomorrow at the soonest)
        nodes.change(core, node, int(core.world.nodes.caps[node]), citizen, growth=grown)
        return "You tend the paddy; the rice turns gold and is ready to harvest."
    nodes.change(core, node, 0, citizen, growth=grown)
    return "You tend the paddy; the rice grows green and tall."


def harvest(core: SimCore, citizen: Citizen, node: int, sessions: int) -> str:
    """Cut a ripe paddy's rice into the farmer's hands; a sickle wears with every session."""
    sickle = tool_in(citizen.inventory, "sickle")
    per = SICKLE_HARVEST if sickle is not None else HARVEST
    before = nodes.stock(core, node)
    count = min(per * sessions, before, core.room_for(citizen, "rice"))
    if count == 0:
        return "You can't carry any more." if before else "There's no rice left standing to harvest."
    seq = nodes.change(core, node, before - count, citizen)
    harvested = nodes.take_into(core, citizen, node, "rice", count, seq)
    tax.assess_harvest(core, citizen, count, harvested)  # the rice tax's one seam (D158)
    broke = False
    for _ in range(sessions if sickle is not None else 0):
        broke = wear.use_tool(core, citizen, "sickle", cause_seq=seq)
        if broke:
            break
    left = " The paddy is stubble now." if before - count == 0 else ""
    return f"You harvest {amount_words(count, ITEMS['rice'])}.{left}" + (" Your sickle breaks." if broke else "")


def lose_at_midnight(core: SimCore, now: Callable[[Vec3], bool]) -> None:
    """Midnight hook: a ripe paddy left standing loses a little rice (birds, rot, lodging)."""
    for node in paddies(core):
        before = nodes.stock(core, node)
        if is_ripe(core, node) and now(core.world.nodes.unit(node)):
            nodes.change(core, node, max(0, before - UNTENDED_LOSS), None)
