import pytest
from pydantic import ValidationError

from app.world.spec import SITE_IDS, WorldSpec, load_site_kinds, load_world_spec, spec_hash
from app.world.town import load_kinds


def test_world_spec_loads_with_every_site() -> None:
    spec = load_world_spec()

    assert [site.id for site in spec.sites] == list(SITE_IDS)
    assert spec.radius_m == 2000
    assert spec.frequency == 60
    assert spec.site("town").terrain.type == "plateau"
    assert spec.site(spec.loop_gate).id == "ice_gate"


def test_site_kinds_extend_the_town_kinds() -> None:
    kinds = load_site_kinds()

    assert set(load_kinds()) < set(kinds)
    assert {"fire_pit", "lean_to", "rock_spire", "giant_tree", "hot_spring_pool"} <= set(kinds)
    for site in load_world_spec().sites:
        assert all(placement.kind in kinds for placement in site.placements), site.id


def test_spec_rejects_a_missing_site() -> None:
    raw = load_world_spec().model_dump(by_alias=True)
    raw["sites"] = [site for site in raw["sites"] if site["id"] != "painted_cave"]

    with pytest.raises(ValidationError, match="sites must be exactly"):
        WorldSpec.model_validate(raw)


def test_spec_rejects_unknown_fields_and_half_biome_overrides() -> None:
    raw = load_world_spec().model_dump(by_alias=True)
    raw["sites"][0]["biome"] = None

    with pytest.raises(ValidationError, match="biome and biome_radius_m"):
        WorldSpec.model_validate(raw)
    with pytest.raises(ValidationError, match="Extra inputs"):
        WorldSpec.model_validate({**load_world_spec().model_dump(by_alias=True), "colour": "blue"})


def test_spec_hash_is_stable_and_follows_the_spec_and_kinds() -> None:
    spec, kinds = load_world_spec(), load_site_kinds()

    assert spec_hash(spec, kinds) == spec_hash(WorldSpec.model_validate(spec.model_dump(by_alias=True)), dict(kinds))
    assert spec_hash(spec.model_copy(update={"seed": 1}), kinds) != spec_hash(spec, kinds)
    fewer = {name: kind for name, kind in kinds.items() if name != "boulder"}
    assert spec_hash(spec, fewer) != spec_hash(spec, kinds)
