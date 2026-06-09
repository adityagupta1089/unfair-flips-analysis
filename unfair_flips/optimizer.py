"""
Enumerate all possible upgrade paths and find the optimal one under
different optimization criteria.

A 'path' is a sequence of upgrade purchases made before attempting to win.
Since upgrades within a type must be bought in order, the state space is:
  (heads_level, worth_level, mult_level)   [time_level handled separately]

For each path we compute the total expected cost:
  total_expected_flips = sum_over_upgrades(flips_to_earn_cost) + E[flips_to_win at final state]

We also compute percentile-based costs for worst-case / best-case strategy analysis.

Note: FlipTime upgrades reduce real seconds but not flip count, so they are
excluded from flip-count optimisation but included in a separate real-time
optimisation that uses (flips * flip_duration) as the cost metric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from .game import (
    GameState,
    expected_flips_to_win,
    expected_earning_per_flip,
    flips_to_earn,
    percentile_flips,
)
from .constants import (
    CONSECUTIVE_TARGET,
    HEADS_COSTS, HEADS_MAX_LEVEL,
    WORTH_COSTS, WORTH_MAX_LEVEL,
    MULT_COSTS, MULT_MAX_LEVEL,
    FLIPTIME_COSTS, FLIPTIME_MAX_LEVEL,
)


# ---------------------------------------------------------------------------
# Path representation
# ---------------------------------------------------------------------------

UPGRADE_NAMES = {
    "H": "HeadsChance +5%",
    "W": "FlipBaseWorth ↑",
    "M": "FlipMultiplier +0.5",
    "T": "FlipTime -0.2s",
}


@dataclass
class PathResult:
    state: GameState           # final state before going for win
    upgrades: list[str]        # sequence of upgrade codes ("H","W","M","T")
    total_expected_flips: float
    total_expected_time: float  # seconds (includes flip duration)
    p50_flips: float
    p95_flips: float
    p99_flips: float

    def summary(self) -> str:
        seq = " → ".join(self.upgrades) if self.upgrades else "(none)"
        return (f"[{seq}]\n"
                f"  Final: {self.state.label()}\n"
                f"  E[flips]={self.total_expected_flips:,.0f}  "
                f"P50={self.p50_flips:,.0f}  "
                f"P95={self.p95_flips:,.0f}  "
                f"P99={self.p99_flips:,.0f}\n"
                f"  E[time]={self.total_expected_time/3600:.1f}h")


# ---------------------------------------------------------------------------
# Core DP: find the optimal path minimizing a given cost metric
# ---------------------------------------------------------------------------

def _cost_metric(state: GameState, metric: str) -> float:
    """Terminal cost of winning from `state` under the chosen metric."""
    p = state.heads_prob
    if metric == "expected_flips":
        return expected_flips_to_win(p)
    if metric == "p50":
        return percentile_flips(p, 0.50)
    if metric == "p95":
        return percentile_flips(p, 0.95)
    if metric == "p99":
        return percentile_flips(p, 0.99)
    if metric == "expected_time":
        return expected_flips_to_win(p) * state.flip_duration
    raise ValueError(f"Unknown metric: {metric}")


def _transition_cost(
    state: GameState,
    next_state: GameState,
    upgrade_cost: int,
    metric: str,
) -> float:
    """
    Cost (in the metric's unit) of saving up for an upgrade from `state`
    then transitioning to `next_state`.
    """
    epf = expected_earning_per_flip(state.heads_prob, state.base_worth, state.combo_mult)
    f2e = flips_to_earn(upgrade_cost, epf)

    if metric == "expected_time":
        # Saving flips * duration
        return f2e * state.flip_duration
    # For all flip-count metrics, cost is just the flips spent earning money.
    # We approximate: during saving we might win, but we ignore that to keep
    # it tractable (conservative — slightly overestimates flip cost).
    return f2e


def dp_optimal_path(
    metric: str = "expected_flips",
    include_time_upgrades: bool = False,
    start: GameState = GameState(),
) -> PathResult:
    """
    Find the upgrade path minimising the total cost under `metric`.

    Uses memoised DFS over (heads_level, worth_level, mult_level[, time_level]).
    """

    @lru_cache(maxsize=None)
    def dp(h: int, w: int, m: int, t: int) -> tuple[float, list[str]]:
        """Returns (min_total_cost, upgrade_sequence) from this state."""
        state = GameState(h, w, m, t)
        # Option: stop upgrading and go for the win now
        best_cost = _cost_metric(state, metric)
        best_seq: list[str] = []

        epf = expected_earning_per_flip(state.heads_prob, state.base_worth, state.combo_mult)

        def try_upgrade(code: str, next_state: GameState, upgrade_cost: int) -> None:
            nonlocal best_cost, best_seq
            tc = _transition_cost(state, next_state, upgrade_cost, metric)
            future_cost, future_seq = dp(
                next_state.heads_level,
                next_state.worth_level,
                next_state.mult_level,
                next_state.time_level,
            )
            total = tc + future_cost
            if total < best_cost:
                best_cost = total
                best_seq = [code] + future_seq

        if h < HEADS_MAX_LEVEL:
            try_upgrade("H", state.buy_heads(), HEADS_COSTS[h])
        if w < WORTH_MAX_LEVEL:
            try_upgrade("W", state.buy_worth(), WORTH_COSTS[w])
        if m < MULT_MAX_LEVEL:
            try_upgrade("M", state.buy_mult(), MULT_COSTS[m])
        if include_time_upgrades and t < FLIPTIME_MAX_LEVEL:
            try_upgrade("T", state.buy_time(), FLIPTIME_COSTS[t])

        return best_cost, best_seq

    dp.cache_clear()
    _, seq = dp(start.heads_level, start.worth_level, start.mult_level, start.time_level)

    # Replay the path to compute full stats
    return _evaluate_path(seq, start)


# ---------------------------------------------------------------------------
# Evaluate any upgrade sequence and produce a PathResult
# ---------------------------------------------------------------------------

def _evaluate_path(upgrades: list[str], start: GameState = GameState()) -> PathResult:
    """Simulate a fixed upgrade sequence and compute all metrics."""
    state = start
    total_flips = 0.0
    total_time = 0.0

    for code in upgrades:
        epf = expected_earning_per_flip(state.heads_prob, state.base_worth, state.combo_mult)
        if code == "H":
            cost = HEADS_COSTS[state.heads_level]
            next_state = state.buy_heads()
        elif code == "W":
            cost = WORTH_COSTS[state.worth_level]
            next_state = state.buy_worth()
        elif code == "M":
            cost = MULT_COSTS[state.mult_level]
            next_state = state.buy_mult()
        elif code == "T":
            cost = FLIPTIME_COSTS[state.time_level]
            next_state = state.buy_time()
        else:
            raise ValueError(f"Unknown upgrade code: {code}")

        f2e = flips_to_earn(cost, epf)
        total_flips += f2e
        total_time += f2e * state.flip_duration
        state = next_state

    # Final win phase
    p = state.heads_prob
    win_flips = expected_flips_to_win(p)
    total_flips += win_flips
    total_time += win_flips * state.flip_duration

    return PathResult(
        state=state,
        upgrades=upgrades,
        total_expected_flips=total_flips,
        total_expected_time=total_time,
        p50_flips=total_flips - win_flips + percentile_flips(p, 0.50),
        p95_flips=total_flips - win_flips + percentile_flips(p, 0.95),
        p99_flips=total_flips - win_flips + percentile_flips(p, 0.99),
    )


# ---------------------------------------------------------------------------
# Enumerate ALL paths up to a budget cap and return ranked results
# ---------------------------------------------------------------------------

def enumerate_paths(
    max_upgrades: int | None = None,
    flip_budget: float = 1e10,
    start: GameState = GameState(),
) -> list[PathResult]:
    """
    Enumerate every valid upgrade sequence and return PathResult for each.

    A valid sequence respects the per-type ordering constraint (must buy
    level k before level k+1 within the same type).

    `max_upgrades` caps total upgrades per path (None = unlimited).
    `flip_budget` skips paths whose expected flips exceed this threshold.
    """
    results: list[PathResult] = []

    def dfs(
        state: GameState,
        seq: list[str],
        accumulated_flips: float,
    ) -> None:
        if max_upgrades is not None and len(seq) >= max_upgrades:
            # Terminal: evaluate and return
            result = _evaluate_path(seq, start)
            results.append(result)
            return

        # Always record the "stop here and win" option
        result = _evaluate_path(seq, start)
        results.append(result)

        # Try each upgrade
        epf = expected_earning_per_flip(state.heads_prob, state.base_worth, state.combo_mult)

        for code, next_state, cost in [
            ("H", state.buy_heads() if state.heads_level < HEADS_MAX_LEVEL else None,
             HEADS_COSTS[state.heads_level] if state.heads_level < HEADS_MAX_LEVEL else None),
            ("W", state.buy_worth() if state.worth_level < WORTH_MAX_LEVEL else None,
             WORTH_COSTS[state.worth_level] if state.worth_level < WORTH_MAX_LEVEL else None),
            ("M", state.buy_mult() if state.mult_level < MULT_MAX_LEVEL else None,
             MULT_COSTS[state.mult_level] if state.mult_level < MULT_MAX_LEVEL else None),
        ]:
            if next_state is None:
                continue
            f2e = flips_to_earn(cost, epf)
            new_acc = accumulated_flips + f2e
            if new_acc > flip_budget:
                continue
            dfs(next_state, seq + [code], new_acc)

    dfs(start, [], 0.0)

    # Deduplicate by (state, upgrades) — same sequence can only appear once
    seen: set[tuple] = set()
    unique: list[PathResult] = []
    for r in results:
        key = tuple(r.upgrades)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


# ---------------------------------------------------------------------------
# Single-step greedy analysis: what's the best upgrade right now?
# ---------------------------------------------------------------------------

@dataclass
class UpgradeOption:
    code: str
    name: str
    cost: int
    flips_to_earn: float
    e_flips_before: float
    e_flips_after: float
    delta_e: float          # flips saved by the upgrade itself
    net_flips_saved: float  # delta_e - flips_to_earn (positive = net benefit)


def best_next_upgrade(state: GameState) -> list[UpgradeOption]:
    """
    For the current game state, rank all available upgrades by net expected
    flips saved: (E[win | current] - E[win | upgraded]) - flips_to_earn.
    """
    p = state.heads_prob
    e_before = expected_flips_to_win(p)
    epf = expected_earning_per_flip(state.heads_prob, state.base_worth, state.combo_mult)

    options: list[UpgradeOption] = []

    candidates = []
    if state.heads_level < HEADS_MAX_LEVEL:
        candidates.append(("H", UPGRADE_NAMES["H"], HEADS_COSTS[state.heads_level], state.buy_heads()))
    if state.worth_level < WORTH_MAX_LEVEL:
        candidates.append(("W", UPGRADE_NAMES["W"], WORTH_COSTS[state.worth_level], state.buy_worth()))
    if state.mult_level < MULT_MAX_LEVEL:
        candidates.append(("M", UPGRADE_NAMES["M"], MULT_COSTS[state.mult_level], state.buy_mult()))
    if state.time_level < FLIPTIME_MAX_LEVEL:
        candidates.append(("T", UPGRADE_NAMES["T"], FLIPTIME_COSTS[state.time_level], state.buy_time()))

    for code, name, cost, next_state in candidates:
        f2e = flips_to_earn(cost, epf)
        e_after = expected_flips_to_win(next_state.heads_prob)
        delta_e = e_before - e_after
        options.append(UpgradeOption(
            code=code,
            name=name,
            cost=cost,
            flips_to_earn=f2e,
            e_flips_before=e_before,
            e_flips_after=e_after,
            delta_e=delta_e,
            net_flips_saved=delta_e - f2e,
        ))

    options.sort(key=lambda o: o.net_flips_saved, reverse=True)
    return options
