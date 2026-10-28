"""Each checkout gets its own test database: `pebble_test` in the main one, `pebble_test_<slug>` in a worktree."""

from pathlib import Path

import pytest

from tests.database_name import suite_database_name


def _main_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "Pebble"
    (root / ".git").mkdir(parents=True)
    return root


def _worktree(tmp_path: Path, name: str) -> Path:
    root = tmp_path / ".worktrees" / name
    root.mkdir(parents=True)
    (root / ".git").write_text("gitdir: /somewhere/.git/worktrees/x\n")
    return root


def test_main_checkout_uses_the_base_name(tmp_path: Path) -> None:
    assert suite_database_name(_main_checkout(tmp_path)) == "pebble_test"


def test_worktree_gets_its_own_name(tmp_path: Path) -> None:
    assert suite_database_name(_worktree(tmp_path, "testdb2")) == "pebble_test_testdb2"


def test_worktree_slug_is_sanitized_and_capped(tmp_path: Path) -> None:
    name = suite_database_name(_worktree(tmp_path, "-My.Feature--Branch-" + "x" * 60))
    assert name == "pebble_test_my_feature_branch_" + "x" * 22
    assert len(name) == len("pebble_test_") + 40


def test_worktree_without_usable_characters_falls_back_to_base(tmp_path: Path) -> None:
    assert suite_database_name(_worktree(tmp_path, "---")) == "pebble_test"


def test_override_wins(tmp_path: Path) -> None:
    assert suite_database_name(_worktree(tmp_path, "a"), override="pebble_test_custom") == "pebble_test_custom"


def test_override_must_keep_the_test_prefix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pebble_test"):
        suite_database_name(_main_checkout(tmp_path), override="pebble")
