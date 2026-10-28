"""Merge the NPC jail settings into every account config of Pebble's private devin-switch.

Keeps keys ds manages itself (e.g. `attribution`, `hooks.SessionEnd`). Safe to re-run.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/devin_jail"))

from npc_settings import npc_settings  # noqa: E402 - path set above; experiments are not a package yet

ACCOUNTS = ROOT / ".runtime/ds/accounts"


def main() -> None:
    settings = npc_settings()
    configs = sorted(ACCOUNTS.glob("*/config/devin/config.json"))
    for path in configs:
        config = json.loads(path.read_text() or "{}")
        hooks = {**config.get("hooks", {}), **settings["hooks"]}
        config.update({**settings, "hooks": hooks})
        path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"applied NPC settings to {len(configs)} account configs")


if __name__ == "__main__":
    main()
