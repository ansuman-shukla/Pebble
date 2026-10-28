"""Which database the test suite uses. Kept free of app imports: conftest calls it before settings are built."""

import re
from pathlib import Path

BASE = "pebble_test"
MAX_SLUG = 40
REPO_ROOT = Path(__file__).resolve().parents[2]


def suite_database_name(repo_root: Path = REPO_ROOT, override: str | None = None) -> str:
    """`pebble_test` in the main checkout, `pebble_test_<worktree dir>` in a git worktree, or `override` if given.

    Each worktree gets its own database so concurrent runs can't truncate each other's committed rows.
    """
    if override:
        if not override.startswith(BASE):
            raise ValueError(f"PEBBLE_TEST_DB must start with {BASE!r}, got {override!r}")
        return override
    if not (repo_root / ".git").is_file():  # a worktree's `.git` is a file pointing at the main repo
        return BASE
    slug = re.sub(r"[^a-z0-9_]+", "_", repo_root.name.lower()).strip("_")[:MAX_SLUG].rstrip("_")
    return f"{BASE}_{slug}" if slug else BASE
