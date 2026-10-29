"""Run the world with its scripted citizens headless (no database) on some seeds and judge it by the run checks.

    uv run python -m scripts.world_run [--days 14] [--seeds 20261028,7] [--only x0,e1.sales]

`--seeds` takes a comma list of seeds ("7," is the one seed 7) or a count N for the first N sweep seeds
(20261028, 7, 1, 2, 3, ...): `--seeds 5` is the 5-seed sweep of the probe-first triage. `--only` keeps the checks
with those names or of those streams. Prints each check per seed and over all seeds; exits 1 if any check fails.
"""

import argparse
import sys
from collections.abc import Sequence

from app.brains.runner import CitizenBrains
from app.engine import citizen_brains
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from scripts.checks import CHECKS
from scripts.checks.base import Check, Outcome
from tests.sim_helpers import real_world

SWEEP_SEEDS = (20261028, 7, 1, 2, 3, 4, 5, 6, 8, 9)
DEFAULT_SEEDS = "20261028,7"


def parse_seeds(text: str) -> tuple[int, ...]:
    if "," in text:
        return tuple(int(part) for part in text.split(",") if part.strip())
    count = int(text)
    if not 1 <= count <= len(SWEEP_SEEDS):
        raise argparse.ArgumentTypeError(
            f"a count of sweep seeds is 1 to {len(SWEEP_SEEDS)}; for one seed say '{text},'"
        )
    return SWEEP_SEEDS[:count]


def select(checks: Sequence[type[Check]], only: str | None) -> list[type[Check]]:
    """The checks named in `only` (comma list of check names or streams), or all of them."""
    if only is None:
        return list(checks)
    wanted = {part.strip() for part in only.split(",") if part.strip()}
    chosen = [check for check in checks if check.name in wanted or check.name.split(".")[0] in wanted]
    unknown = wanted - {check.name for check in chosen} - {check.name.split(".")[0] for check in chosen}
    if unknown:
        raise SystemExit(f"no checks named {sorted(unknown)}; known: {[check.name for check in checks]}")
    return chosen


def populated(seed: int, planner: Planner) -> tuple[Simulation, CitizenBrains]:
    """A new run on the real world: the cast and their stores in, each with their scripted brain."""
    sim = Simulation.new(planner.world, seed=seed, planner=planner)
    cast = load_citizens(CITIZENS)
    for store_id, items in cast.stores.items():
        for item, count in items.items():
            sim.stock_store(store_id, item, count)
    for spec in cast.citizens:
        sim.add_citizen(spec)
    brains = citizen_brains(sim, seed)
    sim.drain()
    return sim, brains


def run_seed(seed: int, days: int, kinds: Sequence[type[Check]], planner: Planner) -> dict[str, Outcome]:
    sim, brains = populated(seed, planner)
    checks = [kind() for kind in kinds]
    for check in checks:
        check.start(sim)
    for _ in range(days * DAY_MINUTES):
        brains(sim)
        for check in checks:
            check.before_step(sim)
        sim.step()
        events = sim.drain()
        for check in checks:
            check.after_step(sim, events)
    return {check.name: check.outcome(sim) for check in checks}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.world_run", description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seeds", type=parse_seeds, default=parse_seeds(DEFAULT_SEEDS))
    parser.add_argument("--only", help="comma list of check names or streams")
    args = parser.parse_args(argv)
    kinds = select(CHECKS, args.only)
    planner = Planner(real_world())
    per_seed: dict[int, dict[str, Outcome]] = {}
    for seed in args.seeds:
        per_seed[seed] = run_seed(seed, args.days, kinds, planner)
        print(f"seed {seed}: " + "; ".join(f"{name} {o.words}" for name, o in per_seed[seed].items()), flush=True)
    print(f"\n{args.days} days, seeds {', '.join(map(str, args.seeds))}")
    failed = 0
    for kind in kinds:
        overall = kind.overall({seed: outcomes[kind.name] for seed, outcomes in per_seed.items()})
        cells = "  ".join(
            f"{per_seed[seed][kind.name].words}{'' if per_seed[seed][kind.name].ok else ' FAIL'}" for seed in args.seeds
        )
        print(f"{'ok  ' if overall.ok else 'FAIL'} {kind.name:<20} {overall.words:<32} | {cells}")
        failed += not overall.ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
