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
