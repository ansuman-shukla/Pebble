"""Run the 22 citizens with their scripted brains headless (no database) and print how their days went.

    uv run python -m scripts.citizens_run [days] [seed]

Per game day: deaths, the town storehouse's rice, food the bands carry, events, decisions (look_around), tick cost;
at the end: per citizen the share of time in each activity and the longest awake stretch without real progress.
"""

import statistics
import sys
import time
from collections import Counter, defaultdict

from app.engine import citizen_brains
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.items import ITEMS
from app.sim.simulation import Simulation
from tests.sim_helpers import real_world

PROGRESS = frozenset({"walk_to", "gather", "eat", "drink", "work", "sleep"})


def main(days: int = 10, seed: int = 20261028) -> None:
    world = real_world()
    sim = Simulation.new(world, seed=seed)
    cast = load_citizens(CITIZENS)
    for store_id, items in cast.stores.items():
        for item, count in items.items():
            sim.stock_store(store_id, item, count)
    for spec in cast.citizens:
        sim.add_citizen(spec)
    brains = citizen_brains(sim, seed)
    sim.drain()
    activity: dict[str, Counter[str]] = defaultdict(Counter)
    last_progress = dict.fromkeys(sim.state.citizens, 0)
    longest_stall = dict.fromkeys(sim.state.citizens, 0)
    print("day  dead  rice  band-food  events  decisions  said  tick-ms(mean/p99)  brain-ms(mean/max)")
    for day in range(days):
        events: Counter[str] = Counter()
        tick_ms: list[float] = []
        brain_ms: list[float] = []
        for _ in range(DAY_MINUTES):
            started = time.perf_counter()
            brains(sim)
            thought = time.perf_counter()
            sim.step()
            done = time.perf_counter()
            brain_ms.append((thought - started) * 1000)
            tick_ms.append((done - thought) * 1000)
            for event in sim.drain():
                events[event.type] += 1
                if event.type == "action_started" and event.actor_id is not None:
                    if getattr(event.payload, "action", None) in PROGRESS:
                        last_progress[event.actor_id] = sim.tick
            for citizen in sim.state.citizens.values():
                kind = "dead" if not citizen.body.alive else citizen.action.kind if citizen.action else "idle"
                activity[citizen.id][kind] += 1
                if citizen.body.alive and citizen.action is not None and citizen.action.kind in PROGRESS:
                    last_progress[citizen.id] = sim.tick
                stall = sim.tick - last_progress[citizen.id]
                longest_stall[citizen.id] = max(longest_stall[citizen.id], stall)
        dead = sum(not c.body.alive for c in sim.state.citizens.values())
        rice = sim.state.stores.get("store-2", {}).get("rice", 0)
        band_food = sum(
            ITEMS[item].food * count
            for c in sim.state.citizens.values()
            if c.region != "town"
            for item, count in c.inventory.items()
        )
        tick_ms.sort()
        print(
            f"{day + 1:>3}  {dead:>4}  {rice:>4}  {band_food:>9.0f}  {sum(events.values()):>6}  "
            f"{events['perceived']:>9}  {events['said']:>4}  "
            f"{statistics.mean(tick_ms):.2f}/{tick_ms[int(len(tick_ms) * 0.99)]:.2f}  "
            f"{statistics.mean(brain_ms):.2f}/{max(brain_ms):.1f}"
        )
    print("\ncitizen    alive  hunger thirst energy health  longest-stall-h  activity shares")
    for cid, citizen in sorted(sim.state.citizens.items()):
        body = citizen.body
        shares = activity[cid]
        total = sum(shares.values())
        top = ", ".join(f"{kind} {count / total:.0%}" for kind, count in shares.most_common(6))
        print(
            f"{cid:<10} {body.alive!s:<5}  {body.hunger:>6.0f} {body.thirst:>6.0f} {body.energy:>6.0f} "
            f"{body.health:>6.0f}  {longest_stall[cid] / 60:>15.1f}  {top}"
        )


if __name__ == "__main__":
    main(*(int(arg) for arg in sys.argv[1:3]))
