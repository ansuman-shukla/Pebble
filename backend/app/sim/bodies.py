"""Citizen bodies: needs drift each tick, thresholds, collapse and death (02-simulation, "Citizen body")."""

from dataclasses import dataclass, field
from typing import Literal

from app.sim.state import AgeTraits, Body

Need = Literal["hunger", "thirst", "energy", "health"]
NEEDS: tuple[Need, ...] = ("hunger", "thirst", "energy", "health")

HUNGER_PER_HOUR = 4.0
THIRST_PER_HOUR = 6.0
ENERGY_AWAKE_PER_HOUR = -5.0
ENERGY_RESTING_PER_HOUR = 3.0
ENERGY_ASLEEP_PER_HOUR = 12.0
STARVING_DAMAGE_PER_HOUR = 2.0
PARCHED_DAMAGE_PER_HOUR = 6.0
HEAL_PER_HOUR = 1.0
ACTIVE_RATE = 1.25  # hunger and thirst while walking, gathering, fleeing or farming
ASLEEP_RATE = 0.75
HEAT_THIRST_RATE = 1.5  # savanna and volcanic ground
HOT_BIOMES = frozenset({"savanna", "volcanic"})
ACTIVE_ACTIONS = frozenset({"walk_to", "gather", "flee", "farm"})  # actions and work tasks (`body_activity`)
RESTING_ACTIONS = frozenset({"rest"})
COLLAPSE_WAKE_ENERGY = 30.0  # a collapsed citizen sleeps at least until this rested

# Rising needs cross upward thresholds, falling ones downward thresholds; the level counts thresholds crossed.
THRESHOLDS: dict[Need, tuple[float, ...]] = {
    "hunger": (60.0, 90.0),
    "thirst": (60.0, 90.0),
    "energy": (30.0, 10.0),
    "health": (50.0, 20.0),
}
LEVEL_WORDS: dict[Need, tuple[str, ...]] = {
    "hunger": ("fed", "hungry", "starving"),
    "thirst": ("quenched", "thirsty", "parched"),
    "energy": ("rested", "tired", "exhausted"),
    "health": ("well", "hurt", "near death"),
}
_RISING: frozenset[Need] = frozenset({"hunger", "thirst"})
_PER_TICK = 1 / 60


def need_value(body: Body, need: Need) -> float:
    value: float = getattr(body, need)
    return value


def need_level(need: Need, value: float) -> int:
    if need in _RISING:
        return sum(value >= threshold for threshold in THRESHOLDS[need])
    return sum(value <= threshold for threshold in THRESHOLDS[need])


@dataclass(frozen=True)
class Crossing:
    need: Need
    old_level: int
    new_level: int
    value: float

    @property
    def worse(self) -> bool:
        return self.new_level > self.old_level

    @property
    def words(self) -> str:
        return LEVEL_WORDS[self.need][self.new_level]


@dataclass
class BodyChange:
    crossings: list[Crossing] = field(default_factory=list)
    died: str | None = None
    collapsed: bool = False


def _clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


def update_body(body: Body, traits: AgeTraits, activity: str | None, hot: bool) -> BodyChange:
    """One tick of needs for a living body; returns threshold crossings since the last report (eating and drinking
    between ticks included), death and collapse."""
    if not body.alive:
        raise ValueError("dead bodies don't change")
    before = dict(zip(NEEDS, body.levels, strict=True))
    rate = traits.need_rate * (ASLEEP_RATE if body.asleep else ACTIVE_RATE if activity in ACTIVE_ACTIONS else 1.0)
    body.hunger = _clamp(body.hunger + HUNGER_PER_HOUR * rate * _PER_TICK)
    body.thirst = _clamp(body.thirst + THIRST_PER_HOUR * rate * (HEAT_THIRST_RATE if hot else 1.0) * _PER_TICK)
    if body.asleep:
        energy_rate = ENERGY_ASLEEP_PER_HOUR
    elif activity in RESTING_ACTIONS:
        energy_rate = ENERGY_RESTING_PER_HOUR
    else:
        energy_rate = ENERGY_AWAKE_PER_HOUR
    body.energy = _clamp(body.energy + energy_rate * _PER_TICK)

    damage = 0.0
    if body.hunger >= THRESHOLDS["hunger"][1]:
        damage += STARVING_DAMAGE_PER_HOUR
    if body.thirst >= THRESHOLDS["thirst"][1]:
        damage += PARCHED_DAMAGE_PER_HOUR
    if damage:
        body.health = _clamp(body.health - damage * _PER_TICK)
    elif body.hunger < THRESHOLDS["hunger"][0] and body.thirst < THRESHOLDS["thirst"][0]:
        body.health = _clamp(body.health + HEAL_PER_HOUR * (2 if body.asleep else 1) * _PER_TICK)

    change = BodyChange()
    levels = tuple(need_level(need, need_value(body, need)) for need in NEEDS)
    for need, level in zip(NEEDS, levels, strict=True):
        if level != before[need]:
            change.crossings.append(Crossing(need, before[need], level, need_value(body, need)))
    body.levels = (levels[0], levels[1], levels[2], levels[3])
    if body.health <= 0:
        body.alive = False
        body.asleep = False
        body.cause_of_death = "dehydration" if body.thirst >= THRESHOLDS["thirst"][1] else "starvation"
        change.died = body.cause_of_death
    elif body.energy <= 0 and not body.asleep:
        change.collapsed = True
    return change


def body_words(body: Body) -> list[str]:
    """The body in the coarse words a person would use about themselves."""
    words: list[str] = []
    if body.hunger >= 90:
        words.append("starving")
    elif body.hunger >= 60:
        words.append("hungry")
    elif body.hunger >= 30:
        words.append("a little hungry")
    if body.thirst >= 90:
        words.append("terribly thirsty")
    elif body.thirst >= 60:
        words.append("thirsty")
    elif body.thirst >= 30:
        words.append("a little thirsty")
    if body.energy <= 10:
        words.append("exhausted")
    elif body.energy <= 30:
        words.append("tired")
    elif body.energy <= 60:
        words.append("a little tired")
    if body.health <= 20:
        words.append("close to death")
    elif body.health <= 50:
        words.append("weak and aching")
    elif body.health < 90:
        words.append("a little weak")
    return words
