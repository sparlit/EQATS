# EAQTS v5.0 Architecture & Design Specification - Round 3

## 1. Executive Summary
Round 3 enhances protocol gateway resilience for multi-broker REST/WS endpoints during transient network congestion.

## 2. Universal Protocol Gateway Failover Architecture
- **Issue**: Single-pass HTTP/REST execution requests can time out during high volatility news events or TCP packet drops.
- **Design Solution**:
  - Implement a 2-stage retry loop with exponential backoff (0.2s) in `UniversalBrokerGateway.execute_order()`.
  - Maintain socket timeout limits (3.0s per attempt).
  - Return diagnostic failure payloads if all retries are exhausted.

```
[ Signal Execution Request ]
             │
             ▼
[ UniversalBrokerGateway.execute_order() ]
             │
             ├─► Attempt 1 (REST HTTP 3.0s socket timeout)
             │      │
             │      ├─► Success: Return Ticket
             │      └─► Timeout / Exception: Sleep 0.2s Backoff
             │
             └─► Attempt 2 (Retry REST HTTP 3.0s)
                    │
                    ├─► Success: Return Ticket
                    └─► Failure: Fallback Diagnostic Payload
```
