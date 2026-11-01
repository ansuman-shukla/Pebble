"""The run checks `scripts.world_run` judges a headless run by.

Each stream keeps its checks in its own module (`checks/<stream>.py`) and adds one row per check to `CHECKS` (the
seam: append rows, keep every row). A check sees one seed's run tick by tick and gives that seed's `Outcome`; its
`overall` judges all the seeds' outcomes together (by default: every seed passes).
"""

from scripts.checks import a1, b1, br0, br1, br2, e1, e2, e3, j1, j2, k1, n1, q1, s1, sc1, t1, x0
from scripts.checks.base import Check

CHECKS: tuple[type[Check], ...] = (
    *x0.CHECKS,
    *b1.CHECKS,
    *e1.CHECKS,
    *s1.CHECKS,
    *j1.CHECKS,
    *br0.CHECKS,
    *e2.CHECKS,
    *a1.CHECKS,
    *e3.CHECKS,
    *n1.CHECKS,
    *t1.CHECKS,
    *k1.CHECKS,
    *j2.CHECKS,
    *sc1.CHECKS,
    *br1.CHECKS,
    *br2.CHECKS,
    *q1.CHECKS,
)
