"""Names spectators read: places, homes, storehouses, and where a point is."""

from app.services.places import PlaceIndex, PlaceRef
from app.sim.world import SimWorld


def test_where_is_the_smallest_place_and_area_the_largest(sim_world: SimWorld) -> None:
    index = PlaceIndex(sim_world)
    well = sim_world.places["well"].centre
    assert index.where(well) == PlaceRef(id="well", name="the well")
    assert index.area(well) == PlaceRef(id="town", name="The castle town")
    camp = sim_world.places["band_a_camp"].centre
    assert index.where(camp) == index.area(camp) == PlaceRef(id="band_a_camp", name="Band A camp")
    antipode = (-well[0], -well[1], -well[2])
    assert index.where(antipode) is None and index.area(antipode) is None


def test_homes_and_stores_have_readable_names(sim_world: SimWorld) -> None:
    index = PlaceIndex(sim_world)
    assert index.structure_name("castle-keep") == "the keep"
    assert index.structure_name("main-e-2") == "a house in the castle town"
    assert index.structure_name("band_b_camp:shelter-w") == "a lean-to at Band B camp"
    assert index.store_name("store-2") == "the storehouse" and index.is_storehouse("store-2")
    assert index.store_name("rice-fields") == "the rice fields" and not index.is_storehouse("rice-fields")
    assert index.place_name("temple") == "the temple"
    assert index.place_name("nowhere") == "nowhere"
