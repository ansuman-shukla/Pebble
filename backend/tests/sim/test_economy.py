"""The goods table (10-world-v1 §2.2, `data/economy.yaml`): one value row with a source and a sink for every item kind,
the stall's lots and targets, and each group judging goods by its own column."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.sim.economy import ECONOMY, EconomySpec, load_economy, value_of
from app.sim.items import ITEMS


def test_every_item_kind_has_one_row_with_a_source_and_a_sink() -> None:
    economy = load_economy()
    assert set(economy.goods) == set(ITEMS)
    assert all(good.source.strip() and good.sink.strip() for good in economy.goods.values())
    assert economy.money_supply == 3000


def test_the_goods_table_holds_the_bible_values() -> None:
    goods = load_economy().goods
    table = {item: (good.town, good.band) for item, good in goods.items()}
    assert table["rice"] == (2, 4) and table["hide"] == (15, 6) and table["obsidian"] == (6, 12)
    assert table["iron sand"] == (4, 0) and table["gold"] == (20, 10) and table["cloth"] == (25, 15)
    assert table["flint spear"] == (15, 30) and table["iron spear"] == (40, 40) and table["iron axe"] == (60, 40)
    assert table["sickle"] == (50, 0) and table["coins"] == (1, 1) and table["berries"] == (None, None)
    lots = {item: (good.stall.lot, good.stall.target) for item, good in goods.items() if good.stall}
    assert lots == {
        "rice": (2, 120),
        "dried meat": (2, 20),
        "wood": (4, 40),
        "hide": (1, 6),
        "obsidian": (1, 6),
        "iron sand": (1, 20),
        "gold": (1, 5),
        "cloth": (1, 6),
        "pack": (1, 3),
        "iron spear": (1, 2),
        "iron axe": (1, 2),
        "sickle": (1, 2),
    }


def test_town_folk_and_bands_value_goods_by_their_own_column() -> None:
    assert value_of("obsidian", "town") == 6 and value_of("obsidian", "band_b") == 12
    assert value_of("hide", "town") == 15 and value_of("hide", "band_a") == 6
    assert value_of("berries", "town") == 0.0  # worth nothing to sell


def _raw_economy() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(ECONOMY.read_text())
    return raw


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda e: e["goods"].pop("gold"), "missing \\['gold'\\]"),
        (lambda e: e["goods"].update(silver=e["goods"]["gold"]), "unknown \\['silver'\\]"),
        (lambda e: e["goods"]["hide"].update(source=""), "source"),
        (lambda e: e["goods"]["hide"].update(sink=""), "sink"),
        (lambda e: e["goods"]["hide"].pop("sink"), "sink"),
        (lambda e: e["goods"]["berries"].update(stall={"lot": 1, "target": 5}), "only goods with a town value"),
        (lambda e: e["goods"]["rice"]["stall"].update(lot=0), "lot"),
        (lambda e: e["breakage"].pop("sickle"), "every tool breaks with use"),
        (lambda e: e["breakage"]["pack"].update(use="sleep"), "use"),
        (lambda e: e["breakage"]["pack"].update(chance=1.0), "chance"),
        (lambda e: e["spoilage"].update(meat=1.5), "spoilage share"),
        (lambda e: e["spoilage"].update(bread=0.5), "spoilage names unknown items"),
        (lambda e: e["spoilage"].update(coins=0.1), "coins can't be in spoilage"),
        (lambda e: e["breakage"].update(coins={"use": "carry", "chance": 0.01}), "coins can't be in breakage"),
    ],
)
def test_the_goods_table_refuses_gaps(change: Callable[[dict[str, Any]], None], error: str) -> None:
    raw = _raw_economy()
    change(raw)
    with pytest.raises(ValidationError, match=error):
        EconomySpec.model_validate(raw)


def test_a_table_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text(ECONOMY.read_text())
    assert load_economy(path) == load_economy()
