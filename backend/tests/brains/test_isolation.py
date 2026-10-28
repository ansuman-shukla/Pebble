"""Scripted brains use the world contract only: nothing in `app.brains` may import the simulation or the store."""

import ast
from pathlib import Path

import app.brains

ALLOWED_APP_MODULES = ("app.brains", "app.world_api.facade", "app.world_api.models", "app.core.rng")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def test_brains_import_only_the_world_contract() -> None:
    package = Path(app.brains.__file__).parent
    modules = sorted(package.glob("*.py"))
    assert {m.stem for m in modules} >= {"brain", "routines", "senses", "profile", "runner"}
    for module in modules:
        app_imports = {name for name in _imports(module) if name == "app" or name.startswith("app.")}
        bad = {name for name in app_imports if not name.startswith(ALLOWED_APP_MODULES)}
        assert not bad, f"{module.name} imports {sorted(bad)}"


def test_brains_never_reach_behind_the_facade() -> None:
    """No `api.sim` or `.core`: the facade's simulation handle is not for minds."""
    package = Path(app.brains.__file__).parent
    for module in sorted(package.glob("*.py")):
        tree = ast.parse(module.read_text())
        reached = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not reached & {"sim", "core"}, module.name
