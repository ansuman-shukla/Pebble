"""Rice paddies (10-world-v1 §1.4): six drawn paddies, each a node, worked only from their spots inside the rects;
a day's tending (three 20-minute sessions) +50, ripe at 100 with 60 rice (the bible's 50 and 60, D180),
harvest 10 a session (15 with a sickle), stubble replanted by tending, a ripe paddy left standing loses 2 a night: a
three-day cycle per paddy."""

from collections.abc import Callable

import pytest

from app.observability.events import NodeChanged
from app.sim import nodes, paddies, slots, wear
from app.sim.clock import DAY_MINUTES
from app.sim.node_table import load_node_kinds
from app.sim.simulation import Simulation
from app.sim.systems import midnight_at
from app.world_api.facade import WorldApi, run_until_done
from tests.sim_helpers import make_spec, stand_at_node, without_animals

FIELDS = (-112.0, 58.0)
CAP = load_node_kinds()["rice_paddy"].cap  # 60
TOWN_PLACES = ["town", "well", "rice-fields", "storehouses"]


def _farmer(sim: Simulation, citizen_id: str = "farmer", **overrides: object) -> WorldApi:
    fields: dict[str, object] = {"skills": ["farming"], "knows_places": TOWN_PLACES, "at": FIELDS}
    fields.update(overrides)
    return WorldApi(sim, sim.add_citizen(make_spec(citizen_id, **fields)).id)


def _paddy(sim: Simulation, paddy_id: str) -> int:
    return sim.world.nodes.index[paddy_id]


def _tended(sim: Simulation, *paddy_ids: str) -> None:
    """These paddies have had today's tending already (day 0)."""
    state = nodes.node_state(sim.core)
    for paddy_id in paddy_ids:
        state.tended[paddy_id], state.tended_growth[paddy_id] = 0, paddies.TEND_GROWTH


def _to_daytime(sim: Simulation, day: int) -> None:
    """Jump the clock (between ticks) to mid-morning of a later town day."""
    sim.state.tick = day * DAY_MINUTES + 120  # the clock starts at 08:00


def test_the_paddies_start_at_growth_0_0_50_50_100_100(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    ids = [f"paddy-{n}" for n in range(1, 7)]
    assert [nodes.growth(sim.core, _paddy(sim, i)) for i in ids] == [0, 0, 50, 50, 100, 100]
    assert [nodes.stock(sim.core, _paddy(sim, i)) for i in ids] == [0, 0, 0, 0, CAP, CAP]
    assert [nodes.stage(sim.core, _paddy(sim, i)) for i in ids] == ["seedlings"] * 2 + ["green"] * 2 + ["gold"] * 2


def test_farmers_go_to_the_paddy_that_needs_them_most(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    first, second, third = (_farmer(sim, name) for name in ("ann", "ben", "cid"))
    for api in (first, second, third):
        api.work("farm")
    sim.run(1)
    held = {api.citizen_id: slots.held_slot(sim.core, sim.citizen(api.citizen_id)) for api in (first, second, third)}
    owners = [slot.owner if slot is not None else None for slot in held.values()]
    assert owners == ["paddy-5"] * 3  # the nearest ripe paddy has four spots: one each
    for citizen_id, slot in held.items():
        assert slot is not None
        assert sim.world.distance_m(sim.citizen(citizen_id).position, slot.position) < 0.01  # stepped into the paddy
        action = sim.citizen(citizen_id).action
        assert action is not None and action.args["where"] == "in the paddies"


def test_tending_grows_a_paddy_once_a_day_until_it_ripens(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    for ripe in ("paddy-5", "paddy-6"):  # harvested already: stubble there, replanted when tended
        nodes.change(sim.core, _paddy(sim, ripe), 0, None)
    _tended(sim, "paddy-5", "paddy-6", "paddy-1", "paddy-2", "paddy-4")
    api = _farmer(sim)
    green = _paddy(sim, "paddy-3")  # the only one still to tend today
    sessions = [run_until_done(sim, api.work("farm"), 21).text for _ in range(3)]  # an hour, in three sessions
    assert sessions[:2] == ["You tend the paddy; the rice grows green and tall."] * 2
    assert [nodes.growth(sim.core, green)] == [100] and sessions[2] == (
        "You tend the paddy; the rice turns gold and is ready to harvest."
    )  # 50 + 17 + 17 + 16: a day's tending is 50
    assert nodes.growth(sim.core, green) == 100 and nodes.stock(sim.core, green) == CAP
    assert paddies.paddy_at(sim.core, sim.citizen(api.citizen_id).position) == green
    again = run_until_done(sim, api.work("farm"), 21)  # the ripe one is first now: a harvest session
    assert again.text == "You harvest some rice." and nodes.stock(sim.core, green) == CAP - 10
    for _ in range(-(-(CAP - 10) // 10)):  # session by session, ten at a time, till it's cut
        sim.citizen(api.citizen_id).inventory.clear()
        run_until_done(sim, api.work("farm"), 21)
    assert nodes.stock(sim.core, green) == 0 and nodes.stage(sim.core, green) == "stubble"
    sim.citizen(api.citizen_id).inventory.clear()
    done = run_until_done(sim, api.work("farm"), 21)  # nothing needs tending today: it counts for nothing
    assert done.text == "You tend the paddy, but it needs nothing more today."
    _to_daytime(sim, 1)
    replanted = run_until_done(sim, api.work("farm"), 21)
    assert replanted.text == "You plant the stubbled paddy with young seedlings."


def test_a_paddy_runs_a_three_day_cycle_of_sixty_rice(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    api = _farmer(sim)
    farmer = sim.citizen(api.citizen_id)
    paddy = _paddy(sim, "paddy-6")
    harvests: dict[int, int] = {}
    for day in range(9):
        _to_daytime(sim, day)
        for _ in range(12):  # a farmer's day here, session by session: harvest it while ripe, else tend it
            stand_at_node(sim, farmer.id, paddy)
            slots.claim(sim.core, farmer, slots.node_slots(sim.core, paddy)[0], farmer.position)
            # the finisher alone, with no farm action running (None): `farm` doesn't read its action
            text = paddies.farm(sim.core, farmer, farmer.action)  # type: ignore[arg-type]  # action is None here
            if farmer.inventory.get("rice"):
                harvests[day] = harvests.get(day, 0) + farmer.inventory.pop("rice")
            if "nothing more today" in text:
                break
    # ripe at the start; then replant, tend, tend to ripe and harvest: a paddy's rice every three days
    assert harvests == {0: CAP, 2: CAP, 5: CAP, 8: CAP}


def test_a_ripe_paddy_left_standing_loses_two_a_night(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    paddy = _paddy(sim, "paddy-5")
    unit = sim.world.nodes.unit(paddy)
    while not midnight_at(sim.core, unit):
        sim.step()
    sim.drain()
    assert nodes.stock(sim.core, paddy) == CAP - 2
    sim.run(DAY_MINUTES)
    assert nodes.stock(sim.core, paddy) == CAP - 4
    growing = _paddy(sim, "paddy-3")
    assert nodes.stock(sim.core, growing) == 0 and nodes.growth(sim.core, growing) == 50  # only ripe rice is lost
    lost = [e.payload for e in sim.drain() if isinstance(e.payload, NodeChanged) and e.payload.node == "paddy-5"]
    assert [(p.before, p.after) for p in lost] == [(CAP - 2, CAP - 4)] and all(p.stage == "gold" for p in lost)


def test_a_ripe_paddy_comes_first_even_from_another_paddy(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    api = _farmer(sim)
    farmer = sim.citizen(api.citizen_id)
    stand_at_node(sim, farmer.id, _paddy(sim, "paddy-4"))  # growing, untended, right here
    nodes.change(sim.core, _paddy(sim, "paddy-5"), 0, None)  # stubble
    _tended(sim, "paddy-5")
    api.work("farm")
    sim.run(1)
    held = slots.held_slot(sim.core, farmer)
    assert held is not None and held.owner == "paddy-6"  # the ripe one, across the dike


def test_an_elder_harvests_a_session_in_twenty_minutes(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    api = _farmer(sim, age=70)
    handle = api.work("farm")
    sim.run(19)
    assert handle.result is None
    assert run_until_done(sim, handle, 2).text == "You harvest some rice."


def test_an_elder_tends_in_half_hour_sessions(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    for ripe in ("paddy-5", "paddy-6"):
        nodes.change(sim.core, _paddy(sim, ripe), 0, None)
    _tended(sim, "paddy-1", "paddy-2", "paddy-4", "paddy-5", "paddy-6")
    api = _farmer(sim, age=70)
    handle = api.work("farm")
    sim.run(28)
    assert handle.result is None  # an elder's session is half an hour (the day's tending an hour and a half)
    assert run_until_done(sim, handle, 3).text.startswith("You tend the paddy")
    assert nodes.growth(sim.core, _paddy(sim, "paddy-3")) == 50 + paddies.TEND_SESSION


def test_a_sickle_harvests_more_and_wears(new_sim: Callable[..., Simulation], monkeypatch: pytest.MonkeyPatch) -> None:
    sim = without_animals(new_sim())
    used: list[str] = []
    monkeypatch.setattr(wear, "use_tool", _recorder(used))
    api = _farmer(sim, inventory={"sickle": 1})
    result = run_until_done(sim, api.work("farm"), 21)
    assert result.text == "You harvest plenty of rice." and sim.citizen(api.citizen_id).inventory["rice"] == 15
    assert used == ["sickle"]  # one roll per 20-minute session


def test_gathering_rice_is_one_harvest_session_at_a_ripe_paddys_spot(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    api = _farmer(sim)
    farmer = sim.citizen(api.citizen_id)
    stand_at_node(sim, farmer.id, _paddy(sim, "paddy-3"))  # green, not ripe
    assert run_until_done(sim, api.gather("rice"), 1).outcome == "failed"
    stand_at_node(sim, farmer.id, _paddy(sim, "paddy-6"))
    handle = api.gather("rice")
    sim.run(19)
    assert handle.result is None
    assert run_until_done(sim, handle, 2).text == "You harvest some rice." and farmer.inventory == {"rice": 10}
    assert nodes.stock(sim.core, _paddy(sim, "paddy-6")) == CAP - 10


def _recorder(used: list[str]) -> Callable[..., bool]:
    """A stand-in for `wear.use_tool` that notes each tool used and never breaks it."""

    def use(_core: object, _citizen: object, item: str, **_cause: object) -> bool:
        used.append(item)
        return False

    return use


def test_a_farmer_done_with_a_paddy_moves_on_to_one_that_needs_work(new_sim: Callable[..., Simulation]) -> None:
    sim = without_animals(new_sim())
    api = _farmer(sim)
    farmer = sim.citizen(api.citizen_id)
    done = _paddy(sim, "paddy-4")
    _tended(sim, "paddy-4")
    stand_at_node(sim, farmer.id, done)
    slots.claim(sim.core, farmer, slots.node_slots(sim.core, done)[0], farmer.position)
    refused = run_until_done(sim, api.work("farm"), 1)
    assert refused.text == "Another paddy needs you more than this one; walk over to it first."
    run_until_done(sim, api.walk_to_place("the rice fields"), 10)
    held = slots.held_slot(sim.core, farmer)
    assert held is not None and held.owner in ("paddy-5", "paddy-6")  # the walk goes to a ripe one


def test_every_paddy_spot_lies_at_the_rice_fields(new_sim: Callable[..., Simulation]) -> None:
    """A farmer on any paddy's spot is "at the rice fields" (else a brain walks there again and again)."""
    sim = new_sim()
    fields = sim.world.places[paddies.FIELDS]
    for node in paddies.paddies(sim.core):
        for spot in sim.world.nodes.spots(node):
            assert sim.world.distance_m(spot.position, fields.centre) <= fields.radius_m
