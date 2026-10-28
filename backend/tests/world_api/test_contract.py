"""The world contract v0 is frozen (M9): the actions, their arguments, the perception and the results a mind gets.

The committed `contract_v0.json` holds the action names, the `WorldApi` methods and the JSON schemas of every action,
result and perception. Any change to them fails here. A deliberate change is a new contract version: record it in
docs/decisions.md, then rewrite the fixture with `uv run python -m tests.world_api.test_contract`.
"""

import inspect
import json
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter

from app.world_api.facade import WorldApi
from app.world_api.models import Action, ActionName, ActionResult, Perception, SelfView

FIXTURE = Path(__file__).with_name("contract_v0.json")


def contract() -> dict[str, object]:
    methods = sorted(
        f"{name}{inspect.signature(member)}"
        for name, member in inspect.getmembers(WorldApi, inspect.isfunction)
        if not name.startswith("_")
    )
    return {
        "actions": list(get_args(ActionName)),
        "world_api": methods,
        "action_schema": TypeAdapter(Action).json_schema(),
        "result_schema": ActionResult.model_json_schema(),
        "perception_schema": Perception.model_json_schema(),
        "self_schema": SelfView.model_json_schema(),
    }


def test_the_world_contract_is_frozen() -> None:
    frozen = json.loads(FIXTURE.read_text())
    assert contract() == frozen, "the world contract changed: see this module's docstring"


def test_every_action_has_a_model_and_a_method() -> None:
    adapter = TypeAdapter(Action)
    names = list(get_args(ActionName))
    assert len(names) == len(set(names)) == 22
    schema = adapter.json_schema()
    assert sorted(schema["discriminator"]["mapping"]) == sorted(names)
    methods = {name for name, _ in inspect.getmembers(WorldApi, inspect.isfunction)}
    assert set(names) - {"walk_to"} <= methods  # walk_to has one method per target kind
    assert {"walk_to", "walk_to_place", "walk_to_person", "walk_to_thing", "walk_towards"} <= methods


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(contract(), indent=2, sort_keys=True) + "\n")
