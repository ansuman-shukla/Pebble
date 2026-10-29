"""Hotspots, rings, the band B move, fixed features and dens (10-world-v1 §1.2)."""

import numpy as np
import pytest

from app.world.flora import Flora, generate_flora
from app.world.generate import GeneratedWorld, generate_world
from app.world.hotspots import place_hotspots, road_distance_m
from app.world.spec import BIOME_NAMES, HotspotsSpec, WorldSpec, load_site_kinds, load_world_spec
from app.world.sphere import angle_between, bearing_deg, lat_lon, unit_from_lat_lon
from app.world.surface import Surface, surface_from_view
from app.world.view import Feature, Hotspot, Road

# the bible's table positions (10 §1.2); hotspots may move up to 150 m from them
TABLE_AT: dict[str, tuple[float, float]] = {
    "gulf_shore": (38, 20),
    "south_marsh": (30, 12),
    "north_woods": (46, 10),
    "elder_grove": (12, 6),
    "obsidian_field": (18, -20),  # the smoking mountain's crater
    "falls_pool": (-2, 15),
    "a_savanna": (20, 98),
    "river_marsh": (10, 88),
    "bridge_meadows": (8, 82),
    "painted_cave_flint": (20, 108),
    "eastern_wall_scar": (10, 125),
}


@pytest.fixture(scope="module")
def spec() -> WorldSpec:
    return load_world_spec()


@pytest.fixture(scope="module")
def world(spec: WorldSpec) -> GeneratedWorld:
    return generate_world(spec, load_site_kinds())


@pytest.fixture(scope="module")
def surface(world: GeneratedWorld, spec: WorldSpec) -> Surface:
    return surface_from_view(world.view(), spec.roads.town_chart_half_m)


@pytest.fixture(scope="module")
def flora(world: GeneratedWorld, spec: WorldSpec) -> Flora:
    return generate_flora(world.view(), spec)


def _hotspot(world: GeneratedWorld, hotspot_id: str) -> Hotspot:
    return next(hotspot for hotspot in world.places.hotspots if hotspot.id == hotspot_id)


def _feature(world: GeneratedWorld, feature_id: str) -> Feature:
    return next(feature for feature in world.places.features if feature.id == feature_id)


def _road(world: GeneratedWorld, road_id: str) -> Road:
    return next(road for road in world.places.roads if road.id == road_id)


def _site_unit(world: GeneratedWorld, site_id: str) -> np.ndarray:
    return np.array(next(site for site in world.sites if site.id == site_id).anchor.position)


def _metres(world: GeneratedWorld, a: np.ndarray, b: np.ndarray) -> float:
    return float(angle_between(np.atleast_2d(a), b)[0] * world.spec.radius_m)


def test_there_are_the_fourteen_hotspots_of_the_table(world: GeneratedWorld) -> None:
    ids = {hotspot.id for hotspot in world.places.hotspots}

    assert ids == set(TABLE_AT) | {"lords_woods", "b_wood", "b_shore"}
    for hotspot_id, at in TABLE_AT.items():
        moved = _metres(world, np.array(_hotspot(world, hotspot_id).centre), unit_from_lat_lon(*at))
        assert moved <= 150, hotspot_id


def test_every_hotspot_is_on_land_of_its_biome_reachable_spaced_and_in_its_ring(
    world: GeneratedWorld, spec: WorldSpec, surface: Surface
) -> None:
    from app.world.paths import reachable

    from_town = reachable(surface.grid, surface.walk, surface.site("town").cell)
    rings = spec.hotspots.rings
    for authored, hotspot in zip(spec.hotspots.hotspots, world.places.hotspots, strict=True):
        assert BIOME_NAMES[world.biomes[hotspot.cell]] in authored.biomes, hotspot.id
        assert from_town[hotspot.cell] and not surface.in_town[hotspot.cell], hotspot.id
        distance = _metres(world, _site_unit(world, hotspot.settlement), np.array(hotspot.centre))
        assert distance == pytest.approx(hotspot.distance_m, abs=0.1)
        bounds = {"home": (0, rings.home_m), "middle": (rings.home_m, rings.middle_m), "far": (rings.far_m, 1e9)}
        low, high = bounds[hotspot.ring]
        assert low < distance <= high, hotspot.id
    centres = np.array([hotspot.centre for hotspot in world.places.hotspots])
    gaps = np.array([angle_between(centres, centre) for centre in centres]) * world.spec.radius_m
    assert (gaps + np.eye(len(centres)) * 1e9).min() >= 40


def test_band_b_lives_west_of_the_town_by_daylight(world: GeneratedWorld) -> None:
    town, camp = _site_unit(world, "town"), _site_unit(world, "band_b_camp")
    _, (town_lon, camp_lon) = lat_lon(np.array([town, camp]))

    assert 1200 <= _metres(world, town, camp) <= 1700
    assert 2 <= (town_lon - camp_lon) / 15 <= 4  # hours behind the town
    assert 2000 <= _metres(world, _site_unit(world, "band_a_camp"), town) <= 3200


def test_band_b_s_hotspots_lie_in_its_middle_ring_and_its_wood_away_from_the_town(world: GeneratedWorld) -> None:
    camp, town = _site_unit(world, "band_b_camp"), _site_unit(world, "town")
    to_town = float(bearing_deg(camp, town[None])[0])
    for hotspot_id in ("b_wood", "b_shore"):
        assert 500 <= _metres(world, camp, np.array(_hotspot(world, hotspot_id).centre)) <= 900
    to_wood = float(bearing_deg(camp, np.array([_hotspot(world, "b_wood").centre]))[0])
    assert abs((to_wood - to_town + 180) % 360 - 180) > 120


def test_the_lords_woods_lie_on_the_west_road_600_m_from_the_town(world: GeneratedWorld) -> None:
    woods = _hotspot(world, "lords_woods")
    road = _road(world, "west_road")

    assert 500 <= woods.distance_m <= 700
    assert woods.cell in road.cells
    assert woods.claim == "town" and set(woods.hunting) == {"deer", "boar"}
    assert _metres(world, _site_unit(world, "band_b_camp"), np.array(woods.centre)) <= 1000


def test_dens_lie_where_the_table_puts_them(world: GeneratedWorld, surface: Surface, flora: Flora) -> None:
    places = world.places
    west = road_distance_m(np.array(_feature(world, "lords_woods:den").position), [_road(world, "west_road")], surface)
    trail = road_distance_m(
        np.array(_feature(world, "bridge_meadows:den").position), [_road(world, "great_trail")], surface
    )
    assert 40 <= west[0] <= 60
    assert 40 <= trail[0] <= 60
    for hotspot_id in ("lords_woods", "bridge_meadows"):  # in the hotspot, beside its stretch of the way
        hotspot = _hotspot(world, hotspot_id)
        den = np.array(_feature(world, f"{hotspot_id}:den").position)
        assert _metres(world, np.array(hotspot.centre), den) <= hotspot.radius_m, hotspot_id

    bushes = flora.units[[places.flora_nodes[kind] == "berry_bush" for kind in flora.kind]]
    for hotspot_id in ("elder_grove", "b_wood"):
        den = np.array(_feature(world, f"{hotspot_id}:den").position)
        nearest = np.sort(angle_between(bushes, den) * world.spec.radius_m)
        assert 30 <= nearest[0] <= 50, hotspot_id
    elder = np.array(_feature(world, "elder_grove:den").position)
    assert (angle_between(bushes, elder) * world.spec.radius_m < 40).any()  # bushes inside its defence ring

    for hotspot_id in ("elder_grove", "b_wood"):  # at the edge on the side away from the ways in
        den = np.array(_feature(world, f"{hotspot_id}:den").position)
        assert road_distance_m(den, places.roads, surface)[0] >= 60, hotspot_id

    lion = _feature(world, "a_savanna:den")
    camp_a = _site_unit(world, "band_a_camp")
    assert lion.animal == "lion" and BIOME_NAMES[world.biomes[lion.cell]] in ("savanna", "grassland")
    assert 600 <= _metres(world, camp_a, np.array(lion.position)) <= 1400
    north = float(bearing_deg(camp_a, np.array([lion.position]))[0])
    assert min(north, 360 - north) <= 45
    assert {feature.animal for feature in places.features if feature.kind == "den"} == {"wolf", "bear", "lion"}


def test_fixed_features_sit_on_their_terrain(world: GeneratedWorld, surface: Surface) -> None:
    features = [feature for feature in world.places.features if feature.hotspot is not None]
    for feature in features:
        hotspot = _hotspot(world, feature.hotspot or "")
        if feature.kind not in ("den", "marker"):
            assert _metres(world, np.array(hotspot.centre), np.array(feature.position)) <= hotspot.radius_m + 1
        cell = feature.cell
        around = [cell, *[int(n) for n in surface.grid.neighbours[cell] if n >= 0]]
        match feature.kind, feature.water:
            case "fishing_spot", "sea":
                assert surface.ocean[around].any() and surface.walk[around].any(), feature.id
            case (("fishing_spot" | "gold_pool"), "lake"):
                assert surface.lake[around].any(), feature.id
            case "fishing_spot", "river":
                assert surface.river[cell], feature.id
            case "iron_sand_bar", _:
                mill = next(river for river in world.rivers if river.name == "Mill river")
                assert cell in mill.cells
            case "obsidian_field", _:
                assert BIOME_NAMES[world.biomes[cell]] == "volcanic"
            case "waterhole", water:
                assert feature.pool or (water == "river" and surface.river[cell]) or surface.lake[around].any()
    counts: dict[str, int] = {}
    for feature in features:
        counts[f"{feature.hotspot}:{feature.kind}"] = counts.get(f"{feature.hotspot}:{feature.kind}", 0) + 1
    assert counts["gulf_shore:fishing_spot"] == 3 and counts["b_shore:fishing_spot"] == 3
    assert counts["falls_pool:fishing_spot"] == 3 and counts["falls_pool:gold_pool"] == 1
    assert counts["obsidian_field:obsidian_field"] == 3 and counts["river_marsh:fishing_spot"] == 2
    caps = {feature.hotspot: feature.cap for feature in features if feature.kind == "flint_seam"}
    assert caps == {"painted_cave_flint": 30, "eastern_wall_scar": 40, "b_shore": 10}
    assert {feature.hotspot for feature in features if feature.kind == "waterhole"} == {
        "lords_woods",
        "a_savanna",
        "bridge_meadows",
    }


def test_claimed_hotspots_show_a_marker_where_their_owners_way_enters(world: GeneratedWorld) -> None:
    markers = {feature.hotspot: feature for feature in world.places.features if feature.kind == "marker"}

    assert {hotspot: marker.owner for hotspot, marker in markers.items()} == {
        "lords_woods": "town",
        "eastern_wall_scar": "band_a",
        "b_wood": "band_b",
    }
    for hotspot_id, marker in markers.items():
        hotspot = _hotspot(world, hotspot_id or "")
        from_centre = _metres(world, np.array(hotspot.centre), np.array(marker.position))
        assert hotspot.radius_m - 45 <= from_centre <= hotspot.radius_m  # at the edge, where the way comes in
        assert any(marker.cell in road.cells for road in world.places.roads if hotspot.id in road.stops)


def test_band_b_hunts_the_grass_round_its_camp(world: GeneratedWorld) -> None:
    (ground,) = world.places.grounds

    assert (ground.site, ground.radius_m, ground.hunting) == ("band_b_camp", 400, ["deer"])
    assert np.allclose(ground.centre, _site_unit(world, "band_b_camp"))


def _with_hotspot(spec: HotspotsSpec, hotspot_id: str, **update: object) -> HotspotsSpec:
    hotspots = [hotspot.model_copy(update=update) if hotspot.id == hotspot_id else hotspot for hotspot in spec.hotspots]
    return spec.model_copy(update={"hotspots": hotspots})


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"biomes": ["taiga"]}, r"lies in (beach|grassland), not in \['taiga'\]"),
        ({"ring": "middle"}, "lies 220 m from town, outside its middle ring"),
        ({"at": (37.0, 12.0)}, "lies in the town chart"),
    ],
)
def test_generation_refuses_a_hotspot_with_no_spot_keeping_the_rules(
    spec: WorldSpec, surface: Surface, update: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=f"gulf_shore has no spot within 150 m .*: at it, it {message}"):
        place_hotspots(_with_hotspot(spec.hotspots, "gulf_shore", **update), surface)


def _placed(hotspots: list[Hotspot], hotspot_id: str) -> Hotspot:
    return next(hotspot for hotspot in hotspots if hotspot.id == hotspot_id)


def test_a_hotspot_off_its_rules_moves_up_to_150_m_to_keep_them(spec: WorldSpec, surface: Surface) -> None:
    target = (38.0, 30.0)  # out in the Bright gulf
    hotspots = place_hotspots(_with_hotspot(spec.hotspots, "gulf_shore", at=target), surface)

    shore = _placed(hotspots, "gulf_shore")
    moved = surface.distance_m(unit_from_lat_lon(*target), np.array(shore.centre))
    assert 0 < moved <= 150
    assert surface.walk[shore.cell] and BIOME_NAMES[surface.biomes[shore.cell]] in ("beach", "grassland")


def test_a_hotspot_whose_target_is_taken_keeps_its_distance(spec: WorldSpec, surface: Surface) -> None:
    gulf = next(hotspot for hotspot in spec.hotspots.hotspots if hotspot.id == "gulf_shore")
    hotspots = place_hotspots(_with_hotspot(spec.hotspots, "north_woods", at=gulf.at), surface)

    shore, woods = _placed(hotspots, "gulf_shore"), _placed(hotspots, "north_woods")
    gap = surface.distance_m(np.array(shore.centre), np.array(woods.centre))
    assert spec.hotspots.min_spacing_m <= gap <= 150


def test_sea_fishing_spots_sit_where_the_drawn_sea_meets_the_shore(world: GeneratedWorld, surface: Surface) -> None:
    spots = [feature for feature in world.places.features if feature.water == "sea"]
    assert len(spots) == 6
    for spot in spots:
        point = np.array(spot.position)
        best = np.inf
        for land in np.flatnonzero(surface.walk & (surface.distances_m(point) < 60)):
            for sea in surface.grid.neighbours[land]:
                if sea < 0 or not surface.ocean[sea]:
                    continue
                high, low = surface.heights[land], surface.heights[sea]
                t = float(np.clip(high / (high - low), 0.05, 0.95))
                shore = surface.grid.positions[land] * (1 - t) + surface.grid.positions[sea] * t
                best = min(best, surface.distance_m(point, shore / np.linalg.norm(shore)))
        assert best < 0.01, spot.id
