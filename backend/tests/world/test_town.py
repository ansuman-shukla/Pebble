from collections import Counter
from collections.abc import Mapping
from itertools import combinations

import pytest

from app.world.geometry import Rect, polygon_bounds
from app.world.town import (
    KindSpec,
    TownPlacement,
    TownSpec,
    TownView,
    expand_town,
    load_kinds,
    load_town,
    load_town_spec,
    placement_blockers,
)

TOWN_LOOKS = {"town-lord", "town-samurai", "town-merchant", "town-farmer", "town-weaver", "town-child"}
TOUCH_EPS = 0.01


@pytest.fixture(scope="module")
def town() -> TownView:
    return load_town()


@pytest.fixture(scope="module")
def kinds() -> Mapping[str, KindSpec]:
    return load_kinds()


def placements_of(town: TownView, prefix: str) -> list[TownPlacement]:
    return [placement for placement in town.placements if placement.id.rsplit("-", 1)[0] == prefix]


def by_id(town: TownView, placement_id: str) -> TownPlacement:
    return next(placement for placement in town.placements if placement.id == placement_id)


def minimal_spec(**sections: object) -> TownSpec:
    return TownSpec.model_validate(
        {
            "name": "test",
            "extent": {"min_x": -10, "max_x": 10, "min_z": -10, "max_z": 10},
            "spawn": {"at": [0, 0], "heading_deg": 0},
            **sections,
        }
    )


def test_every_placement_kind_is_catalogued(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    assert {placement.kind for placement in town.placements} <= set(kinds)


def test_placements_follow_their_kind(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    for placement in town.placements:
        kind = kinds[placement.kind]
        turned = placement.rotation_deg in (90, 270)
        expected = tuple(reversed(kind.footprint)) if turned else kind.footprint
        assert (placement.footprint.x, placement.footprint.z) == expected, placement.id
        assert placement.walk == kind.walk, placement.id


def test_placement_ids_are_unique(town: TownView) -> None:
    ids = Counter(placement.id for placement in town.placements)
    assert [placement_id for placement_id, count in ids.items() if count > 1] == []


def test_placements_lie_inside_the_extent(town: TownView) -> None:
    extent = town.extent.rect()
    assert [placement.id for placement in town.placements if not placement.rect().inside(extent)] == []


def test_spawn_and_citizens_lie_inside_the_extent(town: TownView) -> None:
    extent = town.extent.rect()
    assert extent.contains(town.spawn.x, town.spawn.z)
    for citizen in town.citizens:
        assert all(extent.contains(x, z) for x, z in [(citizen.x, citizen.z), *citizen.route]), citizen.look


def test_solid_blockers_do_not_overlap(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    blockers = [
        (placement.id, rect)
        for placement in town.placements
        if placement.walk == "solid"
        for rect in placement_blockers(placement, kinds[placement.kind])
    ]
    overlapping = [
        (first_id, second_id)
        for (first_id, first), (second_id, second) in combinations(blockers, 2)
        if first_id != second_id and first.overlaps(second, TOUCH_EPS)
    ]
    assert overlapping == []


def test_streets_and_roads_are_clear_of_solids(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    ways = [(area.id, polygon_bounds(area.polygon)) for area in town.areas if area.kind in ("street", "road")]
    in_the_way = [
        (way_id, placement.id)
        for placement in town.placements
        if placement.kind != "castle_gatehouse"  # its pillars flank the street; the passage is open
        for blocker in placement_blockers(placement, kinds[placement.kind])
        for way_id, way in ways
        if blocker.overlaps(way, TOUCH_EPS)
    ]
    assert in_the_way == []


def test_town_has_the_landmark_buildings(town: TownView) -> None:
    counts = Counter(placement.kind for placement in town.placements)
    assert counts["castle_keep"] == 1
    assert counts["castle_gatehouse"] == 3
    assert counts["moat_bridge"] == 1
    for kind in ("pagoda", "temple_hall", "bell_tower", "well", "water_wheel", "teahouse", "lookout_tower"):
        assert counts[kind] >= 1, kind
    assert counts["townhouse"] >= 20
    assert counts["rice_paddy"] >= 100


def test_citizens_are_the_six_town_looks(town: TownView) -> None:
    assert sorted(citizen.look for citizen in town.citizens) == sorted(TOWN_LOOKS)
    walkers = {citizen.look for citizen in town.citizens if citizen.route}
    assert walkers == {"town-samurai", "town-farmer", "town-child"}


def test_water_has_the_moat_ring_and_the_stream(town: TownView) -> None:
    water = {item.id: item for item in town.water}
    assert water["moat"].kind == "moat"
    assert len(water["moat"].holes) == 1
    assert water["stream"].kind == "stream"
    assert water["stream"].polygon == [(-160, -160), (-152, -160), (-152, 160), (-160, 160)]


def test_runs_along_x_expand_into_unrotated_segments(town: TownView) -> None:
    wall = placements_of(town, "castle-wall-n")

    assert len(wall) == 25
    assert {placement.rotation_deg for placement in wall} == {0}
    assert [(placement.x, placement.z) for placement in wall] == [(-24 + 2 * i, -28) for i in range(25)]


def test_runs_along_z_expand_into_turned_segments(town: TownView) -> None:
    wall = placements_of(town, "town-wall-wn")

    assert len(wall) == 85
    assert {placement.rotation_deg for placement in wall} == {90}
    assert {(placement.footprint.x, placement.footprint.z) for placement in wall} == {(0.7, 2)}
    assert [placement.z for placement in wall] == [-96 + 2 * i for i in range(85)]
    assert {placement.x for placement in wall} == {-100}


@pytest.mark.parametrize("tiles_id", ["well-plaza", "paddy-1", "paddy-4"])
def test_tiles_cover_their_rect_exactly(tiles_id: str, town: TownView) -> None:
    spec = next(tiles for tiles in load_town_spec().tiles if tiles.id == tiles_id)
    rect = Rect(*spec.rect)
    tiles = placements_of(town, tiles_id)

    assert all(tile.rect().inside(rect) for tile in tiles)
    assert not any(first.rect().overlaps(second.rect()) for first, second in combinations(tiles, 2))
    covered = sum(tile.footprint.x * tile.footprint.z for tile in tiles)
    assert covered == pytest.approx((rect.x1 - rect.x0) * (rect.z1 - rect.z0))


def test_turned_gatehouse_keeps_its_passage_open(town: TownView, kinds: Mapping[str, KindSpec]) -> None:
    gate = by_id(town, "west-gate")

    pillars = sorted(placement_blockers(gate, kinds["castle_gatehouse"]), key=lambda rect: rect.z0)

    assert [tuple(round(edge, 6) for edge in (p.x0, p.z0, p.x1, p.z1)) for p in pillars] == [
        (-101.4, 73.0, -98.6, 74.7),
        (-101.4, 77.3, -98.6, 79.0),
    ]
    assert not any(pillar.contains(gate.x, gate.z) for pillar in pillars)


@pytest.mark.parametrize(
    ("rotation", "front"),
    [(0, (0.0, 3.0)), (90, (3.0, 0.0)), (180, (0.0, -3.0)), (270, (-3.0, 0.0))],
)
def test_front_is_one_metre_past_the_footprint_in_the_facing_direction(
    rotation: int, front: tuple[float, float], kinds: Mapping[str, KindSpec]
) -> None:
    spec = minimal_spec(placements=[{"id": "house", "kind": "townhouse", "at": [0, 0], "rotation_deg": rotation}])

    house = expand_town(spec, kinds).placements[0]

    assert house.front() == pytest.approx(front)


def test_unknown_kinds_are_rejected(kinds: Mapping[str, KindSpec]) -> None:
    spec = minimal_spec(placements=[{"id": "thing", "kind": "space_station", "at": [0, 0]}])

    with pytest.raises(ValueError, match="space_station"):
        expand_town(spec, kinds)


def test_duplicate_ids_are_rejected(kinds: Mapping[str, KindSpec]) -> None:
    spec = minimal_spec(
        placements=[{"id": "wall-0", "kind": "well", "at": [5, 5]}],
        runs=[{"id": "wall", "kind": "stone_wall", "from": [-4, 0], "to": [4, 0]}],
    )

    with pytest.raises(ValueError, match="wall-0"):
        expand_town(spec, kinds)


def test_runs_must_fit_whole_segments(kinds: Mapping[str, KindSpec]) -> None:
    spec = minimal_spec(runs=[{"id": "wall", "kind": "stone_wall", "from": [-4, 0], "to": [3, 0]}])

    with pytest.raises(ValueError, match="whole number"):
        expand_town(spec, kinds)


def test_diagonal_runs_are_rejected(kinds: Mapping[str, KindSpec]) -> None:
    spec = minimal_spec(runs=[{"id": "wall", "kind": "stone_wall", "from": [0, 0], "to": [4, 4]}])

    with pytest.raises(ValueError, match="axis-aligned"):
        expand_town(spec, kinds)


def test_runs_going_west_or_north_place_segments_from_the_start(kinds: Mapping[str, KindSpec]) -> None:
    spec = minimal_spec(runs=[{"id": "fence", "kind": "bamboo_fence", "from": [0, 4], "to": [0, -2]}])

    fence = expand_town(spec, kinds).placements

    assert [(segment.x, segment.z, segment.rotation_deg) for segment in fence] == [(0, 3, 90), (0, 1, 90), (0, -1, 90)]


def test_blockers_must_stay_inside_the_footprint() -> None:
    with pytest.raises(ValueError, match="inside the footprint"):
        KindSpec(footprint=(2, 2), walk="solid", blockers=[(-1.5, -0.5, 0.5, 0.5)])


def test_only_solids_take_blockers() -> None:
    with pytest.raises(ValueError, match="only solid"):
        KindSpec(footprint=(2, 2), walk="surface", blockers=[(-0.5, -0.5, 0.5, 0.5)])
