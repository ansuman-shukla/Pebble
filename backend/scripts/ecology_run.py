"""Run the world with its 22 scripted citizens headless (no database) and print how the ecology went.

    uv run python -m scripts.ecology_run [days] [seed]

Per game day: living animals (herbivores / predators / fish shoals), animal deaths by cause, respawns, injuries to
citizens and the deaths among them, hunts tried and won, fish caught, how much of the night each camp fire burned,
events and tick cost. At the end: the population per kind against its cap, and every injury with its conditions.
"""

import statistics
import sys
import time
from collections import Counter

from app.engine import citizen_brains
from app.sim.animals import GROUP_M, GROUP_SAFE
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES, NIGHT_ALTITUDE_DEG
from app.sim.fauna import HERBIVORES, PREDATORS
from app.sim.fire import SAFE_M, near_lit_fire
from app.sim.simulation import Simulation
from tests.sim_helpers import real_world


def main(days: int = 10, seed: int = 20261028) -> None:
    sim = Simulation.new(real_world(), seed=seed)
    sim.add_cast(load_citizens(CITIZENS))
    brains = citizen_brains(sim, seed)
    sim.drain()
    core = sim.core
    caps = Counter[str]()
    for group in sim.state.groups.values():
        caps[group.kind] += group.size
    injuries: list[str] = []
    print("day  herb  pred  fish  animal-deaths(hunted/prey)  spawns  injuries  citizen-deaths  hunts(won)  fish  "
          "camp-fire-night%  events  tick-ms")  # fmt: skip
    for day in range(days):
        events: Counter[str] = Counter()
        causes: Counter[str] = Counter()
        hunts = Counter[str]()
        fish = 0
        night_fire = Counter[str]()
        night_ticks = 0
        tick_ms: list[float] = []
        for _ in range(DAY_MINUTES):
            brains(sim)
            started = time.perf_counter()
            sim.step()
            tick_ms.append((time.perf_counter() - started) * 1000)
            for camp in ("band_a_camp:fire-pit", "band_b_camp:fire-pit"):
                fire = sim.state.fires[camp]
                if core.is_night_at(fire.position):
                    night_fire[f"{camp}:night"] += 1
                    night_fire[camp] += fire.lit
            night_ticks += 1
            for event in sim.drain():
                events[event.type] += 1
                payload = event.payload.model_dump()
                if event.type == "died" and event.actor_kind == "animal":
                    causes["hunted" if payload["cause"] == "hunted" else "prey"] += 1
                elif event.type in ("action_finished", "action_interrupted") and payload["action"] == "hunt":
                    hunts["won" if payload["text"].startswith("You bring down") else "lost"] += 1
                elif event.type == "action_finished" and payload["action"] == "fish" and payload["outcome"] == "done":
                    fish += 1
                elif event.type == "injured" and event.actor_kind == "citizen" and event.actor_id is not None:
                    victim = sim.citizen(event.actor_id)
                    near = sum(
                        1 for other in core.living() if core.distance_m(other.position, victim.position) <= GROUP_M
                    )
                    injuries.append(
                        f"day {day + 1} {event.actor_id}: {payload['cause']} -{payload['amount']:.0f} "
                        f"(sun {core.altitude(victim.position):.0f}°, night<{NIGHT_ALTITUDE_DEG}, "
                        f"people within {GROUP_M:.0f} m {near} (safe at {GROUP_SAFE}), "
                        f"lit fire within {SAFE_M:.0f} m {near_lit_fire(core, victim.position, SAFE_M)})"
                    )
        living = [a for a in sim.state.animals.values() if a.alive]
        herb = sum(a.kind in HERBIVORES for a in living)
        pred = sum(a.kind in PREDATORS for a in living)
        shoal = sum(a.kind == "fish" for a in living)
        dead = sum(not c.body.alive for c in sim.state.citizens.values())
        fire_share = " ".join(
            f"{100 * night_fire[c] / max(1, night_fire[f'{c}:night']):.0f}"
            for c in ("band_a_camp:fire-pit", "band_b_camp:fire-pit")
        )
        print(
            f"{day + 1:>3}  {herb:>4}  {pred:>4}  {shoal:>4}  {causes['hunted']:>13}/{causes['prey']:<12}  "
            f"{events['animal_spawned']:>6}  {events['injured']:>8}  {dead:>14}  "
            f"{hunts['won'] + hunts['lost']:>5}({hunts['won']})  {fish:>4}  {fire_share:>16}  "
            f"{sum(events.values()):>6}  {statistics.mean(tick_ms):.2f}"
        )
    living_by_kind = Counter(a.kind for a in sim.state.animals.values() if a.alive)
    print("\nkind        living / cap")
    for kind in sorted(caps):
        print(f"{kind:<11} {living_by_kind[kind]:>4} / {caps[kind]}")
    print("\ninjuries:")
    print("\n".join(injuries) or "none")
    for citizen in sorted(sim.state.citizens.values(), key=lambda c: c.id):
        if not citizen.body.alive:
            print(f"{citizen.id} died: {citizen.body.cause_of_death}")


if __name__ == "__main__":
    main(*(int(arg) for arg in sys.argv[1:3]))
