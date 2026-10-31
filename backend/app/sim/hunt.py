"""The hunt's numbers (10-world-v1 §4.6): stalk, sensing, pounce, the 1-D race and the strike, as pure functions of
the species table, so the live hunt (`animals.py`) and the bible's worked odds come from the same rules.

    stalk from stalk_m, closing at 0.6 × walk, one 10 s sub-step at a time:
      gap ≤ pounce range ─▶ unseen: pounce (caught)
      else the prey notices: always inside its "always senses" gap, 30 % at ≤ 30 m, 15 % at 30-60 m
        noticed ─▶ race: each runs its burst for its burst seconds, then its sustained speed, for the race's length
                   (or until the prey reaches cover); caught iff the predator's run reaches gap + the prey's run
    caught ─▶ strike: the predator's strike chance × the prey's fight-back factor
"""

import math
from dataclasses import dataclass
from typing import Literal

from app.core.rng import Rng
from app.sim.fauna import SPECIES, Species

SUB_STEP_S = 10.0
STALK_SHARE = 0.6  # a stalker closes at this share of its walk
NOTICE = ((30.0, 0.30), (60.0, 0.15))  # (gap up to, chance a sub-step): nearer first
HUNTS_A_NIGHT = 4  # the worked odds' tries by a hungry predator group between dusk and dawn
Sensed = Literal["pounce", "noticed", "unseen"]


@dataclass(frozen=True)
class Dash:
    """A run: `burst_mps` for `burst_s` seconds, then `sustained_mps`, stopping after `room_m` (a cornered prey)."""

    burst_mps: float
    burst_s: float
    sustained_mps: float
    room_m: float = math.inf

    def metres(self, seconds: float) -> float:
        burst = min(seconds, self.burst_s)
        return min(self.room_m, burst * self.burst_mps + max(0.0, seconds - self.burst_s) * self.sustained_mps)

    def seconds_to(self, metres: float) -> float:
        """When the run has covered that far (inf if it never does)."""
        if metres > self.room_m + 1e-9:
            return math.inf
        burst_m = self.burst_s * self.burst_mps
        if metres <= burst_m:
            return metres / self.burst_mps
        return self.burst_s + (metres - burst_m) / self.sustained_mps if self.sustained_mps > 0 else math.inf

    def breaks(self) -> tuple[float, ...]:
        """The moments its speed changes."""
        stop = self.seconds_to(self.room_m) if math.isfinite(self.room_m) else math.inf
        return tuple(t for t in (self.burst_s, stop) if math.isfinite(t))


def dash(species: Species, winded: bool = False, room_m: float = math.inf) -> Dash:
    """How the species runs; a winded one (it ran its burst minutes ago) has only its sustained speed."""
    return Dash(species.trot_mps if winded else species.run_mps, species.burst_s, species.trot_mps, room_m)


def race_seconds(predator: Species, prey: Species) -> float:
    """How long a race can last: the predator's chase, cut short by the prey's cover."""
    return min(predator.race_s, prey.cover_s) if prey.cover_s else predator.race_s


def catch_time(predator: Dash, prey: Dash, gap_m: float, seconds: float) -> float | None:
    """The first moment within `seconds` the predator's run reaches the gap plus the prey's run, or None: both runs
    are piecewise straight, so the answer lies at a break or between two of them."""
    moments = sorted({0.0, seconds, *(t for t in (*predator.breaks(), *prey.breaks()) if 0 < t < seconds)})

    def lead(t: float) -> float:
        return predator.metres(t) - gap_m - prey.metres(t)

    if lead(0.0) >= 0:
        return 0.0
    for a, b in zip(moments, moments[1:], strict=False):
        before, after = lead(a), lead(b)
        if after >= 0:
            return a + (b - a) * -before / (after - before)
    return None


def largest_gap(predator: Species, prey: Species) -> float:
    """G*: the largest starting gap a noticed predator still closes (its greatest lead over the race)."""
    seconds = race_seconds(predator, prey)
    run, flight = dash(predator), dash(prey)
    moments = {0.0, seconds, *(t for t in (*run.breaks(), *flight.breaks()) if 0 < t < seconds)}
    return max(run.metres(t) - flight.metres(t) for t in moments)


def notice_chance(gap_m: float, prey: Species) -> float:
    """The chance a sub-step that the prey notices a stalker this far off."""
    if gap_m <= prey.senses_m:
        return 1.0
    return next((chance for limit, chance in NOTICE if gap_m <= limit), 0.0)


def stalk_step_m(predator: Species) -> float:
    """How far a stalker closes in a sub-step."""
    return STALK_SHARE * predator.walk_mps * SUB_STEP_S


def sense(gap_m: float, predator: Species, prey: Species, rng: Rng) -> Sensed:
    """One sub-step of a stalk at this gap: an unseen predator inside its pounce range pounces at once, otherwise
    the prey may notice it (one roll)."""
    if gap_m <= predator.pounce_m:
        return "pounce"
    chance = notice_chance(gap_m, prey)
    if chance >= 1.0 or (chance > 0 and rng.random() < chance):
        return "noticed"
    return "unseen"


def strike_chance(predator: Species, prey: Species) -> float:
    return predator.strike * prey.resists


def catch_odds(predator_kind: str, prey_kind: str) -> float:
    """P(caught) of one hunt that starts at the stalk distance: summed over the sub-step the prey notices it (caught
    iff that gap is within G*) or the pounce, by the rules of `sense`."""
    predator, prey = SPECIES[predator_kind], SPECIES[prey_kind]
    closes = largest_gap(predator, prey)
    gap, unseen, caught = predator.stalk_m, 1.0, 0.0
    while unseen > 0:
        if gap <= predator.pounce_m:
            return caught + unseen
        chance = notice_chance(gap, prey)
        if gap <= closes + 1e-9:
            caught += unseen * chance
        unseen *= 1.0 - chance
        gap -= stalk_step_m(predator)
    return caught


def kill_odds(predator_kind: str, prey_kind: str) -> float:
    return catch_odds(predator_kind, prey_kind) * strike_chance(SPECIES[predator_kind], SPECIES[prey_kind])


def kill_odds_a_night(predator_kind: str, prey_kind: str) -> float:
    return 1.0 - (1.0 - kill_odds(predator_kind, prey_kind)) ** HUNTS_A_NIGHT
