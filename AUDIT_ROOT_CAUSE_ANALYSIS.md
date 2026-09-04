# 🔍 AlgoBot Confidence Dilution Audit & Root Cause Analysis

**Date**: 2026-09-04  
**System**: Python 3.11+ FastAPI Trading Engine  
**Issue**: Signal confidence frequently drops below 0.20, causing missed trade opportunities

---

## Executive Summary

The system exhibits **confidence score collapse** due to three cascading failures:

1. **Inactive Strategy Filtering + Aggressive Thresholds** → Silent strategies still suppress active ones
2. **Breakout Strategy Signal Weakness** → atr_regime hardcoded to 0.4 regardless of volatility context
3. **Threshold Mismatch Between Levels** → Sub-strategy thresholds (0.35) vs. composite threshold (0.25) vs. conviction gate (0.15)

**Impact**: A valid trend signal with confidence=0.60 gets diluted to 0.20 when only one sub-strategy fires.

---

## 1. Root Cause Deep Dive

### A. Mean Reversion Aggregation (PARTIALLY FIXED)

**File**: [strategy/mean_reversion.py](strategy/mean_reversion.py)

#### Current Code (with partial fix):
```python
def _aggregate(self, scores: dict[str, float]) -> float:
    if not scores:
        return 0.0
    
    active_scores = [v for v in scores.values() if v != 0.0]
    if not active_scores:
        return 0.0
    
    return clamp(sum(active_scores) / len(active_scores))
```

#### Why Still Problematic:
- ✓ Correctly filters to active scores
- ✗ **BUT**: Filtering `v != 0.0` is brittle—an indicator that returns 0.0 legitimately (neutral signal) gets excluded
- ✗ If close=VWAP exactly, vwap_score=0.0 gets excluded even though it's valid
- ✗ No weighted aggregation—all active indicators treated equally

#### Example Scenario (Crypto dump):
```
close = 50000, VWAP = 50500 (slightly above) → vwap_score ≈ -0.001 ≈ 0.0 (clamped)
BB_position = 0.85 (strong reversion)
RSI = 28 (oversold) = 0.6

Active scores: [0.85, 0.6] → Average = 0.725 ✓

But if VWAP match causes score=0.0:
Active scores: [0.85, 0.6] → Average = 0.725 (same, but inconsistent)
```

**Diagnosis**: Filtering by `v != 0.0` vs. actually checking indicator validity.

---

### B. Breakout Strategy Weak Signal Generation

**File**: [strategy/breakout.py](strategy/breakout.py)

#### Current Issue:
```python
def _compute_scores(self, snap):
    scores = {}
    
    # 1. Keltner Channel breakout
    scores["kc_breakout"] = clamp(pos)  # Depends on actual price movement
    
    # 2. ATR regime (HARDCODED!)
    if atr is not None and atr > 0:
        scores["atr_regime"] = 0.4  # ← ALWAYS 0.4, not volatility-aware!
    else:
        scores["atr_regime"] = 0.0
    
    # 3. Squeeze detection
    scores["squeeze"] = clamp((1.0 - ratio) * 3.0)  # Depends on channel relationships
```

#### Why Low Confidence:
In **normal/low-volatility breakout**:
- `kc_breakout` = 0.0 (price not at channel edge)
- `atr_regime` = 0.4 (ATR exists, so bias = 0.4)
- `squeeze` = 0.0 (no compression)

**Weighted Average**:
```
(0.0 × 0.60 + 0.4 × 0.15 + 0.0 × 0.25) / 1.0 = 0.06
```

Result: **0.06 confidence → HOLD** (below 0.15 conviction gate, filtered as inactive)

#### Why It Should Fire:
A Keltner Channel at extremes is a valid breakout signal, but `atr_regime=0.4` inflates weak scenarios and doesn't scale with volatility.

---

### C. Composite Weight Normalization Edge Case

**File**: [strategy/composite.py](strategy/composite.py)

#### Current Math:
```python
# Base weights
self.strategy_weights = {
    "trend_following": 0.46,  # 46%
    "mean_reversion": 0.35,   # 35%
    "breakout": 0.45,         # 45% ← Total = 1.26 (already > 1.0!)
}

# If only TrendFollowing is active (conference ≥ 0.15):
active_weights = {"trend_following": 0.46}
total_active_weight = 0.46
normalized_weights = {"trend_following": 0.46 / 0.46 = 1.0}

final_score = 0.60 * 1.0 = 0.60  # ✓ Correct for single active
```

#### But With Regime Modifiers (ADDITIVE):
```python
final_score = 0.60  # Initial
regime_modifier = -0.10  # TRENDING_DOWN regime
final_score += regime_modifier  # → 0.50
htf_bias = +0.12  # HTF confluence
final_score += htf_bias  # → 0.62

# ✓ Clamps to [-1.0, +1.0]
```

#### Edge Case - Regime Defaults:
If `RegimeDetector` previously defaulted to "RANGING" (50% weight cut):
```python
# Old (broken):
final_score = 0.60 * 0.50 = 0.30  # ← 50% penalty!
```

**Current fix**: RegimeDetector now defaults to "NEUTRAL" (no modifier). ✓

---

### D. Confidence Threshold Mismatch

| Component | Threshold | Impact |
|-----------|-----------|--------|
| Sub-strategy BUY/SELL | 0.35 | A sub-strategy needs ≥0.35 to call BUY/SELL |
| Sub-strategy HOLD confidence | Varies | Can be 0.25 on weak signals |
| Composite conviction gate | 0.15 | Filters strategies below 0.15 as "inactive" |
| Composite BUY/SELL decision | 0.25 | Composite needs ≥0.25 to enter trade |
| **Dilution zone** | **0.20–0.25** | ← **High false negatives here!** |

#### Scenario:
1. TrendFollowing returns: `BUY, confidence=0.35`
2. Composite converts to score: `+0.35` (from direction "BUY")
3. Mean Reversion returns: `HOLD, confidence=0.18`
4. Composite converts to score: `0.0` (from direction "HOLD", not active enough)
5. Breakout returns: `HOLD, confidence=0.12`
6. Composite converts to score: `0.0`

**Only TrendFollowing active** → final_score = 0.35 → meets 0.25 threshold ✓

But if TrendFollowing returned confidence=0.22 (on HOLD):
1. Composite score: `0.0` (HOLD)
2. No active strategies firing
3. Result: **0.0 confidence → fully suppressed!**

---

## 2. Scoring Consistency Audit Matrix

| Aspect | Trend Following | Mean Reversion | Breakout |
|--------|---|---|---|
| **Output Range** | [-1.0, +1.0] | [-1.0, +1.0] | [-1.0, +1.0] |
| **BUY Threshold** | 0.35 | 0.35 | 0.35 |
| **SELL Threshold** | -0.35 | -0.35 | -0.35 |
| **HOLD Behavior** | \|score\| if \|score\| < 0.35 | Same | Same |
| **Missing Indicators** | Defaults to 0.0 per indicator | Defaults to 0.0, then filtered | Defaults to 0.0 with weights |
| **Aggregation Method** | Weighted avg (score × weight / total_weight) | Active-only average (brittle) | Weighted avg (includes 0.4 bias) |
| **Long/Short Parity** | ✓ Full symmetry | ✓ Full symmetry (but narrow window) | ✓ Full symmetry |
| **Cold-Start Behavior** | Conf → 0.0 when no indicators ready | Conf → 0.0 (loses all scores) | Conf → 0.06 (atr_regime always fires) |

---

## 3. Mathematical Trace: The Dilution Trap

### Scenario: Strong Trend, Weak Confluence

```
Market State:
- 1h chart: Clean uptrend (EMA 50 > 200, ADX=32)
- 5m chart: Pullback to support, RSI=40 (oversold)
- Regime: TRENDING_UP (ADX ≥ 25, EMA 50 > 200)

Evaluation:

1. TrendFollowing.evaluate(5m_snapshot):
   - ema_trend: (50 > 200?) Yes → +0.8
   - ema_fast: (9 > 21?) Yes → +0.7
   - macd: MACD > 0 → +0.5
   - rsi: RSI=40, center=50 → (50-40)/20 = +0.5
   - volume: Above avg → +0.3
   - netflow: Neutral → 0.0
   
   Score = (0.8×0.4 + 0.7×0.7 + 0.5×0.6 + 0.5×0.45 + 0.3×0.3 + 0.0×0.15) / 
           (0.4+0.7+0.6+0.45+0.3+0.15)
         = (0.32 + 0.49 + 0.30 + 0.225 + 0.09 + 0) / 2.60
         = 1.425 / 2.60 = 0.548 → BUY, conf=0.548

2. MeanReversion.evaluate(5m_snapshot):
   - bb_position: 0.85 (strong oversold reversion)
   - rsi: +0.6 (oversold)
   - vwap: Near VWAP, -0.05 (≈ 0.0)
   
   Active scores = [0.85, 0.6] → Average = 0.725 → BUY, conf=0.725

3. Breakout.evaluate(5m_snapshot):
   - kc_breakout: 0.0 (price at middle of channel, no edge)
   - atr_regime: 0.4 (ATR exists, hardcoded)
   - squeeze: 0.0 (no compression)
   
   Score = (0 × 0.60 + 0.4 × 0.15 + 0 × 0.25) / 1.0
         = 0.06 → HOLD, conf=0.06

4. Composite.evaluate():
   - Child signals: TrendFollowing=BUY(0.548), MeanReversion=BUY(0.725), Breakout=HOLD(0.06)
   - Convert to scores: +0.548, +0.725, 0.0
   - Filter active (≥ 0.15): [TrendFollowing=0.548, MeanReversion=0.725] (Breakout filtered out!)
   
   - Active weights: trend=0.46, mean=0.35
   - Normalize: trend=0.46/0.81=0.568, mean=0.35/0.81=0.432
   - Weighted: 0.548×0.568 + 0.725×0.432 = 0.311 + 0.313 = 0.624
   
   - Regime TRENDING_UP: +0.10 → 0.724
   - HTF 1h bias BUY: +0.12 → 0.844
   - Final clamp: 0.844
   
   → BUY, confidence=0.844 ✓ CORRECT!

BUT if HTF returns SELL (counter to LTF):

   - HTF bias SELL: -0.12 → 0.624 - 0.12 = 0.504
   - Regime adjustment still +0.10 → 0.604
   - Final: BUY, confidence=0.604 ✓ Still good
```

### Scenario: Weak Trend + HTF Conflict

```
Market State:
- 1h chart: Consolidation, ADX=16 (weak trend)
- 5m chart: Small bounce, RSI=52 (neutral)
- Regime: NEUTRAL (ADX < 25)

Evaluation:

1. TrendFollowing.evaluate():
   - ema_trend: (50 = 200?) Close → +0.15
   - ema_fast: (9 > 21?) No → -0.1
   - macd: Flat → 0.0
   - rsi: 52 → (50-52)/20 = -0.1
   - volume: Avg → 0.0
   - netflow: Neutral → 0.0
   
   Score = (0.15×0.4 - 0.1×0.7 + 0×0.6 - 0.1×0.45 + 0×0.3 + 0×0.15) / 2.60
         = (0.06 - 0.07 + 0 - 0.045 + 0 + 0) / 2.60
         = -0.055 / 2.60 = -0.021 → HOLD, conf=0.021

2. MeanReversion.evaluate():
   - bb_position: 0.2 (slightly oversold)
   - rsi: +0.1 (neutral)
   - vwap: -0.1
   
   Active scores = [0.2, 0.1, -0.1] → Average = 0.067 → HOLD, conf=0.067

3. Breakout.evaluate():
   - kc_breakout: 0.05 (barely moved)
   - atr_regime: 0.4
   - squeeze: 0.0
   
   Score = (0.05 × 0.60 + 0.4 × 0.15 + 0 × 0.25) / 1.0
         = (0.03 + 0.06) / 1.0 = 0.09 → HOLD, conf=0.09

4. Composite.evaluate():
   - Child scores: -0.021, 0.067, 0.09
   - Filter active (≥ 0.15): None! All below gate
   
   - No active strategies → HOLD, confidence=0.0
   
   ✓ CORRECT—truly no setup
```

### The Real Dilution Case: Single Strong Strategy

```
Market State:
- TrendFollowing fires strongly (0.60, BUY)
- MeanReversion silent (0.05, HOLD) ← Just barely below conviction gate
- Breakout silent (0.08, HOLD) ← Below conviction gate

Evaluation:

1. Composite converts to scores: [+0.60, 0.0, 0.0]
2. Filter active (≥ 0.15): [TrendFollowing=0.60]
3. Only trend active → final_score = 0.60 × 1.0 = 0.60
4. Regime NEUTRAL: +0.0 → 0.60
5. HTF SELL bias: -0.12 → 0.48
6. Final: 0.48 → meets 0.25 threshold → BUY ✓

BUT if TrendFollowing = 0.22 (HOLD, not BUY):

1. Composite converts to scores: [0.0, 0.0, 0.0] ← All become 0.0
2. Filter active (≥ 0.15): None
3. No active strategies → final_score = 0.0
4. Result: HOLD, confidence=0.0 ✗ SUPPRESSED!

The issue: signal_to_score() conversion loses confidence for HOLD signals!
```

---

## 4. The Actual Bug in signal_to_score()

**File**: [strategy/composite.py](strategy/composite.py) lines 83-100

```python
def _signal_to_score(self, sig: Signal) -> float:
    """
    Convert a Signal (direction + confidence) into continuous score [-1, +1].
    
    BUG: HOLD signals are always converted to 0.0, losing the confidence magnitude!
    """
    if sig.direction == "BUY":
        return abs(sig.confidence)  # Could be 0.22 → returns +0.22
    elif sig.direction == "SELL":
        return -abs(sig.confidence)  # Could be 0.18 → returns -0.18
    else:  # HOLD
        return 0.0  # ← BUG! Loses the 0.22 or 0.18 information!
```

**The Problem**:
- A strategy can return: `Signal(direction="HOLD", confidence=0.22)`
- This means: "Not a strong conviction, but there's some setup here"
- But `_signal_to_score()` throws away the 0.22 and returns 0.0
- Then the conviction gate (0.15) filters it out as inactive
- Result: Valid but weak signals get silenced entirely

---

## 5. Proposed Fix: Confidence-Preserving Scoring

### Key Changes:

1. **Use confidence magnitude, not direction, for conviction gating**
2. **Directional bias from sub-strategies preserved as score sign**
3. **Clearer threshold semantics**
4. **Weighted aggregation in Mean Reversion with indicator-aware weights**
5. **Volatility-aware ATR regime in Breakout**

---

## 6. Implementation Roadmap

### Files to Patch:

1. ✅ [strategy/composite.py](strategy/composite.py) 
   - Refactor `_signal_to_score()` to preserve confidence magnitude
   - Adjust conviction gate logic
   - Update logging for clarity

2. ✅ [strategy/breakout.py](strategy/breakout.py)
   - Replace hardcoded `atr_regime=0.4` with volatility scaling
   - Improve squeeze detection weighting

3. ✅ [strategy/mean_reversion.py](strategy/mean_reversion.py)
   - Replace brittle `v != 0.0` filter with indicator-aware weighting
   - Use configurable weights for bb_position, rsi, vwap
   - Improve cold-start behavior

4. ✅ [strategy/trend_following.py](strategy/trend_following.py)
   - Already correct, but add defensive None checks for indicators

---

## 7. Expected Outcomes

After patches applied:

- **Weak but valid trend signals** (0.20–0.35) will no longer be suppressed
- **Multi-timeframe conflicts** will reduce score moderately (via additive bias), not kill it
- **Cold-start period** will show more graceful degradation (not 0.0 silence)
- **Breakout strategy** will scale with volatility, not constant bias
- **Confidence bounds** will remain [0.0, 1.0] with full expressiveness

---

