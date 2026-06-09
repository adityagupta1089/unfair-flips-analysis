"""Game state and core mathematical models."""

import math
from dataclasses import dataclass, field
from typing import NamedTuple

from .constants import (
    CONSECUTIVE_TARGET,
    INITIAL_HEADS_PROB, INITIAL_BASE_WORTH, INITIAL_COMBO_MULT, INITIAL_FLIP_DURATION,
    HEADS_COSTS, HEADS_DELTA, HEADS_MAX_LEVEL,
    FLIPTIME_COSTS, FLIPTIME_DELTA, FLIPTIME_MAX_LEVEL,
    MULT_COSTS, MULT_DELTA, MULT_MAX_LEVEL,
    WORTH_COSTS, WORTH_VALUES, WORTH_MAX_LEVEL,
)


@dataclass(frozen=True)
class GameState:
    """Upgrade levels purchased so far (0 = no upgrade bought yet)."""
    heads_level: int = 0    # 0–8
    worth_level: int = 0    # 0–4
    mult_level: int = 0     # 0–5
    time_level: int = 0     # 0–5

    # --- Derived properties ---

    @property
    def heads_prob(self) -> float:
        return INITIAL_HEADS_PROB + self.heads_level * HEADS_DELTA

    @property
    def base_worth(self) -> int:
        return WORTH_VALUES[self.worth_level]

    @property
    def combo_mult(self) -> float:
        return INITIAL_COMBO_MULT + self.mult_level * MULT_DELTA

    @property
    def flip_duration(self) -> float:
        return INITIAL_FLIP_DURATION + self.time_level * FLIPTIME_DELTA

    # --- Next upgrade cost for each type (None if maxed) ---

    @property
    def next_heads_cost(self) -> int | None:
        return HEADS_COSTS[self.heads_level] if self.heads_level < HEADS_MAX_LEVEL else None

    @property
    def next_worth_cost(self) -> int | None:
        return WORTH_COSTS[self.worth_level] if self.worth_level < WORTH_MAX_LEVEL else None

    @property
    def next_mult_cost(self) -> int | None:
        return MULT_COSTS[self.mult_level] if self.mult_level < MULT_MAX_LEVEL else None

    @property
    def next_time_cost(self) -> int | None:
        return FLIPTIME_COSTS[self.time_level] if self.time_level < FLIPTIME_MAX_LEVEL else None

    # --- Transitions ---

    def buy_heads(self) -> "GameState":
        assert self.heads_level < HEADS_MAX_LEVEL
        return GameState(self.heads_level + 1, self.worth_level, self.mult_level, self.time_level)

    def buy_worth(self) -> "GameState":
        assert self.worth_level < WORTH_MAX_LEVEL
        return GameState(self.heads_level, self.worth_level + 1, self.mult_level, self.time_level)

    def buy_mult(self) -> "GameState":
        assert self.mult_level < MULT_MAX_LEVEL
        return GameState(self.heads_level, self.worth_level, self.mult_level + 1, self.time_level)

    def buy_time(self) -> "GameState":
        assert self.time_level < FLIPTIME_MAX_LEVEL
        return GameState(self.heads_level, self.worth_level, self.mult_level, self.time_level + 1)

    def label(self) -> str:
        return (f"p={self.heads_prob:.0%} base={self.base_worth}¢ "
                f"mult={self.combo_mult:.1f}x flip={self.flip_duration:.1f}s")


def head_earning(k: int, base_worth: int, combo_mult: float) -> int:
    """Money earned (cents) for the kth consecutive head (1-indexed)."""
    return base_worth * math.ceil(combo_mult ** (k - 1))


def expected_flips_to_win(p: float, n: int = CONSECUTIVE_TARGET) -> float:
    """
    Expected number of flips to get n consecutive heads.

    Standard formula: E = sum_{k=1}^{n} (1/p)^k
    Derived by solving the Markov chain on streak states 0..n-1.
    """
    inv_p = 1.0 / p
    return sum(inv_p ** k for k in range(1, n + 1))


def win_prob_per_attempt(p: float, n: int = CONSECUTIVE_TARGET) -> float:
    """Probability of winning (n consecutive heads) in a single uninterrupted run."""
    return p ** n


def expected_earning_per_attempt(
    p: float, base_worth: int, combo_mult: float, n: int = CONSECUTIVE_TARGET
) -> float:
    """
    Expected cents earned in one 'attempt' (a run until tails or win).

    P(exactly k heads then tails) = p^k * (1-p)  for k = 0..n-1
    P(n consecutive heads, win)   = p^n
    """
    total = 0.0
    for k in range(n):
        prob = (p ** k) * (1 - p)
        total += prob * sum(head_earning(j, base_worth, combo_mult) for j in range(1, k + 1))
    # Win case
    total += (p ** n) * sum(head_earning(j, base_worth, combo_mult) for j in range(1, n + 1))
    return total


def expected_flips_per_attempt(p: float, n: int = CONSECUTIVE_TARGET) -> float:
    """Expected number of flips in one attempt."""
    total = 0.0
    for k in range(n):
        prob = (p ** k) * (1 - p)
        total += prob * (k + 1)
    total += (p ** n) * n
    return total


def expected_earning_per_flip(
    p: float, base_worth: int, combo_mult: float, n: int = CONSECUTIVE_TARGET
) -> float:
    """Expected cents earned per flip in steady state."""
    return expected_earning_per_attempt(p, base_worth, combo_mult, n) / expected_flips_per_attempt(p, n)


def flips_to_earn(cost_cents: int, earning_per_flip: float) -> float:
    """Expected flips needed to accumulate enough money for an upgrade."""
    if earning_per_flip <= 0:
        return math.inf
    return cost_cents / earning_per_flip


def win_prob_distribution(p: float, n: int = CONSECUTIVE_TARGET):
    """
    Returns (p_win_per_attempt, expected_attempts_to_win).
    The number of attempts until win ~ Geometric(p^n).
    """
    pw = win_prob_per_attempt(p, n)
    return pw, 1.0 / pw


def percentile_flips(p: float, pct: float, n: int = CONSECUTIVE_TARGET) -> float:
    """
    The pct-th percentile of the number of flips to win, approximated using
    the geometric distribution on attempts.

    Number of winning attempts ~ Geometric(pw) => CDF P(A <= a) = 1-(1-pw)^a
    => a_pct = ceil(log(1-pct) / log(1-pw))
    Each non-winning attempt has mean length flips_per_attempt.
    The final winning attempt has exactly n flips.

    We approximate total flips ~ a_pct * mean_attempt_length.
    """
    pw = win_prob_per_attempt(p, n)
    if pw >= 1.0:
        return float(n)
    mean_attempt = expected_flips_per_attempt(p, n)
    # Number of attempts until first win: geometric
    a_pct = math.ceil(math.log(1 - pct) / math.log(1 - pw))
    # Total flips: (a_pct - 1) non-winning attempts + 1 winning attempt of n flips
    return (a_pct - 1) * mean_attempt + n
