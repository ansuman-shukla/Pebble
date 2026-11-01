"""Tending the hurt (10 §3.4: +3 health an hour while tended): a healer walks up to someone in view who looks hurt and
tends them, though not in the night; the monk tends anyone, a band's healers (Oru, Vesa) the people they know."""

from functools import partial

from app.brains.routines import WORK, Context, Option, _count_today, _then
from app.brains.senses import DISTANCE, is_name

TEND = WORK + 20  # the hurt are tended before the day's work (the monk's prayers)
TEND_TRIES = 6  # tends of one person a day before leaving them be
HURT_LOOKS = ("looking hurt", "looking near death")


def tend_the_hurt(ctx: Context, strangers: bool = True) -> list[Option]:
    """Tend someone in view who looks hurt, walking up to them first; `strangers`: anyone, else only those known by
    name."""
    if "healing" not in ctx.profile.skills or ctx.phase == "night":
        return []
    for person in ctx.perception.people:
        looks = person.doing or ""
        if not any(words in looks for words in HURT_LOOKS) or DISTANCE[person.nearness] == "far":
            continue
        if not (strangers or is_name(person.label)) or _count_today(ctx, f"tending {person.label}") >= TEND_TRIES:
            continue
        aim = f"Tend {person.label}, who is hurt" if is_name(person.label) else "Tend a stranger who is hurt"  # ≤ 80
        if person.nearness != "right beside you":
            return [Option(TEND, f"go up to {person.label}", partial(ctx.api.walk_to_person, person.label), aim)]
        tend = _then(partial(ctx.mark_done, f"tending {person.label}"), partial(ctx.api.tend, person.label))
        return [Option(TEND, "tend", tend, aim)]
    return []
