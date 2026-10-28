"""The engine's brain hook: every tick, each living citizen's brain decides if it has nothing running."""

from collections.abc import Iterable

from app.brains.brain import UtilityBrain
from app.brains.profile import BrainProfile
from app.world_api.facade import WorldApi


class CitizenBrains:
    def __init__(self, citizens: Iterable[tuple[WorldApi, BrainProfile]], seed: int) -> None:
        self.brains = {profile.citizen_id: UtilityBrain(api, profile, seed) for api, profile in citizens}

    def __call__(self, sim: object) -> None:  # noqa: ARG002  # the engine passes the simulation to every hook
        for citizen_id in sorted(self.brains):
            self.brains[citizen_id].tick()
