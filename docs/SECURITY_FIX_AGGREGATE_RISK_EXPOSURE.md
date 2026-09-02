# Security Fix: Aggregate Risk Exposure Calculation

## Issue Summary
The order-admission path was approving trades using `RISK_PER_TRADE_PERCENT × position count`, while the order's actual lot size, stop distance, instrument value, and broker-normalized volume were not included in the aggregate-risk calculation. This could result in stop-out losses materially exceeding `GLOBAL_RISK_LIMIT_CAP_PERCENT` while admission checks passed.

## Root Cause
1. **Count-based risk calculation**: Both `evaluate_invariants()` and the global-cap comparison derived risk from `RISK_PER_TRADE_PERCENT` and the number of positions rather than from executable volume, entry price, stop-loss distance, tick size, and tick value.

2. **Separate lot sizing**: The actual `lot_size` and `sl` were calculated in `brain.py` using complex formulas including:
   - Equity-based risk amount
   - Symbol-specific pip specifications
   - Kelly criterion (0.25 fractional)
   - Sub-allocation modifiers
   - Minimum lot floors per asset class

3. **No exposure validation**: The reservation recorded only `RISK_PER_TRADE_PERCENT`; no later check recomputed aggregate stop-loss exposure before routing the order.

## Fix Implementation

### 1. New Exposure Calculation Function (`eqats_planes.py`)
Added `calculate_stop_loss_exposure()` function that:
- Calculates actual monetary stop-loss exposure as a percentage of equity
- Takes into account: symbol, lot_size, entry_price, stop_loss, and current equity
- Uses symbol-specific pip specifications (Forex, JPY pairs, Gold, Silver, Crypto, Indices)
- Returns exposure as percentage of equity

### 2. Updated Safety Invariant Evaluation (`eqats_planes.py`)
Modified `evaluate_invariants()` to:
- Accept new optional parameter `actual_aggregate_exposure_pct`
- Use actual exposure for INV-001 check when provided
- Fall back to count-based calculation for backward compatibility
- Compare actual exposure against `RISK_PER_TRADE_PERCENT * MAX_CONCURRENT_TRADES`

### 3. Updated Order Admission Logic (`main.py`)
Modified the trade admission path to:
- Calculate aggregate exposure from all existing positions
- Calculate proposed order's exposure using actual lot size and stop-loss
- Sum existing and proposed exposure for total portfolio exposure
- Pass actual exposure to `evaluate_invariants()`
- Use actual exposure for global risk cap check
- Reserve actual exposure amount instead of configured percentage
- Log exposure calculations for audit trail
- Fall back to count-based calculation if actual exposure cannot be determined

## Security Benefits

1. **Accurate Risk Measurement**: Aggregate risk now reflects actual monetary exposure, not just position count.

2. **Multi-Asset Protection**: Different asset classes (Forex, Crypto, Indices) with varying contract values and minimum lots are properly accounted for.

3. **Stop-Loss Distance Awareness**: Wide stop-losses on volatile instruments are properly weighted in risk calculations.

4. **Broker Normalization Handling**: Minimum lot requirements and volume steps are factored into exposure calculations.

5. **Multiple Signal Protection**: Multiple signals from the same scan with different lot sizes are properly aggregated.

## Backward Compatibility

- Existing tests continue to work as the new parameter is optional
- Count-based calculation is retained as fallback when actual exposure cannot be calculated
- Legacy code paths remain functional for systems that don't provide stop-loss information

## Testing Recommendations

1. Test with minimum lot sizes (e.g., XRP at 1.0 lot minimum)
2. Test with wide stop-losses on volatile instruments
3. Test with multiple concurrent positions across different asset classes
4. Verify that aggregate exposure correctly blocks orders when limit is reached
5. Verify fallback to count-based calculation when stop-loss is unavailable

## Configuration Impact

No configuration changes required. The fix uses existing configuration values:
- `RISK_PER_TRADE_PERCENT`: Still used as the per-trade risk target
- `MAX_CONCURRENT_TRADES`: Still used to calculate maximum allowed aggregate exposure
- `GLOBAL_RISK_LIMIT_CAP_PERCENT`: Now enforced using actual exposure

## Deployment Notes

- No database schema changes required
- No API changes required
- Logging added for exposure calculations (INFO level)
- Warnings logged when fallback to count-based calculation occurs
