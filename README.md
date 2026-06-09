# Unfair Flips — Mathematical Analysis

A mathematical analysis of the Steam game [Unfair Flips](https://store.steampowered.com/app/3925760/Unfair_Flips/), computing optimal upgrade paths using dynamic programming and Markov chain models.

## The Game

You flip a coin repeatedly. Get **10 consecutive heads** to win. Between flips, you spend earned money on upgrades:

| Upgrade | Effect | Levels | Cost (¢) |
|---|---|---|---|
| HeadsChance | +5% per flip | 8 | 1 → 10 → 100 → 1K → 10K → 100K → 1M → 10M |
| FlipMultiplier | +0.5× streak bonus | 5 | 1 → 10 → 100 → 1K → 10K |
| FlipBaseWorth | Base ¢ per head | 4 | 25 → 100 → 625 → 10K |
| FlipTime | −0.2s per flip | 5 | 1 → 10 → 100 → 1K → 10K |

**Starting state:** 20% heads chance, 1¢ base, 1.0× multiplier, 2.0s per flip.

**Money formula** (from decompiled game source):
```
earn(k) = base_worth × ⌈combo_mult^(k−1)⌉   for the k-th consecutive head
```

At the default multiplier of 1.0× this is just 1¢ per head every time. Once you buy multiplier upgrades, later streaks earn exponentially more.

## Math

### Expected flips to win

Getting n consecutive heads with probability p per flip is a Markov chain. The exact closed-form solution is:

```
E[flips] = Σ_{k=1}^{n} (1/p)^k
```

At 20% this is ~12.2 million flips. At 60% it drops to ~411.

### Earning rate

Per-flip earning rate in steady state:

```
¢/flip = E[earnings per attempt] / E[flips per attempt]
```

where an "attempt" is a run until tails (or win). This drives how quickly you can afford each upgrade tier.

### Percentiles

Winning attempts follow a geometric distribution with success probability `p^10`. The q-th percentile total flips:

```
a_q = ⌈log(1−q) / log(1−p^10)⌉
total_flips_q ≈ (a_q − 1) × mean_attempt_length + 10
```

## Results

### Effect of HeadsChance on difficulty

| p | E[flips] | P50 | P95 | P99 |
|---|---|---|---|---|
| 20% | 12.21M | 8.46M | 36.57M | 56.22M |
| 25% | 1.40M | 969K | 4.19M | 6.44M |
| 30% | 241.9K | 167.7K | 724.8K | 1.11M |
| 35% | 55.8K | 38.7K | 167.1K | 256.8K |
| 40% | 15.9K | 11.0K | 47.6K | 73.2K |
| 45% | 5.3K | 3.7K | 16.0K | 24.6K |
| 50% | 2.0K | 1.4K | 6.1K | 9.4K |
| 55% | 875 | 615 | 2.6K | 4.0K |
| 60% | 411 | 293 | 1.2K | 1.9K |

The jump from 20%→25% alone reduces expected flips by ~8.8×. HeadsChance is the dominant lever.

### Money per streak (1¢ base)

| Streak | mult=1.0 | mult=1.5 | mult=2.0 | mult=2.5 | mult=3.0 | mult=3.5 |
|---|---|---|---|---|---|---|
| 1 | 1¢ | 1¢ | 1¢ | 1¢ | 1¢ | 1¢ |
| 5 | 1¢ | 6¢ | 16¢ | 40¢ | 81¢ | 151¢ |
| 10 | 1¢ | 39¢ | 512¢ | $38 | $197 | $788 |
| **Total** | **10¢** | **$1.19** | **$10.23** | **$63.62** | **$295** | **$1,103** |

A full 10-streak at mult=3.5 earns 110× more than at mult=1.0.

### Optimal upgrade paths

Four strategies were evaluated using dynamic programming over the full state space `(H, W, M, T)`:

| Strategy | Path | Final state | E[flips] | P95 | E[time] |
|---|---|---|---|---|---|
| Minimise E[flips] | M→H→W→H→M→W→M→H→W→M→H→W→M→H→H→H | 55% / $1 / 3.5× / 2.0s | 1.3K | 3.1K | 44.9 min |
| Minimise P95 | M→H→W→H→M→W→M→H→W→M→H→W→M→H→H→H→H | 60% / $1 / 3.5× / 2.0s | 1.4K | 2.2K | 47.3 min |
| Minimise E[time] | M→H→T→W→H→M→T→W→M→H→T→W→M→H→T→W→M→H→T→H→H | 55% / $1 / 3.5× / 1.0s | 1.4K | 3.1K | **25.9 min** |
| Minimise P95+time | (same as P95 — time upgrades don't help worst-case) | 60% / $1 / 3.5× / 2.0s | 1.4K | 2.2K | 47.3 min |

**The time-optimal path** interleaves FlipTime upgrades with the usual sequence, halving flip duration over the game and finishing in ~26 minutes vs ~45 minutes.

### Time-optimal path breakdown

| Step | Upgrade | Cost | ¢/flip | Earn flips | Earn time | Cumulative |
|---|---|---|---|---|---|---|
| 1 | FlipMultiplier +0.5 | 1¢ | 0.20 | 5 | 10s | 10s |
| 2 | HeadsChance +5% | 1¢ | 0.25 | 4 | 8s | 18s |
| 3 | FlipTime −0.2s | 1¢ | 0.33 | 3 | 6s | 24s |
| 4 | FlipBaseWorth ↑ | 25¢ | 0.33 | 75 | 2.2 min | 2.6 min |
| 5 | HeadsChance +5% | 10¢ | 1.67 | 6 | 11s | 2.8 min |
| 6 | FlipMultiplier +0.5 | 10¢ | 2.16 | 5 | 8s | 3.0 min |
| 7 | FlipTime −0.2s | 10¢ | 2.61 | 4 | 7s | 3.1 min |
| 8 | FlipBaseWorth ↑ | $1.00 | 2.61 | 38 | 1.0 min | 4.1 min |
| 9 | FlipMultiplier +0.5 | $1.00 | 5.22 | 19 | 31s | 4.6 min |
| 10 | HeadsChance +5% | $1.00 | 8.42 | 12 | 19s | 4.9 min |
| 11 | FlipTime −0.2s | $1.00 | 14.1 | 7 | 11s | 5.1 min |
| 12 | FlipBaseWorth ↑ | $6.25 | 14.1 | 44 | 1.0 min | 6.1 min |
| 13 | FlipMultiplier +0.5 | $10.00 | 35.2 | 28 | 40s | 6.8 min |
| 14 | HeadsChance +5% | $10.00 | 71.5 | 14 | 20s | 7.1 min |
| 15 | FlipTime −0.2s | $10.00 | 155.8 | 6 | 9s | 7.3 min |
| 16 | FlipBaseWorth ↑ | $100 | 155.8 | 64 | 1.3 min | 8.6 min |
| 17 | FlipMultiplier +0.5 | $100 | 623.1 | 16 | 19s | 8.9 min |
| 18 | HeadsChance +5% | $100 | 1684.4 | 6 | 7s | 9.0 min |
| 19 | FlipTime −0.2s | $100 | 4012.5 | 2 | 3s | 9.1 min |
| 20 | HeadsChance +5% | $1,000 | 4012.5 | 25 | 25s | 9.5 min |
| 21 | HeadsChance +5% | $10,000 | 8968.8 | 111 | 1.9 min | 11.3 min |
| → | WIN at 55% | | | 875 | 14.6 min | **25.9 min** |

The upgrade phase takes ~11 minutes; the final win phase takes ~15 minutes.

### Which metric to optimise?

- **E[flips]** — best average over many playthroughs. Stops buying HeadsChance one level earlier (55% instead of 60%).
- **P95** — reduces tail risk at the cost of ~0.1K more expected flips. Pushes to 60% heads.
- **E[time]** — same as E[flips] but interleaves FlipTime purchases, cutting real-world duration nearly in half (26 vs 45 min). Recommended if you care about wall-clock time.
- **Worst-case** — technically infinite (any p < 1 can run forever). P99 is the practical bound.

## How to use

```bash
pip install -e .

# Full analysis (all tables + optimal paths)
analyze

# Recommendations starting from a specific upgrade state
analyze --state H3M2W1T1   # 3 heads upgrades, 2 mult, 1 worth, 1 time
```

State string format: `H<n>M<n>W<n>T<n>` where each number is the upgrade level purchased (0 = none).

## How game constants were obtained

The game is a Unity build. Constants were extracted by:

1. **Decompiling the DLL** with [`ilspycmd`](https://github.com/icsharpcode/ILSpy): `ilspycmd Assembly-CSharp.dll`
   - `CoinFlip.cs`: money formula, default values (`flipDuration=5.0`, `flipComboMultiplier=2.0`)
   - `CoinUpgrade.cs`: per-upgrade-type enum and effect deltas

2. **Scanning the Unity asset binary** (`level0`) for int64 cost sequences — type trees are stripped in the release build so UnityPy cannot deserialize MonoBehaviours. Raw binary search for known sequences (`[25, 100, 625, 10000]` for FlipBaseWorth, etc.) confirmed all upgrade costs.

3. **Prefab overrides**: initial values in `CoinFlip.cs` are overridden by the Unity prefab — confirmed by matching YouTube gameplay footage: `flipDuration=2.0s`, `flipComboMultiplier=1.0×`.

## Project structure

```
unfair_flips/
  constants.py   # all game constants (extracted from DLL + assets)
  game.py        # GameState dataclass + Markov chain math
  optimizer.py   # DP over upgrade state space, greedy ranker
  analyze.py     # CLI entry point, report sections
pyproject.toml
```
