"""The action tables (D105): each row runs its handler only for its own action model."""

from collections.abc import Callable

import pytest

from app.sim import resting
from app.sim.actions import STARTS, handles
from app.sim.simulation import Simulation
from app.world_api.models import Rest, Wait
from tests.sim_helpers import make_spec


def test_a_row_refuses_another_actions_model(new_sim: Callable[..., Simulation]) -> None:
    sim = new_sim()
    citizen = sim.add_citizen(make_spec("ann"))
    with pytest.raises(TypeError):
        handles(Rest, resting.start_rest)(sim.core, citizen, Wait(minutes=5))
    with pytest.raises(TypeError):
        STARTS["rest"](sim.core, citizen, Wait(minutes=5))
    STARTS["wait"](sim.core, citizen, Wait(minutes=5))
    assert citizen.action is not None and citizen.action.kind == "wait"
