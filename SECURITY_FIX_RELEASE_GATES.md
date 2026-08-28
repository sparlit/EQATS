# Security Fix: ReleaseGateRunner Live Broker Order Prevention

## Vulnerability Summary
The `ReleaseGateRunner` class accepted arbitrary caller-supplied connectors and unconditionally invoked order-placement methods during G11 validation, allowing live-capable connectors to execute real broker trades during release validation.

## Root Cause
1. **Constructor bypass**: The `__init__` method accepted any connector without validation
2. **Direct execution**: G11 called `self.conn.execute_order()` directly without safety checks
3. **Missing validation**: No verification of `config.DEMO_ACCOUNT_ONLY` or connector demo status
4. **Ignored failures**: G11 returned success even when execution or cleanup failed
5. **No admission control**: Did not use the safe `execute_admitted_order()` path

## Security Fix Implementation

### 1. Constructor-Level Enforcement (Lines 16-34)
Added mandatory connector safety validation in `__init__`:
- Rejects any supplied connector that is not verified as safe
- Raises `PermissionError` with explicit security message
- Prevents live connectors from being used at instantiation time

### 2. Connector Safety Validation (Lines 36-62)
Implemented `_is_safe_connector()` method with defense-in-depth checks:
- **Layer 1**: Verify `isinstance(conn, connector.SimulatorConnector)` (always safe)
- **Layer 2**: Check `isinstance(conn, connector.MT5Connector)` with `demo_only=True`
- **Layer 3**: Verify `is_demo` attribute is `True`
- **Layer 4**: Query `get_account_info()` and check `is_demo` flag
- **Default**: Fail-safe to `False` if verification cannot be completed

### 3. G11 Security Hardening (Lines 231-291)
Completely rewrote `_check_g11_independent_execution_verification()`:

**Security Enforcement:**
- Double-check connector safety before any execution
- Verify `config.DEMO_ACCOUNT_ONLY=True` when not in `SIMULATION_MODE`
- Return explicit security violation failures

**Proper Execution Validation:**
- Wrap execution in try-except to catch exceptions
- Validate execution success before proceeding
- Verify ticket is returned
- Check order is retrievable via `get_open_orders()`
- Validate all order parameters match request (symbol, direction, lot_size)
- Verify cleanup succeeds via `close_order()`
- Return failure if any step fails (no silent success)

**Cleanup Guarantee:**
- Always attempt to close test order, even on validation failure
- Verify close operation succeeds
- Report cleanup failures explicitly

## Security Properties

### Defense in Depth
1. **Constructor gate**: Blocks unsafe connectors at instantiation
2. **Runtime gate**: Re-validates connector safety in G11
3. **Config gate**: Enforces `DEMO_ACCOUNT_ONLY` setting
4. **Type gate**: Multiple layers of connector type checking

### Fail-Safe Design
- Unknown connector types are rejected (not allowed)
- Verification failures default to unsafe
- Execution failures are reported, not hidden
- Cleanup failures cause gate failure

### Explicit Security Violations
- Clear error messages identify security blocks
- Distinguishes security failures from functional failures
- Provides actionable guidance in error messages

## Testing
Created comprehensive test suite in `test_release_gates_security.py`:
- Tests live connector blocking in constructor
- Tests simulator connector acceptance
- Tests demo connector acceptance
- Tests G11 security enforcement
- Tests G11 parameter validation
- Tests G11 cleanup verification
- Tests failure modes and error handling

## Impact
- **Breaking Change**: Code that previously passed live connectors to `ReleaseGateRunner` will now raise `PermissionError`
- **Backward Compatible**: Default behavior (no connector supplied) unchanged
- **Safe Connectors**: `SimulatorConnector` and demo-only connectors continue to work
- **Production Safety**: Prevents accidental real trades during CI/CD validation

## Verification
The fix ensures:
1. ✅ Live connectors cannot be used for release validation
2. ✅ G11 validates execution logic without real broker risk
3. ✅ All execution failures are properly reported
4. ✅ Test orders are always cleaned up
5. ✅ Security violations are explicit and actionable
6. ✅ Multiple layers of defense prevent bypass
