"""Justice and tending (10-world-v1 §3.4): `accuse`, `seize`, `judge` (a fine or confinement) and `tend`.

- **Accuse** (instant): tell someone awake within speaking range every deed you know of a person; society learns the
  hearsay from `accused`, and the one told hears it said ("Kaz stole rice.").
- **Seize** (1 min, reach 2 m): p = clamp(0.5 + 0.3·(armed − armed) + 0.3·(strength − strength) + 0.2 per armed
  helper of the seizer's group within 3 m of the target, 0.1, 0.95), rolled on `justice.seize`; armed = carrying a
  spear or trained in arms. Children can't be seized. Held, the target can only look, speak, wait and set a goal, and
  is led behind the seizer (`movement.lead_held`), whose walk slows to 0.8×.
- **Custody** runs on one 12 h clock from the seizure: held, then confined in the gaol (someone held who is led into
  it takes a free gaol seat at the tick's end) or tied at a band's fire by a judgement. It ends at a judgement (a fine
  paid in full frees at once), when a confinement is served, when the 12 h are up, or when the seizer is hurt, asleep
  or dead, or when they die: one `released` each time (judged, timeout, seizer_down, died).
- **Judge** (15 min, within 4 m): the lord inside the castle walls, or a band leader within 15 m of the band's fire
  pit; the target held or confined; the judge must know a deed of theirs not yet judged or, the lord, their
  household's tax overdue 3 days running. A fine takes the purse's coins, then the household chest's, then goods at
  their town value; those robbed are paid what they lost first, the rest goes to the treasury. A fine not paid in full
  keeps them in custody and leaves its deeds open to a confinement. Confinement is in the gaol in town, tied at the
  fire in a band, and never outlasts the custody's 12 h.
- **Tend** (30 min, reach 2 m, the healing skill): the hurt person gains 3 health an hour while tended (`tended`).

The system `justice` keeps who is in custody, the deeds judged, what each theft or poaching took (from its event, the
`on_event` hook) and the health each running tend has given.
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from functools import cache
from typing import Literal, cast

from pydantic import JsonValue, TypeAdapter

from app.observability.events import (
    Accused,
    Confined,
    EventDraft,
    ItemLocation,
    Judged,
    Released,
    Seized,
    SentenceServed,
    Stole,
    Target,
    Tended,
    Trespassed,
)
from app.sim import slots, society, tax
from app.sim.acting import begin, capital, refuse, settled
from app.sim.citizens import store_ids
from app.sim.clock import TICKS_PER_HOUR
from app.sim.coins import number_words, price_words
from app.sim.core import HEARING_M, KEPT_HEARD, SimCore
from app.sim.doing import apply_partial
from app.sim.economy import value_of
from app.sim.items import tool_in
from app.sim.ownership import CAMP_GROUPS, CHEST, KEEP
from app.sim.perception import match_person, normalize, person_label
from app.sim.state import ActionState, Citizen, Heard, Region, System
from app.sim.vec import Vec3
from app.world.town import load_town
from app.world_api.models import Accuse, ActionName, ActionResult, Confinement, Fine, Judge, Seize, Tend

SEIZE_MINUTES = 1
SEIZE_REACH_M = 2.0
HELPER_M = 3.0  # an armed helper of the seizer's this close to the target adds to the chance
JUDGE_MINUTES = 15
JUDGE_REACH_M = 4.0
FIRE_COURT_M = 15.0  # a band leader judges within this far of the band's fire pit
TEND_MINUTES = 30
TEND_REACH_M = 2.0
TEND_PER_HOUR = 3.0
CUSTODY_HOURS = 12  # the gaol has water but no food
ARREARS_DAYS = 3  # days of `tax_overdue` running before the lord may fine a household's arrears
HEALING = "healing"
ARMS = "arms"
TREASURY = KEEP + CHEST
GAOL = "gaol"  # the place, and its seats in the slot layout
COURT_AREA = "castle-courtyard"  # the town area inside the castle walls, where the lord judges
HELD_MAY: frozenset[ActionName] = frozenset({"say", "wait", "set_goal", "recall"})  # (and look and check)
CONFINED_MAY: frozenset[ActionName] = HELD_MAY | {"drink", "eat", "sleep"}
CAMPS: dict[Region, str] = {group: camp for camp, group in CAMP_GROUPS.items()}
CustodyPlace = Literal["held", "gaol", "fire"]
PLACE_WORDS: dict[CustodyPlace, str] = {"held": "", "gaol": "the gaol", "fire": "the band's fire"}
Court = Literal["town", "band"]


@dataclass
class Custody:
    since: int  # the tick they were seized: custody ends this many CUSTODY_HOURS on at the latest
    keeper: str | None  # who holds them while held; None once confined
    place: CustodyPlace = "held"
    until: int | None = None  # a confinement sentence's last tick
    judgement: int | None = None  # the `judged` seq of the confinement being served


@dataclass(frozen=True)
class Loss:
    """What a theft or a poaching took, at its town value, and from whom."""

    owner: str  # the robbed household or group
    item: str
    mon: float


@dataclass
class Justice:
    custody: dict[str, Custody] = field(default_factory=dict)  # citizen -> their custody
    judged: list[int] = field(default_factory=list)  # deed seqs judged (sorted)
    losses: dict[int, Loss] = field(default_factory=dict)  # deed seq -> what it took
    tended: dict[str, float] = field(default_factory=dict)  # healer -> health given in their running tend


_BLOCK = TypeAdapter(Justice)


def _dump(justice: Justice) -> JsonValue:
    return cast(JsonValue, _BLOCK.dump_python(justice, mode="json"))


def _load(data: JsonValue) -> Justice:
    return _BLOCK.validate_python(data)


JUSTICE = System[Justice]("justice", 1, new=lambda _world: Justice(), dump=_dump, load=_load)


# --- what other systems read ---


def custody_of(core: SimCore, citizen_id: str) -> Custody | None:
    return JUSTICE.of(core.state).custody.get(citizen_id)


def in_custody(core: SimCore, citizen_id: str) -> bool:
    return citizen_id in JUSTICE.of(core.state).custody


def held_pairs(core: SimCore) -> list[tuple[str, str]]:
    """(held, seizer) for everyone held (not confined), by id."""
    return [
        (person, custody.keeper)
        for person, custody in sorted(JUSTICE.of(core.state).custody.items())
        if custody.keeper is not None
    ]


def leading(core: SimCore, keeper_id: str) -> str | None:
    """The person this citizen holds, if any."""
    return next((person for person, keeper in held_pairs(core) if keeper == keeper_id), None)


def restraint(core: SimCore, citizen: Citizen, kind: ActionName) -> str | None:
    """Why someone in custody may not do this (held: only look, speak, wait; confined: also drink, eat and sleep), or
    None when they may."""
    custody = custody_of(core, citizen.id)
    if custody is None:
        return None
    if custody.keeper is not None:
        if kind in HELD_MAY:
            return None
        return f"{capital(person_label(citizen, core.state.citizens[custody.keeper]))} holds you fast."
    if kind in CONFINED_MAY:
        return None
    return "You are confined in the gaol." if custody.place == "gaol" else "You are tied at the fire."


def on_event(core: SimCore, event: EventDraft) -> None:
    """Event hook: what each theft and poaching took, so a fine can pay it back."""
    payload = event.payload
    if isinstance(payload, Stole):
        loss = Loss(payload.owner, payload.item, payload.count * value_of(payload.item, "town"))
    elif isinstance(payload, Trespassed) and payload.took is not None:
        took = payload.took
        loss = Loss(payload.owner, took.item, took.count * value_of(took.item, "town"))
    else:
        return
    JUSTICE.of(core.state).losses[event.seq] = loss


# --- accuse ---


def accuse(core: SimCore, citizen: Citizen, action: Accuse) -> ActionResult:
    to = match_person(core, citizen, action.to)
    if to is None:
        return refuse(core, citizen, "accuse", "You don't see anyone like that.")
    told = person_label(citizen, to)
    if core.distance_m(citizen.position, to.position) > HEARING_M["normal"]:
        return refuse(core, citizen, "accuse", f"{capital(told)} is too far away to hear you.")
    if to.body.asleep:
        return refuse(core, citizen, "accuse", f"{capital(told)} is asleep.")
    person = _named(core, citizen, action.person)
    if person is None or person.id == citizen.id:
        return refuse(core, citizen, "accuse", "You don't know anyone like that.")
    label = person_label(citizen, person)
    if person.id == to.id:
        return refuse(core, citizen, "accuse", f"You can't accuse {label} before themselves.")
    deeds = [deed for deed in society.known_deeds(core, citizen.id) if deed.doer == person.id]
    if not deeds:
        return refuse(core, citizen, "accuse", f"You know of no wrong done by {label}.")
    seq = core.emit("accused", Accused(person=person.id, to=to.id, deeds=[deed.seq for deed in deeds]), actor=citizen)
    words = f"{person.name} {_deeds_words(core, deeds)}."
    who = person_label(to, citizen)
    to.heard.append(Heard(core.state.tick, seq, citizen.id, who, words, "normal", citizen.position))
    del to.heard[:-KEPT_HEARD]
    return ActionResult(action="accuse", outcome="done", text=f'You tell {told}: "{words}"')


def _named(core: SimCore, citizen: Citizen, who: str) -> Citizen | None:
    """Someone the citizen knows by that name (seen or not), else someone in view like that."""
    query = normalize(who)
    for person_id in sorted(citizen.people):
        person = core.state.citizens.get(person_id)
        if person is not None and query and query == normalize(person.name):
            return person
    return match_person(core, citizen, who)


def _deeds_words(core: SimCore, deeds: list[society.Deed]) -> str:
    """What the deeds were, as said aloud ("stole rice and trespassed at night")."""
    losses = JUSTICE.of(core.state).losses
    said: list[str] = []
    for deed in deeds:
        loss = losses.get(deed.seq)
        victim = core.state.citizens[deed.victim].name if deed.victim is not None else "someone"
        words = {
            "theft": f"stole {loss.item if loss else 'something'}",
            "poaching": f"poached {loss.item if loss else 'game'}",
            "trespass": "trespassed at night",
            "assault": f"struck {victim}",
            "killing": f"killed {victim}",
        }[deed.kind]
        if words not in said:
            said.append(words)
    return said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]


# --- seize ---


def start_seize(core: SimCore, citizen: Citizen, action: Seize) -> int:
    person = match_person(core, citizen, action.person)
    why = _cannot_seize(core, citizen, person)
    if why is not None or person is None:
        return settled(core, citizen, "seize", "failed", why or "")
    seize = begin(
        core,
        citizen,
        "seize",
        person.name,
        {"person": person.id},
        destination=person_label(citizen, person),
        target=_target(person),
    )
    seize.target_id, seize.until_tick = person.id, core.state.tick + SEIZE_MINUTES
    return seize.number


def finish_seize(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    person = core.state.citizens[str(action.target_id)]
    why = _cannot_seize(core, citizen, person if person.body.alive else None)
    if why is not None:
        core.end_action(citizen, "failed", why)
        return
    label, seizer = person_label(citizen, person), capital(person_label(person, citizen))
    helpers = _helpers(core, citizen, person)
    held = core.state.rng("justice.seize").random() < seize_chance(citizen, person, len(helpers))
    seq = core.emit("seized", Seized(person=person.id, held=held, helpers=helpers), actor=citizen)
    if not held:
        _stop(core, person, f"{seizer} tries to seize you!", seq)
        core.end_action(citizen, "failed", f"{capital(label)} twists free of your grip.")
        return
    prisoner = leading(core, person.id)
    if prisoner is not None:  # a seizer seized lets go of whoever they held
        _release(core, core.state.citizens[prisoner], "seizer_down", person.id, seq)
    JUSTICE.of(core.state).custody[person.id] = Custody(since=core.state.tick, keeper=citizen.id)
    slots.release(core, person)
    _stop(core, person, f"{seizer} seizes you; you are held fast.", seq)
    core.end_action(citizen, "done", f"You seize {label}; you hold them fast.")


def seize_chance(seizer: Citizen, target: Citizen, armed_helpers: int) -> float:
    """§3.4: clamp(0.5 + 0.3·(armed_s − armed_t) + 0.3·(str_s − str_t) + 0.2 per armed helper, 0.1, 0.95)."""
    chance = 0.5 + 0.3 * (_armed(seizer) - _armed(target))
    chance += 0.3 * (seizer.traits.strength - target.traits.strength) + 0.2 * armed_helpers
    return min(0.95, max(0.1, chance))


def _armed(citizen: Citizen) -> int:
    return int(ARMS in citizen.skills or tool_in(citizen.inventory, "spear") is not None)


def _helpers(core: SimCore, seizer: Citizen, target: Citizen) -> list[str]:
    """Armed people of the seizer's group, awake and free, within HELPER_M of the target."""
    group = society.group_of(core, seizer.id)
    return [
        other.id
        for other in core.living()
        if other.id not in (seizer.id, target.id)
        and not other.body.asleep
        and not in_custody(core, other.id)
        and society.group_of(core, other.id) == group
        and _armed(other)
        and core.distance_m(other.position, target.position) <= HELPER_M
    ]


def _cannot_seize(core: SimCore, seizer: Citizen, person: Citizen | None) -> str | None:
    if person is None:
        return "You don't see anyone like that."
    label = person_label(seizer, person)
    if person.id == seizer.id:
        return "You can't seize yourself."
    if person.group == "child":
        return "You can't seize a child."
    if in_custody(core, person.id):
        return f"{capital(label)} is held already."
    if leading(core, seizer.id) is not None:
        return "You already hold someone."
    if slots.is_inside(core, person) or core.distance_m(seizer.position, person.position) > SEIZE_REACH_M:
        return f"{capital(label)} is out of your reach."
    return None


def _stop(core: SimCore, person: Citizen, text: str, cause_seq: int) -> None:
    """Interrupt what the person is doing (a sleeper wakes)."""
    action = person.action
    if action is None:
        return
    apply_partial(core, person, action)
    if person.body.alive:
        core.end_action(person, "interrupted", text, cause_seq)


def _target(person: Citizen) -> Target:
    return Target(kind="person", id=person.id, name=person.name, position=person.position)


# --- custody: confining, serving, releasing ---


def custody_ends(custody: Custody) -> int:
    """The last tick of a custody: its 12 h from the seizure, sooner if a confinement sentence ends before."""
    cap = custody.since + CUSTODY_HOURS * TICKS_PER_HOUR
    return cap if custody.until is None else min(cap, custody.until)


def keep_custody(core: SimCore) -> None:
    """Every-tick hook: custody ends when they die (`released` died), when the seizer is hurt, asleep, dead or in
    custody themselves (seizer_down), when a confinement sentence is served (`sentence_served`, then `released`
    judged), or after its 12 h (timeout)."""
    justice = JUSTICE.of(core.state)
    for person_id, custody in sorted(justice.custody.items()):
        person = core.state.citizens[person_id]
        if not person.body.alive:
            _release(core, person, "died", None)
            continue
        if custody.keeper is not None:
            keeper = core.state.citizens[custody.keeper]
            if not keeper.body.alive or keeper.body.asleep or keeper.id in core.hurt or in_custody(core, keeper.id):
                _release(core, person, "seizer_down", keeper.id)
                continue
        if core.state.tick < custody_ends(custody):
            continue
        if custody.judgement is not None:
            served = SentenceServed(sentence="confine", judgement=custody.judgement)
            core.emit("sentence_served", served, actor=person, cause_seq=custody.judgement)
            _release(core, person, "judged", None, custody.judgement)
        else:
            _release(core, person, "timeout", None)


def lock_up(core: SimCore) -> None:
    """Tick-end hook (after the held are led): someone held who stands in the gaol takes a free seat there and is
    confined (`confined`), until judged or their custody's 12 h are up; nobody held when the gaol is full."""
    gaol = core.world.places[GAOL]
    for person_id, keeper in held_pairs(core):
        person = core.state.citizens[person_id]
        if core.distance_m(person.position, gaol.centre) <= gaol.radius_m and _into_gaol(core, person):
            custody = JUSTICE.of(core.state).custody[person_id]
            custody.keeper, custody.place = None, "gaol"
            confined = Confined(place=PLACE_WORDS["gaol"], until_tick=custody_ends(custody), by=keeper)
            core.emit("confined", confined, actor=person)


def _gaol_seats(core: SimCore) -> tuple[slots.Slot, ...]:
    return slots.layout(core).places.get(GAOL, ())


def _gaol_free(core: SimCore, person: Citizen) -> bool:
    taken = {claim.slot for citizen_id, claim in slots.slot_state(core).claims.items() if citizen_id != person.id}
    return any(seat.id not in taken for seat in _gaol_seats(core))


def _into_gaol(core: SimCore, person: Citizen) -> bool:
    """A free gaol seat for the person, stepped to now (or at the next tick's end); False when the gaol is full."""
    seat = slots.take_first_free(core, person, _gaol_seats(core))
    if seat is None:
        return False
    slots.step_to(core, person, seat.position, straight=True, far=True)
    return True


def _release(
    core: SimCore,
    person: Citizen,
    cause: Literal["judged", "timeout", "seizer_down", "died"],
    by: str | None,
    cause_seq: int | None = None,
) -> None:
    _end(core, person)
    core.emit("released", Released(cause=cause, by=by), actor=person, cause_seq=cause_seq)


def _end(core: SimCore, person: Citizen) -> None:
    custody = JUSTICE.of(core.state).custody.pop(person.id)
    if custody.place == "gaol":
        slots.release(core, person)


# --- judge ---


def start_judge(core: SimCore, citizen: Citizen, action: Judge) -> int:
    person = match_person(core, citizen, action.person)
    why = _cannot_judge(core, citizen, person, action.sentence)
    if why is not None or person is None:
        return settled(core, citizen, "judge", "failed", why or "")
    sentence = action.sentence
    amount = sentence.mon if isinstance(sentence, Fine) else sentence.hours
    judge = begin(
        core,
        citizen,
        "judge",
        person.name,
        {"person": person.id, "sentence": sentence.kind, "amount": amount},
        destination=person_label(citizen, person),
        target=_target(person),
    )
    judge.target_id, judge.item, judge.amount = person.id, sentence.kind, amount
    judge.until_tick = core.state.tick + JUDGE_MINUTES
    return judge.number


def finish_judge(core: SimCore, judge: Citizen, action: ActionState) -> None:
    person = core.state.citizens[str(action.target_id)]
    sentence = Fine(mon=action.amount) if action.item == "fine" else Confinement(hours=action.amount)
    why = _cannot_judge(core, judge, person if person.body.alive else None, sentence)
    if why is not None:
        core.end_action(judge, "failed", why)
        return
    court = cast(Court, _court(core, judge))
    deeds = _open_deeds(core, judge, person)
    label = person_label(judge, person)
    if isinstance(sentence, Fine):
        judged = Judged(person=person.id, sentence="fine", fine_mon=sentence.mon, deeds=deeds, arrears=not deeds)
        seq = core.emit("judged", judged, actor=judge)
        payees = _payees(core, court, judge, person, deeds)
        paid = _collect(core, person, sentence.mon, list(payees), seq)
        _repaid(core, payees)
        if not deeds and person.home is not None:
            tax.pay_by_fine(core, person, person.home, paid, seq)
        fined = f"You fine {label} {price_words(sentence.mon)}"
        if paid < sentence.mon:  # still in custody; the deeds are left open to a confinement
            core.end_action(judge, "done", f"{fined}; they can pay only {price_words(paid) if paid else 'nothing'}.")
            return
        _mark_judged(core, deeds)
        core.emit("sentence_served", SentenceServed(sentence="fine", judgement=seq), actor=person, cause_seq=seq)
        _release(core, person, "judged", judge.id, seq)
        core.end_action(judge, "done", f"{fined}; it is paid.")
        return
    custody = JUSTICE.of(core.state).custody[person.id]
    if custody.keeper is not None and court == "town" and not _into_gaol(core, person):
        core.end_action(judge, "failed", f"You can't get {label} into the gaol.")  # a seat free, but no way to it
        return
    judged = Judged(person=person.id, sentence="confine", confine_h=float(sentence.hours), deeds=deeds)
    seq = core.emit("judged", judged, actor=judge)
    _mark_judged(core, deeds)
    custody.until, custody.judgement = core.state.tick + sentence.hours * TICKS_PER_HOUR, seq
    if custody.keeper is not None:
        custody.keeper, custody.place = None, "gaol" if court == "town" else "fire"
        confined = Confined(place=PLACE_WORDS[custody.place], until_tick=custody_ends(custody), by=judge.id)
        core.emit("confined", confined, actor=person, cause_seq=seq)
    hours = "an hour" if sentence.hours == 1 else f"{number_words(sentence.hours)} hours"
    core.end_action(judge, "done", f"You sentence {label} to {hours} confined.")


def _cannot_judge(core: SimCore, judge: Citizen, person: Citizen | None, sentence: Fine | Confinement) -> str | None:
    if person is None:
        return "You don't see anyone like that."
    court = _court(core, judge)
    if court not in ("town", "band"):
        return court
    label = capital(person_label(judge, person))
    custody = custody_of(core, person.id)
    if custody is None or person.id == judge.id:
        return f"{label} isn't held."
    if core.distance_m(judge.position, person.position) > JUDGE_REACH_M:
        return f"{label} is too far away to judge."
    deeds = _open_deeds(core, judge, person)
    if not deeds and not (court == "town" and _overdue(core, person)):
        return f"You know of no wrong done by {person_label(judge, person)}."
    if isinstance(sentence, Confinement) and not deeds:
        return "Tax owed is paid in coin or rice, not in confinement."
    if isinstance(sentence, Confinement) and court == "town" and custody.keeper is not None:
        return None if _gaol_free(core, person) else "The gaol is full."
    return None


def _court(core: SimCore, judge: Citizen) -> str:
    """The court a judge sits in: "town" (the lord inside the castle walls), "band" (a leader by the band's fire
    pit), else why they can't judge."""
    titles = society.titles(core, judge.id)
    if "lord" in titles:
        return "town" if _in_castle(core, judge.position) else "You judge inside the castle walls."
    if "leader" in titles:
        camp = CAMPS.get(society.group_of(core, judge.id))
        pit = core.world.structures.get(f"{camp}:fire-pit") if camp is not None else None
        if pit is not None and core.distance_m(judge.position, pit.centre) <= FIRE_COURT_M:
            return "band"
        return "You judge by your band's fire."
    return "You have no right to judge anyone."


def _in_castle(core: SimCore, unit: Vec3) -> bool:
    point = core.world.town_point(unit)
    if point is None:
        return False
    x0, z0, x1, z1 = _court_rect()
    return x0 <= point[0] <= x1 and z0 <= point[1] <= z1


@cache
def _court_rect() -> tuple[float, float, float, float]:
    area = next(area for area in load_town().areas if area.id == COURT_AREA)
    xs, zs = [x for x, _ in area.polygon], [z for _, z in area.polygon]
    return (min(xs), min(zs), max(xs), max(zs))


def _open_deeds(core: SimCore, judge: Citizen, person: Citizen) -> list[int]:
    """The deeds of the person the judge knows of that nobody has judged yet."""
    judged = set(JUSTICE.of(core.state).judged)
    known = society.known_deeds(core, judge.id)
    return [deed.seq for deed in known if deed.doer == person.id and deed.seq not in judged]


def _overdue(core: SimCore, person: Citizen) -> bool:
    """Their household has owed tax past its time for ARREARS_DAYS local midnights running (§3.4: 3 days
    `tax_overdue`), still unpaid."""
    owed = tax.TAX.of(core.state).accounts.get(person.home or "")
    return owed is not None and owed.days >= ARREARS_DAYS and bool(owed.rice or owed.arrears)


def _mark_judged(core: SimCore, deeds: list[int]) -> None:
    justice = JUSTICE.of(core.state)
    justice.judged = sorted(set(justice.judged) | set(deeds))


# --- fines ---


@dataclass
class _Payee:
    where: ItemLocation
    share: float  # mon still owed to them
    deed: int | None = None  # the theft or poaching they are paid back for


def _payees(core: SimCore, court: Court, judge: Citizen, person: Citizen, deeds: list[int]) -> list[_Payee]:
    """Who a fine pays, in order: those the judged deeds robbed (what each took), then the rest: the treasury in
    town, the victim in a band (`_band_victim`)."""
    losses = JUSTICE.of(core.state).losses
    payees = [
        _Payee(where, losses[seq].mon, seq)
        for seq in deeds
        if seq in losses and (where := _victim(core, losses[seq].owner)) is not None
    ]
    if court == "town":
        rest = _store(TREASURY)
    else:
        rest = payees[0].where if payees else _band_victim(core, judge, person, deeds)
    return [*payees, _Payee(rest, math.inf)]


def _band_victim(core: SimCore, judge: Citizen, person: Citizen, deeds: list[int]) -> ItemLocation:
    """Who a band court's fine goes to when nothing was taken (§3.4: in bands, to the victim): the one struck, if
    alive, else the wronged group (a band's leader, the town's treasury), else the judge."""
    judged = [deed for deed in society.deeds_by(core, person.id) if deed.seq in deeds]
    for deed in judged:
        if deed.victim is not None and core.state.citizens[deed.victim].body.alive:
            return ItemLocation(kind="inventory", id=deed.victim)
    for deed in judged:
        if (where := _victim(core, deed.group)) is not None:
            return where
    return ItemLocation(kind="inventory", id=judge.id)


def _repaid(core: SimCore, payees: list[_Payee]) -> None:
    """What each robbed payee was paid comes off the loss, so a fine paid short and judged again (a fine left open)
    never pays anyone back twice."""
    losses = JUSTICE.of(core.state).losses
    for payee in payees:
        if payee.deed is not None:
            losses[payee.deed] = replace(losses[payee.deed], mon=max(0.0, payee.share))


def _victim(core: SimCore, owner: str) -> ItemLocation | None:
    """Where what a household or group lost is paid back: the household's chest, the treasury for the town and the
    lord's household, a band's leader."""
    if owner in ("town", KEEP):
        return _store(TREASURY)
    if owner in CAMPS:
        chief = society.leader(core, owner)
        return ItemLocation(kind="inventory", id=chief) if chief is not None else None
    chest = owner + CHEST
    return _store(chest) if chest in store_ids() else _store(TREASURY)


def _store(store_id: str) -> ItemLocation:
    return ItemLocation(kind="store", id=store_id)


def _sources(core: SimCore, person: Citizen) -> Iterator[tuple[ItemLocation, dict[str, int], str]]:
    """What a fine is taken from, in order: the purse's coins, the household chest's, then goods (by name) carried and
    in the chest."""
    purse = (ItemLocation(kind="inventory", id=person.id), person.inventory)
    chest_id = f"{person.home}{CHEST}" if person.home is not None else ""
    holders = [purse]
    if chest_id in store_ids():
        holders.append((_store(chest_id), core.state.stores.setdefault(chest_id, {})))
    for where, holder in holders:
        yield where, holder, "coins"
    for where, holder in holders:
        for item in sorted(item for item in holder if item != "coins" and value_of(item, "town") > 0):
            yield where, holder, item


def _collect(core: SimCore, person: Citizen, mon: int, payees: list[_Payee], cause_seq: int) -> int:
    """Take up to `mon` (goods at their town value, a last piece may go a little over) and pay it out in order:
    returns the mon paid (≤ `mon`). Coins only move between holders, so the money supply stays whole."""
    left = float(mon)
    for where, holder, item in _sources(core, person):
        unit = 1.0 if item == "coins" else value_of(item, "town")
        while left > 1e-9 and holder.get(item, 0) > 0:
            payee = payees[0]
            count = min(holder[item], math.ceil(min(payee.share, left) / unit - 1e-9))
            _move(core, person, holder, where, payee.where, item, count, cause_seq)
            left -= count * unit
            payee.share -= count * unit
            if payee.share <= 1e-9:
                payees.pop(0)
    return mon - math.ceil(max(0.0, left) - 1e-9)


def _move(
    core: SimCore,
    person: Citizen,
    holder: dict[str, int],
    source: ItemLocation,
    destination: ItemLocation,
    item: str,
    count: int,
    cause_seq: int,
) -> None:
    holder[item] -= count
    if holder[item] == 0:
        del holder[item]
    if destination.kind == "store":
        into = core.state.stores.setdefault(str(destination.id), {})
    else:
        into = core.state.citizens[str(destination.id)].inventory
    into[item] = into.get(item, 0) + count
    core.item_moved(person, item, count, source, destination, cause_seq=cause_seq)


# --- tend ---


def start_tend(core: SimCore, citizen: Citizen, action: Tend) -> int:
    person = match_person(core, citizen, action.person)
    why = _cannot_tend(core, citizen, person)
    if why is not None or person is None:
        return settled(core, citizen, "tend", "failed", why or "")
    tend = begin(
        core,
        citizen,
        "tend",
        person.name,
        {"person": person.id},
        destination=person_label(citizen, person),
        target=_target(person),
    )
    tend.target_id, tend.until_tick = person.id, core.state.tick + TEND_MINUTES
    JUSTICE.of(core.state).tended[citizen.id] = 0.0
    return tend.number


def advance_tend(core: SimCore, citizen: Citizen, action: ActionState) -> None:
    """Each minute the tended person gains TEND_PER_HOUR / 60 health (up to full); at the half hour's end `tended`."""
    person = core.state.citizens[str(action.target_id)]
    label = person_label(citizen, person)
    given = JUSTICE.of(core.state).tended
    if not person.body.alive or core.distance_m(citizen.position, person.position) > TEND_REACH_M:
        given.pop(citizen.id, None)
        core.end_action(citizen, "interrupted", f"You stop tending: {label} is out of your reach.")
        return
    gain = min(TEND_PER_HOUR / TICKS_PER_HOUR, 100.0 - person.body.health)
    person.body.health += gain
    given[citizen.id] = given.get(citizen.id, 0.0) + gain
    if action.until_tick is None or core.state.tick < action.until_tick:
        return
    health = given.pop(citizen.id)
    core.emit("tended", Tended(person=person.id, health=round(health, 2)), actor=citizen)
    core.end_action(citizen, "done", f"You tend {label}; they look a little better.")


def _cannot_tend(core: SimCore, healer: Citizen, person: Citizen | None) -> str | None:
    if person is None:
        return "You don't see anyone like that."
    if person.id == healer.id:
        return "You can't tend yourself."
    if HEALING not in healer.skills:
        return "You don't know how to tend the hurt."
    label = capital(person_label(healer, person))
    if core.distance_m(healer.position, person.position) > TEND_REACH_M:
        return f"{label} is out of your reach."
    if person.body.health >= 100.0:
        return f"{label} isn't hurt."
    return None
