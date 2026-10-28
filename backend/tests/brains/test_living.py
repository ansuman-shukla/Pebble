"""The M7 done-when: the 15 scripted citizens live 10 game days headless without getting stuck.

One 10-day run (~40 s) feeds every test here: nobody dies (deaths only from real causes, and the default cast
doesn't starve or parch), everyone keeps making progress and moving, nobody passes through the town's walls,
bands sleep at camp at night and forage by day, the farmers work the fields and the storehouse fills up.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pytest

from app.engine import citizen_brains
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.navigation import Planner
from app.sim.perception import HOME_RADIUS_M
from app.sim.simulation import Simulation
from app.sim.world import SimWorld
from tests.sim_helpers import local_hour

DAYS = 10
SEED = 20261028
PROGRESS = frozenset({"walk_to", "gather", "eat", "drink", "work", "sleep"})
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
    said: int = 0


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
    for _ in range(DAYS * DAY_MINUTES):
        brains(sim)
        before = {c.id: c.position for c in sim.state.citizens.values()}
        sim.step()
        day = (sim.tick - 1) // DAY_MINUTES
        for event in sim.drain():
            if event.type == "died" and event.actor_id is not None:
                out.deaths.append((event.actor_id, str(getattr(event.payload, "cause", ""))))
            elif event.type == "said":
                out.said += 1
            elif event.type == "action_started" and event.actor_id is not None:
                payload = event.payload.model_dump()
                kind = str(payload["args"].get("task", payload["action"]))
                out.started[(event.actor_id, day, kind)] += 1
        for citizen in sim.state.citizens.values():
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
        if sim.tick % DAY_MINUTES == 0:
            out.rice.append(sim.state.stores[STORE].get("rice", 0))
    return out


def test_nobody_dies_in_ten_days(life: Life) -> None:
    assert life.deaths == []
    assert all(c.body.alive and c.body.health > 50 for c in life.sim.state.citizens.values())


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
    assert len(bands) == 9
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
