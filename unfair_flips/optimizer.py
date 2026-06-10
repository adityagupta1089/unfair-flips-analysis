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

def _result_metric(result: "PathResult", metric: str) -> float:
    """Extract the scalar cost value from a PathResult for the given metric."""
    if metric == "expected_time":
        return result.total_expected_time
    if metric in ("expected_flips", "p50"):
        return result.total_expected_flips
    if metric == "p95":
        return result.p95_flips
    if metric == "p99":
        return result.p99_flips
    raise ValueError(f"Unknown metric: {metric}")


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
    maximize: bool = False,
) -> PathResult:
    """
    Find the upgrade path minimising (or maximising) the total cost under `metric`.

    Uses memoised DFS over (heads_level, worth_level, mult_level[, time_level]).
    Set maximize=True to find the worst possible upgrade ordering.
    """

    @lru_cache(maxsize=None)
    def dp(h: int, w: int, m: int, t: int) -> tuple[float, list[str]]:
        state = GameState(h, w, m, t)
        best_cost = _cost_metric(state, metric)
        best_seq: list[str] = []

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
            is_better = total > best_cost if maximize else total < best_cost
            if is_better:
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
# Upgrade decision spread: at each step, how much do choices differ?
# ---------------------------------------------------------------------------

@dataclass
class SpreadOption:
    code: str
    name: str
    total_cost: float
    delta_vs_best: float
    chosen: bool


@dataclass
class UpgradeSpreadStep:
    step: int
    state: GameState
    options: list[SpreadOption]
    best_cost: float
    spread: float         # max(upgrade costs) - min(upgrade costs), excl. WIN


def greedy_kth_worst_path(
    k: int = 2,
    metric: str = "expected_time",
    include_time_upgrades: bool = True,
    start: GameState = GameState(),
) -> PathResult:
    """
    Simulate a player who, at each step, picks the k-th worst available upgrade
    (ranked by transition_cost + dp_optimal from the resulting state).

    k=1 → always picks the absolute worst option (same result as dp maximize greedy).
    k=2 → picks the 2nd worst (avoids the single worst mistake each step).

    This is greedy (not DP), so it can be suboptimal in unexpected ways.
    """
    state = start
    seq: list[str] = []

    while True:
        candidates: list[tuple[str, GameState, int]] = []
        if state.heads_level < HEADS_MAX_LEVEL:
            candidates.append(("H", state.buy_heads(), HEADS_COSTS[state.heads_level]))
        if state.worth_level < WORTH_MAX_LEVEL:
            candidates.append(("W", state.buy_worth(), WORTH_COSTS[state.worth_level]))
        if state.mult_level < MULT_MAX_LEVEL:
            candidates.append(("M", state.buy_mult(), MULT_COSTS[state.mult_level]))
        if include_time_upgrades and state.time_level < FLIPTIME_MAX_LEVEL:
            candidates.append(("T", state.buy_time(), FLIPTIME_COSTS[state.time_level]))

        if not candidates:
            break

        scored: list[tuple[float, str, GameState]] = []
        for code, next_state, cost in candidates:
            tc = _transition_cost(state, next_state, cost, metric)
            future = dp_optimal_path(metric=metric, include_time_upgrades=include_time_upgrades,
                                     start=next_state)
            scored.append((tc + _result_metric(future, metric), code, next_state))

        scored.sort(key=lambda x: x[0], reverse=True)  # descending = worst first
        pick_idx = min(k - 1, len(scored) - 1)
        _, chosen_code, next_state = scored[pick_idx]

        seq.append(chosen_code)
        state = next_state

    return _evaluate_path(seq, start)


def compute_upgrade_spread(
    upgrades: list[str],
    metric: str = "expected_time",
    include_time_upgrades: bool = True,
    start: GameState = GameState(),
) -> list[UpgradeSpreadStep]:
    """
    For each step along `upgrades`, compute the total metric cost of
    every available upgrade (and "win now") at that state.

    total cost of choosing upgrade U at state S =
        transition_cost(S → buy(U)) + dp_optimal(start=buy(U))

    This shows which steps have high leverage (large spread between options)
    vs. steps where any choice is roughly equivalent.
    """
    steps = []
    state = start

    for step_num, chosen_code in enumerate(upgrades, 1):
        candidates: list[tuple[str, GameState, int]] = []
        if state.heads_level < HEADS_MAX_LEVEL:
            candidates.append(("H", state.buy_heads(), HEADS_COSTS[state.heads_level]))
        if state.worth_level < WORTH_MAX_LEVEL:
            candidates.append(("W", state.buy_worth(), WORTH_COSTS[state.worth_level]))
        if state.mult_level < MULT_MAX_LEVEL:
            candidates.append(("M", state.buy_mult(), MULT_COSTS[state.mult_level]))
        if include_time_upgrades and state.time_level < FLIPTIME_MAX_LEVEL:
            candidates.append(("T", state.buy_time(), FLIPTIME_COSTS[state.time_level]))

        raw_options: list[SpreadOption] = []

        # "Win now" baseline
        win_cost = _cost_metric(state, metric)
        raw_options.append(SpreadOption(code="WIN", name="Win now", total_cost=win_cost, delta_vs_best=0.0, chosen=False))

        # Each purchasable upgrade
        for code, next_state, cost in candidates:
            tc = _transition_cost(state, next_state, cost, metric)
            future = dp_optimal_path(metric=metric, include_time_upgrades=include_time_upgrades, start=next_state)
            total = tc + _result_metric(future, metric)
            raw_options.append(SpreadOption(
                code=code,
                name=UPGRADE_NAMES[code],
                total_cost=total,
                delta_vs_best=0.0,
                chosen=code == chosen_code,
            ))

        raw_options.sort(key=lambda o: o.total_cost)
        best_cost = raw_options[0].total_cost
        for o in raw_options:
            o.delta_vs_best = o.total_cost - best_cost

        # Spread is over purchasable upgrades only (exclude WIN)
        upgrade_costs = [o.total_cost for o in raw_options if o.code != "WIN"]
        spread = max(upgrade_costs) - min(upgrade_costs)
        options = raw_options

        steps.append(UpgradeSpreadStep(
            step=step_num,
            state=state,
            options=options,
            best_cost=best_cost,
            spread=spread,
        ))

        if chosen_code == "H":
            state = state.buy_heads()
        elif chosen_code == "W":
            state = state.buy_worth()
        elif chosen_code == "M":
            state = state.buy_mult()
        elif chosen_code == "T":
            state = state.buy_time()

    return steps


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
