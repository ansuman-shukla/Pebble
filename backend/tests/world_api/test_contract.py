"""The world contract (03-actions-perception): the actions, their arguments, the perception and the results a mind gets.

Contract v1 is a draft (D96): C1 owns it until Q1 freezes `contract_v1.json`. `contract_v1_draft.json` holds the
action names, the `WorldApi` methods and the JSON schemas of every action, result and perception, plus a changelog
whose last line carries the hash of the schemas it describes. Any change to them fails here until the draft file is
rewritten with a line saying what changed:

    uv run python -m tests.world_api.test_contract "walk_to and follow take a pace"

Contract v0 (`contract_v0.json`, D74) stays frozen as a record, and v1 must keep every v0 shape: each v0 action,
argument, method and perception field as it was, adding only optional fields, optional parameters and new words, so
what a v0 mind sends and reads still holds under v1.
"""

import ast
import hashlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any, get_args

from pydantic import TypeAdapter

from app.world_api.facade import WorldApi
from app.world_api.models import CONTRACT_VERSION, Action, ActionName, ActionResult, Perception, SelfView

V0 = Path(__file__).with_name("contract_v0.json")
DRAFT = Path(__file__).with_name("contract_v1_draft.json")
WORDING = {"description", "title", "examples"}  # what may change or be added without changing a shape


def contract() -> dict[str, Any]:
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


def fingerprint(schemas: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()[:16]


def draft() -> dict[str, Any]:
    return dict(json.loads(DRAFT.read_text()))


def extends(old: Any, new: Any, at: str = "") -> list[str]:
    """Where the `new` JSON schema fails to accept everything the `old` one did (empty: it extends it)."""
    if not (isinstance(old, dict) and isinstance(new, dict)):
        return [] if old == new else [f"{at}: {old!r} became {new!r}"]
    problems = [f"{at}.{key}: added" for key in new.keys() - old.keys() - WORDING - {"default", "$defs"}]
    for key, was in old.items():
        if key in WORDING:
            continue
        if key not in new:
            problems.append(f"{at}.{key}: removed")
        elif key == "enum":
            problems += [f"{at}.enum: {word!r} removed" for word in was if word not in new[key]]
        elif key == "required":
            problems += [f"{at}.required: {name!r} added" for name in new[key] if name not in was]
        elif key == "mapping":
            problems += [f"{at}.mapping.{name}: changed" for name, ref in was.items() if new[key].get(name) != ref]
        elif key in ("properties", "$defs"):
            for name, schema in was.items():
                if name not in new[key]:
                    problems.append(f"{at}.{key}.{name}: removed")
                else:
                    problems += extends(schema, new[key][name], f"{at}.{name}")
        elif key in ("anyOf", "oneOf"):
            problems += [
                f"{at}.{key}: {option!r} has no match"
                for option in was
                if all(extends(option, candidate) for candidate in new[key])
            ]
        else:
            problems += extends(was, new[key], f"{at}.{key}")
    return problems


def keeps_method(old: str, new: dict[str, str]) -> bool:
    """A v0 method still takes its v0 call: same name and return, new parameters only at the end, with defaults."""
    name, _, signature = old.partition("(")
    now = new.get(name)
    if now is None:
        return False
    params, _, returns = signature.rpartition(") -> ")
    new_params, _, new_returns = now.partition("(")[2].rpartition(") -> ")
    if returns != new_returns or not new_params.startswith(params):
        return False
    added = ast.parse(f"def f({new_params.removeprefix(params).removeprefix(', ')}): pass").body[0]
    assert isinstance(added, ast.FunctionDef)
    return len(added.args.defaults) == len(added.args.args)


def test_the_draft_file_matches_the_models() -> None:
    written = draft()
    assert written["version"] == CONTRACT_VERSION
    body = {key: value for key, value in written.items() if key not in ("version", "changelog")}
    assert body == contract(), "the world contract changed: see this module's docstring"


def test_every_change_to_the_draft_has_a_changelog_line() -> None:
    changelog = draft()["changelog"]
    assert changelog[-1]["contract"] == fingerprint(contract()), "add a changelog line: see this module's docstring"
    assert all(line["change"].strip() for line in changelog)
    assert len({line["contract"] for line in changelog}) == len(changelog)  # a line per change


def test_v1_keeps_every_v0_shape() -> None:
    v0, v1 = json.loads(V0.read_text()), contract()
    assert v1["actions"][: len(v0["actions"])] == v0["actions"]
    methods = {entry.partition("(")[0]: entry for entry in v1["world_api"]}
    calls = [method for method in v0["world_api"] if not method.startswith("do(")]  # `do`: the action schema below
    assert len(calls) == len(v0["world_api"]) - 1
    assert [method for method in calls if not keeps_method(method, methods)] == []
    for part in ("action_schema", "result_schema", "perception_schema", "self_schema"):
        assert extends(v0[part], v1[part], part) == []


def test_a_schema_that_drops_or_tightens_anything_does_not_extend_v0() -> None:
    v0 = json.loads(V0.read_text())
    perception = v0["perception_schema"]
    assert extends(perception, perception) == []
    gone = json.loads(json.dumps(perception))
    gone["$defs"]["Seen"]["properties"]["kind"]["anyOf"][0]["enum"].remove("water")
    assert extends(perception, gone) != []
    required = json.loads(json.dumps(perception))
    required["$defs"]["Seen"]["properties"]["ground"] = {"type": "string"}
    assert extends(perception, required) == []  # a new optional field
    required["$defs"]["Seen"]["required"].append("ground")
    assert extends(perception, required) != []
    tighter = json.loads(json.dumps(v0["action_schema"]))
    tighter["$defs"]["Say"]["properties"]["words"]["maxLength"] = 60
    assert extends(v0["action_schema"], tighter) != []
    capped = json.loads(json.dumps(v0["action_schema"]))
    capped["$defs"]["Rest"]["properties"]["minutes"]["multipleOf"] = 5
    assert extends(v0["action_schema"], capped) != []
    dropped = json.loads(json.dumps(v0["action_schema"]))
    del dropped["discriminator"]["mapping"]["recall"]
    assert extends(v0["action_schema"], dropped) != []


def test_a_method_keeps_its_v0_call_only_with_trailing_defaults() -> None:
    old = "follow(self, person: str) -> app.world_api.facade.ActionHandle"
    handle = " -> app.world_api.facade.ActionHandle"
    assert keeps_method(old, {"follow": "follow(self, person: str, pace: str = 'walk')" + handle})
    assert not keeps_method(old, {"follow": "follow(self, person: str, pace: str)" + handle})
    assert not keeps_method(old, {"follow": "follow(self, who: str)" + handle})
    assert not keeps_method(old, {"follow": "follow(self, person: str) -> None"})
    assert not keeps_method(old, {"walk": old})


def test_every_action_has_a_model_and_a_method() -> None:
    adapter = TypeAdapter(Action)
    names = list(get_args(ActionName))
    assert len(names) == len(set(names)) == 32
    schema = adapter.json_schema()
    assert sorted(schema["discriminator"]["mapping"]) == sorted(names)
    methods = {name for name, _ in inspect.getmembers(WorldApi, inspect.isfunction)}
    assert set(names) - {"walk_to"} <= methods  # walk_to has one method per target kind
    assert {"walk_to", "walk_to_place", "walk_to_person", "walk_to_thing", "walk_towards"} <= methods


def test_contract_descriptions_carry_no_digits() -> None:
    """Docstrings become what a mind reads about an action or a field, and minds get words, never numbers."""

    def descriptions(schema: Any) -> list[str]:
        if isinstance(schema, dict):
            own = [schema["description"]] if isinstance(schema.get("description"), str) else []
            return own + [text for value in schema.values() for text in descriptions(value)]
        if isinstance(schema, list):
            return [text for value in schema for text in descriptions(value)]
        return []

    schemas = contract()
    texts = [text for part in schemas if part.endswith("_schema") for text in descriptions(schemas[part])]
    assert texts and [text for text in texts if any(char.isdigit() for char in text)] == []


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        sys.exit('usage: python -m tests.world_api.test_contract "what changed in the contract"')
    schemas = contract()
    changelog = draft()["changelog"] if DRAFT.exists() else []
    if changelog and changelog[-1]["contract"] == fingerprint(schemas):
        sys.exit("the contract has not changed since the last changelog line")
    changelog.append({"contract": fingerprint(schemas), "change": sys.argv[1].strip()})
    DRAFT.write_text(
        json.dumps({"version": CONTRACT_VERSION, "changelog": changelog, **schemas}, indent=2, sort_keys=True) + "\n"
    )
