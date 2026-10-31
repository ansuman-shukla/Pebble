"""The town economy through `world_api`: farmers harvest the ripe paddies (the paddy cycle: tests/sim/test_paddies.py),
food goes into the lord's granary (the storehouses) and his household eats from it, others take from it only by
stealing, role tasks need the skill and the place, and every change replays from its events."""

from collections.abc import Callable

from app.observability.events import Stole
from app.observability.replay import ReplayEvent, from_snapshot, replay
from app.sim import nodes
from app.sim.bodies import ACTIVE_RATE, HUNGER_PER_HOUR
from app.sim.node_table import load_node_kinds
from app.sim.paddies import paddy_at
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import make_spec, without_animals

FIELDS = (-112.0, 58.0)
STOREHOUSES = (70.0, 85.0)
STORE = "store-2"  # the storehouse at the storehouses' stand
MARKET = (20.0, 56.0)
CAP = load_node_kinds()["rice_paddy"].cap  # a ripe paddy's rice
TOWN_PLACES = ["town", "well", "main-gate", "west-gate", "rice-fields", "storehouses", "market", "castle"]


def _farmer(sim: Simulation, at: tuple[float, float] = FIELDS, **overrides: object) -> WorldApi:
    fields: dict[str, object] = {"role": "rice farmer", "skills": ["farming"], "knows_places": TOWN_PLACES, "at": at}
    fields.update(overrides)
    return WorldApi(sim, sim.add_citizen(make_spec("farmer", name="Genzo", **fields)).id)


def test_a_session_in_a_ripe_paddy_harvests_its_rice(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = _farmer(sim)
    farmer = sim.citizen(api.citizen_id)
    hunger = farmer.body.hunger
    handle = api.work("farm")
    assert farmer.action is not None and farmer.action.label == "tending the rice paddies"
    sim.run(19)
    assert handle.result is None  # a 20-minute session
    result = run_until_done(sim, handle, 2)
    assert (result.outcome, result.text) == ("done", "You harvest some rice.")
    assert farmer.inventory == {"rice": 10}
    paddy = paddy_at(sim.core, farmer.position)
    assert paddy is not None and sim.world.nodes.ids[paddy] in ("paddy-5", "paddy-6")  # a ripe one, standing in it
    assert nodes.stock(sim.core, paddy) == CAP - 10
    assert farmer.body.hunger - hunger > HUNGER_PER_HOUR * ACTIVE_RATE * 0.95 / 3  # field work is hard work


def test_a_full_farmer_leaves_the_ripe_rice_standing(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())  # a deer wandering into view would end the hour
    api = _farmer(sim, inventory={"rice": 120})  # 24 kg of 25
    result = run_until_done(sim, api.work("farm"), 61)
    assert result.text == "You harvest some rice."
    farmer = sim.citizen(api.citizen_id)
    assert farmer.inventory == {"rice": 125}
    paddy = paddy_at(sim.core, farmer.position)
    assert paddy is not None and nodes.stock(sim.core, paddy) == CAP - 5
    again = run_until_done(sim, api.work("farm"), 61)
    assert again.text == "You can't carry any more."
    assert nodes.stock(sim.core, paddy) == CAP - 5


def test_rice_goes_into_the_granary_and_the_keep_s_household_eats_from_it(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    sim.stock_store(STORE, "rice", 30)
    api = _farmer(sim, at=STOREHOUSES, inventory={"rice": 20, "reeds": 3}, home="castle-keep")
    stored = run_until_done(sim, api.work("store food"), 10)
    assert stored.text == "You put plenty of rice in the storehouse."
    assert sim.state.stores[STORE] == {"rice": 50}
    assert sim.citizen(api.citizen_id).inventory == {"reeds": 3}  # only food goes into the store

    farmer = sim.citizen(api.citizen_id)
    farmer.body.hunger = 55.0
    eaten = run_until_done(sim, api.eat("rice"), 10)
    assert eaten.text == "You eat some rice. You feel full."
    assert sim.state.stores[STORE] == {"rice": 44}
    assert farmer.body.hunger < 1.0
    assert farmer.inventory == {"reeds": 3}


def test_a_stranger_eating_from_the_granary_steals_and_it_is_reached_only_close_by(
    new_sim: Callable[..., Simulation],
) -> None:
    sim = new_sim()
    sim.stock_store(STORE, "rice", 30)
    sim.add_citizen(make_spec("kenji", at=(0.0, 3.0), home="castle-keep"))  # the robbed household
    stranger = WorldApi(sim, sim.add_citizen(make_spec("stranger", at=STOREHOUSES, region="band_a")).id)
    sim.citizen("stranger").body.hunger = 50.0
    sim.drain()
    assert run_until_done(sim, stranger.eat("rice"), 10).outcome == "done"
    assert [e.payload.count for e in sim.drain() if isinstance(e.payload, Stole)] == [5]
    townsman = WorldApi(sim, sim.add_citizen(make_spec("townsman", at=MARKET, knows_places=TOWN_PLACES)).id)
    sim.citizen("townsman").body.hunger = 50.0
    assert run_until_done(sim, townsman.eat("rice"), 1).outcome == "failed"
    assert run_until_done(sim, townsman.work("store food"), 1).text == "There's no storehouse within reach."
    assert sim.state.stores[STORE] == {"rice": 25}


def test_role_tasks_need_the_skill_and_the_place(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = _farmer(sim, at=MARKET, skills=["farming", "trade", "weaving"], home="farmhouse-1")  # the loom's house
    assert run_until_done(sim, api.work("farm"), 1).text == "There are no fields here to tend."
    assert run_until_done(sim, api.work("guard"), 1).text == "You don't know how to do that."
    assert run_until_done(sim, api.work("dance"), 1).text == "You don't know how to do that."
    assert run_until_done(sim, api.work("weave"), 1).text == "Your loom is at home."
    assert run_until_done(sim, api.work("store food"), 1).text == "There's no storehouse within reach."
    trade = run_until_done(sim, api.work("trade"), 61)
    assert (trade.outcome, trade.text) == ("done", "You keep the stall a while; nobody comes to trade.")
    run_until_done(sim, api.walk_to_place("home"), 60)
    sim.citizen(api.citizen_id).inventory["reeds"] = 2
    assert run_until_done(sim, api.work("weave"), 61).text == "You weave a length of cloth."


def test_work_stops_when_a_need_worsens_or_night_falls(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = _farmer(sim)
    sim.citizen(api.citizen_id).body.thirst = 59.99
    result = run_until_done(sim, api.work("farm"), 5)
    assert (result.outcome, result.text) == ("interrupted", "You stop working: you are getting thirsty.")
    assert sim.citizen(api.citizen_id).inventory == {}  # nothing is harvested in a few minutes


def test_storing_and_farming_replay_from_events(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    start = take_snapshot(sim.state)
    sim.stock_store(STORE, "rice", 30)
    api = _farmer(sim)
    run_until_done(sim, api.work("farm"), 61)
    run_until_done(sim, api.walk_to_place("the storehouses"), 60)
    run_until_done(sim, api.work("store food"), 10)
    events = [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in sim.drain()]
    rebuilt = replay(start, events)
    assert rebuilt.same_as(from_snapshot(take_snapshot(sim.state)))
    assert rebuilt.stores[STORE] == {"rice": 30 + 4}  # the rice tax on the harvest session: ⌈40 % of 10⌉
    assert rebuilt.nodes == from_snapshot(take_snapshot(sim.state)).nodes != {}
