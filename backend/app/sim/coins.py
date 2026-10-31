"""The mon (10-world-v1 §2.1): how a holder says the coins they count.

Coin counts are in-world knowledge (D63 bans ids and ranges, not what a person can count): a few coins are counted
one by one, more are strung on a cord by the hundred.
"""

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen".split()
_ONES += "seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
STRING = 100  # coins on a string


def number_words(n: int) -> str:
    """1-99 in words ("seven", "twenty-one"); larger numbers in digits."""
    if not 0 < n < 100:
        return str(n)
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def coin_words(count: int) -> str:
    """ "a coin", "seven coins" (2-12), "a short string of coins" (13-99), "a string of coins", "two strings of
    coins" (by the hundred, rounded down)."""
    if count <= 0:
        return "no coins"
    if count == 1:
        return "a coin"
    if count <= 12:
        return f"{number_words(count)} coins"
    if count < STRING:
        return "a short string of coins"
    strings = count // STRING
    return "a string of coins" if strings == 1 else f"{number_words(strings)} strings of coins"


def count_in_words(n: int) -> str:
    """1-9 999 spelled out, as a price is counted coin by coin ("a hundred and twelve", "two thousand and fifteen")."""
    if not 0 < n < 10_000:
        raise ValueError(f"{n} is not a count from 1 to 9 999")
    thousands, rest = divmod(n, 1000)
    hundreds, below = divmod(rest, 100)
    parts = [f"{'a' if thousands == 1 else number_words(thousands)} thousand"] if thousands else []
    parts += [f"{'a' if hundreds == 1 else number_words(hundreds)} hundred"] if hundreds else []
    if below:
        return " ".join(parts) + (" and " if parts else "") + number_words(below)
    return " ".join(parts)


def price_words(count: int) -> str:
    """A price or a payment, every coin counted in words ("a coin", "seventeen coins", "a hundred and twelve coins")."""
    return "a coin" if count == 1 else f"{count_in_words(count)} coins"
