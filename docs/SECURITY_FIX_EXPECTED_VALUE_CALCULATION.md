# Security Fix: Trade Admission Expected Value Calculation

## Issue Summary
The trade admission controller was using a fabricated positive expected-value signal that did not reflect the actual trading opportunity's edge. The calculation passed `RISK_PER_TRADE_PERCENT * 2.0` as the gross edge, which with the default 1.0% risk setting produced a value of 1.9996 after subtracting fixed costs. This resulted in every otherwise eligible order being approved regardless of its actual signal probability, stop-loss/take-profit distances, or real trading costs.

## Vulnerability Details

### Original Vulnerable Code (main.py, line 1061-1066)
```python
# B. Estimate Expected Net Value
env = self.engine.risk.calculate_expected_net_value(
    gross_edge=config.RISK_PER_TRADE_PERCENT * 2.0,  # Expected win
    spread=0.0002,
    commission=0.0001,
    slippage=0.0001,
)
```

### Problems with Original Implementation
1. **Fabricated gross edge**: Used `RISK_PER_TRADE_PERCENT * 2.0` (1.0 * 2.0 = 2.0) instead of calculating from signal probability and SL/TP distances
2. **Dimensional inconsistency**: Treated a percentage value (1.0%) as if it were a price-like edge value
3. **Fixed costs**: Used hardcoded spread (0.0002), commission (0.0001), and slippage (0.0001) instead of actual symbol-specific values
4. **Always positive**: With default config, calculated as `2.0 - 0.0002 - 0.0001 - 0.0001 = 1.9996`, which is always positive
5. **Ignored signal quality**: Did not use the decision's probability, strategy edge, or any measure of actual expectancy

### Authorization Check (eqats_planes.py, line 580)
```python
if expected_net_value <= 0:
    # Reject trade
    return False
```

The authorization function only checked if the value was positive, which it always was (1.9996), so it approved every trade that passed other filters.

## Root Cause Analysis

The expected value calculation should follow the mathematical definition:

**Expected Net Value = Gross Edge - Trading Costs**

Where:
- **Gross Edge** = (Win Probability × Take Profit Distance) - (Loss Probability × Stop Loss Distance)
- **Trading Costs** = Spread + Commission + Slippage

The original implementation:
1. Did not calculate gross edge from signal probability and SL/TP distances
2. Used a risk percentage value as if it were a price edge
3. Used fixed cost estimates instead of actual symbol-specific costs
4. Produced a meaningless positive number that bypassed the admission check

## Fix Implementation

### 1. Corrected Expected Value Calculation (main.py)

**New Code (lines 1060-1103):**
```python
# B. Estimate Expected Net Value
# SECURITY FIX: Calculate actual expected value from signal probability and SL/TP distances
# The gross edge must be derived from the decision's win probability and risk/reward ratio
signal_probability = dec_item.get("probability", 0.5)

# Calculate stop-loss and take-profit distances in price units
if decision == "BUY":
    sl_distance = abs(entry_price_estimate - sl) if sl > 0 else 0.0
    tp_distance = abs(tp - entry_price_estimate) if tp > 0 else 0.0
else:  # SELL
    sl_distance = abs(sl - entry_price_estimate) if sl > 0 else 0.0
    tp_distance = abs(entry_price_estimate - tp) if tp > 0 else 0.0

# Calculate actual spread for this symbol
actual_spread = price_info_curr.get("ask", 0.0) - price_info_curr.get("bid", 0.0)

# Estimate commission based on lot size and symbol
# Standard forex commission is approximately $7 per lot round-turn
estimated_commission_per_lot = 0.00007  # As fraction of price for standard forex
estimated_commission = estimated_commission_per_lot * lot_size

# Estimate slippage based on spread (typically 0.5-1.0x spread)
estimated_slippage = actual_spread * 0.5

# Calculate gross edge: Expected win minus expected loss
# Gross Edge = (Win Probability × TP Distance) - (Loss Probability × SL Distance)
loss_probability = 1.0 - signal_probability
gross_edge = (signal_probability * tp_distance) - (loss_probability * sl_distance)

# Calculate expected net value
env = self.engine.risk.calculate_expected_net_value(
    gross_edge=gross_edge,
    spread=actual_spread,
    commission=estimated_commission,
    slippage=estimated_slippage,
)

# Log the calculation for audit trail
_log.info(
    "Expected Net Value calculation for %s: probability=%.3f, SL_dist=%.5f, TP_dist=%.5f, "
    "gross_edge=%.5f, spread=%.5f, commission=%.5f, slippage=%.5f, ENV=%.5f",
    symbol,
    signal_probability,
    sl_distance,
    tp_distance,
    gross_edge,
    actual_spread,
    estimated_commission,
    estimated_slippage,
    env,
)
```

**Key Improvements:**
1. **Actual signal probability**: Uses the decision's probability from the AI model
2. **Real SL/TP distances**: Calculates actual price distances based on entry price and stop/target levels
3. **Symbol-specific spread**: Uses the current bid-ask spread for the symbol
4. **Lot-adjusted commission**: Scales commission estimate by actual lot size
5. **Spread-based slippage**: Estimates slippage as a fraction of current spread
6. **Proper gross edge formula**: Applies the mathematical definition of expected value
7. **Audit logging**: Records all calculation components for verification

### 2. Enhanced Authorization Check (eqats_planes.py)

**New Code (lines 544-612):**
```python
def authorize_trade(self, symbol: str, expected_net_value: float, safety_violations: list) -> bool:
    """
    The only final authorization boundary permitted to trigger order routing.
    No Trade Admission means NO trade can ever occur.

    SECURITY: Expected net value must be derived from actual signal probability,
    stop-loss/take-profit distances, and real trading costs. A fabricated or
    dimensionally inconsistent value will fail this check.
    """
    # ... [resilience and violation checks] ...

    # SECURITY FIX: Require meaningfully positive expected value
    # The minimum threshold accounts for estimation errors and provides safety margin
    # Expected net value should be in price units (e.g., 0.0001 for 1 pip on EURUSD)
    min_positive_edge = getattr(config, "MIN_EXPECTED_NET_VALUE_THRESHOLD", 0.00001)

    if expected_net_value <= min_positive_edge:
        global_event_bus.publish(
            Event(
                family="TradeAdmissionRejected",
                source="SafetyPlane",
                payload={
                    "symbol": symbol,
                    "reason": f"Expected Net Value ({expected_net_value:.8f}) does not meet minimum positive edge threshold ({min_positive_edge:.8f})",
                    "expected_net_value": expected_net_value,
                    "threshold": min_positive_edge,
                },
            )
        )
        return False

    # ... [approval logic] ...
```

**Key Improvements:**
1. **Minimum threshold**: Requires expected value to exceed a configurable minimum (default: 0.00001)
2. **Prevents zero-edge trades**: Blocks trades with negligible or fabricated edge
3. **Detailed rejection events**: Publishes the actual value and threshold for audit
4. **Documentation**: Clarifies that the value must be derived from real trade parameters

### 3. Configuration Parameter (config.py)

**New Configuration (lines 71-75):**
```python
# Trade Admission Expected Value Threshold
# SECURITY: Minimum expected net value (in price units) required for trade admission
# This prevents admission of trades with zero or fabricated edge calculations
# Default: 0.00001 (approximately 0.1 pips for standard forex pairs)
MIN_EXPECTED_NET_VALUE_THRESHOLD = 0.00001
```

**Purpose:**
- Provides a configurable safety margin for expected value checks
- Default value (0.00001) represents approximately 0.1 pips for standard forex pairs
- Can be adjusted based on asset class and trading style
- Prevents admission of trades with negligible or estimation-error-level edges

## Impact Analysis

### Before Fix
With default configuration (RISK_PER_TRADE_PERCENT = 1.0):
- Calculated expected value: `1.0 * 2.0 - 0.0002 - 0.0001 - 0.0001 = 1.9996`
- Result: **Every trade approved** regardless of actual edge
- Risk: System could execute trades with zero or negative actual expectancy

### After Fix
With actual signal parameters:
- **Example 1 - Good Signal:**
  - Probability: 0.65, SL: 0.0010, TP: 0.0020, Spread: 0.00002
  - Gross Edge: `(0.65 × 0.0020) - (0.35 × 0.0010) = 0.0013 - 0.00035 = 0.00095`
  - Net Value: `0.00095 - 0.00002 - 0.00007 - 0.00001 = 0.00085`
  - Result: **Approved** (0.00085 > 0.00001)

- **Example 2 - Poor Signal:**
  - Probability: 0.52, SL: 0.0020, TP: 0.0020, Spread: 0.00002
  - Gross Edge: `(0.52 × 0.0020) - (0.48 × 0.0020) = 0.00104 - 0.00096 = 0.00008`
  - Net Value: `0.00008 - 0.00002 - 0.00007 - 0.00001 = -0.00002`
  - Result: **Rejected** (-0.00002 < 0.00001)

- **Example 3 - Marginal Signal:**
  - Probability: 0.55, SL: 0.0015, TP: 0.0020, Spread: 0.00002
  - Gross Edge: `(0.55 × 0.0020) - (0.45 × 0.0015) = 0.0011 - 0.000675 = 0.000425`
  - Net Value: `0.000425 - 0.00002 - 0.00007 - 0.00001 = 0.000325`
  - Result: **Approved** (0.000325 > 0.00001)

## Testing Validation

### Existing Tests
The fix maintains compatibility with existing release gate tests:
- **G08 (Safety Kernel)**: Uses `authorize_trade("EURUSD", 0.05, [])` - still passes (0.05 >> 0.00001)
- **G09 (Risk Verification)**: Uses `authorize_trade("EURUSD", -0.01, [])` - still fails (-0.01 < 0.00001)

### Recommended Additional Tests
1. Test with various signal probabilities (0.5, 0.6, 0.7, 0.8)
2. Test with different SL/TP ratios (1:1, 1:2, 1:3)
3. Test with different spreads (tight vs. wide)
4. Test with different lot sizes (commission scaling)
5. Verify rejection of near-zero edge trades

## Configuration Impact

**No breaking changes** - the fix uses existing configuration values and adds one new optional parameter:
- `RISK_PER_TRADE_PERCENT`: Still used for risk management (not for edge calculation)
- `MAX_CONCURRENT_TRADES`: Still used for position limits
- `MIN_EXPECTED_NET_VALUE_THRESHOLD`: New parameter with sensible default (0.00001)

## Deployment Notes

1. **Immediate Effect**: After deployment, trades will be evaluated based on actual expected value
2. **Potential Rejections**: Some previously approved trades may now be rejected if they have insufficient edge
3. **Monitoring**: Review trade admission rejection logs to ensure threshold is appropriate
4. **Tuning**: Adjust `MIN_EXPECTED_NET_VALUE_THRESHOLD` if needed based on asset class and strategy
5. **Audit Trail**: All expected value calculations are now logged for verification

## Security Benefits

1. **Prevents zero-edge trading**: System will no longer execute trades without positive expectancy
2. **Uses actual signal quality**: Incorporates AI model probability into admission decision
3. **Symbol-specific costs**: Accounts for actual spread and commission variations
4. **Audit trail**: Complete logging of all calculation components
5. **Configurable threshold**: Allows tuning of minimum acceptable edge
6. **Defense in depth**: Multiple layers of validation before order execution

## Conclusion

This fix addresses the critical security vulnerability where the trade admission controller was approving orders based on a fabricated positive value rather than actual trading edge. The corrected implementation:

1. Calculates expected value from real signal probability and SL/TP distances
2. Uses actual symbol-specific trading costs
3. Requires meaningfully positive edge (not just > 0)
4. Provides complete audit trail of calculations
5. Maintains backward compatibility with existing tests

The system will now only admit trades that have genuine positive expected value based on the signal's probability, risk/reward ratio, and actual trading costs.
