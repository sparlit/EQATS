# Security Fix: Fail-Open Broker Adapter Vulnerability

## Vulnerability Summary

**Title:** Fail-open broker adapter records orders that were never submitted

**Severity:** High

**Impact:** A misconfigured or unsupported live trading deployment could continue with phantom positions, missing protective orders, and corrupted reconciliation/risk state instead of failing closed.

## Root Cause

The `UniversalBrokerGateway` had three critical fail-open vulnerabilities:

1. **Unconditional Connection Success**: The `connect()` method unconditionally set `is_connected_flag=True` for REST-like protocols (REST_WS, CCXT, CTRADER, IBKR) without validating that a `rest_url` endpoint was configured.

2. **Synthetic Success in Fallback**: The `execute_order()` method had a fallback path that returned `success=True` with a synthetic ticket and zero price when no concrete execution branch applied. This occurred when:
   - REST-like protocols were configured without `rest_url`
   - Unsupported protocols were used
   - Any protocol that didn't match MT5, FIX, or REST branches

3. **No Protocol Validation**: Unsupported protocols were not rejected at initialization, allowing them to reach the fail-open fallback.

## Attack Scenario

1. Deploy with REST_WS protocol but omit `rest_url` configuration
2. System connects successfully (fail-open)
3. Trading signals trigger order execution
4. `execute_order()` skips REST submission branch (no `rest_url`)
5. Fallback returns synthetic success with ticket `UNI_<timestamp>`
6. Circuit breaker records success
7. `UniversalConnector` accepts the response as a real order
8. `ExecutionPlane` publishes `OrderAccepted` and `PositionOpened` events
9. System continues trading with phantom positions
10. Risk management operates on corrupted state
11. Real capital exposure diverges from system state

## Fix Implementation

### 1. Protocol Validation at Initialization (`__init__`)

**Location:** `institutional_integrations/universal_broker_adapter.py`, lines 55-66

**Change:** Added validation to reject unsupported protocols at initialization:

```python
# Validate protocol is supported before initialization
if self.protocol not in self.SUPPORTED_PROTOCOLS:
    _log.error(
        "UniversalBrokerGateway: Unsupported protocol '%s' specified. "
        "Supported protocols: %s",
        self.protocol,
        ", ".join(self.SUPPORTED_PROTOCOLS)
    )
    raise ValueError(
        f"Unsupported protocol '{self.protocol}'. "
        f"Supported protocols: {', '.join(self.SUPPORTED_PROTOCOLS)}"
    )
```

**Impact:** Prevents unsupported protocols from being instantiated, failing fast at configuration time.

### 2. REST Endpoint Validation in `connect()`

**Location:** `institutional_integrations/universal_broker_adapter.py`, lines 211-235

**Change:** Added validation for REST-like protocols to require `rest_url`:

```python
# REST_WS, IBKR, CTRADER, CCXT protocol interfaces require rest_url
if self.protocol in ["REST_WS", "IBKR", "CTRADER", "CCXT"]:
    # Validate that rest_url is configured for REST-like protocols
    if not hasattr(self, "rest_url") or not self.rest_url:
        _log.error(
            "UniversalBrokerGateway: Protocol %s requires 'rest_url' configuration. "
            "Connection rejected to prevent fail-open execution.",
            self.protocol
        )
        print(
            f"Universal Broker Gateway [{self.protocol}] Connection Error: "
            f"'rest_url' must be configured for protocol {self.protocol}. "
            f"Cannot establish connection without valid endpoint."
        )
        self.is_connected_flag = False
        return False
    
    # Endpoint is configured, mark as connected
    self.is_connected_flag = True
    print(
        f"Universal Broker Gateway: Connected via protocol [{self.protocol}] "
        f"for Broker [{self.broker_config.get('broker_name', 'Default')}] "
        f"at endpoint {self.rest_url}"
    )
    return True
```

**Impact:** Prevents REST-like protocols from connecting without a valid endpoint, ensuring orders cannot be submitted without a real broker connection.

### 3. Unsupported Protocol Rejection in `connect()`

**Location:** `institutional_integrations/universal_broker_adapter.py`, lines 237-250

**Change:** Added explicit rejection for protocols that don't match any supported branch:

```python
# Reject unsupported protocols to prevent fail-open fallback
_log.error(
    "UniversalBrokerGateway: Unsupported protocol '%s'. "
    "Supported protocols: %s. Connection rejected.",
    self.protocol,
    ", ".join(self.SUPPORTED_PROTOCOLS)
)
print(
    f"Universal Broker Gateway Connection Error: "
    f"Protocol '{self.protocol}' is not supported. "
    f"Supported protocols: {', '.join(self.SUPPORTED_PROTOCOLS)}"
)
self.is_connected_flag = False
return False
```

**Impact:** Provides defense-in-depth by catching any protocols that bypass initialization validation.

### 4. Fail-Closed Fallback in `execute_order()`

**Location:** `institutional_integrations/universal_broker_adapter.py`, lines 576-591

**Change:** Replaced synthetic success with explicit failure:

**Before:**
```python
# Fallback / Generic execution payload acknowledgment
ticket = f"UNI_{int(time.time() * 1000)}"
self._breaker.record_success()
return {
    "success": True,
    "ticket": ticket,
    "price": 0.0,
    "error": "",
    "protocol": self.protocol,
}
```

**After:**
```python
# Fail-closed: No valid execution path was taken
# This prevents phantom orders when rest_url is missing or protocol is misconfigured
_log.error(
    "UniversalBrokerGateway: Order execution failed - no valid execution path for protocol %s. "
    "This indicates a configuration error (missing rest_url) or unsupported protocol.",
    self.protocol
)
self._breaker.record_failure()
return {
    "success": False,
    "ticket": "",
    "price": 0.0,
    "error": f"No valid execution path for protocol {self.protocol}. Check configuration.",
    "reason": "CONFIGURATION_ERROR",
    "protocol": self.protocol,
}
```

**Impact:** Ensures that any order reaching the fallback path fails explicitly, preventing phantom positions.

## Testing

Added comprehensive tests in `test_circuit_breaker.py`:

### Test 1: `test_universal_broker_gateway_fail_closed_without_rest_url()`

Tests that REST-like protocols (REST_WS, CCXT, IBKR, CTRADER) without `rest_url`:
- Fail to connect
- Return `success=False` on order execution
- Return `reason="CONFIGURATION_ERROR"`
- Do not generate synthetic tickets

### Test 2: `test_universal_broker_gateway_rejects_unsupported_protocol()`

Tests that unsupported protocols:
- Raise `ValueError` at initialization
- Include protocol name and supported protocols in error message

## Security Properties

After this fix, the system enforces the following security properties:

1. **Fail-Closed by Default**: Any misconfiguration or unsupported protocol results in explicit failure rather than synthetic success.

2. **Early Validation**: Protocol and endpoint validation occurs at initialization and connection time, failing fast before any trading operations.

3. **No Phantom Orders**: Orders cannot be recorded as successful without actual broker submission.

4. **Circuit Breaker Integrity**: The circuit breaker only records success for real broker operations, not synthetic fallbacks.

5. **State Consistency**: The execution plane and risk management systems operate on accurate state, as phantom positions cannot be created.

## Deployment Considerations

### Breaking Changes

This fix introduces intentional breaking changes for misconfigured deployments:

1. **REST-like protocols without `rest_url`**: Will now fail to connect instead of silently accepting orders.
2. **Unsupported protocols**: Will now raise `ValueError` at initialization instead of falling back to synthetic success.

### Migration Path

For existing deployments:

1. **Verify Configuration**: Ensure all REST-like protocols (REST_WS, CCXT, CTRADER, IBKR) have `rest_url` configured.
2. **Validate Protocols**: Ensure only supported protocols are used: MT5, FIX, REST_WS, IBKR, CTRADER, CCXT, SIMULATOR.
3. **Test Connection**: Verify that `connect()` returns `True` before deploying to production.
4. **Monitor Logs**: Watch for "Connection Error" or "CONFIGURATION_ERROR" messages indicating misconfiguration.

### Backward Compatibility

The fix maintains backward compatibility for correctly configured deployments:

- **MT5**: No changes to behavior
- **FIX**: No changes to behavior
- **SIMULATOR**: No changes to behavior
- **REST-like protocols with valid `rest_url`**: No changes to behavior

Only misconfigured or unsupported deployments will experience breaking changes, which is the intended security improvement.

## Verification

To verify the fix is working:

1. **Run Tests**: Execute `pytest test_circuit_breaker.py::test_universal_broker_gateway_fail_closed_without_rest_url`
2. **Check Logs**: Look for "Connection rejected to prevent fail-open execution" messages
3. **Monitor Circuit Breaker**: Verify that configuration errors increment failure count, not success count
4. **Validate State**: Confirm that no phantom positions are created in the execution plane

## References

- **Pentest Finding**: Line 344 in `institutional_integrations/universal_broker_adapter.py`
- **Root Cause**: Fail-open fallback in `execute_order()` and unconditional connection success in `connect()`
- **Fix Locations**: 
  - `__init__()`: Lines 55-66
  - `connect()`: Lines 211-250
  - `execute_order()`: Lines 576-591
- **Tests**: `test_circuit_breaker.py`: Lines 129-195
