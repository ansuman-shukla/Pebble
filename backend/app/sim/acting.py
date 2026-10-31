"""Bookkeeping every action module shares: starting and settling durative actions, refusals, naming items and
finding them within reach. Every failure is an in-world sentence.
"""

import re
from collections.abc import Mapping

from app.observability.events import ActionEnded, ActionStarted, JsonScalar
from app.sim.core import REACH_M, SimCore
from app.sim.items import ITEM_WORDS, TOOL_WORDS, tool_in
from app.sim.perception import normalize
from app.sim.state import ActionState, Citizen
from app.world_api.models import ActionName, ActionResult

_NUMBERS = {
    word: index + 1
    for index, word in enumerate("one two three four five six seven eight nine ten eleven twelve".split())
} | {"a": 1, "an": 1}
# the amounts the world itself says, read back ("a great deal of rice" and "a lot of" mean all of it)
_VAGUE: dict[str, int | None] = {"a few": 3, "a little": 3, "a handful": 8, "a great": None, "a lot": None}
VERB: dict[str, str] = {
    "walk_to": "walking",
    "follow": "following",
    "gather": "gathering",
    "eat": "eating",
    "drink": "drinking",
    "rest": "resting",
    "sleep": "sleeping",
    "wait": "waiting",
    "flee": "running",
    "work": "working",
    "hunt": "hunting",
    "fish": "fishing",
    "make_fire": "making a fire",
    "feed_fire": "tending the fire",
    "attack": "fighting",
    "craft": "crafting",
}


def begin(
    core: SimCore, citizen: Citizen, kind: ActionName, label: str, args: dict[str, JsonScalar], destination: str = ""
) -> ActionState:
    number = citizen.next_action
    citizen.next_action += 1
    seq = core.emit("action_started", ActionStarted(number=number, action=kind, args=args, label=label), actor=citizen)
    action = ActionState(
        number=number,
        kind=kind,
        started_tick=core.state.tick,
        started_seq=seq,
        args=args,
        label=label,
        destination=destination,
    )
    citizen.action = action
    return action


def settled(core: SimCore, citizen: Citizen, kind: ActionName, outcome: str, text: str) -> int:
    """A durative action that ends the moment it is asked for (failed, or already done)."""
    number = citizen.next_action
    citizen.next_action += 1
    result = ActionResult(action=kind, outcome="done" if outcome == "done" else "failed", text=text)
    core.emit(
        "action_finished",
        ActionEnded(number=number, action=kind, outcome=result.outcome, text=text),
        actor=citizen,
    )
    core.record_result(citizen, number, result)
    return number


def refuse(core: SimCore, citizen: Citizen, kind: ActionName, text: str) -> ActionResult:
    result = ActionResult(action=kind, outcome="failed", text=text)
    core.emit(
        "action_finished",
        ActionEnded(number=0, action=kind, outcome="failed", text=text),
        actor=citizen,
        visibility="private",
    )
    return result


def item_name(words: str) -> str | None:
    """The item the words name: the last word or two-word name that is an item ("some dried meat" -> dried meat)."""
    query = normalize(words).split()
    for end in range(len(query), 0, -1):
        for start in (end - 2, end - 1):
            name = ITEM_WORDS.get(" ".join(query[max(start, 0) : end]))
            if start >= 0 and name is not None:
                return name
    return None


def carried_name(words: str, inventory: Mapping[str, int]) -> str | None:
    """The item the words name, or for a bare tool word ("the spear", "an axe") the best of that tool carried."""
    item = item_name(words)
    last = normalize(words).split()[-1:]
    if item is not None or not last or last[0] not in TOOL_WORDS:
        return item
    return tool_in(inventory, TOOL_WORDS[last[0]])


def item_amount(words: str, have: int) -> int:
    """How many of `have` the words ask for: "a fish", "two berries", "3 roots", "half the meat", "a few nuts";
    anything else ("some", "all", just the item) means all of it."""
    query = " ".join(re.sub(r"[^a-z0-9' -]", " ", words.lower()).split())  # articles kept: "a fish" is one
    head, _, rest = query.partition(" ")
    vague = next((phrase for phrase in _VAGUE if query.startswith(phrase + " ")), None)
    wanted: int | None
    if vague is not None:
        wanted = _VAGUE[vague]
    elif head == "half":
        wanted = (have + 1) // 2
    elif head.isdigit():
        wanted = int(head)
    elif head in _NUMBERS and rest:
        wanted = _NUMBERS[head]
    else:
        wanted = None
    return have if wanted is None else max(1, min(wanted, have))


def stack_in_reach(core: SimCore, citizen: Citizen, item: str) -> str | None:
    options = [
        (core.distance_m(citizen.position, stack.position), stack.id)
        for stack in core.state.ground.values()
        if stack.item == item and stack.count > 0
    ]
    near = [option for option in options if option[0] <= REACH_M]
    return min(near)[1] if near else None


def capital(text: str) -> str:
    return text[:1].upper() + text[1:]
