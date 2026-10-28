"""The Python face of the world contract for one citizen: what scripted brains call (and later the MCP proxy).

Instant actions return their result at once. Durative actions return an `ActionHandle` whose result appears when
the action ends in game time (completion or interrupt); the engine keeps ticking meanwhile.
"""

from dataclasses import dataclass

from app.sim.simulation import Simulation
from app.world_api.models import (
    Action,
    ActionResult,
    Attack,
    CheckSelf,
    Compass,
    DirectionTarget,
    Drink,
    Drop,
    Eat,
    FeedFire,
    Fish,
    Flee,
    Follow,
    Gather,
    Give,
    Hunt,
    LookAround,
    MakeFire,
    Perception,
    PersonTarget,
    PickUp,
    PlaceTarget,
    Recall,
    Rest,
    RoughDistance,
    Say,
    SelfView,
    Sleep,
    Target,
    ThingTarget,
    Volume,
    Wait,
    WalkTo,
    Work,
)


@dataclass(frozen=True)
class ActionHandle:
    sim: Simulation
    citizen_id: str
    number: int

    @property
    def result(self) -> ActionResult | None:
        return self.sim.result(self.citizen_id, self.number)

    @property
    def done(self) -> bool:
        return self.result is not None


class WorldApi:
    def __init__(self, sim: Simulation, citizen_id: str) -> None:
        if citizen_id not in sim.state.citizens:
            raise ValueError(f"unknown citizen {citizen_id}")
        self.sim = sim
        self.citizen_id = citizen_id

    def do(self, action: Action) -> Perception | SelfView | ActionResult | ActionHandle:
        """Any action by its model (how the MCP proxy will call in)."""
        if isinstance(action, LookAround):
            return self.sim.perceive(self.citizen_id)
        if isinstance(action, CheckSelf):
            return self.sim.check_self(self.citizen_id)
        if isinstance(action, Say | PickUp | Drop | Give | Recall):
            return self.sim.instant(self.citizen_id, action)
        return ActionHandle(self.sim, self.citizen_id, self.sim.start(self.citizen_id, action))

    def _start(self, action: Action) -> ActionHandle:
        return ActionHandle(self.sim, self.citizen_id, self.sim.start(self.citizen_id, action))

    # --- senses ---

    def look_around(self) -> Perception:
        return self.sim.perceive(self.citizen_id)

    def check_self(self) -> SelfView:
        return self.sim.check_self(self.citizen_id)

    # --- instant ---

    def say(self, words: str, volume: Volume = "normal") -> ActionResult:
        return self.sim.instant(self.citizen_id, Say(words=words, volume=volume))

    def pick_up(self, item: str) -> ActionResult:
        return self.sim.instant(self.citizen_id, PickUp(item=item))

    def drop(self, item: str) -> ActionResult:
        return self.sim.instant(self.citizen_id, Drop(item=item))

    def give(self, item: str, person: str) -> ActionResult:
        return self.sim.instant(self.citizen_id, Give(item=item, person=person))

    def recall(self, about: str) -> ActionResult:
        return self.sim.instant(self.citizen_id, Recall(about=about))

    # --- durative ---

    def walk_to(self, target: Target) -> ActionHandle:
        return self._start(WalkTo(target=target))

    def walk_to_place(self, name: str) -> ActionHandle:
        return self.walk_to(PlaceTarget(name=name))

    def walk_to_person(self, who: str) -> ActionHandle:
        return self.walk_to(PersonTarget(who=who))

    def walk_to_thing(self, what: str) -> ActionHandle:
        return self.walk_to(ThingTarget(what=what))

    def walk_towards(self, direction: Compass, distance: RoughDistance) -> ActionHandle:
        return self.walk_to(DirectionTarget(direction=direction, distance=distance))

    def gather(self, resource: str) -> ActionHandle:
        return self._start(Gather(resource=resource))

    def eat(self, item: str) -> ActionHandle:
        return self._start(Eat(item=item))

    def drink(self) -> ActionHandle:
        return self._start(Drink())

    def rest(self, minutes: int) -> ActionHandle:
        return self._start(Rest(minutes=minutes))

    def sleep(self) -> ActionHandle:
        return self._start(Sleep())

    def wait(self, minutes: int) -> ActionHandle:
        return self._start(Wait(minutes=minutes))

    def flee(self) -> ActionHandle:
        return self._start(Flee())

    # --- typed now, implemented in M6/M7 ---

    def follow(self, person: str) -> ActionHandle:
        return self._start(Follow(person=person))

    def fish(self) -> ActionHandle:
        return self._start(Fish())

    def hunt(self, animal: str) -> ActionHandle:
        return self._start(Hunt(animal=animal))

    def make_fire(self) -> ActionHandle:
        return self._start(MakeFire())

    def feed_fire(self) -> ActionHandle:
        return self._start(FeedFire())

    def work(self, task: str) -> ActionHandle:
        return self._start(Work(task=task))

    def attack(self, target: str) -> ActionHandle:
        return self._start(Attack(target=target))


def run_until_done(sim: Simulation, handle: ActionHandle, max_ticks: int) -> ActionResult:
    """Headless: tick the whole simulation until the action ends (tests and fast-forward tools)."""
    for _ in range(max_ticks):
        result = handle.result
        if result is not None:
            return result
        sim.step()
    result = handle.result
    if result is None:
        raise TimeoutError(f"action {handle.number} of {handle.citizen_id} still running after {max_ticks} ticks")
    return result
