"""Ecology, once per tick: fires burn down and animals live (`app.sim.animals`).

Wild plants, fish and minerals are nodes (10-world-v1 §1.1): they grow back in the `nodes` system's own tick hook
(`app.sim.nodes.grow`), each piece one `node_changed`.
"""

from app.sim import animals, fire
from app.sim.core import SimCore


def step(core: SimCore) -> None:
    """Advance the ecology by one tick."""
    fire.burn(core)
    animals.step(core)
