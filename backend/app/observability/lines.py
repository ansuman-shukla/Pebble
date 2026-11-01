"""The line registry (10-world-v1 §5.4, §6.3): one readable line and an importance 0-3 per event type, for the
spectators' event feed and timelines.

    3  death, an attack on a person, theft seen, a judgement, a predator's kill
    2  a hunter's kill, a sale, trespass, a tree felled, an injury, a harvest, a seizure
    1  speech, a node emptied, a fire lit, small news (tools, prices, bells, tending)
    0  hidden (bookkeeping: summaries, perception, actions, needs, item moves)

A `Line` is a `str.format` template over the event's payload fields plus `{actor}`; its variants (first match wins)
say it better for some payloads. Fields naming a citizen, an animal, a group or a household read as their name ("Kenji",
"a wolf", "band A", "Genzo's house" for its eldest member, "their house" after `{actor}` when it is theirs), lists read
as "Goro and Kenji", item counts as "2 meat and a berry", day and hour counts with their unit ("1 day"), `{a_kind}` is a
field with its article ("an obsidian field"), `words` turns a field's code words into prose ("shake_head" -> "shakes
their head") and `fields` tells a field from the whole payload ("{fire}": "band A's fire pit"). World v1 lines a
citizen does start with `{actor}`, so their timeline tells them without the name.

Seam: every stream adds its event type's row here with the payload (one row per type; a test fails without it).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

from app.observability.events import PAYLOAD_TYPES
from app.sim.fauna import SPECIES
from app.sim.items import ITEMS

Importance = Literal[0, 1, 2, 3]
GROUP_NAMES = {"town": "the town", "band_a": "band A", "band_b": "band B"}
ACTOR = "{actor} "  # how a line told from its actor starts


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
    fields: Mapping[str, Callable[[Told], str]] = field(default_factory=dict)  # fields told from the whole payload


class Resident(NamedTuple):
    name: str
    home: str | None
    age: int


@dataclass(frozen=True)
class Names:
    """Ids in words: citizens by name, a household by its eldest member as "Genzo's house" or "Ama's shelter",
    animals as "a deer", groups as "band A", anything else as given."""

    people: Mapping[str, Resident]
    heads: Mapping[str, str]  # household (home id) -> the id of its eldest member, whom it is named for

    def __call__(self, ref: str) -> str:
        if ref in self.people:
            return self.people[ref].name
        if ref in self.heads:
            return f"{self.people[self.heads[ref]].name}'s {_dwelling(ref)}"
        if ref in GROUP_NAMES:
            return GROUP_NAMES[ref]
        if (kind := ref.partition(":")[0]) in SPECIES:
            return SPECIES[kind].one
        return ref.replace("_", " ")

    def of(self, ref: str, actor: str | None) -> str:
        """`ref` in words as said of the actor: the household named for them is "their house" (not "Genzo pays tax
        for Genzo's house")."""
        if actor is not None and self.heads.get(ref) == actor:
            return f"their {_dwelling(ref)}"
        return self(ref)


def _dwelling(home: str) -> str:
    return "shelter" if ":" in home else "house"  # camp homes are "<camp>:<shelter>"


def namer(people: Mapping[str, Resident]) -> Names:
    heads: dict[str, str] = {}
    for ref, person in sorted(people.items(), key=lambda item: (-item[1].age, item[0])):
        if person.home is not None:
            heads.setdefault(person.home, ref)
    return Names(people, heads)


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
        "to",
        "witnesses",
    }
)
UNITS = {"days": "day", "confine_h": "hour"}  # number fields told with their unit ("1 day", "6 hours")


def _field(name: str, *values: Any) -> Callable[[Told], bool]:
    return lambda told: told.payload.get(name) in values


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


def _fewer(told: Told) -> bool:
    return int(told.payload.get("after", 0)) < int(told.payload.get("before", 0))


def _on_ground(told: Told) -> bool:
    """A place one is on rather than in ("band A's ground", not "the Lord's woods")."""
    return str(told.payload.get("place", "")).endswith("ground")


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
_STARTS = {
    **_DOING,
    "walk_to": "walking to",
    "drink": "drinking at",
    "make_fire": "making a fire in",
    "feed_fire": "feeding",
}
_GESTURES = {
    "wave": "waves",
    "bow": "bows",
    "nod": "nods",
    "shake_head": "shakes their head",
    "point": "points",
    "laugh": "laughs",
    "jump": "jumps",
}
_NODES = {"deadwood": "deadwood pile"}  # node kinds whose words aren't the kind's own
_MINED = ("flint_seam", "obsidian_field", "iron_sand_bar", "gold_pool")
_REGARD = {  # standing words (10 §3.6) as said of the person
    "honoured": "honoured",
    "well regarded": "well regarded",
    "nothing said": "neither trusted nor distrusted",
    "distrusted": "distrusted",
    "outcast": "cast out",
}


def amount(item: str, count: int) -> str:
    """A count of an item as a spectator reads it: one of it ("a hide", "a measure of rice"), pieces counted with
    their plural ("2 hides", "3 berries"), a mass in measures as a number ("12 rice")."""
    kind = ITEMS.get(item)
    if kind is None:
        return _a(item) if count == 1 else f"{count} {item}"
    if count == 1:
        return kind.one
    return f"{count} {kind.name if kind.mass else kind.plural or kind.name}"


def _amount_of(count: str) -> Callable[[Told], str]:
    """The payload's `item` counted by its `count` field."""
    return lambda told: amount(str(told.payload["item"]), int(told.payload[count]))


def _fire(told: Told) -> str:
    """Which fire: "band A's fire pit" (a camp's pit, id "<camp>:fire-pit"), "a fire basket at the main gate" (a
    town basket, id "<place>-fire-<side>"), "a campfire"."""
    ref, kind = str(told.payload["id"]), told.payload["kind"]
    if kind == "pit":
        group = GROUP_NAMES.get(ref.partition(":")[0].removesuffix("_camp"))
        return f"{group}'s fire pit" if group is not None else "a fire pit"
    if kind == "basket":
        place, fire, _ = ref.rpartition("-fire")
        return f"a fire basket at the {place.replace('-', ' ')}" if fire else "a fire basket"
    return "a campfire"


LINES: dict[str, Line] = {  # by event type
    "tick_summary": Line("The world moves on a minute", 0),
    "snapshot": Line("The world is saved at tick {tick}", 0),
    "citizen_spawned": Line("{name} comes into the world", 0),
    "perceived": Line("{actor} looks around", 0, (Variant(_field("kind", "check_self"), "{actor} takes stock", 0),)),
    "action_started": Line(
        "{actor} starts {action} {label}",
        0,
        (
            Variant(_both(_field("action", "walk_to"), _label_says_where), "{actor} starts walking {label}", 0),
            Variant(_field("action", "work"), "{actor} starts {label}", 0),
            Variant(_field("action", "fish"), "{actor} starts fishing", 0),
        ),
        words={"action": _STARTS},
    ),
    "action_finished": Line(
        "{actor} is done {action}",
        0,
        (Variant(_field("outcome", "failed"), "{actor} fails at {action}", 0),),
        words={"action": _DOING},
    ),
    "action_interrupted": Line("{actor} stops {action}", 0, words={"action": _DOING}),
    "said": Line(
        "{actor}: “{words}”",
        1,
        (Variant(_field("volume", "shout"), "{actor} shouts: “{words}”", 2),),  # a call to all, a cry of theft
    ),
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
            Variant(
                _both(_by("animal"), _field("cause", "hunted"), _set("attacker")), "{attacker} brings down {actor}", 2
            ),
            Variant(_both(_by("animal"), _field("cause", "hunted")), "{actor} is brought down by a hunter", 2),
            Variant(_both(_killed_by_a_predator, _set("attacker")), "{attacker} brings down {actor}", 3),
            Variant(_killed_by_a_predator, "{actor} is {cause}", 3),
            Variant(_by("animal"), "{actor} dies ({cause})", 1),
            Variant(_set("attacker"), "{attacker} kills {actor}", 3),
        ),
    ),
    "item_moved": Line("{amount} moved", 0, fields={"amount": _amount_of("count")}),
    "resource_changed": Line("{resource} in cell {cell}: {before} → {after}", 0),
    "knowledge_changed": Line("{actor} learns of {ref}", 0),
    "animal_spawned": Line("{actor} joins its group", 0),
    "fire_changed": Line(
        "{fire} burns lower",
        0,
        (
            Variant(_field("lit", False), "{fire} goes out", 0),
            Variant(_field("strength", 1.0), "{fire} burns high", 1),
        ),
        fields={"fire": _fire},
    ),
    "intervention": Line("The gods intervene: {kind}", 2),
    # world v1: told with the citizen who did it first, so a timeline can drop the name (`tell(..., own=True)`)
    "node_changed": Line(
        "{a_kind} now has {after} {item}",
        0,
        (
            Variant(_both(_by("citizen"), _field("kind", "rice_paddy"), _fewer), "{actor} harvests rice", 2),
            # a felling empties the tree; `tree_felled` tells it in the feed
            Variant(_both(_by("citizen"), _field("kind", "tree"), _fewer), "{actor} cuts {a_kind} into logs", 0),
            Variant(_both(_by("citizen"), _field("after", 0)), "{actor} takes the last {item} from {a_kind}", 1),
            Variant(_both(_by("citizen"), _field("kind", "fishing_spot"), _fewer), "{actor} catches {item}", 0),
            Variant(_both(_by("citizen"), _field("kind", *_MINED), _fewer), "{actor} mines {item} from {a_kind}", 0),
            Variant(_both(_by("citizen"), _fewer), "{actor} gathers {item} from {a_kind}", 0),
            Variant(_by("citizen"), "{actor} tends {a_kind}", 0),
            Variant(lambda told: not _fewer(told), "{a_kind} grows more {item}", 0),
        ),
        words={"kind": _NODES},
    ),
    "tree_felled": Line("{actor} fells a tree", 2),
    "trespassed": Line(
        "{actor} trespasses in {place}",
        2,
        (
            Variant(_both(_set("took"), _on_ground), "{actor} poaches {took} on {place}", 2),
            Variant(_set("took"), "{actor} poaches {took} in {place}", 2),
            Variant(_field("kind", "walls"), "{actor} is inside {place} at night", 2),
            Variant(_field("kind", "castle"), "{actor} is inside the castle walls at night", 2),
            Variant(_on_ground, "{actor} trespasses on {place}", 2),
        ),
    ),
    "stole": Line(
        "{actor} steals {amount} from {owner}",
        2,
        (Variant(_set("witnesses"), "{actor} steals {amount} from {owner}, seen by {witnesses}", 3),),
        fields={"amount": _amount_of("count")},
    ),
    "bought": Line("{actor} buys {amount} for {coins} mon", 2, fields={"amount": _amount_of("count")}),
    "sold": Line("{actor} sells {amount} for {coins} mon", 2, fields={"amount": _amount_of("count")}),
    "crafted": Line("{actor} makes {amount}", 1, fields={"amount": _amount_of("count")}),
    "spoiled": Line(
        "Some of the food in {holder} spoils: {items}",
        1,
        (
            Variant(_by("citizen"), "{actor} finds {items} spoiled", 1),
            Variant(_field("holder_kind", "inventory"), "Some of {holder}'s food spoils: {items}", 1),
        ),
    ),
    "tool_broke": Line("{actor} wears out their {item}", 1),
    "tax_assessed": Line(
        "{actor} adds {rice} rice to the tax {household} owes",
        0,
        (Variant(_field("rice", 0), "{household} owes {coins} mon more in dues", 0),),
    ),
    "tax_paid": Line(
        "{actor} pays {rice} rice and {coins} mon of tax for {household}",
        1,
        (
            Variant(_field("coins", 0), "{actor} pays {rice} rice of tax for {household}", 1),
            Variant(_field("rice", 0), "{actor} pays {coins} mon of tax for {household}", 1),
        ),
    ),
    "tax_overdue": Line(
        "{household} is {days} behind on tax ({rice} rice, {coins} mon)",
        2,
        (Variant(_by("citizen"), "{actor} is {days} behind on tax for {household} ({rice} rice, {coins} mon)", 2),),
    ),
    "ledger": Line("{actor} ends the day with {coins} mon, worth {wealth_mon} mon", 0),
    "prices_changed": Line(
        "{item} is {word} at the stall now: {sell} mon for {lot_amount}", 1, fields={"lot_amount": _amount_of("lot")}
    ),
    "accused": Line("{actor} accuses {person} before {to}", 2),
    "seized": Line(
        "{actor} tries to seize {person}",
        2,
        (Variant(_field("held", True), "{actor} seizes {person}", 2),),
    ),
    "released": Line(
        "{actor} goes free ({cause})",
        1,
        (Variant(_field("cause", "died"), "{actor} dies in custody", 2),),
        words={"cause": {"judged": "judged", "timeout": "held too long", "seizer_down": "the seizer is down"}},
    ),
    "confined": Line("{actor} is confined in {place}", 2),
    "judged": Line(
        "{actor} sentences {person} to a fine of {fine_mon} mon",
        3,
        (Variant(_field("sentence", "confine"), "{actor} sentences {person} to {confine_h} confined", 3),),
    ),
    "sentence_served": Line("{actor} has served the sentence ({sentence})", 1),
    "standing_changed": Line(
        "{actor} is now {word} by {group} ({cause})",
        1,
        (Variant(_field("cause", "drift"), "{actor} drifts back toward their old standing with {group}", 0),),
        words={"word": _REGARD},
    ),
    "leader_changed": Line("{actor} becomes {title} of {group}", 2),
    "bell_rang": Line("The {kind} bell rings", 1, (Variant(_by("citizen"), "{actor} rings the {kind} bell", 1),)),
    "tended": Line("{actor} tends {person}", 1),
    "gestured": Line(
        "{actor} {kind}",
        1,
        (
            Variant(_both(_set("to"), _field("kind", "wave")), "{actor} waves to {to}", 1),
            Variant(_both(_set("to"), _field("kind", "bow")), "{actor} bows to {to}", 1),
            Variant(_both(_set("to"), _field("kind", "nod")), "{actor} nods to {to}", 1),
            Variant(_both(_set("to"), _field("kind", "point")), "{actor} points at {to}", 1),
            Variant(_both(_set("to"), _field("kind", "shake_head")), "{actor} shakes their head at {to}", 1),
        ),
        words={"kind": _GESTURES},
    ),
    "goal_set": Line("{actor} means to {text} ({driver})", 0),
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


def tell(told: Told, names: Names, *, own: bool = False) -> tuple[str, Importance]:
    """The event's line (in words) and its importance. `own` tells it on the actor's own timeline: without the
    actor's name in front ("buys 4 rice for 8 mon"), when the line starts with it."""
    template, rank = pick(told)
    fields = _Fields(told, names, LINES[told.type], template)
    if own and template.startswith(ACTOR):
        return template.removeprefix(ACTOR).format_map(fields), rank
    told_line = template.format_map(fields).strip()
    return told_line[:1].upper() + told_line[1:], rank


class _Fields(dict[str, Any]):
    """The template's fields in words, looked up as the template names them. A field after `{actor}` that names the
    actor's own household reads "their house"."""

    def __init__(self, told: Told, names: Names, line: Line, template: str) -> None:
        super().__init__()
        self.told, self.names, self.line, self.template = told, names, line, template

    def __missing__(self, key: str) -> Any:
        if key == "actor":
            return self.names(self.told.actor_id) if self.told.actor_id else "someone"
        if key.startswith("a_"):  # "{a_kind}": the field with its article ("an obsidian field")
            return _a(str(self[key.removeprefix("a_")]))
        if key in self.line.fields:
            return self.line.fields[key](self.told)
        value = self.told.payload.get(key)
        if value is None:
            return ""
        if key in self.line.words:
            return self.line.words[key].get(str(value), str(value).replace("_", " "))
        return _words(key, value, self.name_of(key))

    def name_of(self, key: str) -> Callable[[str], str]:
        """How an id in this field reads: as said of the actor when the line has named them before it."""
        actor_at = self.template.find("{actor}")
        if 0 <= actor_at < self.template.find(f"{{{key}}}"):
            return lambda ref: self.names.of(ref, self.told.actor_id)
        return self.names


def _words(key: str, value: Any, names: Callable[[str], str]) -> Any:
    if key in UNITS:
        return f"{value:g} {UNITS[key]}{'' if value == 1 else 's'}"
    if isinstance(value, list):
        return _and([names(v) if key in NAMED_FIELDS else str(v) for v in value])
    if isinstance(value, dict):
        if set(value) == {"item", "count"}:
            return amount(value["item"], value["count"])
        return _and([amount(item, count) for item, count in value.items()])
    if isinstance(value, str):
        return names(value) if key in NAMED_FIELDS else value.replace("_", " ")
    return value


def _a(words: str) -> str:
    return f"{'an' if words[:1] in tuple('aeiou') else 'a'} {words}"


def _and(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
