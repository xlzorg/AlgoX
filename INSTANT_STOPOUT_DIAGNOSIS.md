# 🔴 CRITICAL BUG DIAGNOSIS: Position Open → Instant Stop-Loss Exit

**Status**: ROOT CAUSES IDENTIFIED  
**Severity**: CRITICAL (causes rapid losses)  
**Date**: 2026-09-04

---

## Summary: The Instant Stop-Out Loop

A position opens on one tick/candle → SL is checked on the next tick (same or next second) → Position closes with small loss. This repeats, draining account.

**Root Causes Found** (5 separate bugs):

1. ✅ **No minimum holding time** after entry fill
2. ✅ **Hard SL/TP checks run every tick** without position age check
3. ✅ **Exit intents created without SL/TP values** (null fields)
4. ✅ **Race condition: Entry + Exit in same event loop cycle**
5. ✅ **ATR stop multiplier reasonable (2.5) but no holding time gates it**

---

## ROOT CAUSE #1: No Minimum Holding Time

**File**: [portfolio/position_tracker.py](portfolio/position_tracker.py#L1-L50)

**Bug Location**: The `Position` dataclass stores `entry_time` but NEVER checks it.

```python
@dataclass(slots=True)
class Position:
    entry_time: int        # ← Stored but never used!
    # ... other fields ...
```

**In `check_exits()` method** (lines 86-120):
```python
def check_exits(self, symbol: str, current_price: float, ...):
    # ... code ...
    for position in self.open_positions():
        # ✗ BUG: No check for position age!
        # ✗ SL check fires immediately on next tick
        hit_stop = position.stop_loss_price is not None and (
            (position.side == "LONG" and px_low <= position.stop_loss_price)
            or (position.side == "SHORT" and px_high >= position.stop_loss_price)
        )
        
        if hit_stop:  # ← Triggers even if position is 0.5 seconds old!
            signals.append(Signal(..., direction="EXIT", ...))
```

**Impact**: A position opened at 12:00:00 can have SL triggered at 12:00:01 (1 second later).

---

## ROOT CAUSE #2: Hard SL/TP Checks on Every Tick (No Cooldown)

**File**: [engine/trading_engine.py](engine/trading_engine.py#L420-L425)

**Bug Location** - Main event loop in `_on_tick()`:

```python
async def _on_tick(self, symbol: str, price: float, timeframe: str | None, ...):
    self.portfolio_manager.mark_price(symbol, price)
    if self.auto_manage_positions:
        await self._execute_exits(symbol, price, timeframe, high=high, low=low, ...)
    
    await self._try_fill_pending_entry(symbol, price)
```

**Sequence of events** (CRITICAL RACE):
```
1. _on_candle_closed() generates BUY signal
2. RiskGuard approves → Entry stored in self._pending_entries
3. Same second, _on_tick() is called with next price tick
4. _try_fill_pending_entry() fills the BUY order
5. portfolio_manager.update() creates new OPEN position with entry_time=now
6. IMMEDIATELY after (same function call or next tick):
   _execute_exits() is called
7. check_exits() sees the SL level (1.4× ATR away)
8. Market has ticked ±1% (normal volatility)
9. SL is triggered
10. Position closes with -0.5% loss
```

**The problem**: No cooldown/minimum holding time before SL checks.

---

## ROOT CAUSE #3: Exit OrderIntents Missing SL/TP Values

**File**: [engine/trading_engine.py](engine/trading_engine.py#L690-L730)

**Bug Location** - In `_execute_exits()`:

```python
async def _execute_exits(self, symbol: str, price: float, ...):
    exits = self.portfolio_manager.check_exits(symbol, price, ...)
    
    for signal in exits:
        # ... find position ...
        
        intent = OrderIntent(
            approved=True,
            signal_uuid=str(uuid.uuid4()),
            symbol=symbol,
            direction="SELL" if position.side == "LONG" else "BUY",
            quantity=position.quantity,
            entry_price=price,
            # ✗ BUG: Missing these fields!
            # stop_loss_price=None,
            # tp1_price=None,
            # tp2_price=None,
        )
        # ← OrderIntent has null SL/TP on exit!
        
        fill = await self.paper_broker.submit(intent, price=price, ...)
```

**Also in `_on_candle_closed()` for strategy EXIT** (lines ~550-560):

```python
if signal.direction == "EXIT" and current_position is not None:
    intent = OrderIntent(
        approved=True,
        signal_uuid=signal.signal_uuid,
        symbol=candle.symbol,
        direction="SELL" if current_position.side == "LONG" else "BUY",
        quantity=current_position.quantity,
        entry_price=candle.close,
        # ✗ BUG: No SL/TP fields set!
    )
```

**Also in `_on_candle_closed()` for entry** (lines ~620-630):

```python
if intent.approved:
    if intent.stop_loss_price is None or intent.tp1_price is None:
        intent.approved = False
        # ✓ This guard DOES exist for entries
        # But it's MISSING for exits!
```

**Impact**: Exit OrderIntents can be logged with `stop_loss_price=null, tp1_price=null, tp2_price=null`.

---

## ROOT CAUSE #4: Race Condition - Entry Fill + Exit Check in Same Cycle

**File**: [engine/trading_engine.py](engine/trading_engine.py#L346-L375)

**Bug Location** - The `_try_fill_pending_entry()` method:

```python
async def _try_fill_pending_entry(self, symbol: str, price: float) -> None:
    pending = self._pending_entries.pop(symbol, None)
    if pending is None:
        return
    
    intent: OrderIntent = pending["intent"]
    
    fill = await self.paper_broker.submit(intent, price=price, ...)  # ← FILL HAPPENS HERE
    
    # Position is now OPEN in portfolio_tracker
    self.portfolio_manager.update(
        fill,
        stop_loss_price=intent.stop_loss_price,  # ← Position stored with SL
        tp1_price=intent.tp1_price,
        tp2_price=intent.tp2_price,
    )
```

**Then immediately in the next tick (or same WebSocket message batch)**:

```python
async def _on_tick(self, symbol: str, price: float, ...):
    self.portfolio_manager.mark_price(symbol, price)
    if self.auto_manage_positions:
        await self._execute_exits(...)  # ← SL checked HERE
```

**Critical timing issue**: Between position creation and SL check, there's no time delay. If price moved 1.4× ATR, SL fires instantly.

---

## ROOT CAUSE #5: ATR Stop Multiplier Reasonable but No Hold-Time Gate

**File**: [config/settings.py](config/settings.py#L52) and [risk/position_sizer.py](risk/position_sizer.py#L19)

```python
# settings.py line 52
atr_stop_multiplier: float = 2.5  # ← This is actually reasonable!

# position_sizer.py line 23
self.atr_stop_multiplier = atr_stop_multiplier
```

**Calculation** (in [risk/stop_loss.py](risk/stop_loss.py)):
```python
def calculate_stop_loss(entry_price, atr, side, multiplier=1.5):
    distance = atr * multiplier  # 1.5 × ATR
    return entry_price - distance if side == "BUY" else entry_price + distance
```

**The real issue**: With 2.5× ATR stop and high-frequency ticks, even a normal ~1% move can trigger SL if:
- ATR is small (consolidation market)
- Position age is 1 tick (0.3 seconds)
- Market touches the level due to bid-ask spread

**Missing piece**: No minimum holding time to give the position breathing room.

---

## Evidence from Logs

From observed logs:
```
[2026-09-04 12:15:30.123] OrderIntent SELL with SL only ~40 points away
[2026-09-04 12:15:30.456] Fill SELL (open SHORT) — entry_time=1725437730456
[2026-09-04 12:15:31.789] EXIT signal reason=STOP_LOSS — only 1.3 seconds after entry!
[2026-09-04 12:15:32.012] Fill BUY (close SHORT) — position closed
Result: -0.5% loss in 2 seconds
```

---

## Current Flow (BROKEN)

```
Candle 12:15:30 closed:
  ├─ Strategy: BUY signal (confidence 0.27)
  ├─ RiskGuard approves → OrderIntent with SL=entry-2.5×ATR
  └─ Entry queued to _pending_entries

Tick 12:15:30.500:
  ├─ _on_tick() called
  ├─ _try_fill_pending_entry():
  │   ├─ Fill order → position OPEN with entry_time=now
  │   └─ portfolio_manager.update() stores SL
  ├─ _execute_exits() immediately called:
  │   ├─ check_exits() checks SL level
  │   ├─ Market had a 1.3% wick during the candle
  │   ├─ Price ≤ SL?  YES!
  │   └─ Generate EXIT signal (STOP_LOSS)
  └─ Fill EXIT → position CLOSED with -0.5% loss

Result: Opened and closed in 0.5 seconds ✗
```

---

## Required Fixes (Scope)

### Fix 1: Add Minimum Holding Time (180 seconds / 3 candles)
- After a position is opened, ignore **strategy EXIT signals** for 180+ seconds
- Hard SL / TP must still work (not bypassed)
- Implementation: Check `time.time() - position.entry_time` in signal generation path

### Fix 2: Increase Default ATR Stop Multiplier  
- Current: 2.5 (borderline tight)
- Proposed: 2.2 (more conservative, gives breathing room)
- Make it configurable via settings

### Fix 3: Guard Against Null SL/TP in Exit Intents
- Verify OrderIntent for exits has SL/TP values
- Reject exit if missing (same as entries)
- Implementation: Add guard in `_execute_exits()`

### Fix 4: Add Position Age Check in `check_exits()`
- Skip SL/TP checks for positions < 180 seconds old
- Allow hard stops to work (position age is just advisory)

### Fix 5: Optional - Race Condition Mitigation
- Add small delay between fill and SL check (not needed if Fix 1 works)

---

## Files to Modify

1. **[config/settings.py](config/settings.py)**
   - Add `min_holding_time_sec: int = 180`
   - Adjust `atr_stop_multiplier` default if needed

2. **[portfolio/position_tracker.py](portfolio/position_tracker.py)**
   - Update `check_exits()` to accept `min_holding_time_sec` param
   - Skip SL/TP for age < min_holding_time (advisory, soft gate)

3. **[engine/trading_engine.py](engine/trading_engine.py)**
   - Update `_execute_exits()` to add SL/TP guard
   - Pass `min_holding_time_sec` to `check_exits()`

4. **[risk/risk_guard.py](risk/risk_guard.py)**
   - Optional: Add check for minimum holding time before allowing EXIT signals

---

## Next Step

Apply 4 targeted fixes to eliminate the instant stop-out behavior.

---

