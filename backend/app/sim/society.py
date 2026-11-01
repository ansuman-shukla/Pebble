"""Society (10-world-v1 §3.2, 3.3, 3.5, 3.6): groups and ranks, the deed log and who knows of each deed, standing,
bonds, band leadership and the lord's succession, the week, and the temple bell with the night law it starts.

The system learns everything from events as they are emitted (its `on_event` hook): a citizen's group, rank, titles,
kin and bonds from `citizen_spawned`; deeds from the one event each kind already has (`stole`, `trespassed`, an
`injured` or `died` with cause violence); hearsay from `accused`; good deeds from sales, gifts, tending, judgements
and served sentences. So no other system calls it to report a deed. Witnesses of a theft or a trespass come in the
event (its emitter fills them with `witnesses`); those of violence are whoever had the attacker in view.

- Standing per citizen per group, -100..100, moves once per deed per wronged group, as soon as one member of that
  group knows of the deed; each holder's values drift back toward their start at their dawn (`standing_changed`).
- Bonds per pair, -100..100, start from the cast's kin and bonds and move with the same events; they have no event
  of their own, so whatever replays the events derives them the same way.
- A band's leader is the adult its members regard most once someone has stood well above the leader for some dawns
  running, or the leader died; the lord's death makes the highest samurai lord (`leader_changed`).
- The monk rings the dawn, noon and dusk bells (`work("ring bell")` at the bell tower, `bell_rang`); the dusk bell
  starts the night law and the dawn bell ends it (sunset and sunrise, a little late, if nobody rings).
Numbers live in `data/society/laws.yaml`.
"""

import bisect
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Literal, cast, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from app.core.config import WORLD_DATA_DIR
from app.observability.events import (
    Accused,
    BellRang,
    CitizenSpawned,
    Died,
    EventDraft,
    Injured,
    ItemMoved,
    Judged,
    LeaderChanged,
    Seized,
    SentenceServed,
    StandingChanged,
    Stole,
    Tended,
    Traded,
    Trespassed,
)
from app.sim.bodies import THRESHOLDS
from app.sim.citizens import Kin, Title
from app.sim.clock import DAY_MINUTES, game_minute
from app.sim.core import SimCore
from app.sim.items import ITEMS
from app.sim.state import ActionState, Citizen, Region, System, age_group
from app.sim.vec import Vec3
from app.sim.wear import dawn_of

LAWS = WORLD_DATA_DIR / "society" / "laws.yaml"
GROUPS: tuple[Region, ...] = get_args(Region)
DeedKind = Literal["theft", "poaching", "trespass", "assault", "killing"]
BellKind = Literal["dawn", "noon", "dusk"]
LocalTest = Callable[[Vec3], bool]  # app.sim.systems' (which registers these hooks, so can't be imported here)
ADULTS = frozenset({"young_adult", "middle_aged", "elder"})  # who may lead a band
VIOLENCE = "violence"
BELL_TOWER = "bell-tower"  # the place the bell is rung at


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StandingWord(_Spec):
    floor: int = Field(ge=-100, le=100)
    word: str = Field(min_length=1)


class StandingLaws(_Spec):
    own: int = Field(ge=-100, le=100)
    leader: int = Field(ge=-100, le=100)
    guests: dict[Region, dict[Region, int]]
    drift: int = Field(ge=0)
    words: list[StandingWord] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_words(self) -> "StandingLaws":
        floors = [row.floor for row in self.words]
        if floors != sorted(floors, reverse=True) or len(set(floors)) != len(floors) or floors[-1] != -100:
            raise ValueError("standing words go from the highest floor down to -100")
        return self


class DeedLaw(_Spec):
    event: Literal["stole", "trespassed", "injured", "died"]
    standing: int = Field(le=0)


class Merits(_Spec):
    sale: int = Field(ge=0)
    gift: int = Field(ge=0)
    gift_per_day: int = Field(ge=0)
    shared_food: int = Field(ge=0)
    tended: int = Field(ge=0)
    accusation: int = Field(ge=0)
    served: int = Field(ge=0)


class LeaderLaws(_Spec):
    fed: int = Field(ge=0)
    starving: int = Field(le=0)


class LeadershipLaws(_Spec):
    margin: int = Field(gt=0)
    dawns: int = Field(gt=0)


class BondLaws(_Spec):
    kin: int = Field(ge=-100, le=100)
    mate: int = Field(ge=-100, le=100)
    gift: int = Field(ge=0)
    gift_per_day: int = Field(ge=0)
    sale: int = Field(ge=0)
    tended: int = Field(ge=0)
    struck: int = Field(le=0)
    robbed: int = Field(le=0)
    accused_by: int = Field(le=0)
    seized_by: int = Field(le=0)


class WeekLaws(_Spec):
    days: int = Field(gt=0)
    market_day: int = Field(ge=1)
    court_day: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_days(self) -> "WeekLaws":
        if max(self.market_day, self.court_day) > self.days:
            raise ValueError("market and court days fall within the week")
        return self


class BellLaws(_Spec):
    ring_minutes: int = Field(gt=0)
    moments: dict[BellKind, int]
    early_minutes: int = Field(ge=0)
    late_minutes: int = Field(ge=0)
    heard_m: float = Field(gt=0)
    night_grace_minutes: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_moments(self) -> "BellLaws":
        if set(self.moments) != set(get_args(BellKind)) or not all(0 <= m < DAY_MINUTES for m in self.moments.values()):
            raise ValueError("the bell has a moment of the day for dawn, noon and dusk")
        if not self.moments["dawn"] < self.moments["noon"] < self.moments["dusk"]:
            raise ValueError("dawn, noon and dusk come in that order")
        gaps = sorted(self.moments.values())
        if min(b - a for a, b in zip(gaps, gaps[1:], strict=False)) <= self.early_minutes + self.late_minutes:
            raise ValueError("a ringer's window must not reach two moments")
        return self


class Laws(_Spec):
    standing: StandingLaws
    deeds: dict[DeedKind, DeedLaw]
    merits: Merits
    leader: LeaderLaws
    leadership: LeadershipLaws
    bonds: BondLaws
    week: WeekLaws
    bell: BellLaws

    @model_validator(mode="after")
    def _check_deeds(self) -> "Laws":
        if set(self.deeds) != set(get_args(DeedKind)):
            raise ValueError(f"laws must list every deed kind {get_args(DeedKind)}")
        return self


@cache
def load_laws() -> Laws:
    return Laws.model_validate(yaml.safe_load(LAWS.read_text()))


# --- state ---


@dataclass
class Member:
    """A citizen as society knows them (from their `citizen_spawned`)."""

    group: Region
    age: int
    home: str | None
    base_rank: int  # their rank without titles (§3.2)
    titles: list[Title] = field(default_factory=list)
    family: dict[str, Kin] = field(default_factory=dict)  # kin by citizen id: what that person is to them

    @property
    def rank(self) -> int:
        return max([self.base_rank, *(TITLE_RANKS[title] for title in self.titles)])

    @property
    def adult(self) -> bool:
        return age_group(self.age) in ADULTS


TITLE_RANKS: dict[Title, int] = {"lord": 5, "samurai": 4, "leader": 4, "ashigaru": 3}


@dataclass(frozen=True)
class Deed:
    """One entry of the deed log, keyed by its event's seq."""

    seq: int
    tick: int
    kind: DeedKind
    doer: str
    group: Region  # the wronged group: its members' knowing it moves the doer's standing with it
    owner: str | None = None  # a theft's robbed household or group
    victim: str | None = None  # violence's victim
    blow: int | None = None  # a killing's killing blow (its `injured`, an assault deed)
    item: str | None = None  # what a theft or poaching took
    store: str | None = None  # the store a theft took it from
    place: str | None = None  # a trespass's or poaching's place, in words ("the castle town", "the Lord's woods")


@dataclass(frozen=True)
class Accusation:
    accuser: str
    person: str
    to: str
    deeds: tuple[int, ...]


@dataclass
class Society:
    members: dict[str, Member] = field(default_factory=dict)
    standing: dict[str, dict[Region, int]] = field(default_factory=dict)  # citizen -> group -> -100..100
    bonds: dict[str, int] = field(default_factory=dict)  # "a|b" (ids sorted) -> -100..100; absent: 0
    deeds: dict[int, Deed] = field(default_factory=dict)
    known: dict[str, list[int]] = field(default_factory=dict)  # citizen -> seqs of the deeds they know of (sorted)
    moved: dict[str, int] = field(default_factory=dict)  # "<deed seq>:<group>" -> the standing change it made
    accusations: list[Accusation] = field(default_factory=list)
    judgements: dict[int, Region] = field(default_factory=dict)  # `judged` seq -> the judge's group
    credited: dict[str, list[int]] = field(default_factory=dict)  # accuser -> deeds their accusations proved (sorted)
    settled: list[int] = field(default_factory=list)  # deeds a judgement named (sorted): nobody wants their doer now
    day: int = 0  # the town day the gift caps count
    gift_standing: dict[str, int] = field(default_factory=dict)  # giver -> standing their gifts raised today
    gift_bonds: dict[str, int] = field(default_factory=dict)  # pair -> bond their gifts raised today
    streaks: dict[str, int] = field(default_factory=dict)  # adult -> the leader's dawns running they stood above
    night: bool = False  # the night law holds in the town (between the dusk and dawn bells)
    rung: dict[BellKind, int] = field(default_factory=dict)  # bell -> the tick it last rang


_BLOCK = TypeAdapter(Society)


def _dump(society: Society) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(society, mode="json"))


def _load(data: JsonValue) -> Society:
    return _BLOCK.validate_python(data)


SOCIETY = System[Society]("society", 1, new=lambda _world: Society(), dump=_dump, load=_load)


# --- what other systems read ---


def standing_word(value: int) -> str:
    """The word for a standing (honoured, well regarded, nothing said, distrusted, outcast)."""
    return next(row.word for row in load_laws().standing.words if value >= row.floor)


def standing(core: SimCore, citizen_id: str, group: Region) -> int:
    return SOCIETY.of(core.state).standing[citizen_id][group]


def rank(core: SimCore, citizen_id: str) -> int:
    return SOCIETY.of(core.state).members[citizen_id].rank


def titles(core: SimCore, citizen_id: str) -> tuple[Title, ...]:
    return tuple(SOCIETY.of(core.state).members[citizen_id].titles)


def group_of(core: SimCore, citizen_id: str) -> Region:
    return SOCIETY.of(core.state).members[citizen_id].group


def leader(core: SimCore, group: Region) -> str | None:
    """The town's lord or a band's leader (living), if it has one."""
    title: Title = "lord" if group == "town" else "leader"
    society = SOCIETY.of(core.state)
    return next(
        (
            member_id
            for member_id, member in sorted(society.members.items())
            if member.group == group and title in member.titles and core.state.citizens[member_id].body.alive
        ),
        None,
    )


def bond(core: SimCore, a: str, b: str) -> int:
    return SOCIETY.of(core.state).bonds.get(_pair(a, b), 0)


def known_deeds(core: SimCore, citizen_id: str) -> list[Deed]:
    """The deeds this citizen saw or was told of, oldest first."""
    society = SOCIETY.of(core.state)
    return [society.deeds[seq] for seq in society.known.get(citizen_id, [])]


def deeds_by(core: SimCore, doer: str) -> list[Deed]:
    """Every deed of this citizen in the log, seen or not ("got away with it"), oldest first."""
    society = SOCIETY.of(core.state)
    return [deed for _, deed in sorted(society.deeds.items()) if deed.doer == doer]


def wanted_for(core: SimCore, citizen_id: str) -> list[Deed]:
    """The deeds this citizen is wanted for, oldest first: those a member of the wronged group knows of (seen or told)
    that no judgement has named yet. Children can't be judged (§3.3), so nobody wants them."""
    society = SOCIETY.of(core.state)
    if age_group(society.members[citizen_id].age) == "child":
        return []
    settled = set(society.settled)
    known = {
        (seq, society.members[knower].group)
        for knower, seqs in society.known.items()
        if knower != citizen_id
        for seq in seqs
    }
    return [deed for deed in deeds_by(core, citizen_id) if deed.seq not in settled and (deed.seq, deed.group) in known]


def witnesses(core: SimCore, doer: str) -> list[str]:
    """Who sees the doer now: the living who had them in view at the end of the last tick (§3.3)."""
    return sorted(citizen.id for citizen in core.living() if citizen.id != doer and doer in citizen.in_view)


def day_of_week(tick: int) -> int:
    """1-7, the same count everywhere: tick 0 falls on the first day (market day)."""
    return game_minute(tick) // DAY_MINUTES % load_laws().week.days + 1


def night_law(core: SimCore) -> bool:
    """The town's night law holds: between the dusk and the dawn bell (§3.3, trespass in the walls)."""
    return SOCIETY.of(core.state).night


# --- learning from events ---


def on_event(core: SimCore, event: EventDraft) -> None:
    """Event hook: everything society knows comes through here, as each event is emitted."""
    handler = _HANDLERS.get(event.type)
    if handler is not None:
        handler(core, SOCIETY.of(core.state), event)


def member_of(spawned: CitizenSpawned) -> Member:
    """The member a `citizen_spawned` enrols (replay builds the same one)."""
    return Member(
        group=spawned.region,
        age=spawned.age,
        home=spawned.home,
        base_rank=_untitled_rank(spawned.age) if spawned.titles else spawned.rank,
        titles=list(spawned.titles),
        family=cast(dict[str, Kin], dict(spawned.family)),
    )


def _enrol(_core: SimCore, society: Society, event: EventDraft) -> None:
    spawned = cast(CitizenSpawned, event.payload)
    member = member_of(spawned)
    society.members[spawned.id] = member
    society.standing[spawned.id] = {group: start_standing(member, group) for group in GROUPS}
    laws = load_laws().bonds
    for other, kin in sorted(spawned.family.items()):
        society.bonds.setdefault(_pair(spawned.id, other), laws.mate if kin == "mate" else laws.kin)
    for other, value in sorted(spawned.bonds.items()):  # what the cast says of a pair beats kin
        society.bonds[_pair(spawned.id, other)] = value


def _untitled_rank(age: int) -> int:
    """§3.2 for someone who loses their title: children 1, elders 3, everyone else 2."""
    return {"child": 1, "elder": 3}.get(age_group(age), 2)


def start_standing(member: Member, group: Region) -> int:
    """Where a member's standing with a group starts, and drifts back to."""
    laws = load_laws().standing
    if group == member.group:
        return laws.leader if {"lord", "leader"} & set(member.titles) else laws.own
    return laws.guests.get(group, {}).get(member.group, 0)


def _stole(core: SimCore, society: Society, event: EventDraft) -> None:
    stole = cast(Stole, event.payload)
    group = _owner_group(society, stole.owner)
    doer, item, store = str(event.actor_id), stole.item, stole.store
    _log(core, society, event, "theft", doer, group, stole.witnesses, owner=stole.owner, item=item, store=store)


def _trespassed(core: SimCore, society: Society, event: EventDraft) -> None:
    trespass = cast(Trespassed, event.payload)
    kind: DeedKind = "poaching" if trespass.took is not None else "trespass"
    item = trespass.took.item if trespass.took is not None else None
    group, seen = cast(Region, trespass.owner), trespass.witnesses
    _log(core, society, event, kind, str(event.actor_id), group, seen, item=item, place=trespass.place)


def _injured(core: SimCore, society: Society, event: EventDraft) -> None:
    injured = cast(Injured, event.payload)
    attacker, victim = injured.attacker, str(event.actor_id)
    if injured.cause != VIOLENCE or attacker is None or attacker not in society.members:
        return
    _bond(society, attacker, victim, load_laws().bonds.struck)
    # a killing blow's `injured` comes before its `died`: a victim left with no health tells nobody
    seen = set(witnesses(core, attacker)) - {victim}
    if core.state.citizens[victim].body.health > 0:
        seen.add(victim)
    _log(core, society, event, "assault", attacker, society.members[victim].group, sorted(seen), victim=victim)


def _died(core: SimCore, society: Society, event: EventDraft) -> None:
    died, dead = cast(Died, event.payload), str(event.actor_id)
    if died.cause == VIOLENCE and died.attacker is not None and died.attacker in society.members:
        blow = event.cause_seq if event.cause_seq in society.deeds else None
        seen = [who for who in witnesses(core, died.attacker) if who != dead]
        group = society.members[dead].group
        _log(core, society, event, "killing", died.attacker, group, seen, victim=dead, blow=blow)
    member = society.members.get(dead)
    if member is None:
        return
    if "lord" in member.titles:
        member.titles.remove("lord")
        _succeed_lord(core, society, dead, event.seq)
    if "leader" in member.titles:
        member.titles.remove("leader")
        heir = _highest_adult(core, society, member.group)
        if heir is not None:
            _crown(core, society, heir, member.group, "leader", dead, "death", event.seq)


def _accused(core: SimCore, society: Society, event: EventDraft) -> None:
    accused, accuser = cast(Accused, event.payload), str(event.actor_id)
    told = tuple(seq for seq in accused.deeds if seq in society.deeds and society.deeds[seq].doer == accused.person)
    society.accusations.append(Accusation(accuser, accused.person, accused.to, told))
    _bond(society, accused.person, accuser, load_laws().bonds.accused_by)
    _learn(core, society, accused.to, told)


def _seized(_core: SimCore, society: Society, event: EventDraft) -> None:
    _bond(society, cast(Seized, event.payload).person, str(event.actor_id), load_laws().bonds.seized_by)


def _judged(core: SimCore, society: Society, event: EventDraft) -> None:
    judged, judge = cast(Judged, event.payload), str(event.actor_id)
    group = society.members[judge].group
    society.judgements[event.seq] = group
    society.settled = sorted(set(society.settled) | set(judged.deeds))
    proved: dict[str, set[int]] = {}  # accuser -> the judged deeds they had told this judge of
    for accusation in society.accusations:
        if accusation.person == judged.person and accusation.to == judge:
            proved.setdefault(accusation.accuser, set()).update(set(judged.deeds) & set(accusation.deeds))
    for accuser, deeds in sorted(proved.items()):
        credited = society.credited.setdefault(accuser, [])
        if deeds - set(credited):  # once per set of deeds: judging the same deeds again credits nobody twice
            credited[:] = sorted(set(credited) | deeds)
            _change(core, society, accuser, group, load_laws().merits.accusation, "accusation", event.seq)


def _served(core: SimCore, society: Society, event: EventDraft) -> None:
    served = cast(SentenceServed, event.payload)
    group = society.judgements.get(served.judgement) if served.judgement is not None else None
    if group is not None:
        _change(core, society, str(event.actor_id), group, load_laws().merits.served, "served", event.seq)


def _tended(core: SimCore, society: Society, event: EventDraft) -> None:
    person, healer = cast(Tended, event.payload).person, str(event.actor_id)
    _bond(society, healer, person, load_laws().bonds.tended)
    _change(core, society, healer, society.members[person].group, load_laws().merits.tended, "tended", event.seq)


def _traded(core: SimCore, society: Society, event: EventDraft) -> None:
    merchant, trader = cast(Traded, event.payload).merchant, str(event.actor_id)
    if merchant == trader or merchant not in society.members:
        return
    _bond(society, trader, merchant, load_laws().bonds.sale)
    group = society.members[merchant].group
    if group != society.members[trader].group:
        _change(core, society, trader, group, load_laws().merits.sale, "sale", event.seq)


def _item_moved(core: SimCore, society: Society, event: EventDraft) -> None:
    """A gift: something handed from one inventory to another by the giver, not as part of anything else (a fine
    or a seizure moves goods with a cause)."""
    moved = cast(ItemMoved, event.payload)
    giver, receiver = moved.source.id, moved.destination.id
    if (
        moved.source.kind != "inventory"
        or moved.destination.kind != "inventory"
        or event.cause_seq is not None
        or giver != event.actor_id
        or giver is None
        or receiver is None
        or giver not in society.members
        or receiver not in society.members
    ):
        return
    laws, today = load_laws(), game_minute(core.state.tick) // DAY_MINUTES
    if today != society.day:
        society.day, society.gift_standing, society.gift_bonds = today, {}, {}
    pair = _pair(giver, receiver)
    raise_bond = min(laws.bonds.gift, laws.bonds.gift_per_day - society.gift_bonds.get(pair, 0))
    if raise_bond > 0:
        society.gift_bonds[pair] = society.gift_bonds.get(pair, 0) + raise_bond
        _bond(society, giver, receiver, raise_bond)
    group = society.members[receiver].group
    shared = group != "town" and group == society.members[giver].group and ITEMS[moved.item].food > 0
    merit = laws.merits.shared_food if shared else laws.merits.gift
    raise_standing = min(merit, laws.merits.gift_per_day - society.gift_standing.get(giver, 0))
    if raise_standing > 0:
        society.gift_standing[giver] = society.gift_standing.get(giver, 0) + raise_standing
        _change(core, society, giver, group, raise_standing, "shared food" if shared else "gift", event.seq)


_HANDLERS: dict[str, Callable[[SimCore, Society, EventDraft], None]] = {
    "citizen_spawned": _enrol,
    "stole": _stole,
    "trespassed": _trespassed,
    "injured": _injured,
    "died": _died,
    "accused": _accused,
    "seized": _seized,
    "judged": _judged,
    "sentence_served": _served,
    "tended": _tended,
    "bought": _traded,
    "sold": _traded,
    "item_moved": _item_moved,
}


def _owner_group(society: Society, owner: str) -> Region:
    """The group a robbed owner belongs to: a group itself, or the group of the household living in that home."""
    if owner in GROUPS:
        return owner
    groups = {member.group for member in society.members.values() if member.home == owner}
    if not groups:  # nobody in society lives there: a camp's empty lean-to is its band's, an empty house the town's
        site, colon, _ = owner.rpartition(":")
        camp = {member.group for member in society.members.values() if colon and (member.home or "").startswith(site)}
        groups = camp or {"town"}
    if len(groups) != 1:
        raise ValueError(f"the owner {owner!r} is a home of several groups")
    return groups.pop()


def _log(
    core: SimCore,
    society: Society,
    event: EventDraft,
    kind: DeedKind,
    doer: str,
    group: Region,
    seen: list[str],
    *,
    owner: str | None = None,
    victim: str | None = None,
    blow: int | None = None,
    item: str | None = None,
    store: str | None = None,
    place: str | None = None,
) -> None:
    society.deeds[event.seq] = Deed(event.seq, event.tick, kind, doer, group, owner, victim, blow, item, store, place)
    for witness in seen:
        _learn(core, society, witness, (event.seq,))


def _learn(core: SimCore, society: Society, knower: str, seqs: tuple[int, ...]) -> None:
    """The knower knows of these deeds now (seen, or told); each one moves its doer's standing with the wronged group
    the first time one of its members knows of it."""
    laws = load_laws()
    known = society.known.setdefault(knower, [])
    member = society.members[knower]
    for seq in seqs:
        deed = society.deeds[seq]
        index = bisect.bisect_left(known, seq)
        if deed.doer == knower or (index < len(known) and known[index] == seq):
            continue
        known.insert(index, seq)
        if deed.kind == "theft" and deed.owner is not None and member.home == deed.owner:
            _bond(society, knower, deed.doer, laws.bonds.robbed)
        key = f"{seq}:{member.group}"
        if member.group != deed.group or key in society.moved:
            continue
        delta = laws.deeds[deed.kind].standing
        if deed.blow is not None:  # the killing blow's assault already counted toward the killing
            delta -= society.moved.get(f"{deed.blow}:{member.group}", 0)
        society.moved[key] = delta
        _change(core, society, deed.doer, deed.group, delta, deed.kind, seq)


def _change(core: SimCore, society: Society, who: str, group: Region, delta: int, cause: str, deed: int | None) -> None:
    before = society.standing[who][group]
    after = max(-100, min(100, before + delta))
    if after == before:
        return
    society.standing[who][group] = after
    payload = StandingChanged(
        group=group, before=before, after=after, word=standing_word(after), cause=cause, deed=deed
    )
    core.emit("standing_changed", payload, actor=core.state.citizens[who], cause_seq=deed)


def _pair(a: str, b: str) -> str:
    if a == b:
        raise ValueError(f"{a} has no bond with themselves")
    return "|".join(sorted((a, b)))


def _bond(society: Society, a: str, b: str, delta: int) -> None:
    key = _pair(a, b)
    society.bonds[key] = max(-100, min(100, society.bonds.get(key, 0) + delta))


# --- leaders ---


def _highest_adult(core: SimCore, society: Society, group: Region) -> str | None:
    """The living adult of the group its members regard most (ties: the higher rank, then by id)."""
    adults = [
        member_id
        for member_id, member in society.members.items()
        if member.group == group and member.adult and core.state.citizens[member_id].body.alive
    ]
    if not adults:
        return None
    return min(adults, key=lambda m: (-society.standing[m][group], -society.members[m].rank, m))


def _succeed_lord(core: SimCore, society: Society, dead: str, cause_seq: int) -> None:
    samurai = [
        member_id
        for member_id, member in society.members.items()
        if "samurai" in member.titles and core.state.citizens[member_id].body.alive
    ]
    if samurai:
        heir = min(samurai, key=lambda m: (-society.members[m].rank, -society.standing[m]["town"], m))
        society.members[heir].titles.remove("samurai")
        _crown(core, society, heir, "town", "lord", dead, "succession", cause_seq)


def _crown(
    core: SimCore,
    society: Society,
    heir: str,
    group: Region,
    title: Literal["lord", "leader"],
    previous: str | None,
    cause: Literal["standing", "death", "succession"],
    cause_seq: int | None,
) -> None:
    society.members[heir].titles.append(title)
    payload = LeaderChanged(group=group, title=title, previous=previous, cause=cause)
    core.emit("leader_changed", payload, actor=core.state.citizens[heir], cause_seq=cause_seq)


def _band(core: SimCore, society: Society, group: Region) -> list[Citizen]:
    return [
        core.state.citizens[member_id]
        for member_id, member in sorted(society.members.items())
        if member.group == group and core.state.citizens[member_id].body.alive
    ]


def _band_fared(core: SimCore, society: Society, chief: str) -> int:
    """What a band leader's standing gains at their dawn from how the band fared: praise if every member is below
    hungry, blame if anyone starves."""
    laws, band = load_laws().leader, _band(core, society, society.members[chief].group)
    if any(citizen.body.hunger >= THRESHOLDS["hunger"][1] for citizen in band):
        return laws.starving
    if all(citizen.body.hunger < THRESHOLDS["hunger"][0] for citizen in band):
        return laws.fed
    return 0


def _challenge(core: SimCore, society: Society, chief: str) -> None:
    """At a band leader's dawn: who has stood well above them for enough of their dawns running; then the band's
    highest-standing adult takes the lead."""
    laws, group = load_laws().leadership, society.members[chief].group
    band = _band(core, society, group)
    bar = society.standing[chief][group] + laws.margin
    for citizen in band:
        if citizen.id == chief or not society.members[citizen.id].adult:
            continue
        if society.standing[citizen.id][group] >= bar:
            society.streaks[citizen.id] = society.streaks.get(citizen.id, 0) + 1
        else:
            society.streaks.pop(citizen.id, None)
    if not any(society.streaks.get(citizen.id, 0) >= laws.dawns for citizen in band):
        return
    for citizen in band:
        society.streaks.pop(citizen.id, None)
    heir = _highest_adult(core, society, group)
    if heir is not None and heir != chief:
        society.members[chief].titles.remove("leader")
        _crown(core, society, heir, group, "leader", chief, "standing", None)


def society_at_dawn(core: SimCore, _now: LocalTest) -> None:
    """Dawn hook: at each living citizen's dawn, a band leader's standing takes how the band fared, every standing
    of theirs drifts one back toward its start (one `standing_changed` for the net change, none if it cancels out),
    and then a leader may be overtaken (`_challenge`)."""
    society = SOCIETY.of(core.state)
    drift = load_laws().standing.drift
    for citizen in core.living():
        if not dawn_of(core, citizen) or citizen.id not in society.members:
            continue
        member = society.members[citizen.id]
        leads = "leader" in member.titles
        fared = _band_fared(core, society, citizen.id) if leads else 0
        for group in GROUPS:
            before = society.standing[citizen.id][group]
            bonus = fared if group == member.group else 0
            moved = max(-100, min(100, before + bonus))
            after = moved + max(-drift, min(drift, start_standing(member, group) - moved))
            if after != before:
                _change(core, society, citizen.id, group, after - before, "leader" if bonus else "drift", None)
        if leads:
            _challenge(core, society, citizen.id)


# --- the bell and the night law ---


def _town_minute(tick: int) -> int:
    """The minute of the day by the town's clock (the sun at the castle): the bells keep it."""
    return game_minute(tick) % DAY_MINUTES


def _until(moment: int, minute: float) -> float:
    """Minutes from `minute` to the moment of the day, the short way round (negative: it passed)."""
    return (moment - minute + DAY_MINUTES / 2) % DAY_MINUTES - DAY_MINUTES / 2


def _rang_lately(society: Society, kind: BellKind, tick: int) -> bool:
    return tick - society.rung.get(kind, -DAY_MINUTES) < DAY_MINUTES // 2


def ring_timing(core: SimCore, _citizen: Citizen) -> int | str:
    """`work("ring bell")` may start from a while before a bell's moment until just after it, if that bell hasn't
    rung: the ringer keeps the hour, and the ringing ends (the bell rings) at the moment, or after a ringing's length
    when started late."""
    bell, society, tick = load_laws().bell, SOCIETY.of(core.state), core.state.tick
    minute = _town_minute(tick)
    for kind, moment in bell.moments.items():
        ahead = _until(moment, minute)
        if -bell.late_minutes <= ahead <= bell.early_minutes:
            if _rang_lately(society, kind, tick):
                return f"The {kind} bell has been rung."
            return max(bell.ring_minutes, round(ahead))
    return "It isn't time for the bell."


def ring_bell(core: SimCore, citizen: Citizen, _action: ActionState) -> str:
    """Work finisher: the bell of the nearest moment rings (`bell_rang`); dusk starts the night law, dawn ends it."""
    society, tick = SOCIETY.of(core.state), core.state.tick
    minute = _town_minute(tick)
    kind = min(load_laws().bell.moments.items(), key=lambda item: abs(_until(item[1], minute)))[0]
    if _rang_lately(society, kind, tick):
        return f"Someone has rung the {kind} bell already."
    society.rung[kind] = tick
    if kind != "noon":
        society.night = kind == "dusk"
    core.emit("bell_rang", BellRang(kind=kind), actor=citizen)
    return f"You ring the {kind} bell; it carries across the town."


def keep_night(core: SimCore) -> None:
    """Every-tick hook: if nobody rings, the night law starts a little after sunset and ends a little after sunrise
    anyway."""
    bell, society = load_laws().bell, SOCIETY.of(core.state)
    minute = _town_minute(core.state.tick)
    dawn, dusk, grace = bell.moments["dawn"], bell.moments["dusk"], bell.night_grace_minutes
    if society.night and dawn + grace <= minute < dusk:
        society.night = False
    elif not society.night and (minute >= dusk + grace or minute < dawn):
        society.night = True
