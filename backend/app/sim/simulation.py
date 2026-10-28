"""The simulation: the single authority on what is true (02-simulation).

Each tick (= 1 game minute): advance durative actions (walkers move) → bodies → ecology (M6) → perception and
interrupts → visits → one `tick_summary`. Actions from brains arrive between ticks. The simulation never reads the
wall clock and draws randomness only from its seeded streams, so the same seed and inputs give the same state.
"""

import numpy as np

from app.core.rng import Rng
from app.observability.events import (
    AnimalPose,
    CitizenSpawned,
    Died,
    EventDraft,
    ItemLocation,
    ItemMoved,
    Moved,
    NeedChanged,
    Perceived,
    TickSummary,
)
from app.sim import actions, ecology
from app.sim.acting import refuse
from app.sim.bodies import COLLAPSE_WAKE_ENERGY, HOT_BIOMES, Crossing, update_body
from app.sim.citizens import CitizenSpec
from app.sim.core import GiftPolicy, SimCore
from app.sim.fauna import place_groups
from app.sim.fire import hearth_fires
from app.sim.items import ITEMS, RESOURCES
from app.sim.navigation import Planner
from app.sim.perception import animal_sightings, perceive, self_view
from app.sim.state import RNG_STREAMS, Animal, Citizen, GroundStack, PlaceKnowledge, WorldState, age_group
from app.sim.vec import Vec3, step_towards
from app.sim.world import SimWorld, site_unit
from app.world_api.models import (
    INSTANT_ACTIONS,
    NOT_YET_ACTIONS,
    Action,
    ActionResult,
    CheckSelf,
    Drop,
    Give,
    LookAround,
    Perception,
    PickUp,
    Say,
    SelfView,
)

INITIAL_RESOURCE_SHARE = 0.5  # cells start between half and fully stocked
WOODPILE = 12  # pieces of wood by each camp's fire pit at the start
WOODPILE_OFFSET_M = 3.2  # beyond the seats round the pit (2 m), between two of them
WOODPILE_BEARING = 112.5


def initial_state(world: SimWorld, seed: int) -> WorldState:
    rngs = {name: Rng.for_subsystem(seed, name) for name in RNG_STREAMS}
    resources = np.zeros_like(world.resource_caps)
    stocked = np.flatnonzero(world.resource_caps.any(axis=1))
    ecology_rng = rngs["ecology"]
    for cell in stocked.tolist():
        for column in range(len(RESOURCES)):
            cap = int(world.resource_caps[cell, column])
            if cap:
                share = INITIAL_RESOURCE_SHARE + (1 - INITIAL_RESOURCE_SHARE) * ecology_rng.random()
                resources[cell, column] = round(cap * share)
    groups, animals = place_groups(world, rngs["animals"])
    fires = hearth_fires(world)
    ground: dict[str, GroundStack] = {}
    for fire_id in sorted(fires):  # each camp keeps a woodpile by its fire pit
        if fires[fire_id].kind == "pit":
            spot = step_towards(fires[fire_id].position, WOODPILE_BEARING, WOODPILE_OFFSET_M, world.radius_m)
            stack_id = f"stack-{len(ground) + 1}"
            ground[stack_id] = GroundStack(stack_id, "wood", WOODPILE, spot, world.nearest_cell(spot))
    return WorldState(
        tick=0,
        next_seq=1,
        next_stack=len(ground) + 1,
        citizens={},
        ground=ground,
        stores={},
        resources=resources,
        rngs=rngs,
        animals={animal.id: animal for animal in animals},
        groups={group.id: group for group in groups},
        fires=fires,
        next_animal=len(animals) + 1,
    )


class Simulation:
    def __init__(
        self,
        world: SimWorld,
        state: WorldState,
        planner: Planner | None = None,
        accepts_gift: GiftPolicy | None = None,
    ) -> None:
        self.core = SimCore(world, planner or Planner(world), state, accepts_gift)

    @classmethod
    def new(cls, world: SimWorld, seed: int | None = None, planner: Planner | None = None) -> "Simulation":
        return cls(world, initial_state(world, world.seed if seed is None else seed), planner)

    @property
    def world(self) -> SimWorld:
        return self.core.world

    @property
    def state(self) -> WorldState:
        return self.core.state

    @property
    def tick(self) -> int:
        return self.core.state.tick

    def drain(self) -> list[EventDraft]:
        """Events emitted since the last drain, in order."""
        events, self.core.outbox = self.core.outbox, []
        return events

    def citizen(self, citizen_id: str) -> Citizen:
        return self.core.state.citizens[citizen_id]

    # --- creating citizens ---

    def add_citizen(self, spec: CitizenSpec) -> Citizen:
        world, state = self.core.world, self.core.state
        if spec.id in state.citizens:
            raise ValueError(f"citizen {spec.id} exists already")
        if spec.home is not None and (spec.home not in world.structures or not world.structures[spec.home].is_home):
            raise ValueError(f"{spec.id}: {spec.home} is not a house")
        unknown = sorted(set(spec.knows_places) - set(world.places))
        if unknown:
            raise ValueError(f"{spec.id}: unknown places {unknown}")
        bad_items = sorted(item for item, count in spec.inventory.items() if item not in ITEMS or count <= 0)
        if bad_items:
            raise ValueError(f"{spec.id}: can't start with {bad_items}")
        position = self._spawn_point(spec)
        cell = world.nearest_cell(position)
        citizen = Citizen(
            id=spec.id,
            name=spec.name,
            look=spec.look,
            appearance=spec.appearance,
            age=spec.age,
            group=age_group(spec.age),
            home=spec.home,
            position=position,
            cell=cell,
            height_m=world.ground_height(position, cell),
            role=spec.role,
            region=spec.region,
            skills=tuple(spec.skills),
            inventory={item: spec.inventory[item] for item in sorted(spec.inventory)},
        )
        for place_id in spec.knows_places:
            place = world.places[place_id]
            citizen.places[place_id] = PlaceKnowledge(level="visited", guess=place.stand)
        citizen.people = set(spec.knows_people) - {spec.id}
        state.citizens[spec.id] = citizen
        body = citizen.body
        self.core.emit(
            "citizen_spawned",
            CitizenSpawned(
                id=citizen.id,
                name=citizen.name,
                look=citizen.look,
                appearance=citizen.appearance,
                age=citizen.age,
                group=citizen.group,
                home=citizen.home,
                position=citizen.position,
                height_m=citizen.height_m,
                cell=citizen.cell,
                body=(body.hunger, body.thirst, body.energy, body.health),
                places=dict.fromkeys(sorted(citizen.places), "visited"),
                people=sorted(citizen.people),
                role=citizen.role,
                region=citizen.region,
                skills=list(citizen.skills),
                heading_deg=citizen.heading_deg,
                inventory=dict(citizen.inventory),
            ),
            actor=citizen,
        )
        seen = self._visibility(self.core.living())  # placing someone isn't anyone "coming into view"
        for other in self.core.living():
            if citizen.id in seen[other.id]:
                other.in_view.add(citizen.id)
        citizen.in_view = seen[citizen.id]
        citizen.animals_in_view = set(_groups(animal_sightings(self.core, [citizen])[citizen.id]))
        self._visit(citizen)
        return citizen

    def stock_store(self, store_id: str, item: str, count: int) -> None:
        """Put a starting stock into a storehouse (one `item_moved` from the world)."""
        structure = self.core.world.structures.get(store_id)
        if structure is None or structure.kind != "storehouse":
            raise ValueError(f"{store_id} is not a storehouse")
        if item not in ITEMS or count <= 0:
            raise ValueError(f"can't stock {count} {item}")
        store = self.core.state.stores.setdefault(store_id, {})
        store[item] = store.get(item, 0) + count
        self.core.emit(
            "item_moved",
            ItemMoved(
                item=item,
                count=count,
                source=ItemLocation(kind="world"),
                destination=ItemLocation(kind="store", id=store_id),
            ),
        )

    def _spawn_point(self, spec: CitizenSpec) -> Vec3:
        world = self.core.world
        if spec.site == "town":
            if not world.town.walk.is_walkable(*spec.at):
                raise ValueError(f"{spec.id} would start on a blocked town spot {spec.at}")
            return world.town.to_unit(*spec.at)
        site = next((s for s in world.sites if s.id == spec.site), None)
        if site is None:
            raise ValueError(f"{spec.id}: unknown site {spec.site}")
        position = site_unit(world.radius_m, site, *spec.at)
        if not self.core.planner.outer.allowed[world.nearest_cell(position)]:
            raise ValueError(f"{spec.id} would start in water or off the walkable ground")
        return position

    # --- senses and actions (called between ticks) ---

    def _actor(self, citizen_id: str) -> Citizen:
        citizen = self.core.state.citizens[citizen_id]
        if not citizen.body.alive:
            raise ValueError(f"{citizen_id} is dead and can't act")
        return citizen

    def perceive(self, citizen_id: str) -> Perception:
        citizen = self._actor(citizen_id)
        perception = perceive(self.core, citizen)
        self.core.emit(
            "perceived",
            Perceived(kind="look_around", text=perception.text()),
            actor=citizen,
            visibility="private",
        )
        return perception

    def check_self(self, citizen_id: str) -> SelfView:
        citizen = self._actor(citizen_id)
        view = self_view(self.core, citizen)
        self.core.emit("perceived", Perceived(kind="check_self", text=view.text()), actor=citizen, visibility="private")
        return view

    def instant(self, citizen_id: str, action: Action) -> ActionResult:
        """Run an instant action (say, pick_up, drop, give; the not-yet ones answer in-world)."""
        if action.action not in INSTANT_ACTIONS and action.action not in NOT_YET_ACTIONS:
            raise ValueError(f"{action.action} is durative; use start()")
        if isinstance(action, LookAround | CheckSelf):
            raise ValueError("look_around and check_self return perceptions; use perceive() / check_self()")
        citizen = self._actor(citizen_id)
        if action.action in NOT_YET_ACTIONS:
            return actions.not_yet(self.core, citizen, action.action)
        if citizen.body.asleep:
            sleep = citizen.action
            if sleep is not None and sleep.collapsed and citizen.body.energy < COLLAPSE_WAKE_ENERGY:
                return refuse(self.core, citizen, action.action, "You are too exhausted.")
            if sleep is not None:
                self.core.end_action(citizen, "interrupted", "You get up.")
        if isinstance(action, Say):
            return actions.say(self.core, citizen, action)
        if isinstance(action, PickUp):
            return actions.pick_up(self.core, citizen, action)
        if isinstance(action, Drop):
            return actions.drop(self.core, citizen, action)
        if isinstance(action, Give):
            return actions.give(self.core, citizen, action)
        raise ValueError(f"no instant handler for {action.action}")

    def start(self, citizen_id: str, action: Action) -> int:
        """Start a durative action; returns its number for `result()`."""
        if action.action in INSTANT_ACTIONS:
            raise ValueError(f"{action.action} is instant; use instant()")
        return actions.start(self.core, self._actor(citizen_id), action)

    def result(self, citizen_id: str, number: int) -> ActionResult | None:
        """The result of a durative action once it has ended, else None."""
        return self.core.state.citizens[citizen_id].results.get(number)

    # --- the tick ---

    def step(self) -> None:
        core = self.core
        core.state.tick += 1
        core.hurt.clear()
        before = {citizen.id: citizen.position for citizen in core.living()}
        poses = {a.id: (a.position, a.heading_deg, a.activity) for a in core.state.animals.values() if a.alive}
        headings = {citizen.id: actions.walk_heading(citizen) for citizen in core.living()}

        # followers move last, after the people they follow have taken this minute's steps
        for citizen in sorted(core.living(), key=lambda c: c.action is not None and c.action.kind == "follow"):
            actions.advance(core, citizen)

        worse: dict[str, list[Crossing]] = {}
        for citizen in core.living():
            worse[citizen.id] = self._body(citizen)

        ecology.step(core)

        living = core.living()
        seen = self._visibility(living)
        sightings = animal_sightings(core, living)
        groups_seen: dict[str, dict[str, tuple[Animal, float, int]]] = {}
        stalkers: dict[str, set[str]] = {}
        for citizen in living:
            groups_seen[citizen.id] = _groups(sightings[citizen.id])
            stalkers[citizen.id] = {a.id for a, _ in sightings[citizen.id] if a.alive and a.target == citizen.id}
            strangers = sorted(other for other in seen[citizen.id] - citizen.in_view if other not in citizen.people)
            coming = actions.approaching(core, citizen, seen[citizen.id], before, headings)
            night = actions.night_fell(core, citizen)
            news = actions.AnimalNews(
                hurt=core.hurt.get(citizen.id),
                threats=tuple(
                    (animal, distance)
                    for animal, distance in sightings[citizen.id]
                    if animal.id in stalkers[citizen.id] - citizen.threats
                ),
                groups=tuple(
                    groups_seen[citizen.id][group]
                    for group in sorted(set(groups_seen[citizen.id]) - citizen.animals_in_view)
                ),
            )
            actions.interrupt(core, citizen, worse[citizen.id], strangers, coming, night, news)
        for citizen in living:
            citizen.in_view = seen[citizen.id]
            citizen.animals_in_view = set(groups_seen[citizen.id])
            citizen.threats = stalkers[citizen.id]
            self._visit(citizen)

        moved: dict[str, Moved] = {}
        for citizen in core.citizens():
            if citizen.id in before and citizen.position != before[citizen.id]:
                route, speed_mps = actions.walk_ahead(core, citizen)
                moved[citizen.id] = Moved(
                    position=citizen.position,
                    height_m=citizen.height_m,
                    cell=citizen.cell,
                    heading_deg=citizen.heading_deg,
                    route=route,
                    speed_mps=speed_mps,
                )
        bodies = {
            citizen.id: (citizen.body.hunger, citizen.body.thirst, citizen.body.energy, citizen.body.health)
            for citizen in core.living()
        }
        animal_poses = {
            animal.id: _pose(animal)
            for animal in (core.state.animals[animal_id] for animal_id in sorted(core.state.animals))
            if (animal.alive or animal.id in poses)  # one that died this tick may have moved first
            and (animal.position, animal.heading_deg, animal.activity) != poses.get(animal.id)
        }
        core.emit("tick_summary", TickSummary(moved=moved, bodies=bodies, animals=animal_poses))

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.step()

    def _body(self, citizen: Citizen) -> list[Crossing]:
        core = self.core
        activity = actions.body_activity(citizen.action)
        hot = core.world.biome(citizen.cell) in HOT_BIOMES
        change = update_body(citizen.body, citizen.traits, activity, hot)
        for crossing in change.crossings:
            core.emit(
                "need_changed",
                NeedChanged(need=crossing.need, level=crossing.words, value=crossing.value, worse=crossing.worse),
                actor=citizen,
                visibility="private",
            )
        if change.died is not None:
            died = core.emit("died", Died(cause=change.died), actor=citizen)
            actions.end_for_death(core, citizen, died)
            citizen.in_view, citizen.animals_in_view, citizen.threats = set(), set(), set()
            return []
        if change.collapsed:
            actions.collapse(core, citizen)
        return [crossing for crossing in change.crossings if crossing.worse]

    def _visibility(self, living: list[Citizen]) -> dict[str, set[str]]:
        """Who each living citizen can see (living people only), by id."""
        if not living:
            return {}
        positions = np.array([citizen.position for citizen in living])
        cosines = np.clip(positions @ positions.T, -1.0, 1.0)
        distances = np.arccos(cosines) * self.core.world.radius_m
        ranges = np.array([self.core.sight_range(citizen) for citizen in living])
        within = distances <= ranges[:, None]
        np.fill_diagonal(within, False)
        ids = [citizen.id for citizen in living]
        return {ids[row]: {ids[column] for column in np.flatnonzero(within[row])} for row in range(len(living))}

    def _visit(self, citizen: Citizen) -> None:
        for place_id in sorted(self.core.world.places):
            place = self.core.world.places[place_id]
            if self.core.distance_m(citizen.position, place.centre) <= place.radius_m:
                self.core.learn_place(citizen, place_id, "visited")


def _pose(animal: Animal) -> AnimalPose:
    return AnimalPose(
        position=animal.position,
        height_m=animal.height_m,
        cell=animal.cell,
        heading_deg=animal.heading_deg,
        activity=animal.activity,
    )


def _groups(sightings: list[tuple[Animal, float]]) -> dict[str, tuple[Animal, float, int]]:
    """Living animal groups in view: the nearest member, its distance, and how many members are seen."""
    groups: dict[str, tuple[Animal, float, int]] = {}
    for animal, distance in sightings:
        if not animal.alive:
            continue
        found = groups.get(animal.group)
        groups[animal.group] = (animal, distance, 1) if found is None else (found[0], found[1], found[2] + 1)
    return groups
