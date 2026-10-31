"""How what a citizen sees is said: the phrases a perception's text is made of (03-actions-perception).

Plain words in, plain words out, so the contract models and the senses share one way of saying things.
"""

from collections.abc import Iterable

NEAREST = "the nearest "  # starts the `where` of a group whose members are at different places


def phrase(label: str, where: str, doing: str | None) -> str:
    """One entry in words ("Oru a few paces to the south (resting)", "three lean-tos, the nearest close by …")."""
    joint = ", " if where.startswith(NEAREST) else " "
    return f"{label}{joint}{where}" + (f" ({doing})" if doing else "")


def phrases(entries: Iterable[tuple[str, str, str | None]]) -> list[str]:
    """Entries (label, where, doing) at the same place doing the same share one phrase ("Suna and Tek a few paces to
    the east (resting)")."""
    groups: list[tuple[str, str | None, list[str]]] = []
    for label, where, doing in entries:
        shared = not where.startswith(NEAREST)
        same = next((g for g in groups if shared and (g[0], g[1]) == (where, doing)), None)
        if same is None:
            groups.append((where, doing, [label]))
        else:
            same[2].append(label)
    return [phrase(join(labels), where, doing) for where, doing, labels in groups]


def join(parts: list[str]) -> str:
    """A list as said: "a", "a and b", "a, b and c"."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]
