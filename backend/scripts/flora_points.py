"""Write the backend's own flora positions for the frontend's node tests (`frontend/tests/smoke/fixtures`).

Usage: `uv run python -m scripts.flora_points world.json out.json` with `world.json` from `GET /api/v1/world`.
Flora is generated from the world and its spec exactly as `GET /world/flora` serves it; the file holds the unit
vector (`Flora.units`) of every item within RADIUS_M of each spot below and of every STRIDE-th item, with the
world's seed, generator version and item count so a test can tell a stale file from a wrong position.
"""

import json
import sys
from pathlib import Path

import numpy as np

from app.world.flora import generate_flora
from app.world.spec import load_world_spec
from app.world.view import WorldView

SPOTS_DEG = {"elder_grove_bush": (11.3839, 6.4071)}  # lat, lon: where `nodes.spec.ts` stands
RADIUS_M = 300.0
STRIDE = 499


def unit_at(lat_deg: float, lon_deg: float) -> np.ndarray:
    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    return np.array([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)])


def main() -> None:
    view = WorldView.model_validate_json(Path(sys.argv[1]).read_text())
    flora = generate_flora(view, load_world_spec())
    units = flora.units
    chosen = set(range(0, len(flora), STRIDE))
    for lat, lon in SPOTS_DEG.values():
        distances = np.arccos(np.clip(units @ unit_at(lat, lon), -1, 1)) * view.radius_m
        chosen |= set(np.flatnonzero(distances <= RADIUS_M).tolist())
    points = {str(i): [round(float(v), 12) for v in units[i]] for i in sorted(chosen)}
    payload = {
        "seed": view.seed,
        "generator_version": view.generator_version,
        "count": len(flora),
        "points": points,
    }
    Path(sys.argv[2]).write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"wrote {len(points)} of {len(flora)} flora points to {sys.argv[2]}")


if __name__ == "__main__":
    main()
