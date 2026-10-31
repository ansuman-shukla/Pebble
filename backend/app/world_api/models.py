"""THE world contract (03-actions-perception): every action a mind can take, its result, and what it perceives.

One source for the Python facade used by scripted brains, the MCP tool schemas of agent minds (phase B) and the
OpenAPI types of the spectator UI. Everything a mind reads is in-world words: no numbers it wouldn't know, no ids.
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from app.world_api.phrases import join, phrases

Volume = Literal["whisper", "normal", "shout"]
Compass = Literal["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
RoughDistance = Literal["a few steps", "a short walk", "a long walk", "very far"]
# how far off something seen is, in the words `Seen.where` starts with
Nearness = Literal["right beside you", "a few paces", "close by", "some way off", "in the distance", "far away"]
# what a thing in view is (fresh water, the sea, food, your home, a shelter, a fire pit, wood or reeds, an item on the
# ground, any other building; contract v1: a gatherable node such as a bush, a tree or a seam, a store such as a
# chest or the racks, the market stall, an animal's remains)
ThingKind = Literal[
    "water",
    "sea",
    "food",
    "home",
    "shelter",
    "fire",
    "material",
    "item",
    "building",
    "node",
    "store",
    "market",
    "remains",
]
# how safe where you stand is: inside the town, close to a lit fire, with others close by, on your own group's
# ground, or none of these
Safety = Literal["inside the walls", "by the fire", "in company", "on home ground", "exposed"]
# what `gather` takes from the wild: plants, the paddies' rice and the minerals of seams, fields, bars and pools
ResourceName = Literal["berries", "roots", "nuts", "reeds", "wood", "rice", "flint", "obsidian", "iron sand", "gold"]
# the tasks `work` does, as it names them
WorkTask = Literal["farm", "store food", "guard", "trade", "weave", "govern", "ring bell", "pray"]
# what `craft` makes, each at its station: spears and the stone axe at a fire pit, iron at the forge, cloth and packs
# at a loom, dried meat at a drying rack
RecipeName = Literal[
    "flint spear",
    "obsidian spear",
    "iron spear",
    "stone axe",
    "iron axe",
    "sickle",
    "cloth",
    "pack",
    "dried meat",
]
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
    # contract v1 (draft)
    "buy",
    "sell",
    "stash",
    "craft",
    "accuse",
    "seize",
    "judge",
    "tend",
    "gesture",
    "set_goal",
]
Outcome = Literal["done", "interrupted", "failed"]
Pace = Literal["walk", "run"]  # how walk_to and follow go; running tires you and turns to a jog when you are spent
GestureKind = Literal["wave", "bow", "nod", "shake_head", "point", "laugh", "jump"]  # seen, never heard
Driver = Literal["hunger", "thirst", "rest", "danger", "duty", "ambition", "social", "night"]  # why a goal is set
PriceWord = Literal["dear", "fair", "cheap"]  # a stall's price for a good against what the good is worth
Sentence = Literal["fine", "confine"]  # what a judge hands down

# the one place the contract's version is set (test_contract writes it into the draft file); D96: C1 owns the draft
# through wave 3, Q1 freezes it as contract_v1.json
CONTRACT_VERSION = "v1-draft"
INSTANT_ACTIONS: frozenset[ActionName] = frozenset(
    ("look_around", "check_self", "say", "pick_up", "drop", "give", "recall")
    + ("buy", "sell", "stash", "accuse", "gesture", "set_goal")
)
FREE_ACTIONS: frozenset[ActionName] = frozenset({"set_goal"})  # take no time and leave the body be: sleepers sleep on


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
    pace: Pace = "walk"


class Follow(_Model):
    action: Literal["follow"] = "follow"
    person: str = Field(min_length=1, max_length=120)
    pace: Pace = "walk"


class Gather(_Model):
    action: Literal["gather"] = "gather"
    resource: str = Field(min_length=1, max_length=60, examples=list(get_args(ResourceName)))


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
    task: str = Field(min_length=1, max_length=60, examples=list(get_args(WorkTask)))


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


# --- contract v1 (draft): until its stream lands, an action answers "You can't do that yet." ---


class Buy(_Model):  # the market stall (E2)
    """Buy a good at an open market stall, paying in coins; goods are sold in lots. The amount counts units as you
    count them (measures of rice, strips of dried meat, pieces of wood), as your goods and the prices are said."""

    action: Literal["buy"] = "buy"
    item: str = Field(min_length=1, max_length=60)
    amount: int = Field(ge=1, le=999)


class Sell(_Model):  # the market stall (E2)
    """Sell a good you carry to an open market stall, which buys only what it sells and only with coins it holds. The
    amount counts units as you count them (measures, strips, pieces), as your goods and the prices are said."""

    action: Literal["sell"] = "sell"
    item: str = Field(min_length=1, max_length=60)
    amount: int = Field(ge=1, le=999)


class Stash(_Model):  # ownership (E3)
    """Put things you carry into your own chest within reach (the merchant: into the stall). The amount counts units
    as you count them (measures, strips, pieces), as your carried goods are said."""

    action: Literal["stash"] = "stash"
    item: str = Field(min_length=1, max_length=60)
    amount: int = Field(ge=1, le=999)


class Craft(_Model):  # crafting (E2)
    """Make a tool or good from what you carry, at its station within reach, if you have the skill."""

    action: Literal["craft"] = "craft"
    recipe: str = Field(min_length=1, max_length=60, examples=list(get_args(RecipeName)))


class Accuse(_Model):  # justice (J1)
    """Tell someone awake within speaking range every deed you know of a person."""

    action: Literal["accuse"] = "accuse"
    person: str = Field(min_length=1, max_length=120)
    to: str = Field(min_length=1, max_length=120)


class Seize(_Model):  # justice (J1)
    """Try to take hold of a person within reach; held, they can only look, speak and wait, and go where you lead."""

    action: Literal["seize"] = "seize"
    person: str = Field(min_length=1, max_length=120)


class Fine(_Model):
    """A fine in coins: from the purse, then the household's chest, then goods; the victim is paid first."""

    kind: Literal["fine"] = "fine"
    mon: int = Field(ge=1, le=200)


class Confinement(_Model):
    """Hours confined: in the gaol in town, tied at the fire in a band."""

    kind: Literal["confine"] = "confine"
    hours: int = Field(ge=1, le=12)


Verdict = Annotated[Fine | Confinement, Field(discriminator="kind")]


class Judge(_Model):  # justice (J1)
    """Sentence a held or confined person within reach for a deed of theirs you know of (or their arrears)."""

    action: Literal["judge"] = "judge"
    person: str = Field(min_length=1, max_length=120)
    sentence: Verdict


class Tend(_Model):  # justice and tending (J2)
    """Tend a hurt person within reach for half an hour; it takes the healing skill."""

    action: Literal["tend"] = "tend"
    person: str = Field(min_length=1, max_length=120)


class Gesture(_Model):
    """A gesture everyone who can see you sees and nobody hears, made to a person in view or to nobody in particular."""

    action: Literal["gesture"] = "gesture"
    kind: GestureKind
    to: str | None = Field(default=None, min_length=1, max_length=120)


class SetGoal(_Model):
    """Say to yourself what you are after now and why. It takes no time, and nobody in the world perceives it."""

    action: Literal["set_goal"] = "set_goal"
    text: str = Field(min_length=1, max_length=80)
    driver: Driver


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
    | Recall
    | Buy
    | Sell
    | Stash
    | Craft
    | Accuse
    | Seize
    | Judge
    | Tend
    | Gesture
    | SetGoal,
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
    # contract v1 (draft): unset until the systems behind them land
    purse: str | None = None  # the coins you carry, in words ("seven coins", "a short string of coins")
    load: str | None = None  # how laden you are ("carrying a heavy load")
    titles: list[str] = []  # ("the lord", "leader of band A")
    standing: str | None = None  # how people here regard you, a sentence ("People here regard you well.")
    wanted: str | None = None  # a sentence ("You are wanted in the castle town for theft.")
    held: str | None = None  # who holds you, a sentence ("Kenji holds you fast.")
    confined: str | None = None  # where you are confined, a sentence ("You are confined in the gaol.")

    def text(self) -> str:
        feeling = "You feel " + join(self.feeling) + "." if self.feeling else "You feel fine."
        carrying = "You carry " + join(self.carrying) + "." if self.carrying else "You carry nothing."
        parts = [feeling, carrying, self.doing]
        parts += [f"You have {self.purse}."] if self.purse else []
        parts += [f"You are {self.load}."] if self.load else []
        parts += [f"You are {join(self.titles)}."] if self.titles else []
        parts += [sentence for sentence in (self.standing, self.wanted, self.held, self.confined) if sentence]
        return " ".join(parts)


class Seen(_Model):
    """One person, animal or (group of) thing(s) in view. A group's `where` is its nearest member's, said as "the
    nearest …" when the others are elsewhere."""

    label: str  # a name, an appearance or a thing ("Aiko", "a man in a fur cloak", "three lean-tos")
    where: str  # rough distance and direction ("a few paces to the north")
    nearness: Nearness  # how far, as `where` says it
    doing: str | None = None
    kind: ThingKind | None = None  # things only
    resource: ResourceName | None = None  # what you could gather there
    # contract v1 (draft), people only: unset until the systems behind them land
    relation: str | None = None  # who they are to you ("your father", "your lord", "someone who struck you")
    regard: str | None = None  # how they stand and what you know of them ("well regarded", "who stole rice")


class PriceSeen(_Model):
    """A good on sale at the stall: its price in words, and whether that is dear, fair or cheap."""

    item: str
    price: str  # ("four coins for two measures")
    word: PriceWord


class MarketView(_Model):
    """What an open market stall you stand at sells."""

    items: list[PriceSeen]


class ChestView(_Model):
    """What your own chest within reach holds."""

    holds: list[str]  # item words ("twenty measures of rice"); empty: the chest is empty


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
    # contract v1 (draft): unset until the systems behind them land
    day_of_week: str | None = None  # ("the seventh day of the week; court day")
    ground: str | None = None  # whose ground or which way this is ("Band A's ground", "the road to the Elder grove")
    safety: Safety | None = None
    market: MarketView | None = None  # at an open stall
    chest: ChestView | None = None  # at your own chest

    def text(self) -> str:
        day = f" It is {self.day_of_week}." if self.day_of_week else ""
        lines = [f"You are {self.place}. {self.time}{day}", self.you.text()]
        whereabouts = [f"This is {self.ground}."] if self.ground else []
        whereabouts += [f"You are {self.safety}."] if self.safety else []
        if whereabouts:
            lines.append(" ".join(whereabouts))
        if self.people:
            lines.append("You see " + "; ".join(_said(self.people)) + ".")
        if self.animals:
            lines.append("Animals: " + "; ".join(_said(self.animals)) + ".")
        if self.things:
            lines.append("Around you: " + "; ".join(_said(self.things)) + ".")
        if self.market is not None:
            prices = [f"{price.item} at {price.price} ({price.word})" for price in self.market.items]
            lines.append("At the stall: " + ("; ".join(prices) if prices else "nothing for sale") + ".")
        if self.chest is not None:
            holds = self.chest.holds
            lines.append("Your chest holds " + join(holds) + "." if holds else "Your chest is empty.")
        verbs = {"whisper": "whispers", "normal": "says", "shout": "shouts"}
        lines += [f'{heard.who} {verbs[heard.volume]}: "{heard.words}"' for heard in self.heard]
        return "\n".join(lines)


def _said(seen: list[Seen]) -> list[str]:
    """A person with what you know of them is told in a phrase of their own ("Genzo, your father, a few paces …")."""
    told = []
    for entry in seen:
        known = [words for words in (entry.relation, entry.regard) if words]
        label = ", ".join([entry.label, *known]) + "," if known else entry.label
        told.append((label, entry.where, entry.doing, bool(known)))
    return phrases(told)
