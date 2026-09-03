# Security Fix: Broker Volume Floor Applied After Risk Admission

## Vulnerability Summary

**Title:** Broker volume floor is applied after risk admission

**Severity:** High

**Impact:** Safety control bypass allowing orders to exceed validated exposure limits

## Root Cause

The vulnerability existed in the order execution flow where:

1. `ScalperBrain._calculate_lot_size()` calculated position size with hardcoded `min_vol=0.01`
2. Main loop validated the calculated `lot_size` with `validate_fat_finger()` and other risk checks
3. `ExecutionPlane.execute_admitted_order()` forwarded the validated `lot_size` to the connector
4. `MT5Connector.execute_order()` applied `max(vol_min, ...)` to increase volume to broker minimum **AFTER** validation
5. `SimulatorConnector.execute_order()` stored the original unmodified `lot_size`

This created a safety control bypass where:
- An order validated at 0.01 lots could be submitted at 1.0 lot (100x exposure increase)
- The simulator recorded 0.01 lots while live trading executed 1.0 lot
- Risk checks (fat-finger, notional limits) were bypassed for the actual executed volume

## Fix Implementation

### 1. Added `get_symbol_volume_constraints()` Method

Added new abstract method to `TradingConnector` base class:

```python
@abc.abstractmethod
def get_symbol_volume_constraints(self, symbol):
    """
    Returns broker volume constraints for the symbol.
    Returns: { 'volume_min': float, 'volume_max': float, 'volume_step': float }
    
    SECURITY: This method must be called BEFORE risk validation to ensure
    that fat-finger checks and notional limits are applied to the actual
    volume that will be submitted to the broker, not a smaller pre-normalized value.
    """
```

Implemented in all connector classes:
- `MT5Connector.get_symbol_volume_constraints()` - Queries live MT5 broker constraints
- `SimulatorConnector.get_symbol_volume_constraints()` - Returns standard constraints
- `UniversalConnector.get_symbol_volume_constraints()` - Routes to appropriate backend
- `UniversalBrokerGateway.get_symbol_volume_constraints()` - Queries broker via protocol

### 2. Updated `execute_order()` Contract

Modified `execute_order()` documentation to enforce pre-normalization:

```python
@abc.abstractmethod
def execute_order(self, symbol, order_type, lot_size, sl, tp):
    """
    Places a trade order.
    order_type: 'BUY' or 'SELL'
    
    SECURITY: lot_size MUST be pre-normalized to broker constraints before calling
    this method. This method MUST NOT modify lot_size to prevent bypassing
    fat-finger and risk admission checks.
    
    Returns: { 'success': bool, 'ticket': str, 'price': float, 'error': str }
    """
```

### 3. Removed Post-Validation Normalization from MT5Connector

**Before (vulnerable code):**
```python
def execute_order(self, symbol, order_type, lot_size, sl, tp):
    # ...
    # Query live broker volume constraints to avoid [Invalid volume] errors
    info = self.mt5.symbol_info(symbol)
    if info is not None:
        vol_min = getattr(info, "volume_min", 0.01) or 0.01
        vol_max = getattr(info, "volume_max", 500.0) or 500.0
        vol_step = getattr(info, "volume_step", 0.01) or 0.01
    else:
        vol_min, vol_max, vol_step = 0.01, 500.0, 0.01

    volume = float(lot_size)
    if vol_step > 0:
        steps = math.floor((volume - vol_min) / vol_step + 1e-9) if volume >= vol_min else 0
        volume = vol_min + (steps * vol_step)

    volume = max(vol_min, min(vol_max, round(volume, 4)))  # ← SECURITY BYPASS
    # ...
```

**After (fixed code):**
```python
def execute_order(self, symbol, order_type, lot_size, sl, tp):
    """
    SECURITY FIX: lot_size MUST be pre-normalized to broker constraints before calling.
    This method no longer modifies lot_size to prevent bypassing fat-finger checks.
    """
    # ...
    # SECURITY FIX: Use lot_size as-is without modification
    # Volume normalization must happen BEFORE risk validation in the main loop
    volume = float(lot_size)
    # ...
```

### 4. Added Pre-Validation Normalization in Main Loop

**Added to main.py before fat-finger validation:**

```python
# SECURITY FIX: Normalize lot_size to broker constraints BEFORE validation
# This ensures fat-finger checks and notional limits are applied to the
# actual volume that will be submitted, preventing safety control bypass
constraints = self.conn.get_symbol_volume_constraints(symbol)
vol_min = constraints["volume_min"]
vol_max = constraints["volume_max"]
vol_step = constraints["volume_step"]

# Apply broker volume constraints
normalized_lot_size = max(vol_min, min(vol_max, float(lot_size)))
if vol_step > 0:
    steps = round((normalized_lot_size - vol_min) / vol_step)
    calc_lots = vol_min + steps * vol_step
    step_str = f"{vol_step:.8f}".rstrip("0")
    precision = len(step_str.split(".")[1]) if "." in step_str else 0
    normalized_lot_size = round(calc_lots, precision)
    normalized_lot_size = max(vol_min, min(vol_max, normalized_lot_size))

# Log volume adjustment if it occurred
if abs(normalized_lot_size - lot_size) > 0.001:
    _log.info(
        "Volume normalized for %s: %.4f -> %.4f (broker min=%.4f)",
        symbol, lot_size, normalized_lot_size, vol_min
    )

# Use normalized volume for all subsequent checks and execution
lot_size = normalized_lot_size

# E. Fat-Finger checking (now validates the actual volume to be submitted)
if not self.engine.execution.validate_fat_finger(symbol, lot_size, feed_price):
    # ...
```

## Security Benefits

1. **Prevents Safety Control Bypass**: Fat-finger checks and notional limits now validate the actual volume that will be submitted to the broker

2. **Eliminates Exposure Divergence**: Both simulator and live execution use the same normalized volume, preventing paper/live exposure mismatch

3. **Maintains Risk Invariants**: All risk admission checks (fat-finger, notional limits, position sizing) operate on the true execution volume

4. **Audit Trail**: Volume adjustments are logged for compliance and debugging

5. **Defense in Depth**: Multiple layers enforce the constraint:
   - Abstract base class contract documents the requirement
   - Main loop performs normalization before validation
   - Connectors no longer modify volume after validation
   - Test suite verifies the fix

## Testing

Created comprehensive test suite in `test_volume_normalization.py`:

1. **test_volume_normalized_before_fat_finger_check**: Verifies volume is normalized before validation
2. **test_simulator_uses_same_volume_as_live**: Ensures simulator stores normalized volume
3. **test_fat_finger_check_blocks_excessive_normalized_volume**: Validates risk checks work on normalized volume
4. **test_mt5_connector_does_not_modify_volume**: Confirms execute_order doesn't modify volume

## Files Modified

1. **connector.py**:
   - Added `get_symbol_volume_constraints()` to `TradingConnector` abstract base class
   - Implemented `get_symbol_volume_constraints()` in `UniversalConnector`, `MT5Connector`, and `SimulatorConnector`
   - Removed post-validation volume normalization from `MT5Connector.execute_order()`
   - Updated `execute_order()` documentation with security requirements

2. **institutional_integrations/universal_broker_adapter.py**:
   - Added `get_symbol_volume_constraints()` to `UniversalBrokerGateway`

3. **main.py**:
   - Added pre-validation volume normalization in main trading loop
   - Added logging for volume adjustments
   - Added module-level logger

4. **test_volume_normalization.py** (new):
   - Comprehensive security test suite

## Deployment Notes

- **Backward Compatible**: The fix maintains all existing functionality while closing the security gap
- **No Configuration Changes**: No config file updates required
- **Logging**: Volume adjustments are logged at INFO level for monitoring
- **Performance**: Minimal performance impact (one additional method call per order)

## Verification

To verify the fix is working:

1. Run the test suite: `python -m pytest test_volume_normalization.py -v`
2. Monitor logs for volume normalization messages when trading symbols with high broker minimums
3. Compare simulator and live execution volumes - they should now match
4. Verify fat-finger checks block orders at the normalized volume, not the pre-normalized volume

## References

- Original vulnerability report: "Broker volume floor is applied after risk admission"
- Related code: `ScalperBrain._calculate_lot_size()`, `ExecutionPlane.validate_fat_finger()`, `MT5Connector.execute_order()`
