"""The run checks `scripts.world_run` judges a headless run by.

Each stream keeps its checks in its own module (`checks/<stream>.py`) and adds one row per check to `CHECKS` (the
seam: append rows, keep every row). A check sees one seed's run tick by tick and gives that seed's `Outcome`; its
`overall` judges all the seeds' outcomes together (by default: every seed passes).
"""

from scripts.checks import b1, x0
from scripts.checks.base import Check

CHECKS: tuple[type[Check], ...] = (*x0.CHECKS, *b1.CHECKS)
