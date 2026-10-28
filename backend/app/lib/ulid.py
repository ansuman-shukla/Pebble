"""ULIDs: 48-bit millisecond time + 80 random bits, Crockford base32, monotonic within one factory."""

import os
import time
from collections.abc import Callable

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_BITS = 80
_RANDOM_MASK = (1 << _RANDOM_BITS) - 1


def encode_ulid(milliseconds: int, randomness: int) -> str:
    if not 0 <= milliseconds < 1 << 48:
        raise ValueError(f"ULID time out of range: {milliseconds}")
    value = (milliseconds << _RANDOM_BITS) | (randomness & _RANDOM_MASK)
    return "".join(_ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5))


def ulid_milliseconds(ulid: str) -> int:
    value = 0
    for char in ulid:
        value = value * 32 + _ALPHABET.index(char)
    return value >> _RANDOM_BITS


class UlidFactory:
    """New ids sort after every earlier id of this factory, even within the same millisecond."""

    def __init__(
        self,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        entropy: Callable[[], int] = lambda: int.from_bytes(os.urandom(10), "big"),
    ) -> None:
        self._clock_ms = clock_ms
        self._entropy = entropy
        self._last_ms = -1
        self._last_random = 0

    def new(self) -> str:
        now = self._clock_ms()
        if now <= self._last_ms:
            now = self._last_ms
            self._last_random += 1
            if self._last_random > _RANDOM_MASK:
                raise OverflowError("too many ULIDs in one millisecond")
        else:
            self._last_ms = now
            self._last_random = self._entropy() & _RANDOM_MASK
        return encode_ulid(now, self._last_random)
