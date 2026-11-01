"""Ambition progress for spectators (10-world-v1 §3.1, §7; D95: never shown to a mind as a score).

A cast citizen's ambition is words plus world checks that must all hold (`sim/citizens.py` lists the 17). Here each
check has a predicate (met or not) and a progress (0-1), read from the replayed world at a tick (`Facts.state`) and
the run's events up to it (`Facts.events`). An ambition's progress is the mean of its checks' (a check not met counts
at most 99 %), and it is done when every check is met.

"N days running" checks count from the last time the thing happened (from the run's start if it never did), so they
fill up day by day and drop to zero when it happens again.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache, cached_property
from typing import Any

from pydantic import BaseModel

from app.observability.replay import ReplayCitizen, ReplayState
from app.sim.bodies import LEVEL_WORDS, NEEDS, Need, need_level
from app.sim.citizens import CITIZENS, DEV_CITIZENS, Ambition, AmbitionCheck, AmbitionClause, load_citizens
from app.sim.clock import DAY_MINUTES
from app.sim.ownership import CHEST
from app.sim.society import GROUPS, day_of_week, load_laws
from app.sim.state import Region

UNMET_CAP = 0.99  # a check not met never shows as complete
VIOLENCE = "violence"


@cache
def cast_ambitions() -> dict[str, Ambition]:
    """Citizen id -> their ambition, from the World v1 cast and the development cast (their ids don't clash)."""
    return {
        spec.id: spec.ambition
        for path in (DEV_CITIZENS, CITIZENS)
        for spec in load_citizens(path).citizens
        if spec.ambition is not None
    }


@dataclass(frozen=True)
class Record:
    """One stored event as the checks and the scoreboard read it."""

    seq: int
    tick: int
    type: str
    actor: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Deed:
    """A deed (10 §3.3) as its event tells it: who did it, against which group, and whether anyone saw who."""

    seq: int
    tick: int
    doer: str
    group: str  # the wronged group
    witnessed: bool


@dataclass(frozen=True)
class Facts:
    """What the checks read: the world replayed at `tick` and the run's events up to it, oldest first."""

    tick: int
    state: ReplayState
    events: Sequence[Record]

    @cached_property
    def by_type(self) -> dict[str, list[Record]]:
        grouped: dict[str, list[Record]] = {}
        for record in self.events:
            grouped.setdefault(record.type, []).append(record)
        return grouped

    def of(self, *types: str) -> list[Record]:
        """Records of these types, oldest first."""
        if len(types) == 1:
            return self.by_type.get(types[0], [])
        return sorted((r for t in types for r in self.by_type.get(t, [])), key=lambda record: record.seq)

    def since(self, days: float, *types: str) -> list[Record]:
        """Records of these types in the last `days` game days."""
        start = self.tick - days * DAY_MINUTES
        return [record for record in self.of(*types) if record.tick > start]

    def group_of(self, owner: str) -> str | None:
        """The group of a household (a home id) or a group name itself."""
        if owner in GROUPS:
            return owner
        return next((c.region for c in self.state.citizens.values() if c.home == owner), None)

    @cached_property
    def deeds(self) -> list[Deed]:
        """Every deed in the events, oldest first: thefts and trespasses are witnessed when their event names
        witnesses; violence always is (the struck see who strikes them)."""
        found: list[Deed] = []
        for record in self.of("stole", "trespassed", "injured", "died"):
            payload, doer = record.payload, record.actor
            if doer is None:
                continue
            if record.type in ("stole", "trespassed"):
                group = self.group_of(str(payload["owner"]))
                if group is not None:
                    found.append(Deed(record.seq, record.tick, doer, group, bool(payload.get("witnesses"))))
            elif payload.get("cause") == VIOLENCE and payload.get("attacker") in self.state.citizens:
                victim = self.state.citizens[doer]
                found.append(Deed(record.seq, record.tick, str(payload["attacker"]), victim.region, True))
        return found


class ClauseProgress(BaseModel):
    check: AmbitionCheck
    met: bool
    progress: int  # 0-100


class AmbitionProgress(BaseModel):
    text: str
    progress: int  # 0-100: the mean of the checks'
    done: bool  # every check met
    clauses: list[ClauseProgress]


@dataclass(frozen=True)
class _Reading:
    met: bool
    share: float  # 0-1


Args = Mapping[str, str | int]
Check = Callable[[Facts, ReplayCitizen, Args], _Reading]


def _ratio(have: float, want: float) -> _Reading:
    return _Reading(have >= want, min(1.0, max(0.0, have / want)) if want > 0 else 1.0)


def _yes(met: bool) -> _Reading:
    return _Reading(met, 1.0 if met else 0.0)


def _running(facts: Facts, last: int | None, days: int) -> _Reading:
    """Days running since `last` (the run's start when None) against the days wanted."""
    return _ratio((facts.tick - (last or 0)) / DAY_MINUTES, days)


def _last_felt(facts: Facts, who: Iterable[str], need: Need, level: int) -> int | None:
    """The last tick any of `who` felt `need` at `level` (an index of its words) or worse: now, or as a crossing
    told (a crossing to better words left the level above)."""
    ids = set(who)
    for citizen_id in ids:
        citizen = facts.state.citizens.get(citizen_id)
        if citizen is not None and citizen.alive and need_level(need, citizen.body[NEEDS.index(need)]) >= level:
            return facts.tick
    for record in reversed(facts.of("need_changed")):
        payload = record.payload
        if record.actor not in ids or payload["need"] != need:
            continue
        index = LEVEL_WORDS[need].index(str(payload["level"]))
        if (index if payload["worse"] else index + 1) >= level:
            return record.tick
    return None


def _members(facts: Facts, group: str) -> list[str]:
    return [citizen.id for citizen in facts.state.citizens.values() if citizen.region == group]


def store_holds(facts: Facts, _me: ReplayCitizen, args: Args) -> _Reading:
    held = facts.state.stores.get(str(args["store"]), {}).get(str(args["item"]), 0)
    reading = _ratio(held, int(args["count"]))
    if "at" in args:  # "at the week's end": met only on the week's last day
        return _Reading(reading.met and day_of_week(facts.tick) == load_laws().week.days, reading.share)
    return reading


def standing_at_least(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    who = facts.state.citizens[str(args.get("who", me.id))]
    value, wanted = who.standing[_region(args["group"])], int(args["value"])
    return _Reading(value >= wanted, _ratio(value + 100, wanted + 100).share)  # standing runs from -100


def deeds_judged(facts: Facts, _me: ReplayCitizen, args: Args) -> _Reading:
    start = facts.tick - int(args["days"]) * DAY_MINUTES
    deeds = [d.seq for d in facts.deeds if d.witnessed and d.group == args["group"] and d.tick > start]
    judged = {seq for record in facts.of("judged") for seq in record.payload.get("deeds", [])}
    done = sum(seq in judged for seq in deeds)
    return _Reading(done == len(deeds), done / len(deeds) if deeds else 1.0)


def seizures_guilty(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    """Their seizures that held the person, followed by a judgement of them (before anyone seized them again)."""
    guilty = 0
    hold_and_judge = facts.of("seized", "judged")
    for index, record in enumerate(hold_and_judge):
        if record.type != "seized" or record.actor != me.id or not record.payload["held"]:
            continue
        person = record.payload["person"]
        after = (r for r in hold_and_judge[index + 1 :] if r.payload.get("person") == person)
        guilty += next((r.type == "judged" for r in after), False)
    return _ratio(guilty, int(args["count"]))


def coins_at_least(_facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    return _ratio(me.inventory.get("coins", 0), int(args["count"]))


def no_tax_owed(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    overdue = [r.tick for r in facts.of("tax_overdue") if r.payload["household"] == me.home]
    return _running(facts, overdue[-1] if overdue else None, int(args["days"]))


def sold(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    count = sum(r.payload["count"] for r in facts.of("sold") if r.actor == me.id and r.payload["item"] == args["item"])
    return _ratio(count, int(args["count"]))


def knows_place(_facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    return _yes(str(args["place"]) in me.places)


def knows_people(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    known = sum(facts.state.citizens[p].region == args["group"] for p in me.people if p in facts.state.citizens)
    return _ratio(known, int(args["count"]))


def gave_crafted(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    """Half way once they crafted the item, done once they hand one to `to` after that."""
    item, to = args["item"], args["to"]
    made = next((r.seq for r in facts.of("crafted") if r.actor == me.id and r.payload["item"] == item), None)
    if made is None:
        return _Reading(False, 0.0)
    given = any(
        r.seq > made and r.payload["item"] == item and _hands(r, me.id, str(to)) for r in facts.of("item_moved")
    )
    return _Reading(given, 1.0 if given else 0.5)


def _hands(moved: Record, giver: str, receiver: str) -> bool:
    """An `item_moved` from the giver's inventory into the receiver's."""
    source, destination = moved.payload["source"], moved.payload["destination"]
    return (source["kind"], source.get("id"), destination["kind"], destination.get("id")) == (
        "inventory",
        giver,
        "inventory",
        receiver,
    )


def tended_people(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    return _ratio(len({r.payload["person"] for r in facts.of("tended") if r.actor == me.id}), int(args["count"]))


def never_starving(facts: Facts, _me: ReplayCitizen, args: Args) -> _Reading:
    starving = LEVEL_WORDS["hunger"].index("starving")
    return _running(
        facts, _last_felt(facts, _members(facts, str(args["group"])), "hunger", starving), int(args["days"])
    )


def owns(facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    item = str(args["item"])
    chest = facts.state.stores.get(f"{me.home}{CHEST}", {}) if me.home is not None else {}
    return _yes(me.inventory.get(item, 0) > 0 or chest.get(item, 0) > 0)


def is_leader(_facts: Facts, me: ReplayCitizen, args: Args) -> _Reading:
    title = "lord" if args["group"] == "town" else "leader"
    return _yes(me.alive and me.region == args["group"] and me.member is not None and title in me.member.titles)


def hunger_below(facts: Facts, _me: ReplayCitizen, args: Args) -> _Reading:
    level = LEVEL_WORDS["hunger"].index(str(args["word"]))
    return _running(facts, _last_felt(facts, [str(args["who"])], "hunger", level), int(args["days"]))


def followed_hunt(facts: Facts, me: ReplayCitizen, _args: Args) -> _Reading:
    """They followed someone while that person was out on a hunt."""
    spans = action_spans(facts, ("follow", "hunt"))
    hunts = [(span.actor, span.start, span.end) for span in spans if span.action == "hunt"]
    return _yes(
        any(
            hunter == span.target and start <= span.end and span.start <= end
            for span in spans
            if span.action == "follow" and span.actor == me.id
            for hunter, start, end in hunts
        )
    )


def no_witnessed_deed(facts: Facts, _me: ReplayCitizen, args: Args) -> _Reading:
    doers = set(_members(facts, str(args["group"])))
    seen = [deed.tick for deed in facts.deeds if deed.witnessed and deed.doer in doers]
    return _running(facts, seen[-1] if seen else None, int(args["days"]))


CHECKS: dict[AmbitionCheck, Check] = {
    "store_holds": store_holds,
    "standing_at_least": standing_at_least,
    "deeds_judged": deeds_judged,
    "seizures_guilty": seizures_guilty,
    "coins_at_least": coins_at_least,
    "no_tax_owed": no_tax_owed,
    "sold": sold,
    "knows_place": knows_place,
    "knows_people": knows_people,
    "gave_crafted": gave_crafted,
    "tended_people": tended_people,
    "never_starving": never_starving,
    "owns": owns,
    "is_leader": is_leader,
    "hunger_below": hunger_below,
    "followed_hunt": followed_hunt,
    "no_witnessed_deed": no_witnessed_deed,
}


def clause_progress(facts: Facts, me: ReplayCitizen, clause: AmbitionClause) -> ClauseProgress:
    reading = CHECKS[clause.check](facts, me, clause.args)
    share = reading.share if reading.met else min(reading.share, UNMET_CAP)
    return ClauseProgress(check=clause.check, met=reading.met, progress=_percent(share))


def ambition_progress(facts: Facts, me: ReplayCitizen, ambition: Ambition) -> AmbitionProgress:
    clauses = [clause_progress(facts, me, clause) for clause in ambition.all_of]
    done = all(clause.met for clause in clauses)
    mean = sum(clause.progress for clause in clauses) / len(clauses)
    return AmbitionProgress(
        text=ambition.text, progress=100 if done else min(99, round(mean)), done=done, clauses=clauses
    )


@dataclass(frozen=True)
class Span:
    """An action from its start to its end (or to the tick it is replayed at, while it runs)."""

    actor: str
    action: str
    start: int
    end: int
    args: Mapping[str, Any]
    target: str | None  # the id of what it is about, if the start told one


def action_spans(facts: Facts, actions: Sequence[str]) -> list[Span]:
    """Every run of these actions, oldest first, from `action_started` to its `action_finished` or
    `action_interrupted` (matched by actor and number)."""
    open_spans: dict[tuple[str, int], Record] = {}
    spans: list[Span] = []

    def close(start: Record, end: int) -> None:
        payload = start.payload
        target = payload.get("target") or {}
        spans.append(Span(str(start.actor), payload["action"], start.tick, end, payload["args"], target.get("id")))

    for record in facts.of("action_started", "action_finished", "action_interrupted"):
        if record.actor is None or record.payload["action"] not in actions:
            continue
        key = (record.actor, int(record.payload["number"]))
        if record.type == "action_started":
            open_spans[key] = record
        elif key in open_spans:
            close(open_spans.pop(key), record.tick)
    for start in open_spans.values():
        close(start, facts.tick)
    return sorted(spans, key=lambda span: (span.start, span.actor))


def _region(value: str | int) -> Region:
    group = str(value)
    if group not in GROUPS:
        raise ValueError(f"{group} is no group")
    return group


def _percent(share: float) -> int:
    return round(100 * share)
