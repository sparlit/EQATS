## Security Fix: Non-idempotent REST Order Retry Mitigation

### Problem Summary
The REST execution path in `UniversalBrokerGateway.execute_order` constructed order payloads without any client-side order identifier or idempotency key. When a broker accepted an order but the response was lost due to timeout or network error, the retry logic would submit an identical request that created a duplicate order at the broker.

### Root Cause
1. **No Client Order ID**: The REST payload (lines 215-223) contained only trading parameters without any stable order identity
2. **No Reconciliation**: After timeout or exception, the code immediately retried without checking if the order was already accepted
3. **Duplicate Submission Risk**: The same `Request` object was submitted on both attempts, creating two distinct broker transactions

### Security Impact
- **Duplicate Orders**: Lost responses could cause double execution of the same logical trade
- **Financial Risk**: Unintended position doubling leading to excessive exposure
- **Compliance Issues**: Inability to track and reconcile orders accurately

### Solution Implemented

#### 1. Added UUID Import (Line 21)
```python
import uuid
```

#### 2. Created Order Reconciliation Method (Lines 194-234)
```python
def _reconcile_order_status(self, client_order_id):
    """
    Queries the broker to check if an order with the given client_order_id was accepted.
    Returns dict with 'found': bool, 'ticket': str, 'price': float if found.
    This prevents duplicate order submission after ambiguous timeout.
    """
```

This method:
- Queries the broker's order status endpoint with the `client_order_id`
- Returns order details if found (ticket, price, status)
- Returns `{"found": False}` if order doesn't exist or query fails
- Handles query failures gracefully to avoid blocking legitimate retries

#### 3. Enhanced REST Order Execution (Lines 253-394)

**Key Changes:**

a) **Generate Stable Client Order ID** (Line 259):
```python
client_order_id = f"EQATS_{uuid.uuid4().hex[:16]}_{int(time.time() * 1000)}"
```
- Generated ONCE before the retry loop
- Both retry attempts use the SAME `client_order_id`
- Format: `EQATS_<16-char-uuid>_<timestamp-ms>`

b) **Include in Payload** (Lines 261-270):
```python
payload = json.dumps(
    {
        "client_order_id": client_order_id,  # NEW: Idempotency key
        "symbol": symbol,
        "side": order_type,
        "volume": lot_size,
        "sl": sl,
        "tp": tp,
    }
)
```

c) **Reconciliation After Timeout** (Lines 301-326):
```python
except (socket.timeout, TimeoutError) as e:
    # After timeout, reconcile to check if order was actually accepted
    reconcile_result = self._reconcile_order_status(client_order_id)
    
    if reconcile_result.get("found"):
        # Order was accepted despite timeout - return success
        return {
            "success": True,
            "ticket": reconcile_result.get("ticket", ""),
            "price": reconcile_result.get("price", 0.0),
            "reconciled": True,
        }
    
    # Order not found at broker - safe to retry with same client_order_id
    if attempt < max_attempts - 1:
        time.sleep(self.retry_backoff_delay)
```

d) **Reconciliation After Generic Exceptions** (Lines 358-384):
Similar reconciliation logic for ambiguous exceptions that might hide accepted orders.

### How It Prevents Duplicates

1. **First Attempt**: Order submitted with `client_order_id = "EQATS_abc123_1234567890"`
2. **Timeout Occurs**: Response lost, unclear if broker accepted the order
3. **Reconciliation**: Query broker: "Do you have order with client_order_id = EQATS_abc123_1234567890?"
   - **If Found**: Return success with broker's ticket number (no duplicate)
   - **If Not Found**: Safe to retry with the SAME `client_order_id`
4. **Retry Attempt**: If needed, submits with the SAME `client_order_id`
   - Broker can deduplicate using the `client_order_id`
   - Even if both requests arrive, broker sees identical `client_order_id` and processes only once

### Broker-Side Requirements

For full idempotency, the broker API should:
1. Accept `client_order_id` in order submission requests
2. Deduplicate orders with the same `client_order_id`
3. Provide an order status query endpoint that accepts `client_order_id`

If the broker doesn't support these features:
- The `client_order_id` is still logged for audit trails
- Reconciliation queries will fail gracefully (return `{"found": False}`)
- The retry will proceed, but at least the client has attempted to prevent duplicates

### Testing

Created comprehensive test suite in `test_order_idempotency.py`:
- ✓ REST order includes client_order_id
- ✓ Timeout triggers reconciliation
- ✓ Reconciliation prevents duplicate on timeout
- ✓ Reconciliation allows retry when order not found
- ✓ Same client_order_id used across retries
- ✓ Generic exception also triggers reconciliation
- ✓ Reconcile order status method works
- ✓ Reconcile handles order not found
- ✓ Reconcile handles query failure

### Backward Compatibility

- **No Breaking Changes**: Existing functionality preserved
- **Graceful Degradation**: If broker doesn't support `client_order_id`, it's simply ignored
- **Circuit Breaker**: Still enforced before order submission
- **Retry Logic**: Still attempts 2 times with configurable backoff
- **Error Handling**: All existing exception handlers maintained

### Additional Benefits

1. **Audit Trail**: Every order has a unique, traceable `client_order_id`
2. **Debugging**: Easier to correlate client requests with broker orders
3. **Reconciliation**: Can query order status after any ambiguous failure
4. **Compliance**: Better order tracking for regulatory requirements

### Files Modified

1. `institutional_integrations/universal_broker_adapter.py`:
   - Added `uuid` import
   - Added `_reconcile_order_status()` method
   - Enhanced `execute_order()` with client_order_id and reconciliation

2. `test_order_idempotency.py` (NEW):
   - Comprehensive test suite for idempotency features
