"""The line registry (10-world-v1 §5.4, §6.3): one readable line and an importance 0-3 per event type, for the
spectators' event feed and timelines.

    3  death, an attack on a person, theft seen, a judgement, a predator's kill
    2  a hunter's kill, a sale, trespass, a tree felled, an injury, a harvest, a seizure
    1  speech, a node emptied, a fire lit, small news (tools, prices, bells, tending)
    0  hidden (bookkeeping: summaries, perception, actions, needs, item moves)

A `Line` is a `str.format` template over the event's payload fields plus `{actor}`; its variants (first match wins)
say it better for some payloads. Fields naming a citizen, an animal or a group read as their name ("Kenji", "a wolf",
"band A"), lists read as "Goro and Kenji", item counts as "2 meat and 1 berries", and `words` turns a field's code
words into prose ("shake_head" -> "shook their head").

Seam: every stream adds its event type's row here with the payload (one row per type; a test fails without it).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.observability.events import PAYLOAD_TYPES

Importance = Literal[0, 1, 2, 3]
Names = Callable[[str], str]  # an id (citizen, animal, group, store...) in words
GROUP_NAMES = {"town": "the town", "band_a": "band A", "band_b": "band B"}


@dataclass(frozen=True)
class Told:
    """What a line is told from: the event as stored."""

    type: str
    actor_kind: str
    actor_id: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Variant:
    when: Callable[[Told], bool]
    template: str
    importance: Importance


@dataclass(frozen=True)
class Line:
    template: str
    importance: Importance
    variants: tuple[Variant, ...] = ()
    words: Mapping[str, Mapping[str, str]] = field(default_factory=dict)  # field -> code word -> prose


NAMED_FIELDS = frozenset(
    {
        "actor",
        "attacker",
        "by",
        "group",
        "heard_by",
        "helpers",
        "holder",
        "household",
        "merchant",
        "owner",
        "person",
        "previous",
        "ref",
        "seen_by",
        "thief",
        "to",
        "witnesses",
    }
)


def _field(name: str, value: Any) -> Callable[[Told], bool]:
    return lambda told: told.payload.get(name) == value


def _set(name: str) -> Callable[[Told], bool]:
    return lambda told: bool(told.payload.get(name))


def _by(kind: str) -> Callable[[Told], bool]:
    return lambda told: told.actor_kind == kind


def _both(*tests: Callable[[Told], bool]) -> Callable[[Told], bool]:
    return lambda told: all(test(told) for test in tests)


def _label_says_where(told: Told) -> bool:
    """A walk's label that says the way already ("to the west", "home")."""
    label = str(told.payload.get("label", ""))
    return label.startswith("to ") or label in ("home", "your home", "")


def _killed_by_a_predator(told: Told) -> bool:
    return told.actor_kind == "animal" and str(told.payload.get("cause", "")).startswith("killed by")


_DOING = {
    "walk_to": "walking",
    "follow": "following",
    "flee": "fleeing",
    "gather": "gathering",
    "fish": "fishing",
    "hunt": "hunting",
    "attack": "attacking",
    "eat": "eating",
    "drink": "drinking",
    "rest": "resting",
    "sleep": "sleeping",
    "wait": "waiting",
    "work": "working",
    "make_fire": "making a fire",
    "feed_fire": "feeding the fire",
}
_STARTS = {**_DOING, "walk_to": "walking to", "work": "working:", "drink": "drinking at"}
_FIRES = {"pit": "the camp's fire pit", "basket": "a fire basket", "campfire": "a campfire"}
_GESTURES = {
    "wave": "waved",
    "bow": "bowed",
    "nod": "nodded",
    "shake_head": "shook their head",
    "point": "pointed",
    "laugh": "laughed",
    "jump": "jumped",
}

LINES: dict[str, Line] = {  # by event type
    "tick_summary": Line("The world moves on a minute", 0),
    "snapshot": Line("The world is saved at tick {tick}", 0),
    "citizen_spawned": Line("{name} comes into the world", 0),
    "perceived": Line("{actor} looks around", 0, (Variant(_field("kind", "check_self"), "{actor} takes stock", 0),)),
    "action_started": Line(
        "{actor} starts {action} {label}",
        0,
        (Variant(_both(_field("action", "walk_to"), _label_says_where), "{actor} starts walking {label}", 0),),
        words={"action": _STARTS},
    ),
    "action_finished": Line(
        "{actor} is done {action}",
        0,
        (Variant(_field("outcome", "failed"), "{actor} fails at {action}", 0),),
        words={"action": _DOING},
    ),
    "action_interrupted": Line("{actor} stops {action}", 0, words={"action": _DOING}),
    "said": Line("{actor}: “{words}”", 1),
    "need_changed": Line("{actor} feels {level}", 0),
    "injured": Line(
        "{actor} is hurt ({cause})",
        2,
        (
            Variant(_by("animal"), "{actor} is wounded ({cause})", 1),
            Variant(_field("cause", "violence"), "{attacker} strikes {actor}", 3),
            Variant(_set("attacker"), "{attacker} attacks {actor}", 3),
        ),
    ),
    "died": Line(
        "{actor} dies ({cause})",
        3,
        (
            Variant(_both(_by("animal"), _field("cause", "hunted")), "{actor} is brought down by a hunter", 2),
            Variant(_killed_by_a_predator, "{actor} is {cause}", 3),
            Variant(_by("animal"), "{actor} dies ({cause})", 1),
            Variant(_field("cause", "violence"), "{attacker} kills {actor}", 3),
            Variant(_set("attacker"), "{attacker} kills {actor}", 3),
        ),
    ),
    "item_moved": Line("{count} {item} moved", 0),
    "resource_changed": Line("{resource} in cell {cell}: {before} → {after}", 0),
    "knowledge_changed": Line("{actor} learns of {ref}", 0),
    "animal_spawned": Line("{actor} joins its group", 0),
    "fire_changed": Line(
        "{kind} burns lower",
        0,
        (
            Variant(_field("lit", False), "{kind} goes out", 0),
            Variant(_field("strength", 1.0), "{kind} burns high", 1),
        ),
        words={"kind": _FIRES},
    ),
    "intervention": Line("The gods intervene: {kind}", 2),
    "node_changed": Line(
        "{kind} {node}: {before} → {after}",
        0,
        (
            Variant(_both(_field("kind", "rice_paddy"), _by("citizen")), "{actor} harvests rice", 2),
            Variant(_both(_field("after", 0), _by("citizen")), "{actor} takes the last {item} from a {kind}", 1),
        ),
        words={"kind": {"berry_bush": "berry bush", "root_patch": "root patch", "reed_bed": "reed bed"}},
    ),
    "tree_felled": Line("{actor} fells a tree", 2),
    "trespassed": Line(
        "{actor} trespasses on {place}",
        2,
        (
            Variant(_set("took"), "{actor} poaches {took} on {place}", 2),
            Variant(_field("kind", "walls"), "{actor} is inside {place} at night", 2),
            Variant(_field("kind", "castle"), "{actor} is inside the castle walls at night", 2),
        ),
    ),
    "stole": Line(
        "{thief} steals {count} {item} from {owner}",
        2,
        (Variant(_set("witnesses"), "{thief} steals {count} {item} from {owner}, seen by {witnesses}", 3),),
    ),
    "bought": Line("{actor} buys {count} {item} for {coins} mon", 2),
    "sold": Line("{actor} sells {count} {item} for {coins} mon", 2),
    "crafted": Line("{actor} makes {count} {item}", 1),
    "spoiled": Line("Some of {holder}'s food spoils: {items}", 1),
    "tool_broke": Line("{actor}'s {item} breaks", 1),
    "tax_assessed": Line("{household} owes {owed_rice} rice and {owed_coins} mon in tax", 0),
    "tax_paid": Line(
        "{household} pays {rice} rice and {coins} mon of tax",
        1,
        (
            Variant(_field("coins", 0), "{household} pays {rice} rice of tax", 1),
            Variant(_field("rice", 0), "{household} pays {coins} mon of tax", 1),
        ),
    ),
    "tax_overdue": Line("{household} is {days} days behind on tax ({rice} rice, {coins} mon)", 2),
    "ledger": Line("{actor} ends the day with {coins} mon, worth {wealth_mon}", 0),
    "prices_changed": Line("{item} is {word} at the stall now: {sell} mon a lot of {lot}", 1),
    "accused": Line("{actor} accuses {person} before {to}", 2),
    "seized": Line(
        "{actor} tries to seize {person}",
        2,
        (Variant(_field("held", True), "{actor} seizes {person}", 2),),
    ),
    "released": Line(
        "{actor} goes free ({cause})",
        1,
        words={"cause": {"judged": "judged", "timeout": "held too long", "seizer_down": "the seizer is down"}},
    ),
    "confined": Line("{actor} is confined in {place}", 2),
    "judged": Line(
        "{actor} sentences {person} to a fine of {fine_mon} mon",
        3,
        (Variant(_field("sentence", "confine"), "{actor} sentences {person} to {confine_h:g} hours confined", 3),),
    ),
    "sentence_served": Line("{actor} has served the sentence ({sentence})", 1),
    "standing_changed": Line(
        "{actor}'s standing with {group} goes from {before} to {after} ({cause})",
        1,
        (Variant(_field("cause", "drift"), "{actor}'s standing with {group} drifts", 0),),
    ),
    "leader_changed": Line("{actor} becomes {title} of {group}", 2),
    "bell_rang": Line("The {kind} bell rings", 1),
    "tended": Line("{actor} tends {person}", 1),
    "gestured": Line(
        "{actor} {kind}",
        1,
        (Variant(_set("to"), "{actor} {kind} at {to}", 1),),
        words={"kind": _GESTURES},
    ),
    "goal_set": Line("{actor} means to {text} ({driver})", 1),
}

_UNREGISTERED = set(PAYLOAD_TYPES) - set(LINES)
if _UNREGISTERED:
    raise ValueError(f"event types without a line: {sorted(_UNREGISTERED)}")


def pick(told: Told) -> tuple[str, Importance]:
    """The template and importance that tell this event."""
    line = LINES[told.type]
    for variant in line.variants:
        if variant.when(told):
            return variant.template, variant.importance
    return line.template, line.importance


def importance(told: Told) -> Importance:
    return pick(told)[1]


def tell(told: Told, names: Names) -> tuple[str, Importance]:
    """The event's line (in words) and its importance."""
    template, rank = pick(told)
    told_line = template.format_map(_Fields(told, names, LINES[told.type].words)).strip()
    return told_line[:1].upper() + told_line[1:], rank


class _Fields(dict[str, Any]):
    """The template's fields in words, looked up as the template names them."""

    def __init__(self, told: Told, names: Names, words: Mapping[str, Mapping[str, str]]) -> None:
        super().__init__()
        self.told, self.names, self.words = told, names, words

    def __missing__(self, key: str) -> Any:
        if key == "actor":
            return self.names(self.told.actor_id) if self.told.actor_id else "someone"
        value = self.told.payload.get(key)
        if value is None:
            return ""
        if key in self.words:
            return self.words[key].get(str(value), str(value).replace("_", " "))
        return _words(key, value, self.names)


def _words(key: str, value: Any, names: Names) -> Any:
    if isinstance(value, list):
        return _and([names(v) if key in NAMED_FIELDS else str(v) for v in value])
    if isinstance(value, dict):
        if set(value) == {"item", "count"}:
            return f"{value['count']} {value['item']}"
        return _and([f"{count} {item}" for item, count in value.items()])
    if isinstance(value, str):
        return names(value) if key in NAMED_FIELDS else value.replace("_", " ")
    return value


def _and(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
