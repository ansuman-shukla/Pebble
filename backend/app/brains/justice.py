"""The witness and culprit rules every brain follows (10 §3.3-3.4), read from the perception's words.

A witness who sees someone known for a wrong (their `regard` names the deed: "who stole rice from the racks") shouts
it out once and brings it to the nearest officer in view (the lord, a samurai, an ashigaru, a band leader): walks up
to them and accuses. Someone wanted (`you.wanted`) runs home when an officer comes into view. Officers themselves
seize instead (the town's and bands' own brains). Until the systems behind those words land the fields are unset and
the rules never fire.

```
 a person seen "who stole …" ─▶ shout it (once) ─▶ officer in view? ── beside ─▶ accuse ─▶ done
                                                        │ further off ─▶ walk up to them
 you are wanted ─▶ officer in view ─▶ run home
```
"""

from pydantic import JsonValue

from app.brains.routines import Context, Option
from app.brains.senses import at_home, beside
from app.world_api.facade import ActionHandle
from app.world_api.models import Seen

WITNESS = 120.0  # over the day's work and meals, under thirst, hunger and danger at their worst
CULPRIT = 150.0  # over everything but a predator at hand


def known_deed(person: Seen) -> str | None:
    """The wrong a person is known for, from what you know of them ("well regarded, who stole rice" -> "stole rice")."""
    regard = person.regard or ""
    start = regard.find("who ")
    return regard[start + len("who ") :] if start >= 0 else None


def first_person(deed: str) -> str:
    """A wrong done to the one who shouts it, as they shout it ("struck you" -> "struck me", "your chest" -> "my
    chest"): the words a look gives are said to the looker."""
    return " ".join({"you": "me", "your": "my"}.get(word, word) for word in deed.split(" "))


def options(ctx: Context) -> list[Option]:
    return _culprit(ctx) or _witness(ctx)


def _officers(ctx: Context, but: str = "") -> list[Seen]:
    """Officers in view and awake, nearest first (people are seen nearest first)."""
    return [
        person
        for person in ctx.perception.people
        if ctx.profile.officer(person.label) and person.label != but and person.doing != "asleep"
    ]


def _culprit(ctx: Context) -> list[Option]:
    p = ctx.perception
    officers = _officers(ctx)
    if not p.you.wanted or not officers or at_home(p):
        return []
    home = lambda: ctx.api.walk_to_place("home", "run")  # noqa: E731  # a tiny closure reads best inline
    return [Option(CULPRIT, "run home", home, f"Get away from {officers[0].label}", "danger")]


def _witness(ctx: Context) -> list[Option]:
    """Shout out a wrong seen in someone (once each), then bring it to an officer; the accusation waits for one."""
    if ctx.profile.titles:
        return []  # officers seize the wrongdoer themselves
    notes = ctx.notes
    known = notes.setdefault("deeds", [])  # [who, deed] seen and shouted out
    pending = notes.setdefault("to accuse", [])  # [who, deed] not yet brought to an officer
    if not isinstance(known, list) or not isinstance(pending, list):
        raise TypeError("deeds and to accuse must be lists")
    for person in ctx.perception.people:
        deed = known_deed(person)
        if deed is not None and [person.label, deed] not in known:
            seen: list[JsonValue] = [person.label, deed]

            def shout(entry: list[JsonValue] = seen) -> ActionHandle:
                known.append(entry)
                pending.append(entry)
                ctx.api.say(f"{entry[0]} {first_person(str(entry[1]))}!", "shout")
                return ctx.api.wait(1)

            return [Option(WITNESS, f"shout about {person.label}", shout, f"Make known what {person.label} did")]
    if not pending:
        return []
    first = pending[0]
    if not isinstance(first, list):
        raise TypeError("each one to accuse is [who, deed]")
    culprit = str(first[0])
    officers = _officers(ctx, but=culprit)
    if not officers:
        return []
    officer = officers[0]
    aim = f"Tell {officer.label} what {culprit} did"
    if not beside(officer):
        return [Option(WITNESS, f"go to {officer.label}", lambda: ctx.api.walk_to_person(officer.label), aim)]

    def accuse() -> ActionHandle:
        ctx.api.accuse(culprit, officer.label)
        pending.remove(first)
        return ctx.api.wait(2)

    return [Option(WITNESS, f"accuse {culprit}", accuse, aim)]
