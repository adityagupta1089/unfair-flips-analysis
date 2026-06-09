# Extracted from Assembly-CSharp.dll via ilspycmd + level0 binary scan.
# All monetary values are in cents (1¢ = $0.01).

CONSECUTIVE_TARGET = 10  # need 10 heads in a row to win

# --- Initial game state (from Unity prefab, overrides C# class defaults) ---
INITIAL_HEADS_PROB = 0.20       # flipHeadsChance
INITIAL_BASE_WORTH = 1          # baseFlipWorthInCents (cents)
INITIAL_COMBO_MULT = 1.0        # flipComboMultiplier (class default=2.0, prefab=1.0)
INITIAL_FLIP_DURATION = 2.0     # flipDuration in seconds (class default=5.0, prefab=2.0)

# --- HeadsChance upgrade ---
# upgradeType = HeadsChance (0)
# Effect: flipHeadsChance += 0.05 per level
# 8 levels: 20% → 25% → 30% → 35% → 40% → 45% → 50% → 55% → 60%
HEADS_COSTS = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000]  # cents
HEADS_DELTA = 0.05
HEADS_MAX_LEVEL = len(HEADS_COSTS)  # 8

# --- FlipTime upgrade ---
# upgradeType = FlipTime (1)
# Effect: flipDuration -= 0.2 per level
# 5 levels: 2.0s → 1.8s → 1.6s → 1.4s → 1.2s → 1.0s
FLIPTIME_COSTS = [1, 10, 100, 1_000, 10_000]  # cents
FLIPTIME_DELTA = -0.2
FLIPTIME_MAX_LEVEL = len(FLIPTIME_COSTS)  # 5

# --- FlipMultiplier upgrade ---
# upgradeType = FlipMultiplier (2)
# Effect: flipComboMultiplier += 0.5 per level
# 5 levels: 1.0 → 1.5 → 2.0 → 2.5 → 3.0 → 3.5
# Verified: mult=3.5 gives ceil(3.5^1)=4, ceil(3.5^2)=13, ceil(3.5^3)=43 (matches transcript)
MULT_COSTS = [1, 10, 100, 1_000, 10_000]  # cents
MULT_DELTA = 0.5
MULT_MAX_LEVEL = len(MULT_COSTS)  # 5

# --- FlipBaseWorth upgrade ---
# upgradeType = FlipBaseWorth (3)
# Effect: sets baseFlipWorthInCents to fixed value per level
# 4 levels: 1¢ → 5¢ → 10¢ → 25¢ → 100¢ ($1)
WORTH_COSTS = [25, 100, 625, 10_000]  # cents
WORTH_VALUES = [1, 5, 10, 25, 100]   # cents at each level (index 0 = initial)
WORTH_MAX_LEVEL = len(WORTH_COSTS)   # 4

# --- Money formula ---
# Each kth consecutive head (1-indexed) earns:
#   base_worth * ceil(combo_mult ^ (k - 1))
# Source: CoinFlip.cs:
#   long num3 = baseFlipWorthInCents * Mathf.CeilToInt(Mathf.Pow(flipComboMultiplier, headsComboNum - 1));
