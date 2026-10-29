"""The M7 and M6 done-whens: the 22 scripted citizens live 10 game days headless among the animals.

One 10-day run (~40 s) feeds every test here: nobody dies (deaths only from real causes, and the default cast
doesn't starve or parch), everyone keeps making progress and moving, nobody passes through the town's walls,
bands sleep at camp at night and forage by day, the farmers work the fields and the storehouse fills up; animal
populations stay within their caps, predators hurt people only at dusk or night when they're alone and away from
fire, hunters hunt, the camp fires burn through the nights and the guard lights the gate's fire baskets.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from app.engine import citizen_brains
from app.observability.events import Injured, TickSummary
from app.sim.animals import DUSK_ALTITUDE_DEG, GROUP_M, GROUP_SAFE
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES, SECONDS_PER_TICK
from app.sim.fauna import HERBIVORES, PREDATORS
from app.sim.fire import SAFE_M, near_lit_fire
from app.sim.navigation import Planner
from app.sim.perception import HOME_RADIUS_M
from app.sim.simulation import Simulation
from app.sim.vec import Vec3
from app.sim.world import SimWorld
from tests.sim_helpers import drawn_on, local_hour

DAYS = 10
SEED = 20261028
PROGRESS = frozenset({"walk_to", "gather", "eat", "drink", "work", "sleep"})
DRAWN_M = 0.01  # a spectator draws every move from where the last one ended, to where the sim has them
MAX_STALL_TICKS = 6 * 60  # awake, nobody stands about (only waiting or resting) longer than this
STORE = "store-2"


@dataclass
class Life:
    sim: Simulation
    deaths: list[tuple[str, str]] = field(default_factory=list)
    walls: list[tuple[int, str]] = field(default_factory=list)  # (tick, citizen) standing on a blocked town cell
    stall: dict[str, int] = field(default_factory=dict)  # longest awake stretch without progress, in ticks
    moved_m: dict[tuple[str, int], float] = field(default_factory=lambda: defaultdict(float))  # (citizen, day)
    started: Counter[tuple[str, int, str]] = field(default_factory=Counter)  # (citizen, day, action or task)
    night: dict[str, list[tuple[bool, float]]] = field(default_factory=lambda: defaultdict(list))  # (asleep, m home)
    rice: list[int] = field(default_factory=list)  # in the storehouse at the end of each day
    # health lost to hunger and thirst: drops in ticks without an injury (health only drops from those, bodies.py)
    need_damage: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    said: int = 0
    attacks: list[tuple[str, float, int, bool, bool]] = field(default_factory=list)  # who, sun, near, fire, town
    populations: list[Counter[str]] = field(default_factory=list)  # living animals by kind at the end of each day
    hunts_won: int = 0
    camp_fire: Counter[str] = field(default_factory=Counter)  # (camp) minutes lit / (camp:night) night minutes
    baskets_lit: list[int] = field(default_factory=list)  # gate baskets burning at local midnight, each night
    actions: Counter[str] = field(default_factory=Counter)  # durative actions started, by name
    gifts: int = 0  # items handed from one citizen to another
    moves: Counter[str] = field(default_factory=Counter)  # citizens' moves in a tick, by the action that moved them
    off_drawn: list[tuple[int, str, float]] = field(default_factory=list)  # (tick, citizen, metres) drawn elsewhere


@pytest.fixture(scope="module")
def life(sim_world: SimWorld, planner: Planner) -> Life:
    sim = Simulation.new(sim_world, seed=SEED, planner=planner)
    cast = load_citizens(CITIZENS)
    for store_id, items in cast.stores.items():
        for item, count in items.items():
            sim.stock_store(store_id, item, count)
    for spec in cast.citizens:
        sim.add_citizen(spec)
    brains = citizen_brains(sim, SEED)
    sim.drain()
    out = Life(sim=sim, stall=dict.fromkeys(sim.state.citizens, 0), rice=[sim.state.stores[STORE]["rice"]])
    walk = sim_world.town.walk
    last_progress = dict.fromkeys(sim.state.citizens, 0)
    drawn = {c.id: c.position for c in sim.state.citizens.values()}  # where a spectator draws them as a tick begins
    for _ in range(DAYS * DAY_MINUTES):
        brains(sim)
        before = {c.id: c.position for c in sim.state.citizens.values()}
        health = {c.id: c.body.health for c in sim.state.citizens.values()}
        injured: set[str] = set()
        moving = {c.id: c.action.kind for c in sim.state.citizens.values() if c.action is not None}
        sim.step()
        day = (sim.tick - 1) // DAY_MINUTES
        for event in sim.drain():
            if event.type == "tick_summary":
                assert isinstance(event.payload, TickSummary)
                _draw(out, event.payload, drawn, before, moving)
            elif event.type == "died" and event.actor_kind == "citizen" and event.actor_id is not None:
                out.deaths.append((event.actor_id, str(getattr(event.payload, "cause", ""))))
            elif isinstance(event.payload, Injured) and event.actor_kind == "citizen" and event.actor_id is not None:
                injured.add(event.actor_id)
                words, _ = sim.core.hurt.get(event.actor_id, ("", 0))
                if words.endswith("attacks you"):  # a predator going for them (not game turning on a hunter)
                    victim = sim.citizen(event.actor_id)
                    near = sum(sim.core.distance_m(o.position, victim.position) <= GROUP_M for o in sim.core.living())
                    out.attacks.append(
                        (
                            victim.id,
                            sim.core.altitude(victim.position),
                            near,
                            near_lit_fire(sim.core, victim.position, SAFE_M),
                            sim_world.town_point(victim.position) is not None,
                        )
                    )
            elif event.type == "action_finished" and getattr(event.payload, "action", "") == "hunt":
                out.hunts_won += 1
            elif event.type == "said":
                out.said += 1
            elif event.type == "item_moved":
                shift = event.payload.model_dump()
                out.gifts += shift["source"]["kind"] == shift["destination"]["kind"] == "inventory"
            elif event.type == "action_started" and event.actor_id is not None:
                payload = event.payload.model_dump()
                out.actions[payload["action"]] += 1
                kind = str(payload["args"].get("task", payload["action"]))
                out.started[(event.actor_id, day, kind)] += 1
        for citizen in sim.state.citizens.values():
            if citizen.id not in injured:
                out.need_damage[citizen.id] += max(0.0, health[citizen.id] - citizen.body.health)
            if not citizen.body.alive:
                continue
            moved = sim_world.distance_m(before[citizen.id], citizen.position)
            out.moved_m[(citizen.id, day)] += moved
            local = sim_world.town_point(citizen.position)
            if local is not None and not walk.is_walkable(*local):
                out.walls.append((sim.tick, citizen.id))
            action = citizen.action
            if citizen.body.asleep or moved > 0 or (action is not None and action.kind in PROGRESS):
                last_progress[citizen.id] = sim.tick
            out.stall[citizen.id] = max(out.stall[citizen.id], sim.tick - last_progress[citizen.id])
            if citizen.region != "town" and 0.5 <= local_hour(sim, citizen.id) < 4.0:
                home = sim_world.structures[str(citizen.home)]
                out.night[citizen.id].append((citizen.body.asleep, sim_world.distance_m(citizen.position, home.door)))
        for camp in ("band_a_camp:fire-pit", "band_b_camp:fire-pit"):
            fire = sim.state.fires[camp]
            if sim.core.is_night_at(fire.position):
                out.camp_fire[f"{camp}:night"] += 1
                out.camp_fire[camp] += fire.lit
        if (sim.tick + 8 * 60) % DAY_MINUTES == 0:  # midnight at the town
            out.baskets_lit.append(sum(sim.state.fires[b].lit for b in ("main-gate-fire-w", "main-gate-fire-e")))
        if sim.tick % DAY_MINUTES == 0:
            out.rice.append(sim.state.stores[STORE].get("rice", 0))
            out.populations.append(Counter(a.kind for a in sim.state.animals.values() if a.alive))
    return out


def _draw(
    out: Life, summary: TickSummary, drawn: dict[str, Vec3], before: dict[str, Vec3], moving: Mapping[str, str]
) -> None:
    """Draws the tick as the globe does: each move along its streamed route for a tick from where it starts."""
    sim = out.sim
    for citizen in sim.state.citizens.values():
        gaps = [sim.world.distance_m(drawn[citizen.id], before[citizen.id])]
        moved = summary.moved.get(citizen.id)
        if moved is None or not moved.route:  # (a move of less than a millimetre is drawn standing)
            drawn[citizen.id] = citizen.position
            gaps.append(sim.world.distance_m(before[citizen.id], citizen.position))
        else:
            out.moves[moving[citizen.id]] += 1
            gaps.append(sim.world.distance_m(moved.route[0].unit, before[citizen.id]))
            drawn[citizen.id] = drawn_on(moved.route, SECONDS_PER_TICK)
            gaps.append(sim.world.distance_m(drawn[citizen.id], citizen.position))
        if max(gaps) > DRAWN_M:
            out.off_drawn.append((sim.tick, citizen.id, max(gaps)))


def test_nobody_dies_in_ten_days(life: Life) -> None:
    assert life.deaths == []
    assert all(c.body.alive and c.body.health > 50 for c in life.sim.state.citizens.values())
    # nobody goes long without water or food: a night parched (thirsty to bed) costs dozens of health points; injuries
    # aren't counted here (game turning on a hunter is a hunter's risk, D70; predators have their own test)
    worst = max(life.need_damage.items(), key=lambda item: item[1], default=("nobody", 0.0))
    assert worst[1] <= 10, f"{worst[0]} lost {worst[1]:.0f} health to hunger and thirst"


def test_every_move_is_drawn_as_walking_from_where_the_last_one_ended(life: Life) -> None:
    """Walks (one tick long or many), follows and hunts alike: no move is ever drawn as a jump."""
    assert life.off_drawn == [], sorted(life.off_drawn, key=lambda g: -g[2])[:20]
    assert life.moves["walk_to"] > 5000 and life.moves["follow"] > 0 and life.moves["hunt"] > 0


def test_everyone_keeps_doing_things_and_moving(life: Life) -> None:
    worst = max(life.stall.items(), key=lambda item: item[1])
    assert worst[1] < MAX_STALL_TICKS, f"{worst[0]} stood about for {worst[1] / 60:.1f} game hours"
    for citizen_id in life.sim.state.citizens:
        for day in range(DAYS):
            assert life.moved_m[(citizen_id, day)] > 100, f"{citizen_id} barely moved on day {day}"
    assert life.said > 15 * DAYS  # people greet each other


def test_nobody_walks_through_the_town_walls(life: Life) -> None:
    assert life.walls == []


def test_bands_sleep_at_camp_at_night_and_forage_by_day(life: Life) -> None:
    bands = [c for c in life.sim.state.citizens.values() if c.region != "town"]
    assert len(bands) == 11
    for citizen in bands:
        samples = life.night[citizen.id]
        assert len(samples) > 3 * 60 * (DAYS - 1)  # every night was sampled
        assert all(asleep for asleep, _ in samples), f"{citizen.id} was awake in the middle of the night"
        assert max(distance for _, distance in samples) <= HOME_RADIUS_M, f"{citizen.id} slept away from home"
        for day in range(1, DAYS):
            assert life.started[(citizen.id, day, "gather")] >= 1, f"{citizen.id} didn't forage on day {day}"
    for day in range(1, DAYS):
        assert sum(life.started[(c.id, day, "gather")] for c in bands) >= 3 * len(bands)


def test_town_folk_sleep_at_home_and_work_their_roles(life: Life) -> None:
    tasks = {"genzo": "farm", "aiko": "weave", "fumiko": "trade", "kenji": "guard", "masanori": "govern"}
    for day in range(1, DAYS):
        for citizen_id, task in tasks.items():
            assert life.started[(citizen_id, day, task)] >= 2, f"{citizen_id} didn't {task} on day {day}"
        assert life.started[("genzo", day, "store food")] >= 1
        assert life.started[("aiko", day, "farm")] >= 1  # she helps in the fields in the afternoon
        assert all(life.started[(c, day, "sleep")] >= 1 for c in ("genzo", "aiko", "hana", "masanori"))


def test_the_farmers_fill_the_storehouse(life: Life) -> None:
    rice = life.rice
    assert len(rice) == DAYS + 1
    assert rice[-1] > rice[0] + 200  # the harvest outpaces what six people eat
    assert all(later >= earlier for earlier, later in zip(rice[1:], rice[2:], strict=False))


def test_animal_populations_stay_within_caps_among_the_people(life: Life) -> None:
    caps: Counter[str] = Counter()
    for group in life.sim.state.groups.values():
        caps[group.kind] += group.size
    assert len(life.populations) == DAYS
    for living in life.populations:
        assert all(living[kind] <= cap for kind, cap in caps.items())
        assert all(living[kind] >= caps[kind] // 2 for kind in HERBIVORES)  # hunting pressure, no extinction
        assert all(living[kind] >= caps[kind] - 1 for kind in PREDATORS)


def test_predators_hurt_people_only_alone_at_dusk_or_night_away_from_fire(life: Life) -> None:
    for victim, sun, near, by_fire, in_town in life.attacks:
        assert sun < DUSK_ALTITUDE_DEG, f"{victim} was attacked by day"
        assert near < GROUP_SAFE, f"{victim} was attacked in a group of {near}"
        assert not by_fire and not in_town, f"{victim} was attacked by a fire or inside the walls"


def test_hunters_hunt_and_the_fires_burn_through_the_night(life: Life) -> None:
    assert life.hunts_won >= DAYS // 2  # four hunters bring down game every other day or so
    for camp in ("band_a_camp:fire-pit", "band_b_camp:fire-pit"):
        share = life.camp_fire[camp] / life.camp_fire[f"{camp}:night"]
        assert share > 0.8, f"{camp} burned only {share:.0%} of the night"
    assert life.baskets_lit[1:] and all(lit == 2 for lit in life.baskets_lit[1:])  # the guard lights both baskets


def test_the_brains_use_every_action_but_recall(life: Life) -> None:
    """M9: the scripted brains exercise the whole v0 contract; `recall` belongs to agent minds (D74)."""
    durative = {"walk_to", "follow", "gather", "fish", "hunt", "eat", "drink", "make_fire", "feed_fire", "rest"}
    # `attack` hangs on a wolf happening to come close to a spear carrier, luck in this run; it's proven instead by
    # test_a_spear_carrier_drives_off_a_wolf_that_comes_close in tests/brains/test_wild_brains.py (D98)
    durative |= {"sleep", "work", "flee", "wait"}
    assert {name for name in durative if not life.actions[name]} == set()
    assert life.said > 0 and life.gifts > 0  # say, and give (hunters share their meat at camp)
