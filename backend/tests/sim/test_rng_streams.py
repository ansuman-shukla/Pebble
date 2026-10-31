"""Named random streams (10-world-v1 §6.5): every roll draws from its own `<system>.<purpose>` stream, fetched in that
system's module, so a new roll gets a new stream and never shifts the numbers an existing roll draws."""

import ast
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import app.sim
from app.core.rng import Rng
from app.sim.state import WorldState

SIM = Path(app.sim.__file__).parent
STREAM = re.compile(r"^[a-z_]+\.[a-z_]+$")
KEEPERS = frozenset({"state.py", "snapshot.py"})  # the only modules that hold the streams themselves


def _draws() -> Iterator[tuple[str, str | None, int]]:
    """(module, stream name or None if not a literal, line) for every `.rng(...)` call in the simulation."""
    for path in sorted(SIM.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rng":
                first = node.args[0] if node.args else None
                name = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
                yield path.stem, name, node.lineno


def _rolls_loose(node: ast.AST) -> bool:
    """`Rng(...)`, the `random` module or numpy's `random`: dice rolled outside the named streams."""
    if isinstance(node, ast.Import):
        return any(alias.name == "random" or alias.name.startswith("numpy.random") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return module in ("random", "numpy.random") or (
            module == "numpy" and any(alias.name == "random" for alias in node.names)
        )
    if isinstance(node, ast.Attribute):
        return node.attr == "random" and isinstance(node.value, ast.Name) and node.value.id in ("np", "numpy")
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Rng"


def _loose_randomness(source: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.stmt | ast.expr) and _rolls_loose(node)
    ]


def _state(seed: int) -> WorldState:
    return WorldState(
        tick=0,
        seed=seed,
        next_seq=1,
        next_stack=1,
        citizens={},
        ground={},
        stores={},
        rngs={},
    )


def test_each_module_draws_only_from_its_own_systems_streams() -> None:
    draws = list(_draws())
    assert len(draws) >= 15  # every existing roll was moved onto a named stream
    wrong = [d for d in draws if d[1] is None or not STREAM.match(d[1]) or d[1].split(".")[0] != d[0]]
    assert wrong == [], "a stream is named by a literal '<module>.<purpose>' from the module that draws on it"


def test_no_two_rolls_share_a_stream() -> None:
    counts = Counter(name for _, name, _ in _draws())
    assert [name for name, count in counts.items() if count > 1] == []


def test_only_the_state_holds_the_streams() -> None:
    for path in sorted(SIM.rglob("*.py")):
        if path.name not in KEEPERS:
            text = path.read_text()
            assert ".rngs" not in text and "for_subsystem" not in text, f"{path.name} reaches a stream by hand"


def test_no_module_rolls_dice_outside_the_streams() -> None:
    loose = {
        path.name: lines
        for path in sorted(SIM.rglob("*.py"))
        if path.name not in KEEPERS and (lines := _loose_randomness(path.read_text()))
    }
    assert loose == {}, "draw from `state.rng('<module>.<purpose>')`, never a fresh Rng or the random modules"


def test_the_dice_lint_catches_each_way_around_the_streams() -> None:
    assert _loose_randomness("rng = Rng(7)\nrng.random()\nstate.rng('animals.graze').random()") == [1]
    for loose in (
        "import random",
        "from random import choice",
        "import numpy.random",
        "from numpy.random import default_rng",
        "from numpy import random",
        "np.random.default_rng(1)",
        "numpy.random.rand()",
    ):
        assert _loose_randomness(loose) == [1], loose
    assert _loose_randomness("import numpy as np\nnp.zeros(3)\nrng.random()") == []


def test_a_stream_is_made_from_the_seed_and_its_name_and_new_draws_shift_no_other() -> None:
    plain, busy = _state(7), _state(7)
    assert plain.rng("animals.graze") is plain.rng("animals.graze")
    assert plain.rng("animals.graze").state == Rng.for_subsystem(7, "animals.graze").state
    assert _state(8).rng("animals.graze").state != plain.rng("animals.graze").state
    for _ in range(5):
        busy.rng("wear.breakage").random()  # a roll a later system adds
    assert [busy.rng("animals.graze").random() for _ in range(3)] == [
        plain.rng("animals.graze").random() for _ in range(3)
    ]
    assert sorted(busy.rngs) == ["animals.graze", "wear.breakage"]
