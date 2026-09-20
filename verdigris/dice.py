"""
dice.py -- Core randomness and task resolution.

DESIGN NOTE
-----------
The resolution system here is an original implementation of a conventional
"attribute + skill + die vs. difficulty" check, a structure common to a great
many tabletop systems. Nothing in this module is transcribed from any
published rulebook; the specific numbers, band names and exploding-die
behaviour below are chosen for this game.

THE CHECK
    total = d10 + attribute + skill + situational_modifier
    success if total >= DV (Difficulty Value)

SWING DICE
    A natural 10 rolls again and adds (uncapped).
    A natural 1 rolls again and subtracts.
    This gives a long-tailed distribution: a desperate character can
    occasionally beat a wall, and a competent one can occasionally faceplant.
    Thematically this is the "street luck" the setting runs on.

MARGIN
    Degree of success matters everywhere in this codebase -- damage bonuses,
    how much intel an interrogation yields, how far a netrun trace advances.
    Callers should read Check.margin, not just Check.success.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


# --------------------------------------------------------------------------
# Difficulty bands
# --------------------------------------------------------------------------
# Referenced by name throughout the codebase so tuning happens in one place.
# Calibration note: a competent-but-unspecialised character (attribute 5,
# skill 3) averages 13.5 on the roll. "routine" is set at 12 so that such a
# character clears it around 70% of the time, and a specialist (attribute 8,
# skill 4) clears it nearly always. Every other band is spaced 3 apart from
# there, widening at the top so "severe" and "nightmare" stay out of reach
# without either heavy investment or a lucky swing.
DV = {
    "trivial": 7,
    "easy": 9,
    "routine": 12,
    "tricky": 15,
    "hard": 18,
    "severe": 22,
    "nightmare": 26,
}


def dv(band: str) -> int:
    """Look up a difficulty value by band name."""
    try:
        return DV[band]
    except KeyError:
        raise KeyError(f"unknown difficulty band {band!r}; expected one of {sorted(DV)}")


# --------------------------------------------------------------------------
# Result object
# --------------------------------------------------------------------------
@dataclass
class Check:
    """The outcome of a single resolution roll."""

    total: int
    dv: int
    raw: int                       # the die result after swings
    swings: list[int] = field(default_factory=list)
    modifiers: dict[str, int] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.total >= self.dv

    @property
    def margin(self) -> int:
        """Positive on success, negative on failure. Magnitude = degree."""
        return self.total - self.dv

    @property
    def critical(self) -> bool:
        """Exceptional success: swung upward AND cleared the bar by 5+."""
        return self.success and self.raw > 10 and self.margin >= 5

    @property
    def fumble(self) -> bool:
        """Exceptional failure: swung downward AND missed by 5+."""
        return not self.success and self.raw < 1 and self.margin <= -5

    def describe(self) -> str:
        mods = " ".join(
            f"{k}{v:+d}" for k, v in self.modifiers.items() if v
        )
        tag = ""
        if self.critical:
            tag = "  [CRITICAL]"
        elif self.fumble:
            tag = "  [FUMBLE]"
        verdict = "SUCCESS" if self.success else "FAILURE"
        return (
            f"d10={self.raw} {mods} => {self.total} vs DV {self.dv}"
            f"  {verdict} (margin {self.margin:+d}){tag}"
        )


# --------------------------------------------------------------------------
# Core rollers
# --------------------------------------------------------------------------
class Dice:
    """
    Seedable RNG wrapper.

    Every subsystem takes a Dice instance rather than touching the `random`
    module directly, so a whole playthrough can be reproduced from one seed --
    essential for debugging procedural generation.
    """

    def __init__(self, seed: int | None = None):
        self.seed = seed
        self.rng = random.Random(seed)

    # -- primitives --------------------------------------------------------
    def d(self, sides: int, count: int = 1) -> int:
        return sum(self.rng.randint(1, sides) for _ in range(count))

    def d6(self, count: int = 1) -> int:
        return self.d(6, count)

    def d10(self, count: int = 1) -> int:
        return self.d(10, count)

    def swing_d10(self, max_swings: int = 6) -> tuple[int, list[int]]:
        """
        Roll d10 with exploding 10s and imploding 1s.

        Returns (net_value, list_of_individual_rolls).
        max_swings caps runaway chains so a pathological seed can't hang.
        """
        rolls = [self.rng.randint(1, 10)]
        value = rolls[0]

        if rolls[0] == 10:
            while len(rolls) <= max_swings:
                nxt = self.rng.randint(1, 10)
                rolls.append(nxt)
                value += nxt
                if nxt != 10:
                    break
        elif rolls[0] == 1:
            while len(rolls) <= max_swings:
                nxt = self.rng.randint(1, 10)
                rolls.append(nxt)
                value -= nxt
                if nxt != 10:
                    break

        return value, rolls

    # -- selection helpers -------------------------------------------------
    def pick(self, seq: Sequence[T]) -> T:
        return self.rng.choice(seq)

    def sample(self, seq: Sequence[T], k: int) -> list[T]:
        k = max(0, min(k, len(seq)))
        return self.rng.sample(list(seq), k)

    def shuffled(self, seq: Iterable[T]) -> list[T]:
        items = list(seq)
        self.rng.shuffle(items)
        return items

    def chance(self, probability: float) -> bool:
        """probability in [0.0, 1.0]"""
        return self.rng.random() < probability

    def between(self, lo: int, hi: int) -> int:
        return self.rng.randint(lo, hi)

    def weighted(self, table: dict[T, float]) -> T:
        """
        Weighted selection from {option: weight}.

        This is the workhorse behind every loot table, encounter table and
        location-feature roll in the procedural generator. Weights need not
        sum to 1; they are normalised here.
        """
        if not table:
            raise ValueError("cannot select from an empty weight table")
        options = list(table.keys())
        weights = [max(0.0, float(table[o])) for o in options]
        if sum(weights) <= 0:
            return self.pick(options)
        return self.rng.choices(options, weights=weights, k=1)[0]

    def weighted_many(self, table: dict[T, float], k: int) -> list[T]:
        """k independent weighted draws (with replacement)."""
        return [self.weighted(table) for _ in range(k)]

    def spawn(self, salt: str) -> "Dice":
        """
        Derive a deterministic child RNG.

        Used so that, e.g., regenerating a location's loot doesn't perturb the
        global stream and desync everything downstream of it.
        """
        base = self.seed if self.seed is not None else 0
        return Dice(hash((base, salt)) & 0xFFFFFFFF)

    # -- the main event ----------------------------------------------------
    def check(
        self,
        attribute: int = 0,
        skill: int = 0,
        difficulty: int | str = "routine",
        **modifiers: int,
    ) -> Check:
        """
        Run a standard resolution check.

        Example:
            d.check(attribute=char.ref, skill=char.skill("firearms"),
                    difficulty="tricky", cover=-2, aimed=+1)
        """
        target = dv(difficulty) if isinstance(difficulty, str) else int(difficulty)
        raw, swings = self.swing_d10()

        mods = {"attr": attribute, "skill": skill}
        mods.update({k: int(v) for k, v in modifiers.items()})

        total = raw + sum(mods.values())
        return Check(total=total, dv=target, raw=raw, swings=swings, modifiers=mods)

    def opposed(
        self,
        a_attr: int, a_skill: int,
        b_attr: int, b_skill: int,
        **modifiers: int,
    ) -> tuple[bool, int]:
        """
        Opposed check: attacker vs. defender.

        Returns (attacker_wins, margin). Ties go to the defender, which keeps
        stealth and social conflict slightly hostile to the aggressor.
        """
        a_raw, _ = self.swing_d10()
        b_raw, _ = self.swing_d10()
        a_total = a_raw + a_attr + a_skill + sum(modifiers.values())
        b_total = b_raw + b_attr + b_skill
        return (a_total > b_total, a_total - b_total)


# A module-level default for callers that genuinely don't care about
# reproducibility (UI flavour text, cosmetic choices).
default_dice = Dice()
