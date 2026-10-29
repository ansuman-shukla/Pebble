"""World v1 goods as item kinds (10-world-v1 §2.1-2.2): coins counted in words, goods said in their plurals and named
back from them, tools one kind per material."""

from collections.abc import Callable

import pytest

from app.sim.acting import item_name
from app.sim.coins import coin_words, number_words
from app.sim.items import ITEMS, amount_words, tool_in
from app.sim.simulation import Simulation
from app.sim.snapshot import resumable, take_snapshot


@pytest.mark.parametrize(
    ("count", "words"),
    [
        (0, "no coins"),
        (1, "a coin"),
        (2, "two coins"),
        (7, "seven coins"),
        (12, "twelve coins"),
        (13, "a short string of coins"),
        (99, "a short string of coins"),
        (100, "a string of coins"),
        (199, "a string of coins"),
        (200, "two strings of coins"),
        (250, "two strings of coins"),
        (2015, "twenty strings of coins"),
        (3000, "thirty strings of coins"),
    ],
)
def test_coins_are_counted_then_strung_by_the_hundred(count: int, words: str) -> None:
    assert coin_words(count) == words
    assert amount_words(count, ITEMS["coins"]) == words  # how anyone says what they carry or see


@pytest.mark.parametrize(
    ("n", "words"), [(1, "one"), (19, "nineteen"), (20, "twenty"), (21, "twenty-one"), (100, "100")]
)
def test_number_words(n: int, words: str) -> None:
    assert number_words(n) == words


@pytest.mark.parametrize(
    ("item", "count", "words"),
    [
        ("hide", 3, "a few hides"),
        ("iron spear", 1, "an iron spear"),
        ("flint spear", 5, "a handful of flint spears"),
        ("obsidian", 2, "a few obsidian shards"),
        ("iron sand", 20, "plenty of iron sand"),
        ("gold", 1, "a grain of gold"),
        ("cloth", 5, "some cloth"),
        ("berries", 3, "a few berries"),  # names already plural keep them
    ],
)
def test_goods_are_said_in_their_plural(item: str, count: int, words: str) -> None:
    assert amount_words(count, ITEMS[item]) == words


@pytest.mark.parametrize(
    ("words", "item"),
    [
        ("a coin", "coins"),
        ("twelve coins", "coins"),
        ("the iron spears", "iron spear"),
        ("a flint spear", "flint spear"),
        ("two hides", "hide"),
        ("an obsidian shard", "obsidian"),
        ("some iron sand", "iron sand"),
        ("a berry", "berries"),
        ("a spear", None),  # which one? spears come by material (`carried_name` takes the best one carried)
    ],
)
def test_goods_are_named_by_their_words(words: str, item: str | None) -> None:
    assert item_name(words) == item


def test_the_v1_goods_are_item_kinds_with_their_weights() -> None:
    weights = {
        "coins": 0.004,
        "flint": 0.5,
        "obsidian": 0.3,
        "iron sand": 1.0,
        "gold": 0.01,
        "cloth": 1.0,
        "pack": 1.5,
        "flint spear": 1.5,
        "obsidian spear": 1.5,
        "iron spear": 1.5,
        "stone axe": 1.2,
        "iron axe": 1.2,
        "sickle": 0.6,
    }
    assert {item: ITEMS[item].weight_kg for item in weights} == weights
    assert "spear" not in ITEMS  # spears come by material, so stacks stay fungible
    assert {name for name, kind in ITEMS.items() if kind.tool == "spear"} == {
        "flint spear",
        "obsidian spear",
        "iron spear",
    }


def test_someone_uses_the_best_tool_they_carry() -> None:
    assert tool_in({"flint spear": 1, "iron spear": 1}, "spear") == "iron spear"
    assert tool_in({"flint spear": 2, "obsidian spear": 1}, "spear") == "obsidian spear"
    assert tool_in({"flint spear": 1, "iron axe": 1}, "spear") == "flint spear"
    assert tool_in({"iron spear": 0, "stone axe": 1}, "spear") is None
    assert tool_in({"stone axe": 1}, "axe") == "stone axe"


def test_a_run_from_before_the_v1_goods_starts_anew(new_sim: Callable[..., Simulation]) -> None:
    snapshot = take_snapshot(new_sim().state).model_dump(mode="json")
    assert resumable(snapshot)
    assert not resumable({**snapshot, "version": 4})  # its inventories hold item kinds that are gone ("spear")
