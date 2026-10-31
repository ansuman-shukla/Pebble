"""The Python face of the world contract for one citizen: what scripted brains call (and later the MCP proxy).

Instant actions return their result at once. Durative actions return an `ActionHandle` whose result appears when
the action ends in game time (completion or interrupt); the engine keeps ticking meanwhile.
"""

from dataclasses import dataclass

from pydantic import JsonValue

from app.sim.simulation import Simulation
from app.world_api.models import (
    INSTANT_ACTIONS,
    Accuse,
    Action,
    ActionResult,
    Attack,
    Buy,
    CheckSelf,
    Compass,
    Craft,
    DirectionTarget,
    Drink,
    Driver,
    Drop,
    Eat,
    FeedFire,
    Fish,
    Flee,
    Follow,
    Gather,
    Gesture,
    GestureKind,
    Give,
    Hunt,
    Judge,
    LookAround,
    MakeFire,
    Pace,
    Perception,
    PersonTarget,
    PickUp,
    PlaceTarget,
    Recall,
    Rest,
    RoughDistance,
    Say,
    Seize,
    SelfView,
    Sell,
    SetGoal,
    Sleep,
    Stash,
    Target,
    Tend,
    ThingTarget,
    Verdict,
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
        if action.action in INSTANT_ACTIONS:
            return self.sim.instant(self.citizen_id, action)
        return ActionHandle(self.sim, self.citizen_id, self.sim.start(self.citizen_id, action))

    def _start(self, action: Action) -> ActionHandle:
        return ActionHandle(self.sim, self.citizen_id, self.sim.start(self.citizen_id, action))

    # --- the mind's own side (not actions: nothing here changes the world) ---

    @property
    def alive(self) -> bool:
        """Whether there is still someone to act (a mind knows when it has died)."""
        return self.sim.citizen(self.citizen_id).body.alive

    def handle(self, number: int) -> ActionHandle:
        """The handle of an action this citizen started earlier (by its number), e.g. after the engine resumed."""
        return ActionHandle(self.sim, self.citizen_id, number)

    @property
    def notes(self) -> dict[str, JsonValue]:
        """A scripted brain's working memory for this citizen. It is kept with the world so a resumed run continues
        exactly; it is never part of what the citizen perceives. Agent minds keep their own memory (05)."""
        return self.sim.state.notes.setdefault(self.citizen_id, {})

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

    def buy(self, item: str, amount: int) -> ActionResult:
        return self.sim.instant(self.citizen_id, Buy(item=item, amount=amount))

    def sell(self, item: str, amount: int) -> ActionResult:
        return self.sim.instant(self.citizen_id, Sell(item=item, amount=amount))

    def stash(self, item: str, amount: int) -> ActionResult:
        return self.sim.instant(self.citizen_id, Stash(item=item, amount=amount))

    def accuse(self, person: str, to: str) -> ActionResult:
        return self.sim.instant(self.citizen_id, Accuse(person=person, to=to))

    def gesture(self, kind: GestureKind, to: str | None = None) -> ActionResult:
        return self.sim.instant(self.citizen_id, Gesture(kind=kind, to=to))

    def set_goal(self, text: str, driver: Driver) -> ActionResult:
        """What this citizen is after now and why: spectators see it, nobody in the world does; it takes no time."""
        return self.sim.instant(self.citizen_id, SetGoal(text=text, driver=driver))

    # --- durative ---

    def walk_to(self, target: Target, pace: Pace = "walk") -> ActionHandle:
        return self._start(WalkTo(target=target, pace=pace))

    def walk_to_place(self, name: str, pace: Pace = "walk") -> ActionHandle:
        return self.walk_to(PlaceTarget(name=name), pace)

    def walk_to_person(self, who: str, pace: Pace = "walk") -> ActionHandle:
        return self.walk_to(PersonTarget(who=who), pace)

    def walk_to_thing(self, what: str, pace: Pace = "walk") -> ActionHandle:
        return self.walk_to(ThingTarget(what=what), pace)

    def walk_towards(self, direction: Compass, distance: RoughDistance, pace: Pace = "walk") -> ActionHandle:
        return self.walk_to(DirectionTarget(direction=direction, distance=distance), pace)

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

    def work(self, task: str) -> ActionHandle:
        """A role task: farm, store food, guard, trade, weave, govern."""
        return self._start(Work(task=task))

    def follow(self, person: str, pace: Pace = "walk") -> ActionHandle:
        return self._start(Follow(person=person, pace=pace))

    def fish(self) -> ActionHandle:
        return self._start(Fish())

    def hunt(self, animal: str) -> ActionHandle:
        return self._start(Hunt(animal=animal))

    def make_fire(self) -> ActionHandle:
        return self._start(MakeFire())

    def feed_fire(self) -> ActionHandle:
        return self._start(FeedFire())

    def attack(self, target: str) -> ActionHandle:
        return self._start(Attack(target=target))

    def craft(self, recipe: str) -> ActionHandle:
        return self._start(Craft(recipe=recipe))

    def seize(self, person: str) -> ActionHandle:
        return self._start(Seize(person=person))

    def judge(self, person: str, sentence: Verdict) -> ActionHandle:
        return self._start(Judge(person=person, sentence=sentence))

    def tend(self, person: str) -> ActionHandle:
        return self._start(Tend(person=person))


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
