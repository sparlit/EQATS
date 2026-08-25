# Circuit Breaker Pattern — Design Specification

## Status: DOCUMENTED (Round 4), NOT YET IMPLEMENTED

## Why

Round 3 added 2-stage exponential retry backoff (0.2s) to the REST/WS order
execution path inside `UniversalBrokerGateway`. Retries are valuable for
transient blips, but they can amplify damage during a sustained broker outage
or API key rotation by hammering a dead endpoint and queueing thousands of
orders behind it.

A circuit breaker sits in front of retries: after N consecutive failures within
a rolling window, it OPENs and short-circuits subsequent calls for a cooldown
period, then HALF-OPENs with a single probe call to determine recovery.

## States

```
        success / probe ok
   +-----------------------------+
   |                             v
[CLOSED] ---failures >= N---> [OPEN] ---cooldown elapsed---> [HALF_OPEN]
   ^                             |                               |
   |                             |                               |
   +-------- failure ------------+---------- probe fails --------+
```

## Where It Belongs

The breaker wraps the *outermost* retry invocation, not the inner sleeps:

```python
# connector.py (illustrative — NOT yet implemented)
class UniversalBrokerGateway:
    def __init__(self, ...):
        self._breaker = CircuitBreaker(
            failure_threshold=5,
            cooldown_seconds=30,
            half_open_probe=True,
        )

    def execute_order(self, order):
        if not self._breaker.allow():
            return {"status": "rejected", "reason": "circuit_open"}
        try:
            # Round 3 retry backoff lives here
            result = self._execute_with_retry(order)
        except BrokerUnreachable as e:
            self._breaker.record_failure()
            raise
        else:
            self._breaker.record_success()
            return result
```

## Configuration

| Parameter | Default | Notes |
|---|---|---|
| `failure_threshold` | 5 | Consecutive failures before OPEN |
| `cooldown_seconds` | 30 | OPEN duration |
| `half_open_probe` | True | One probe before fully closing |
| `excluded_exceptions` | `(RiskViolation,)` | Don't trip on app-level rejections |

## Telemetry

When the breaker trips, emit:
- `event_bus.publish("circuit_breaker", {"state": "open", "service": "gateway"})`
- Counter: `circuit_breaker_trips_total{service=...}`
- Gauge: `circuit_breaker_state{service=...}`  (0=closed,1=half,2=open)

## Test Plan (for the implementation round)

1. Unit test: 5 failures -> OPEN; 30s wait -> HALF_OPEN; success -> CLOSED
2. Chaos test: simulate 100 broker timeouts, assert < 110 actual calls made
3. Integration: when breaker is OPEN, order route returns immediately with
   `{"status": "rejected", "reason": "circuit_open"}`

## Round 5+ Candidate

This document is the design contract. Implementation is queued for a future
round once the Council confirms readiness.
