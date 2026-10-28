"""Seeded random numbers for the simulation: one stream per subsystem, the whole state is one integer.

SplitMix64 in pure Python: the same numbers on every platform and Python/numpy version, cheap to snapshot.
"""

import hashlib

_MASK = (1 << 64) - 1


class Rng:
    def __init__(self, state: int) -> None:
        self.state = state & _MASK

    @classmethod
    def for_subsystem(cls, seed: int, subsystem: str) -> "Rng":
        digest = hashlib.sha256(f"{seed}:{subsystem}".encode()).digest()
        return cls(int.from_bytes(digest[:8], "little"))

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & _MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def random(self) -> float:
        """Uniform in [0, 1)."""
        return (self.next_u64() >> 11) / float(1 << 53)

    def randint(self, low: int, high: int) -> int:
        """Uniform integer in [low, high] (both included); the modulo bias is below 1e-17 for small ranges."""
        if high < low:
            raise ValueError(f"empty range [{low}, {high}]")
        return low + self.next_u64() % (high - low + 1)
