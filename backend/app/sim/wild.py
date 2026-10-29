"""Living off the wild (03-actions-perception): `hunt(animal)`, `attack(target)`, `fish()`, `make_fire()`,
`feed_fire()`. Outcomes depend on skill, tool (a spear), strength and company; hunting and fighting can hurt you.

```
 hunt / attack an animal: stalk it (creeping, unnoticed by its group) ─▶ close enough? ─▶ strike
     hunt: chance by skill × spear × strength × helpers ─▶ meat and hide, or it gets away (and may turn on you)
     attack: a blow that wounds it; a predator that survives is driven off (and may bite back)
 attack a person within reach: a blow that hurts them
 fish: 30 minutes at a river, lake or shallow sea shore ─▶ a few fish from the water's stock (or none)
 make_fire (skill "fire", wood): light a hearth within reach or a campfire where you stand
 feed_fire (wood): more fuel for a lit fire within reach; wood carried first, then wood on the ground beside it
```
"""

import math

from app.observability.events import ItemLocation, ResourceChanged
from app.sim import animals, fire
from app.sim.acting import begin, capital, settled
from app.sim.clock import SECONDS_PER_TICK
from app.sim.core import REACH_M, WALK_AHEAD_TICKS, SimCore, Stride
from app.sim.ecology import schedule_regrowth
from app.sim.fauna import SPECIES
from app.sim.items import ITEMS, RESOURCE_INDEX, amount_words
from app.sim.locomotion import gait_mps
from app.sim.perception import match_animal, match_person, person_label
from app.sim.state import ActionState, Animal, Citizen, Fire
from app.sim.vec import Vec3, bearing_deg, normalize
from app.world_api.models import Attack, Hunt

HUNT_MINUTES = 60  # stalking gives up after this long ("You lose the trail.")
HUNT_STRIKE_M = 15.0  # close enough to rush it or throw a spear
ATTACK_STRIKE_M = 3.0
STALK_PACE_M = gait_mps("stalk") * SECONDS_PER_TICK  # metres a minute, creeping (bodies.yaml)
UNSKILLED = 0.4  # without the hunting skill
SPEAR = 1.4
HELPER_BONUS = 0.25  # per other hunter after the same group close by (at most two count)
HELPER_M = 30.0
CHANCE_RANGE = (0.05, 0.9)
BLOW = (10.0, 25.0)  # an attack's injury, × strength (× spear)
FIGHT_BACK = 0.5  # chance an attacked predator bites back
FISH_MINUTES = 30
FISH_CHANCE = 0.35  # by hand
FISH_CATCH = (1, 3)
WOODPILE_M = 5.0  # wood on the ground this close to a fire is its woodpile
MAKE_FIRE_MINUTES = 10
FEED_FIRE_MINUTES = 2
FISHING_WATERS = frozenset({"shallow_ocean", "lake"})


# --- hunting and fighting ---


def start_hunt(core: SimCore, citizen: Citizen, action: Hunt) -> int:
    animal = match_animal(core, citizen, action.animal)
    if animal is None:
        return settled(core, citizen, "hunt", "failed", f"You don't see any {action.animal} around here.")
    species = SPECIES[animal.kind]
    if species.swims and animal.kind != "duck":
        return settled(core, citizen, "hunt", "failed", "You can't hunt in the water; try fishing.")
    hunt = begin(core, citizen, "hunt", species.one, {"animal": animal.kind})
    hunt.target_id, hunt.until_tick = animal.id, core.state.tick + HUNT_MINUTES
    return hunt.number


def start_attack(core: SimCore, citizen: Citizen, action: Attack) -> int:
    person = match_person(core, citizen, action.target)
    if person is not None:
        label = person_label(citizen, person)
        if core.distance_m(citizen.position, person.position) > REACH_M:
            return settled(core, citizen, "attack", "failed", f"{capital(label)} is too far away to strike.")
        attack = begin(core, citizen, "attack", label, {"target": "person"})
        attack.target_id, attack.until_tick = person.id, core.state.tick + 1
        return attack.number
    animal = match_animal(core, citizen, action.target)
    if animal is None:
        return settled(core, citizen, "attack", "failed", "You don't see anyone or anything like that.")
    if SPECIES[animal.kind].swims and animal.kind != "duck":
        return settled(core, citizen, "attack", "failed", "You can't reach it in the water.")
    attack = begin(core, citizen, "attack", SPECIES[animal.kind].one, {"target": "animal"})
    attack.target_id, attack.until_tick = animal.id, core.state.tick + HUNT_MINUTES
    return attack.number


def advance_stalk(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    """One minute of a hunt or an attack: creep closer, strike once close enough."""
    if action.kind == "attack" and action.args.get("target") == "person":
        _strike_person(core, citizen, action)
        return
    animal = core.state.animals.get(action.target_id or "")
    name = action.label
    if animal is None or not animal.alive:
        core.end_action(citizen, "interrupted", f"You stop {_verb(action)}: {name} is gone.")
        return
    distance = core.distance_m(citizen.position, animal.position)
    if distance > core.sight_range(citizen):
        core.end_action(citizen, "interrupted", f"You stop {_verb(action)}: you lose sight of {name}.")
        return
    strike_m = HUNT_STRIKE_M if action.kind == "hunt" else ATTACK_STRIKE_M
    if distance > strike_m:
        if action.until_tick is not None and core.state.tick >= action.until_tick:
            core.end_action(citizen, "failed", f"You lose the trail of {name}.")
            return
        pace = STALK_PACE_M * citizen.traits.speed
        step = min(pace, distance - strike_m * 0.8)
        target = _towards(citizen.position, animal.position, step / distance)
        if not _walkable(core, citizen, target):
            core.end_action(citizen, "failed", f"You can't get any closer to {name}.")
            return
        core.strides[citizen.id] = _stalk_stride(core, citizen, action, (target, step), animal.position, strike_m)
        core.place_at(citizen, target)
        if core.distance_m(citizen.position, animal.position) > strike_m:
            return
    if action.kind == "hunt":
        _strike_hunt(core, citizen, animal)
    else:
        _strike_animal(core, citizen, animal)


def _stalk_stride(
    core: SimCore, citizen: Citizen, action: ActionState, step: tuple[Vec3, float], quarry: Vec3, strike_m: float
) -> Stride:
    """This minute's creep (`step`: where to and how many metres, straight at the stalking pace) and, while still
    out of reach, the next WALK_AHEAD_TICKS minutes of it towards where the animal is now."""
    pace = STALK_PACE_M * citizen.traits.speed / SECONDS_PER_TICK  # metres a game second
    target, metres = step
    reached = metres / pace  # a full creep takes the whole minute
    walked = ((citizen.position, 0.0), (target, reached))
    gap = core.distance_m(target, quarry)
    left = min(WALK_AHEAD_TICKS * STALK_PACE_M * citizen.traits.speed, gap - strike_m * 0.8)
    if left <= 0:
        return Stride(action.number, walked, gait="stalk")
    onward = _towards(target, quarry, left / gap)
    if not _walkable(core, citizen, onward):
        return Stride(action.number, walked, gait="stalk")
    return Stride(action.number, walked, ((onward, reached + left / pace),), gait="stalk")


def hunt_chance(core: SimCore, citizen: Citizen, animal: Animal) -> float:
    """03: outcome by skill, tool, strength and group."""
    chance = SPECIES[animal.kind].catch
    chance *= 1.0 if "hunting" in citizen.skills else UNSKILLED
    chance *= SPEAR if citizen.inventory.get("spear", 0) else 1.0
    chance *= math.sqrt(citizen.traits.strength)
    helpers = [
        other
        for other in core.living()
        if other.id != citizen.id
        and other.action is not None
        and other.action.kind == "hunt"
        and other.action.target_id in core.state.groups[animal.group].members
        and core.distance_m(other.position, citizen.position) <= HELPER_M
    ]
    chance *= 1.0 + HELPER_BONUS * min(2, len(helpers))
    return min(CHANCE_RANGE[1], max(CHANCE_RANGE[0], chance))


def _strike_hunt(core: SimCore, citizen: Citizen, animal: Animal) -> None:
    species = SPECIES[animal.kind]
    rng = core.state.rng("wild.hunt")
    if rng.random() < hunt_chance(core, citizen, animal):
        died = animals.kill(core, animal, "hunted")
        taken = [
            _take_from(core, citizen, animal, item, count, died)
            for item, count in (("meat", species.meat), ("hide", species.hide))
            if count
        ]
        got = " and ".join(words for words in taken if words)
        tail = f" You take {got}." if got else " You can't carry any of it."
        core.end_action(citizen, "done", f"You bring down {species.one}.{tail}")
        return
    _scatter(core, animal, citizen.position)
    text = f"{capital(species.one)} gets away."
    if species.fights_back and rng.random() < species.fights_back:
        low, high = species.hurts
        text = f"{capital(species.one)} turns on you and gets away."
        core.end_action(citizen, "failed", text)
        core.injure(
            citizen,
            low + (high - low) * rng.random(),
            "animal attack",
            f"{species.one} turns on you",
            attacker=animal.id,
        )
        return
    core.end_action(citizen, "failed", text)


def _strike_animal(core: SimCore, citizen: Citizen, animal: Animal) -> None:
    species = SPECIES[animal.kind]
    rng = core.state.rng("wild.attack")
    blow = (BLOW[0] + (BLOW[1] - BLOW[0]) * rng.random()) * citizen.traits.strength
    blow *= SPEAR if citizen.inventory.get("spear", 0) else 1.0
    if animals.wound(core, animal, blow, f"attacked by {citizen.name}"):
        core.end_action(citizen, "done", f"You kill {species.one}.")
        return
    _scatter(core, animal, citizen.position)
    if species.bite[1] > 0 and rng.random() < FIGHT_BACK:
        core.end_action(citizen, "done", f"You strike {species.one}; it bites back and runs off.")
        low, high = species.bite
        core.injure(
            citizen, low + (high - low) * rng.random(), "animal attack", f"{species.one} bites you", attacker=animal.id
        )
        return
    core.end_action(citizen, "done", f"You strike {species.one} and it runs off.")


def _strike_person(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    victim = core.state.citizens.get(action.target_id or "")
    if victim is None or not victim.body.alive:
        core.end_action(citizen, "interrupted", f"You stop fighting: {action.label} is gone.")
        return
    if core.distance_m(citizen.position, victim.position) > REACH_M:
        core.end_action(citizen, "failed", f"{capital(action.label)} is out of reach.")
        return
    rng = core.state.rng("wild.strike")
    blow = (BLOW[0] + (BLOW[1] - BLOW[0]) * rng.random()) * citizen.traits.strength * 0.5
    blow *= SPEAR if citizen.inventory.get("spear", 0) else 1.0
    core.end_action(citizen, "done", f"You strike {action.label}.")
    core.injure(victim, blow, "violence", f"{person_label(victim, citizen)} strikes you", attacker=citizen.id)


def _scatter(core: SimCore, animal: Animal, threat: Vec3) -> None:
    """A missed animal's group bolts away from the hunter."""
    for member_id in core.state.groups[animal.group].members:
        member = core.state.animals[member_id]
        if member.alive and not SPECIES[member.kind].predator:
            away = bearing_deg(threat, member.position)
            animals.run_from(core, member, away)
    if SPECIES[animal.kind].predator:
        animals.drive_off(core, animal, threat)


def _take_from(core: SimCore, citizen: Citizen, animal: Animal, item: str, count: int, cause_seq: int) -> str:
    count = min(count, core.room_for(citizen, item))
    if count <= 0:
        return ""
    citizen.inventory[item] = citizen.inventory.get(item, 0) + count
    core.item_moved(
        citizen,
        item,
        count,
        ItemLocation(kind="animal", id=animal.id, cell=animal.cell),
        ItemLocation(kind="inventory", id=citizen.id),
        cause_seq=cause_seq,
    )
    return amount_words(count, ITEMS[item])


def _verb(action: ActionState) -> str:
    return "hunting" if action.kind == "hunt" else "fighting"


def _towards(origin: Vec3, goal: Vec3, share: float) -> Vec3:
    return normalize(tuple(o + (g - o) * share for o, g in zip(origin, goal, strict=True)))  # type: ignore[arg-type]


def _walkable(core: SimCore, citizen: Citizen, position: Vec3) -> bool:
    """Stalking goes straight across open ground: never within the town's walls (animals are never there)."""
    if core.world.town_point(position) is not None or core.world.town_point(citizen.position) is not None:
        return False
    return core.planner.outer.allowed[core.world.nearest_cell(position, citizen.cell)]


# --- fishing ---


def fishing_cell(core: SimCore, citizen: Citizen) -> int | str:
    """The water cell to fish from (the one with the most fish within reach), or why there's none."""
    world = core.world
    if world.town_point(citizen.position) is not None:
        return "There's no water to fish in here."
    column = RESOURCE_INDEX["fish"]
    options = [citizen.cell] if world.river[citizen.cell] else []
    options += [cell for cell in world.neighbours[citizen.cell] if world.biome(cell) in FISHING_WATERS]
    if not options:
        deep = any(world.biome(cell) == "deep_ocean" for cell in world.neighbours[citizen.cell])
        return "The water here is too deep to fish without a boat." if deep else "There's no water to fish in here."
    return max(options, key=lambda cell: (int(core.state.resources[cell, column]), -cell))


def start_fish(core: SimCore, citizen: Citizen) -> int:
    cell = fishing_cell(core, citizen)
    if isinstance(cell, str):
        return settled(core, citizen, "fish", "failed", cell)
    if core.room_for(citizen, "fish") == 0:
        return settled(core, citizen, "fish", "failed", "You can't carry any more.")
    fish = begin(core, citizen, "fish", "fish", {})
    fish.amount, fish.until_tick = cell, core.state.tick + FISH_MINUTES
    return fish.number


def _finish_fish(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    cell, column = action.amount, RESOURCE_INDEX["fish"]
    stock = int(core.state.resources[cell, column])
    if stock == 0:
        core.end_action(citizen, "failed", "You catch nothing; the water seems empty of fish.")
        return
    rng = core.state.rng("wild.fish")
    chance = FISH_CHANCE * (SPEAR if citizen.inventory.get("spear", 0) else 1.0)
    chance *= (1.3 if "hunting" in citizen.skills else 1.0) * math.sqrt(citizen.traits.strength)
    if rng.random() >= min(CHANCE_RANGE[1], chance):
        core.end_action(citizen, "failed", "The fish slip away from you.")
        return
    count = min(rng.randint(*FISH_CATCH), stock, core.room_for(citizen, "fish"))
    core.state.resources[cell, column] = stock - count
    schedule_regrowth(core, cell, "fish")
    seq = core.emit(
        "resource_changed",
        ResourceChanged(cell=cell, resource="fish", before=stock, after=stock - count),
        actor=citizen,
    )
    citizen.inventory["fish"] = citizen.inventory.get("fish", 0) + count
    core.item_moved(
        citizen,
        "fish",
        count,
        ItemLocation(kind="resource", cell=cell),
        ItemLocation(kind="inventory", id=citizen.id),
        cause_seq=seq,
    )
    core.end_action(citizen, "done", f"You catch {amount_words(count, ITEMS['fish'])}.")


# --- fire ---


def _woodpiles(core: SimCore, citizen: Citizen, hearth: Fire | None) -> list[str]:
    """Wood on the ground to burn: stacks beside the fire (its woodpile), or within the citizen's reach."""
    return sorted(
        stack.id
        for stack in core.state.ground.values()
        if stack.item == "wood"
        and stack.count > 0
        and (
            core.distance_m(stack.position, hearth.position) <= WOODPILE_M
            if hearth is not None
            else core.distance_m(stack.position, citizen.position) <= REACH_M
        )
    )


def _wood_at_hand(core: SimCore, citizen: Citizen, hearth: Fire | None) -> int:
    piles = sum(core.state.ground[stack_id].count for stack_id in _woodpiles(core, citizen, hearth))
    return citizen.inventory.get("wood", 0) + piles


def _hearth_in_reach(core: SimCore, citizen: Citizen) -> Fire | None:
    return fire.nearest_fire(core, citizen.position, fire.REACH_M)


def start_make_fire(core: SimCore, citizen: Citizen) -> int:
    if "fire" not in citizen.skills:
        return settled(core, citizen, "make_fire", "failed", "You don't know how to make fire.")
    hearth = _hearth_in_reach(core, citizen)
    if hearth is not None and hearth.lit:
        return settled(core, citizen, "make_fire", "done", "The fire is already burning.")
    if hearth is None and core.world.town_point(citizen.position) is not None:
        return settled(core, citizen, "make_fire", "failed", "You can't light a fire here.")
    if _wood_at_hand(core, citizen, hearth) == 0:
        return settled(core, citizen, "make_fire", "failed", "You have no wood to burn.")
    where = "a fire" if hearth is None else _hearth_words(hearth)
    make = begin(core, citizen, "make_fire", where, {})
    make.target_id, make.until_tick = hearth.id if hearth else None, core.state.tick + MAKE_FIRE_MINUTES
    return make.number


def start_feed_fire(core: SimCore, citizen: Citizen) -> int:
    hearth = _hearth_in_reach(core, citizen)
    if hearth is None:
        return settled(core, citizen, "feed_fire", "failed", "There's no fire within reach.")
    if not hearth.lit:
        return settled(core, citizen, "feed_fire", "failed", "The fire is out; it has to be made again.")
    if hearth.fuel > fire.MAX_FUEL - fire.WOOD_MINUTES:
        return settled(core, citizen, "feed_fire", "done", "The fire is burning well; it needs no more wood.")
    if _wood_at_hand(core, citizen, hearth) == 0:
        return settled(core, citizen, "feed_fire", "failed", "You have no wood to burn.")
    feed = begin(core, citizen, "feed_fire", _hearth_words(hearth), {})
    feed.target_id, feed.until_tick = hearth.id, core.state.tick + FEED_FIRE_MINUTES
    return feed.number


def _hearth_words(hearth: Fire) -> str:
    return {"pit": "the fire pit", "basket": "the fire basket", "campfire": "the campfire"}[hearth.kind]


def _finish_make_fire(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    hearth = core.state.fires.get(action.target_id) if action.target_id is not None else None
    if hearth is not None and hearth.lit:
        core.end_action(citizen, "done", "The fire is already burning.")
        return
    if hearth is None:
        fire_id = f"fire:{core.state.next_fire}"
        core.state.next_fire += 1
        hearth = Fire(
            id=fire_id,
            kind="campfire",
            position=citizen.position,
            cell=citizen.cell,
            height_m=citizen.height_m,
        )
        core.state.fires[fire_id] = hearth
    burned, seq = _burn_wood(core, citizen, hearth, fire.KINDLING_WOOD)
    if burned == 0:
        core.end_action(citizen, "failed", "You have no wood left to burn.")
        if hearth.kind == "campfire" and hearth.fuel == 0 and not hearth.lit:
            del core.state.fires[hearth.id]  # nothing was ever lit there
        return
    fire.add_fuel(hearth, burned * fire.WOOD_MINUTES)
    fire.changed(core, hearth, seq)
    core.end_action(citizen, "done", _LIT[hearth.kind])


_LIT = {
    "pit": "You get a fire going in the fire pit.",
    "basket": "You get a fire going in the fire basket.",
    "campfire": "You get a fire going.",
}


def _finish_feed_fire(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    hearth = core.state.fires.get(action.target_id or "")
    if hearth is None or not hearth.lit:
        core.end_action(citizen, "failed", "The fire has gone out.")
        return
    room = (fire.MAX_FUEL - hearth.fuel) // fire.WOOD_MINUTES
    if room == 0:
        core.end_action(citizen, "done", "The fire is burning well; it needs no more wood.")
        return
    burned, seq = _burn_wood(core, citizen, hearth, room)
    if burned == 0:
        core.end_action(citizen, "failed", "You have no wood left to burn.")
        return
    fire.add_fuel(hearth, burned * fire.WOOD_MINUTES)
    fire.changed(core, hearth, seq)
    core.end_action(citizen, "done", "You feed the fire; it burns brightly.")


def _burn_wood(core: SimCore, citizen: Citizen, hearth: Fire, most: int) -> tuple[int, int | None]:
    """Put up to `most` pieces of wood on the fire, carried wood first; (pieces, last item_moved seq)."""
    burned, seq = 0, None
    destination = ItemLocation(kind="fire", id=hearth.id)
    carried = min(most, citizen.inventory.get("wood", 0))
    if carried:
        citizen.inventory["wood"] -= carried
        if citizen.inventory["wood"] == 0:
            del citizen.inventory["wood"]
        seq = core.item_moved(citizen, "wood", carried, ItemLocation(kind="inventory", id=citizen.id), destination)
        burned += carried
    for stack_id in _woodpiles(core, citizen, hearth):
        if burned >= most:
            break
        stack = core.state.ground[stack_id]
        count = min(most - burned, stack.count)
        stack.count -= count
        if stack.count == 0:
            del core.state.ground[stack_id]
        source = ItemLocation(kind="ground", id=stack.id, cell=stack.cell, position=stack.position)
        seq = core.item_moved(citizen, "wood", count, source, destination)
        burned += count
    return burned, seq


def complete(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    """A timed wild action ends (fish, make_fire, feed_fire)."""
    if action.kind == "fish":
        _finish_fish(core, citizen, action)
    elif action.kind == "make_fire":
        _finish_make_fire(core, citizen, action)
    elif action.kind == "feed_fire":
        _finish_feed_fire(core, citizen, action)
    else:
        raise ValueError(f"{action.kind} is not a timed wild action")
