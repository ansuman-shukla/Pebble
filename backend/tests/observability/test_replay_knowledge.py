"""Replay keeps what citizens can do and know: skills, places and people from their spawn and what they learn."""

from collections.abc import Callable

from app.observability.replay import ReplayEvent, from_snapshot, replay
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.simulation import Simulation
from app.sim.snapshot import take_snapshot


def test_replay_from_before_the_spawn_knows_what_they_know(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim(seed=7)
    start = take_snapshot(sim.state)  # nobody yet
    for spec in load_citizens(CITIZENS).citizens:
        sim.add_citizen(spec)
    events = [ReplayEvent(e.tick, e.type, e.actor_id, e.payload.model_dump(mode="json")) for e in sim.drain()]
    rebuilt = replay(start, events)
    assert rebuilt.same_as(from_snapshot(take_snapshot(sim.state)))
    genzo = rebuilt.citizens["genzo"]
    assert genzo.skills == ("farming",)
    assert genzo.people == {
        "aiko",
        "daisuke",
        "ennen",
        "fumiko",
        "goro",
        "hana",
        "kenji",
        "masanori",
        "tetsu",
        "tokuji",
    }
    assert genzo.places["rice-fields"] == "visited"
