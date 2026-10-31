"""The World v1 cast (`data/citizens/citizens.yaml`): 22 identities per the 10-world-v1 §3.1 roster that all spawn into
the real world, with their society data (ranks, titles, traits, family, bonds, ambitions, coins)."""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.core.config import REPO_ROOT
from app.observability.events import CitizenSpawned
from app.sim.citizens import AMBITION_ARGS, CITIZENS, KIN_INVERSE, CitizenSpec, CitizensSpec, load_citizens
from app.sim.simulation import Simulation
from app.sim.state import age_group
from app.sim.world import load_town_places
from app.world.town import load_kinds, load_town, load_town_spec
from app.world.walkability import town_walk_grid

LOOKS = REPO_ROOT / "frontend" / "src" / "lib" / "world" / "citizen-looks.ts"
FIGURE_SEX = {"masculine": "male", "feminine": "female"}
ROSTER = [  # 10-world-v1 §3.1, in roster order: (id, age, rank)
    ("masanori", 55, 5),
    ("kenji", 34, 4),
    ("goro", 22, 3),
    ("fumiko", 40, 3),
    ("genzo", 28, 2),
    ("aiko", 26, 2),
    ("hana", 9, 1),
    ("tokuji", 58, 3),
    ("tetsu", 45, 3),
    ("daisuke", 31, 2),
    ("ennen", 50, 4),
    ("ama", 44, 4),
    ("bo", 36, 2),
    ("oru", 63, 3),
    ("tek", 24, 2),
    ("lia", 15, 2),
    ("suna", 30, 2),
    ("barro", 38, 4),
    ("nim", 29, 2),
    ("kaz", 19, 2),
    ("pip", 7, 1),
    ("vesa", 61, 3),
]
NEW = {"goro", "tokuji", "tetsu", "daisuke", "ennen", "bo", "vesa"}  # the seven World v1 adds
TITLES = {"masanori": ["lord"], "kenji": ["samurai"], "goro": ["ashigaru"], "ama": ["leader"], "barro": ["leader"]}
TRAITS = {  # H G B T
    "masanori": (0.7, 0.3, 0.5, 0.6),
    "goro": (0.6, 0.4, 0.8, 0.7),
    "ennen": (0.95, 0.9, 0.4, 0.1),
    "kaz": (0.3, 0.5, 0.95, 0.8),
    "vesa": (0.8, 0.7, 0.2, 0.2),
}
HOMES = {  # the seven new homes (§3.1)
    "goro": "cross-s-1",  # by the west gate
    "tokuji": "farmhouse-2",
    "tetsu": "cross-n-9",  # beside the forge
    "daisuke": "cross-n-8",
    "ennen": "temple-hall",
    "bo": "band_a_camp:shelter-n",
    "vesa": "band_b_camp:shelter-w",
}
MONEY_SUPPLY = 3000  # mon, closed (§2.1)
TREASURY = 2015


def _looks() -> dict[str, tuple[str, str]]:
    """look id -> (region, sex) from the frontend's look configs."""
    pattern = re.compile(r"id: '([^']+)',\s*region: '([^']+)',[\s\S]*?figure: '([^']+)'")
    return {look: (region, FIGURE_SEX[figure]) for look, region, figure in pattern.findall(LOOKS.read_text())}


@pytest.fixture(scope="module")
def cast() -> CitizensSpec:
    return load_citizens(CITIZENS)


def _raw_cast() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(CITIZENS.read_text())
    return raw


def _by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {citizen["id"]: citizen for citizen in raw["citizens"]}


def test_the_cast_follows_the_roster(cast: CitizensSpec) -> None:
    citizens = cast.citizens
    assert [(c.id, c.age, c.rank) for c in citizens] == ROSTER
    assert Counter(c.region for c in citizens) == {"town": 11, "band_a": 6, "band_b": 5}
    assert len({c.name for c in citizens}) == 22
    looks = _looks()
    assert len(looks) == 22
    assert sorted(c.look for c in citizens) == sorted(looks)
    for citizen in citizens:
        assert looks[citizen.look] == (citizen.region, citizen.sex), citizen.id
        assert citizen.role and citizen.personality and citizen.appearance, citizen.id
    ids = {c.id for c in citizens}
    for citizen in citizens:
        assert set(citizen.knows_people) <= ids - {citizen.id}, citizen.id
        mates = {c.id for c in citizens if c.region == citizen.region} - {citizen.id}
        assert mates <= set(citizen.knows_people), f"{citizen.id} should know everyone in their region"
    bands = [c for c in citizens if c.region != "town"]
    assert all(c.inventory.get("dried meat", 0) > 0 and c.home and c.home.startswith(c.site) for c in bands)
    assert all(c.site == "town" and c.home for c in citizens if c.region == "town")
    assert cast.stores["store-2"]["rice"] >= 300  # the town has food for some days


def test_ranks_titles_and_traits_follow_the_roster(cast: CitizensSpec) -> None:
    by_id = {c.id: c for c in cast.citizens}
    assert {c.id: c.titles for c in cast.citizens if c.titles} == TITLES
    for citizen in cast.citizens:
        assert citizen.traits is not None, citizen.id
        assert (citizen.rank == 1) == (citizen.age < 13), f"{citizen.id}: children and only children rank 1"
    for cid, (honesty, generosity, boldness, temper) in TRAITS.items():
        traits = by_id[cid].traits
        assert traits is not None
        assert (traits.honesty, traits.generosity, traits.boldness, traits.temper) == (
            honesty,
            generosity,
            boldness,
            temper,
        ), cid


def test_family_links_are_symmetric_and_name_the_roster_kin(cast: CitizensSpec) -> None:
    by_id = {c.id: c for c in cast.citizens}
    for citizen in cast.citizens:
        for other, kin in citizen.family.items():
            assert by_id[other].family[citizen.id] == KIN_INVERSE[kin], (citizen.id, other)
    assert by_id["genzo"].family == {"aiko": "mate", "hana": "child"}
    assert by_id["goro"].family == {"tokuji": "parent's sibling"}  # Tokuji's nephew
    assert by_id["lia"].family == {"ama": "parent", "bo": "parent"}
    assert by_id["barro"].family == {"nim": "mate", "pip": "child", "kaz": "sibling", "vesa": "parent"}
    assert by_id["vesa"].family == {"barro": "child", "kaz": "child", "pip": "grandchild"}


def test_bonds_follow_the_roster(cast: CitizensSpec) -> None:
    by_id = {c.id: c for c in cast.citizens}
    assert by_id["masanori"].bonds == {"kenji": 60, "ennen": 30, "barro": -20}
    assert by_id["goro"].bonds == {"kenji": 40, "kaz": -20}
    assert by_id["kaz"].bonds == {"tek": -30, "goro": -20}
    ennen = by_id["ennen"].bonds
    assert set(ennen) == {c.id for c in cast.citizens} - {"ennen"}  # everyone
    assert ennen["masanori"] == 30 and set(ennen.values()) == {10, 30}


def test_every_ambition_names_known_checks_with_their_arguments(cast: CitizensSpec) -> None:
    for citizen in cast.citizens:
        assert citizen.ambition is not None, citizen.id
        for clause in citizen.ambition.all_of:
            required, optional = AMBITION_ARGS[clause.check]
            assert required <= set(clause.args) <= required | optional, (citizen.id, clause.check)
    by_id = {c.id: c for c in cast.citizens}
    goro = by_id["goro"].ambition
    assert goro is not None and [(c.check, c.args) for c in goro.all_of] == [("seizures_guilty", {"count": 3})]
    masanori = by_id["masanori"].ambition
    assert masanori is not None and [c.check for c in masanori.all_of] == ["store_holds", "standing_at_least"]
    stores = {
        cid: clause.args["store"]
        for cid, citizen in by_id.items()
        for clause in (citizen.ambition.all_of if citizen.ambition else [])
        if clause.check == "store_holds"
    }
    assert stores == {"masanori": "store-2", "genzo": "farmhouse-1-chest", "suna": "band_a_camp:drying-rack"}


@pytest.mark.parametrize(
    ("clause", "error"),
    [
        ({"check": "coins_at_least"}, "missing \\['count'\\]"),
        ({"check": "coins_at_least", "args": {"count": 5, "item": "rice"}}, "unknown \\['item'\\]"),
        ({"check": "get_rich", "args": {}}, "check"),
    ],
)
def test_ambition_checks_refuse_wrong_arguments(clause: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        CitizenSpec.model_validate({**_raw_cast()["citizens"][0], "ambition": {"text": "x", "all_of": [clause]}})


@pytest.mark.parametrize(
    ("ambition", "error"),
    [
        ({"text": "", "all_of": [{"check": "followed_hunt"}]}, "text"),
        ({"text": "be happy", "all_of": []}, "all_of"),  # an ambition the world can't check
    ],
)
def test_ambitions_need_words_and_a_check(ambition: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        CitizenSpec.model_validate({**_raw_cast()["citizens"][0], "ambition": ambition})


def test_starting_coins_and_the_treasury_make_the_money_supply(cast: CitizensSpec) -> None:
    assert cast.coins() == MONEY_SUPPLY
    assert cast.chests["castle-keep"] == {"coins": TREASURY}
    purse = {c.id: c.inventory.get("coins", 0) for c in cast.citizens}
    assert purse["masanori"] == 0 and purse["fumiko"] == 500 and purse["hana"] == 5
    others = [c for c in cast.citizens if c.region == "town" and c.age >= 13 and c.id not in ("masanori", "fumiko")]
    assert len(others) == 8 and {purse[c.id] for c in others} == {60}
    assert all(purse[c.id] == 0 for c in cast.citizens if c.region != "town")  # bands start with none
    assert cast.chests["farmhouse-1"] == cast.chests["farmhouse-2"] == {"rice": 20}


def test_every_town_home_has_its_household_chest(cast: CitizensSpec) -> None:
    placements = {p.id: p for p in load_town().placements}
    by_id = {c.id: c for c in cast.citizens}
    assert {cid: by_id[cid].home for cid in HOMES} == HOMES
    for home in {c.home for c in cast.citizens if c.region == "town"}:
        chest = placements[f"{home}-chest"]
        door = placements[str(home)].front(0.75)
        assert chest.kind == "chest" and abs(chest.x - door[0]) + abs(chest.z - door[1]) < 6, home


def test_the_town_has_its_v1_furniture() -> None:
    kinds = Counter(p.kind for p in load_town().placements)
    assert kinds["market_stall"] == kinds["forge"] == kinds["loom"] == 1
    assert kinds["anvil"] == 0  # the forge model has its own anvil: the forge is the station (§2.3)
    assert kinds["drying_rack"] == 3  # the two field racks by the paddies and the farmyard rack
    assert kinds["field_barricade"] == 5  # the gaol pen
    assert {"gaol", "bell-tower", "forge"} <= {p.id for p in load_town_places().places}


def test_the_loom_stands_by_the_weaver_s_door_with_open_ground_in_front() -> None:
    town = load_town()
    placements = {p.id: p for p in town.placements}
    loom, house = placements["farmhouse-1-loom"], placements["farmhouse-1"]
    door = house.front(0.75)
    walk = town_walk_grid(town, load_kinds())
    assert abs((loom.z - loom.footprint.z / 2) - (house.z + house.footprint.z / 2)) <= 0.1  # backed onto the veranda
    assert abs(loom.x - house.x) + loom.footprint.x / 2 <= 3  # beside the door, not off past the corner
    assert walk.is_walkable(*loom.front(0.4)) and walk.is_walkable(*door)  # the weaver's seat; the way in


def test_the_rice_fields_stand_lies_inside_a_paddy() -> None:
    stand = next(p for p in load_town_places().places if p.id == "rice-fields").at
    paddies = [tiles.rect for tiles in load_town_spec().tiles if tiles.kind == "rice_paddy"]
    assert any(x0 < stand[0] < x1 and z0 < stand[1] < z1 for x0, z0, x1, z1 in paddies)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda c: c["genzo"]["family"].update(hana="parent"), "hana is genzo's parent"),
        (lambda c: c["hana"]["family"].pop("aiko"), "aiko must be hana's parent"),
        (lambda c: c["goro"]["family"].update(nobody="sibling"), "unknown kin nobody"),
        (lambda c: c["goro"]["bonds"].update(kenji=10), "give their bond differently"),
        (lambda c: c["goro"]["bonds"].update(goro=10), "own kin or bond"),
        (lambda c: c["goro"]["bonds"].update(kaz=-101), "-100 to 100"),
        (lambda c: c["goro"]["bonds"].update(kaz=101), "-100 to 100"),
        (lambda c: c["goro"].update(rank=4), "doesn't match the titles"),
        (lambda c: c["masanori"]["ambition"]["all_of"][0]["args"].update(store="granary"), "unknown store 'granary'"),
        (lambda c: c["suna"]["ambition"]["all_of"][0]["args"].update(store="drying-rack"), "unknown store"),
        (lambda c: c["suna"]["ambition"]["all_of"][0]["args"].update(store="band_a_camp:fire-pit"), "unknown store"),
        (lambda c: c["genzo"]["ambition"]["all_of"][0]["args"].update(store="farmhouse-1"), "unknown store"),
        (lambda c: c["hana"]["ambition"]["all_of"][0]["args"].update(place="band_c_camp"), "unknown place"),
        (lambda c: c["nim"]["ambition"]["all_of"][0]["args"].update(who="nobody"), "unknown who"),
        (lambda c: c["tetsu"]["ambition"]["all_of"][0]["args"].update(to="nobody"), "unknown to"),
        (lambda c: c["barro"]["ambition"]["all_of"][0]["args"].update(group="band_c"), "unknown group"),
        (lambda c: c["tetsu"]["ambition"]["all_of"][0]["args"].update(item="spear"), "unknown item 'spear'"),
        (lambda c: c["bo"]["ambition"]["all_of"][0]["args"].update(item="iron axes"), "unknown item"),
        (lambda c: c["goro"]["inventory"].update(spear=1), "goro can't start with \\['spear'\\]"),
        (lambda c: c["goro"]["inventory"].update(coins=0), "goro can't start with \\['coins'\\]"),
    ],
)
def test_the_cast_refuses_broken_links(change: Callable[[dict[str, dict[str, Any]]], None], error: str) -> None:
    raw = _raw_cast()
    change(_by_id(raw))
    with pytest.raises(ValidationError, match=error):
        CitizensSpec.model_validate(raw)


def test_citizen_ids_are_unique() -> None:
    raw = _raw_cast()
    raw["citizens"].append({**raw["citizens"][4], "family": {}, "bonds": {}})  # a second genzo
    with pytest.raises(ValidationError, match="citizen ids must be unique"):
        CitizensSpec.model_validate(raw)


@pytest.mark.parametrize(
    ("where", "stock", "error"),
    [
        ("chests", {"castle-keep": {"coin": 5}}, "castle-keep-chest can't start with \\['coin'\\]"),
        ("stores", {"store-2": {"rice": -1}}, "store-2 can't start with \\['rice'\\]"),
    ],
)
def test_stores_and_chests_start_with_item_kinds(where: str, stock: dict[str, Any], error: str) -> None:
    raw = _raw_cast()
    raw[where].update(stock)
    with pytest.raises(ValidationError, match=error):
        CitizensSpec.model_validate(raw)


def test_chests_belong_to_someone_s_home() -> None:
    raw = _raw_cast()
    raw["chests"]["cross-n-3"] = {"rice": 5}
    with pytest.raises(ValidationError, match="chests of nobody's home"):
        CitizensSpec.model_validate(raw)


def test_everyone_spawns_at_home_ground_and_knows_their_way_home(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    cast = load_citizens(CITIZENS)
    for spec in cast.citizens:
        citizen = sim.add_citizen(spec)
        assert (citizen.role, citizen.region, citizen.group) == (spec.role, spec.region, age_group(spec.age))
        home = sim.world.structures[str(citizen.home)]
        assert home.is_home and home.site == spec.site
        assert sim.world.distance_m(citizen.position, home.door) < 140, spec.id
    assert {c.inventory.get("dried meat", 0) > 0 for c in sim.state.citizens.values() if c.region != "town"} == {True}
    assert NEW <= set(sim.state.citizens)


def test_a_citizen_s_spawn_tells_their_rank_titles_kin_and_bonds(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.add_cast(load_citizens(CITIZENS))
    spawned = {e.payload.id: e.payload for e in sim.drain() if isinstance(e.payload, CitizenSpawned)}
    ama = spawned["ama"]
    assert (ama.rank, ama.titles, ama.family, ama.bonds) == (4, ["leader"], {"bo": "mate", "lia": "child"}, {"oru": 50})
    assert (spawned["hana"].rank, spawned["hana"].titles) == (1, [])
    for spec in load_citizens(CITIZENS).citizens:
        told = spawned[spec.id]
        assert (told.rank, told.titles, told.family, told.bonds) == (spec.rank, spec.titles, spec.family, spec.bonds)
