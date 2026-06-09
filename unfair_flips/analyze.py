"""
Main analysis script for Unfair Flips.

Usage:
    python -m unfair_flips.analyze              # full analysis
    python -m unfair_flips.analyze --state H3M2 # start from given upgrade levels
    python -m unfair_flips.analyze --paths      # enumerate and rank all paths
"""

from __future__ import annotations

import argparse
import math
import sys

from .constants import (
    HEADS_COSTS, WORTH_COSTS, MULT_COSTS, FLIPTIME_COSTS,
    INITIAL_HEADS_PROB, INITIAL_BASE_WORTH, INITIAL_COMBO_MULT,
)
from .game import (
    GameState, expected_flips_to_win, expected_earning_per_flip,
    percentile_flips, head_earning,
)
from .optimizer import (
    dp_optimal_path, best_next_upgrade, compute_upgrade_spread,
    UPGRADE_NAMES, _evaluate_path,
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_flips(n: float) -> str:
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K"
    return f"{n:.0f}"


def fmt_cents(c: int) -> str:
    if c < 100:
        return f"{c}¢"
    if c < 10_000:
        return f"${c/100:.2f}"
    return f"${c/100:,.0f}"


def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}min"
    return f"{seconds/3600:.1f}h"


# ---------------------------------------------------------------------------
# Section: basic stats at each upgrade state
# ---------------------------------------------------------------------------

def print_state_table() -> None:
    print("\n" + "=" * 80)
    print("EXPECTED FLIPS TO WIN vs HEADS CHANCE")
    print("=" * 80)
    print(f"{'p':>6}  {'E[flips]':>12}  {'P50':>12}  {'P95':>12}  {'P99':>12}")
    print("-" * 60)

    for level in range(9):  # 0..8 (20% through 60%)
        p = INITIAL_HEADS_PROB + level * 0.05
        e = expected_flips_to_win(p)
        p50 = percentile_flips(p, 0.50)
        p95 = percentile_flips(p, 0.95)
        p99 = percentile_flips(p, 0.99)
        print(f"{p:>6.0%}  {fmt_flips(e):>12}  {fmt_flips(p50):>12}  "
              f"{fmt_flips(p95):>12}  {fmt_flips(p99):>12}")


def print_money_table() -> None:
    print("\n" + "=" * 80)
    print("MONEY EARNED PER STREAK (at different combo multiplier levels)")
    print("=" * 80)

    from .constants import INITIAL_COMBO_MULT, MULT_DELTA

    mult_levels = [INITIAL_COMBO_MULT + i * MULT_DELTA for i in range(6)]
    base = 1  # 1¢ base worth

    header = f"{'Streak':>7}" + "".join(f"  mult={m:.1f}" for m in mult_levels)
    print(header)
    print("-" * len(header))

    for k in range(1, 11):
        row = f"{k:>7}"
        for m in mult_levels:
            earning = head_earning(k, base, m)
            row += f"  {earning:>8}¢"
        print(row)

    print()
    print("cumulative earnings for a full 10-streak (1¢ base):")
    for m in mult_levels:
        total = sum(head_earning(k, 1, m) for k in range(1, 11))
        print(f"  mult={m:.1f}:  {total}¢ = {fmt_cents(total)}")


def print_earning_rate_table() -> None:
    print("\n" + "=" * 80)
    print("EXPECTED EARNING RATE (¢/flip) at different game states")
    print("=" * 80)

    from .constants import WORTH_VALUES, MULT_DELTA

    print(f"{'p':>5}  {'base':>6}  {'mult':>6}  {'¢/flip':>10}")
    print("-" * 35)

    for h in [0, 4, 8]:
        p = INITIAL_HEADS_PROB + h * 0.05
        for w in [0, 2, 4]:
            base = WORTH_VALUES[w]
            for m in [0, 2, 5]:
                mult = INITIAL_COMBO_MULT + m * MULT_DELTA
                epf = expected_earning_per_flip(p, base, mult)
                print(f"{p:>5.0%}  {base:>5}¢  {mult:>6.1f}  {epf:>10.4f}")


# ---------------------------------------------------------------------------
# Section: metric comparison
# ---------------------------------------------------------------------------

def print_metric_comparison() -> None:
    print("\n" + "=" * 80)
    print("OPTIMAL PATH BY METRIC")
    print("=" * 80)

    flip_metrics = [
        ("expected_flips", False, "Minimise E[flips] (no time upgrades)"),
        ("p95",            False, "Minimise P95 flips (worst-case, no time upgrades)"),
    ]
    time_metrics = [
        ("expected_time",  True,  "Minimise E[time] (including FlipTime upgrades)"),
        ("p95",            True,  "Minimise P95 flips (including FlipTime upgrades)"),
    ]

    for metric, include_time, label in flip_metrics + time_metrics:
        result = dp_optimal_path(metric=metric, include_time_upgrades=include_time)
        seq = " → ".join(result.upgrades) if result.upgrades else "(no upgrades)"
        print(f"\n  [{label}]")
        print(f"  Path: {seq}")
        print(f"  Final state: {result.state.label()}")
        print(f"  E[flips]={fmt_flips(result.total_expected_flips)}  "
              f"P95={fmt_flips(result.p95_flips)}  "
              f"E[time]={fmt_time(result.total_expected_time)}")


def print_metric_discussion() -> None:
    print("\n" + "=" * 80)
    print("WHICH METRIC SHOULD YOU USE?")
    print("=" * 80)
    print("""
  E[flips]  — Minimises average outcome over many playthroughs. Best if you
               want the strategy that "works on average." This is the classical
               optimisation target.

  P50       — Minimises the median. Half of players beat this, half don't.
               Very close to E[flips] for this game because the distribution
               is approximately log-normal.

  P95/P99   — Minimises the tail risk: "what's the worst-case for 95%/99%
               of players?" Useful if you want a guaranteed completion time.
               Typically favours buying MORE upgrades than the E[flips] path,
               because heavy coin upgrades shrink the tail dramatically.

  True worst-case  — Infinity. The game is never guaranteed to end; there is
               always a non-zero probability of running forever (for any p<1).
               P99 is the practical substitute.

  TLDR: The E[flips] and P50 strategies are nearly identical. The P95/P99
  strategies invest more in upgrades, making early phases longer but the
  win-phase much more reliable.
""")




# ---------------------------------------------------------------------------
# Section: what to buy next (given current state)
# ---------------------------------------------------------------------------

def print_path_breakdown(upgrades: list[str], start: GameState = GameState()) -> None:
    """Show a step-by-step breakdown of a path's time and flip costs."""
    print("\n" + "=" * 80)
    print("PATH BREAKDOWN (time-to-earn included at each step)")
    print("=" * 80)

    state = start
    cumulative_flips = 0.0
    cumulative_time = 0.0

    header = (f"  {'Step':>4}  {'Upgrade':28}  {'Cost':>8}  "
              f"{'¢/flip':>8}  {'Earn flips':>12}  {'Earn time':>10}  {'Cum. time':>10}")
    print(header)
    print("  " + "-" * 100)

    from .constants import HEADS_COSTS, WORTH_COSTS, MULT_COSTS, FLIPTIME_COSTS
    from .optimizer import UPGRADE_NAMES
    from .game import flips_to_earn

    for step_num, code in enumerate(upgrades, 1):
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
            continue

        f2e = flips_to_earn(cost, epf)
        t2e = f2e * state.flip_duration
        cumulative_flips += f2e
        cumulative_time += t2e

        print(f"  {step_num:>4}  "
              f"{UPGRADE_NAMES[code]:<28}  {fmt_cents(cost):>8}  "
              f"{epf:>8.4f}  {fmt_flips(f2e):>12}  "
              f"{fmt_time(t2e):>10}  {fmt_time(cumulative_time):>10}")
        state = next_state

    # Win phase
    p = state.heads_prob
    win_flips = expected_flips_to_win(p)
    win_time = win_flips * state.flip_duration
    cumulative_flips += win_flips
    cumulative_time += win_time
    print(f"  {'→':>4}  {'WIN (at {:.0%} per flip)'.format(p):<28}  {'':>8}  "
          f"{'':>8}  {fmt_flips(win_flips):>12}  "
          f"{fmt_time(win_time):>10}  {fmt_time(cumulative_time):>10}")
    print()
    print(f"  Total: {fmt_flips(cumulative_flips)} flips  |  {fmt_time(cumulative_time)}")


def print_upgrade_spread(upgrades: list[str], metric: str = "expected_time",
                         include_time_upgrades: bool = True,
                         start: GameState = GameState()) -> None:
    """
    For each step of the path show all available upgrades ranked by total
    metric cost, with the spread between best and worst highlighted.
    """
    unit = "min" if metric == "expected_time" else "flips"
    scale = 60.0 if metric == "expected_time" else 1.0

    def fmt_cost(v: float) -> str:
        if metric == "expected_time":
            return fmt_time(v)
        return fmt_flips(v)

    print("\n" + "=" * 80)
    print(f"UPGRADE DECISION SPREAD ({metric.replace('_', ' ')}-optimal path)")
    print("=" * 80)
    print(f"  How much does the choice of upgrade matter at each step?")
    print(f"  Spread = (worst upgrade cost) − (best upgrade cost) in {unit}.")
    print(f"  A large spread means a high-stakes decision; small = roughly equivalent.\n")

    steps = compute_upgrade_spread(upgrades, metric=metric,
                                   include_time_upgrades=include_time_upgrades, start=start)

    name_w = 22
    state_w = 36
    header = (f"  {'Step':>4}  {'State (before)':<{state_w}}  "
              f"{'#':>2}  {'Upgrade':<{name_w}}  {'Total':>9}  {'vs best':>9}  {'Spread':>9}")
    sep = "  " + "-" * (len(header) - 2)
    print(header)
    print(sep)

    for step in steps:
        for rank, opt in enumerate(step.options, 1):
            marker = " ★" if opt.chosen else ""
            state_str = step.state.label() if rank == 1 else ""
            spread_str = fmt_cost(step.spread) if rank == 1 else ""
            delta_str = "—" if opt.delta_vs_best == 0.0 else f"+{fmt_cost(opt.delta_vs_best)}"
            print(f"  {step.step if rank == 1 else '':>4}  {state_str:<{state_w}}  "
                  f"{rank:>2}  {opt.name:<{name_w}}  "
                  f"{fmt_cost(opt.total_cost):>9}  {delta_str:>9}  "
                  f"{spread_str:>9}{marker}")
        print()


def print_next_upgrade(state: GameState) -> None:
    print("\n" + "=" * 80)
    print(f"BEST NEXT UPGRADE for: {state.label()}")
    print("=" * 80)

    options = best_next_upgrade(state)
    if not options:
        print("  All upgrades maxed out. Just keep flipping!")
        return

    epf = expected_earning_per_flip(state.heads_prob, state.base_worth, state.combo_mult)
    print(f"\n  Current earning rate: {epf:.4f}¢/flip")
    print(f"  E[flips to win now]: {fmt_flips(expected_flips_to_win(state.heads_prob))}")
    print()
    print(f"  {'Upgrade':30}  {'Cost':>8}  {'Earn flips':>12}  "
          f"{'ΔE[flips]':>12}  {'Net saved':>12}")
    print("  " + "-" * 80)

    for opt in options:
        marker = " ★" if opt == options[0] else ""
        print(f"  {opt.name:<30}  {fmt_cents(opt.cost):>8}  "
              f"{fmt_flips(opt.flips_to_earn):>12}  "
              f"{fmt_flips(opt.delta_e):>12}  "
              f"{fmt_flips(opt.net_flips_saved):>12}{marker}")

    best = options[0]
    print(f"\n  Recommendation: Buy {UPGRADE_NAMES[best.code]}")
    if best.net_flips_saved > 0:
        print(f"  This saves ~{fmt_flips(best.net_flips_saved)} expected flips (net).")
    else:
        print(f"  Note: no upgrade saves flips at this state — just go for the win!")


# ---------------------------------------------------------------------------
# Parse state string like "H3M2W1"
# ---------------------------------------------------------------------------

def parse_state(s: str) -> GameState:
    import re
    counts = {"H": 0, "W": 0, "M": 0, "T": 0}
    for code, level in re.findall(r"([HWMT])(\d+)", s.upper()):
        counts[code] = int(level)
    return GameState(
        heads_level=counts["H"],
        worth_level=counts["W"],
        mult_level=counts["M"],
        time_level=counts["T"],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Unfair Flips analysis tool")
    parser.add_argument("--state", default="", help="Current state e.g. H3M2W1T1")
    args = parser.parse_args()

    state = parse_state(args.state) if args.state else GameState()

    print_state_table()
    print_money_table()
    print_metric_discussion()
    print_metric_comparison()

    # Show breakdown for the time-optimal path
    best_time = dp_optimal_path(metric="expected_time", include_time_upgrades=True)
    print_path_breakdown(best_time.upgrades)
    print_upgrade_spread(best_time.upgrades)

    print_next_upgrade(state)

    print()


if __name__ == "__main__":
    main()
