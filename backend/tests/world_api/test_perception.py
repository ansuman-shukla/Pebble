"""What `look_around` says: time from the local sun, things grouped and chosen by importance within a word budget,
and never a number or an id."""

from collections.abc import Callable

from app.sim.clock import TIMES
from app.sim.simulation import Simulation
from app.world_api.facade import WorldApi
from tests.sim_helpers import make_spec


def test_the_time_reads_naturally_through_a_whole_day(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    api = WorldApi(sim, sim.add_citizen(make_spec()).id)
    sentences = {when: set[str]() for _, when, _ in TIMES}
    for _ in range(24 * 4):
        perception = api.look_around()
        first_line = perception.text().splitlines()[0]
        assert first_line == f"You are {perception.place}. {perception.time}"
        assert (perception.time_of_day, perception.time) in {(when, sentence) for _, when, sentence in TIMES}
        assert "It is the sun" not in first_line and "It is It" not in first_line
        sentences[perception.time_of_day].add(perception.time)
        sim.run(15)
    assert all(sentences.values())  # every time of day came round
