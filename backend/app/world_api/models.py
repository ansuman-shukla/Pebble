"""THE world contract (03-actions-perception): every action a mind can take, its result, and what it perceives.

One source for the Python facade used by scripted brains, the MCP tool schemas of agent minds (phase B) and the
OpenAPI types of the spectator UI. Everything a mind reads is in-world words: no numbers it wouldn't know, no ids.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.world_api.phrases import join, phrases

Volume = Literal["whisper", "normal", "shout"]
Compass = Literal["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
RoughDistance = Literal["a few steps", "a short walk", "a long walk", "very far"]
# how far off something seen is, in the words `Seen.where` starts with
Nearness = Literal["right beside you", "a few paces", "close by", "some way off", "in the distance", "far away"]
# what a thing in view is (fresh water, the sea, food, your home, a shelter, a fire pit, wood or reeds, an item on the
# ground, any other building)
ThingKind = Literal["water", "sea", "food", "home", "shelter", "fire", "material", "item", "building"]
ResourceName = Literal["berries", "roots", "nuts", "reeds", "wood"]  # wild plants, as `gather` names them
# the local sun, coarsely; `Perception.time` says the same in a sentence
TimeOfDay = Literal[
    "pre-dawn",
    "dawn",
    "early morning",
    "mid-morning",
    "midday",
    "early afternoon",
    "late afternoon",
    "sunset",
    "dusk",
    "night",
]
ActionName = Literal[
    "look_around",
    "check_self",
    "say",
    "walk_to",
    "follow",
    "gather",
    "fish",
    "hunt",
    "eat",
    "drink",
    "pick_up",
    "drop",
    "give",
    "make_fire",
    "feed_fire",
    "rest",
    "sleep",
    "work",
    "attack",
    "flee",
    "wait",
    "recall",
]
Outcome = Literal["done", "interrupted", "failed"]

INSTANT_ACTIONS: frozenset[ActionName] = frozenset({"look_around", "check_self", "say", "pick_up", "drop", "give"})
NOT_YET_ACTIONS: frozenset[ActionName] = frozenset({"recall"})  # typed now, answered in phase B (05-memory)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- targets of walk_to ---


class PlaceTarget(_Model):
    """A place the citizen knows, by the name they know it by ("the well", "home")."""

    kind: Literal["place"] = "place"
    name: str = Field(min_length=1, max_length=120)


class PersonTarget(_Model):
    """A person in view: by name if known, else as they look ("a man in a fur cloak")."""

    kind: Literal["person"] = "person"
    who: str = Field(min_length=1, max_length=120)


class ThingTarget(_Model):
    """A thing in view: food, water, an item or a structure ("berries", "the river", "the well")."""

    kind: Literal["thing"] = "thing"
    what: str = Field(min_length=1, max_length=120)


class DirectionTarget(_Model):
    kind: Literal["direction"] = "direction"
    direction: Compass
    distance: RoughDistance


Target = Annotated[PlaceTarget | PersonTarget | ThingTarget | DirectionTarget, Field(discriminator="kind")]


# --- actions ---


class LookAround(_Model):
    action: Literal["look_around"] = "look_around"


class CheckSelf(_Model):
    action: Literal["check_self"] = "check_self"


class Say(_Model):
    action: Literal["say"] = "say"
    words: str = Field(min_length=1, max_length=600)
    volume: Volume = "normal"


class WalkTo(_Model):
    action: Literal["walk_to"] = "walk_to"
    target: Target


class Follow(_Model):
    action: Literal["follow"] = "follow"
    person: str = Field(min_length=1, max_length=120)


class Gather(_Model):
    action: Literal["gather"] = "gather"
    resource: str = Field(min_length=1, max_length=60)


class Fish(_Model):
    action: Literal["fish"] = "fish"


class Hunt(_Model):
    action: Literal["hunt"] = "hunt"
    animal: str = Field(min_length=1, max_length=120)


class Eat(_Model):
    action: Literal["eat"] = "eat"
    item: str = Field(min_length=1, max_length=60)


class Drink(_Model):
    action: Literal["drink"] = "drink"


class PickUp(_Model):
    action: Literal["pick_up"] = "pick_up"
    item: str = Field(min_length=1, max_length=60)


class Drop(_Model):
    action: Literal["drop"] = "drop"
    item: str = Field(min_length=1, max_length=60)


class Give(_Model):
    action: Literal["give"] = "give"
    item: str = Field(min_length=1, max_length=60)
    person: str = Field(min_length=1, max_length=120)


class MakeFire(_Model):
    action: Literal["make_fire"] = "make_fire"


class FeedFire(_Model):
    action: Literal["feed_fire"] = "feed_fire"


class Rest(_Model):
    action: Literal["rest"] = "rest"
    minutes: int = Field(ge=1, le=720)


class Sleep(_Model):
    action: Literal["sleep"] = "sleep"


class Work(_Model):
    action: Literal["work"] = "work"
    task: str = Field(min_length=1, max_length=60)


class Attack(_Model):
    action: Literal["attack"] = "attack"
    target: str = Field(min_length=1, max_length=120)


class Flee(_Model):
    action: Literal["flee"] = "flee"


class Wait(_Model):
    action: Literal["wait"] = "wait"
    minutes: int = Field(ge=1, le=720)


class Recall(_Model):
    action: Literal["recall"] = "recall"
    about: str = Field(min_length=1, max_length=200)


Action = Annotated[
    LookAround
    | CheckSelf
    | Say
    | WalkTo
    | Follow
    | Gather
    | Fish
    | Hunt
    | Eat
    | Drink
    | PickUp
    | Drop
    | Give
    | MakeFire
    | FeedFire
    | Rest
    | Sleep
    | Work
    | Attack
    | Flee
    | Wait
    | Recall,
    Field(discriminator="action"),
]


class ActionResult(_Model):
    action: ActionName
    outcome: Outcome
    text: str  # what happened, in-world ("You arrive at the well.")


# --- perception ---


class SelfView(_Model):
    feeling: list[str]  # coarse body words; empty = "you feel fine"
    carrying: list[str]
    doing: str

    def text(self) -> str:
        feeling = "You feel " + join(self.feeling) + "." if self.feeling else "You feel fine."
        carrying = "You carry " + join(self.carrying) + "." if self.carrying else "You carry nothing."
        return f"{feeling} {carrying} {self.doing}"


class Seen(_Model):
    """One person, animal or (group of) thing(s) in view. A group's `where` is its nearest member's, said as "the
    nearest …" when the others are elsewhere."""

    label: str  # a name, an appearance or a thing ("Aiko", "a man in a fur cloak", "three lean-tos")
    where: str  # rough distance and direction ("a few paces to the north")
    nearness: Nearness  # how far, as `where` says it
    doing: str | None = None
    kind: ThingKind | None = None  # things only
    resource: ResourceName | None = None  # a wild plant you could gather


class HeardWords(_Model):
    who: str  # name, appearance, or "someone" when the speaker isn't in view
    words: str
    volume: Volume


class Perception(_Model):
    """What a look around tells. People and animals are always all there; things are grouped and chosen by importance
    (water, food, shelter, fire, then the rest, nearest first) so everything seen fits a short paragraph."""

    you: SelfView
    place: str
    time: str  # a sentence from the sun ("It is late afternoon.", "The sun is about to set.")
    time_of_day: TimeOfDay
    people: list[Seen]
    animals: list[Seen]
    things: list[Seen]
    heard: list[HeardWords]

    def text(self) -> str:
        lines = [f"You are {self.place}. {self.time}", self.you.text()]
        if self.people:
            lines.append("You see " + "; ".join(_said(self.people)) + ".")
        if self.animals:
            lines.append("Animals: " + "; ".join(_said(self.animals)) + ".")
        if self.things:
            lines.append("Around you: " + "; ".join(_said(self.things)) + ".")
        verbs = {"whisper": "whispers", "normal": "says", "shout": "shouts"}
        lines += [f'{heard.who} {verbs[heard.volume]}: "{heard.words}"' for heard in self.heard]
        return "\n".join(lines)


def _said(seen: list[Seen]) -> list[str]:
    return phrases((entry.label, entry.where, entry.doing) for entry in seen)
