"""Tick cost and event volume of the simulation core: `uv run python -m scripts.bench_sim [citizens] [game hours]`.

Citizens get a crude busy routine (walk between town places, drink when thirsty, chat now and then) through the
world api, so walking, perception and interrupts all run. No database: events are only counted.
"""

import statistics
import sys
import time
from collections import Counter

from app.core.rng import Rng
from app.sim.citizens import CitizenSpec
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.snapshot import canonical_json, take_snapshot
from app.sim.world import sim_world_from_view
from app.world.generate import GENERATOR
from app.world.spec import load_site_kinds, load_world_spec
from app.world_api.facade import WorldApi

PLACES = ["the well", "the market", "the main gate", "the west gate", "the castle", "the storehouses", "home"]
KNOWN = ["town", "well", "market", "main-gate", "west-gate", "castle", "storehouses"]


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    world = sim_world_from_view(GENERATOR.generate(load_world_spec(), load_site_kinds()))
    sim = Simulation.new(world, planner=Planner(world))
    homes = sorted(s.id for s in world.structures.values() if s.is_home)
    rng = Rng(1)
    for index in range(count):
        home = world.structures[homes[index % len(homes)]]
        sim.add_citizen(
            CitizenSpec(
                id=f"c{index}",
                name=f"Citizen{index}",
                look="town-farmer",
                appearance=f"a person with a number {index} cloak",
                age=18 + index % 50,
                at=home.door_xz,
                home=home.id,
                knows_places=KNOWN,
            )
        )
    sim.drain()
    durations: list[float] = []
    inputs: list[float] = []
    events: Counter[str] = Counter()
    for _ in range(hours * 60):
        started = time.perf_counter()
        for citizen in sim.core.living():
            if citizen.action is not None or citizen.body.asleep:
                continue
            api = WorldApi(sim, citizen.id)
            if citizen.body.thirst > 50 and sim.world.distance_m(citizen.position, world.places["well"].stand) < 3:
                api.drink()
            elif citizen.body.thirst > 50:
                api.walk_to_place("the well")
            elif rng.random() < 0.05:
                api.say("Good day to you!")
            else:
                api.walk_to_place(PLACES[rng.randint(0, len(PLACES) - 1)])
        inputs.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        sim.step()
        durations.append((time.perf_counter() - started) * 1000)
        events.update(event.type for event in sim.drain())
    snapshot_kb = len(canonical_json(take_snapshot(sim.state))) / 1000
    durations.sort()
    per_day = 24 / hours
    print(f"{count} citizens, {hours} game hours ({len(durations)} ticks)")
    print(
        f"tick ms: mean {statistics.fmean(durations):.2f}, p50 {durations[len(durations) // 2]:.2f}, "
        f"p99 {durations[int(len(durations) * 0.99)]:.2f}, max {durations[-1]:.2f}"
    )
    print(f"actions between ticks (planning walks etc.) ms: mean {statistics.fmean(inputs):.2f}, max {max(inputs):.2f}")
    print(f"events per game day: {round(sum(events.values()) * per_day)}")
    print("  " + ", ".join(f"{kind} {round(n * per_day)}" for kind, n in events.most_common()))
    print(f"snapshot {snapshot_kb:.0f} kB")


if __name__ == "__main__":
    main()
