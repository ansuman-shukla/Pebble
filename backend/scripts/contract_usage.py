"""Run the world with its 22 scripted citizens headless (no database) and count how they use the world contract.

    uv run python -m scripts.contract_usage [days] [seed]

Counts every action the brains call (by name, `walk_to` by what it aims at, with their outcomes) and
every part of the perceptions they receive (non-empty fields, thing kinds, plants, nearness words, times of day and
heard volumes). Actions or parts that are never used are listed at the end.
"""

import sys
from collections import Counter
from typing import get_args

from app.engine import citizen_brains
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.simulation import Simulation
from app.world_api.models import (
    Action,
    ActionName,
    ActionResult,
    Nearness,
    Perception,
    SelfView,
    ThingKind,
    TimeOfDay,
    Volume,
    WalkTo,
)
from tests.sim_helpers import real_world

INSTANT = ("say", "pick_up", "drop", "give", "recall")
actions = Counter[str]()
parts = Counter[str]()


def count_action(action: Action) -> None:
    actions[action.action] += 1
    if isinstance(action, WalkTo):
        actions[f"walk_to:{action.target.kind}"] += 1


def count_perception(p: Perception) -> None:
    parts["look_around"] += 1
    for name in ("place", "time", "time_of_day", "people", "animals", "things", "heard"):
        if getattr(p, name):
            parts[name] += 1
    parts["you.feeling"] += bool(p.you.feeling)
    parts["you.carrying"] += bool(p.you.carrying)
    parts[f"time_of_day:{p.time_of_day}"] += 1
    for seen in p.people + p.animals + p.things:
        parts[f"nearness:{seen.nearness}"] += 1
        parts["seen.doing"] += seen.doing is not None
    for seen in p.things:
        parts[f"thing:{seen.kind}"] += 1
        if seen.resource is not None:
            parts[f"plant:{seen.resource}"] += 1
    for heard in p.heard:
        parts[f"heard:{heard.volume}"] += 1


def instrument(sim: Simulation) -> None:
    perceive, check_self, instant, start = sim.perceive, sim.check_self, sim.instant, sim.start

    def perceive_counted(citizen_id: str) -> Perception:
        perception = perceive(citizen_id)
        actions["look_around"] += 1
        count_perception(perception)
        return perception

    def check_self_counted(citizen_id: str) -> SelfView:
        actions["check_self"] += 1
        return check_self(citizen_id)

    def instant_counted(citizen_id: str, action: Action) -> ActionResult:
        count_action(action)
        result = instant(citizen_id, action)
        actions[f"{action.action}={result.outcome}"] += 1
        return result

    def start_counted(citizen_id: str, action: Action) -> int:
        count_action(action)
        return start(citizen_id, action)

    sim.perceive = perceive_counted  # type: ignore[method-assign]  # counting wrapper for this script only
    sim.check_self = check_self_counted  # type: ignore[method-assign]  # counting wrapper for this script only
    sim.instant = instant_counted  # type: ignore[method-assign]  # counting wrapper for this script only
    sim.start = start_counted  # type: ignore[method-assign]  # counting wrapper for this script only


def main(days: int = 10, seed: int = 20261028) -> None:
    sim = Simulation.new(real_world(), seed=seed)
    sim.add_cast(load_citizens(CITIZENS))
    brains = citizen_brains(sim, seed)
    sim.drain()
    instrument(sim)
    finished = Counter[str]()
    for _ in range(days * DAY_MINUTES):
        brains(sim)
        sim.step()
        for event in sim.drain():
            if event.type in ("action_finished", "action_interrupted"):
                payload = event.payload.model_dump()
                finished[f"{payload['action']}={payload['outcome']}"] += 1
    alive = sum(c.body.alive for c in sim.state.citizens.values())
    print(f"{days} game days, {alive}/{len(sim.state.citizens)} alive\n\nactions:")
    for name in get_args(ActionName):
        outcomes = actions if name in INSTANT else finished  # a done instant action leaves no action event
        detail = ", ".join(f"{k.split('=')[1]} {n}" for k, n in sorted(outcomes.items()) if k.startswith(name + "="))
        targets = ", ".join(f"{k.split(':')[1]} {n}" for k, n in actions.items() if k.startswith(name + ":"))
        print(f"  {name:<12} {actions[name]:>7}  {targets}  [{detail}]")
    print("\nperception parts:")
    expected = (
        ["place", "time", "time_of_day", "people", "animals", "things", "heard", "you.feeling", "you.carrying"]
        + ["seen.doing"]
        + [f"time_of_day:{t}" for t in get_args(TimeOfDay)]
        + [f"nearness:{n}" for n in get_args(Nearness)]
        + [f"thing:{k}" for k in get_args(ThingKind)]
        + [f"heard:{v}" for v in get_args(Volume)]
    )
    for name in expected + sorted(k for k in parts if k.startswith("plant:")):
        print(f"  {name:<28} {parts[name]:>8}")
    unused = [name for name in get_args(ActionName) if not actions[name]] + [
        name for name in expected if not parts[name]
    ]
    print("\nunused:", ", ".join(unused) or "none")


if __name__ == "__main__":
    main(*(int(arg) for arg in sys.argv[1:3]))
