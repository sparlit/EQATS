# Round 4 — Designer: Post-Hardening Architecture

## System State After Rounds 1-3

```
+---------------------------+      +----------------------------+
|   Tkinter GUI (gui.py)    |      | 30 Institutional Modules  |
|   6419 LOC monolith       |      | drl_execution_agent.py     |
|                           |      | portfolio_optimizer.py     |
+----------+----------------+      | whale_tracker.py           |
           |                         | go_gateway.py              |
           v                         | tft_tcn_predictor.py       |
+---------------------------+        | cointegration_pairs.py     |
|  main.py orchestrator     |        | ... 24 more               |
|  (1129 LOC)               |        +-------------+--------------+
|  - Brain agents           |                      |
|  - Risk gating            |                      v
|  - Telemetry fanout       |        +----------------------------+
+----+----------+-----------+        | event_bus.py               |
     |          |                    | (pub/sub backbone)         |
     v          v                    +----------------------------+
+--------+ +----------------+
| brain  | | connector.py   |
| .py    | | (767 LOC)      |
| 623    | | UniversalBroker|
| LOC    | | Gateway        |
+--------+ +----------------+
     |          |
     v          v
+---------------------------+
| database.py               |
| SQLite WAL + auto-checkpt |
+---------------------------+
```

## Round 4 Hardening Targets

```
                BEFORE                           AFTER
            (Round 3 end)                     (Round 4)
+--------------------------------+   +--------------------------------+
| gui.py:2266-2275               |   | gui.py:2266-2275               |
|   try:                         |   |   try:                         |
|     ...                        |   |     ...                        |
|   except:         (M-001)      |   |   except Exception as e:       |
|     pass                       |   |     logger.exception(e)        |
+--------------------------------+   +--------------------------------+

+--------------------------------+   +--------------------------------+
| 46 silent `pass` in except    |   | <=8 silent pass                |
| swallowed all errors (M-002)  |   | rest now log via debug logger  |
+--------------------------------+   +--------------------------------+

+--------------------------------+   +--------------------------------+
| WS telemetry server            |   | WS telemetry server            |
| (commit 8f62709) UNTESTED      |   | + test_websocket_telemetry.py  |
+--------------------------------+   +--------------------------------+

+--------------------------------+   +--------------------------------+
| 30 institutional modules       |   | docs/INSTITUTIONAL_            |
| undocumented (gap)             |   | INTEGRATIONS.md lists each     |
+--------------------------------+   +--------------------------------+

+--------------------------------+   +--------------------------------+
| Retry backoff without circuit  |   | docs/CIRCUIT_BREAKER.md        |
| breaker (gap)                  |   | documents next-layer resilience|
+--------------------------------+   +--------------------------------+
```

## Data Flow (unchanged from Round 3)

```
MT5 broker
   |
   v
connector.py (UniversalBrokerGateway)
   |  -- retry x2 backoff (Round 3)
   |  -- [future] circuit breaker (Round 5 candidate)
   v
brain_agents_orchestrator.py
   |
   +--> brain.py (predictive_brain + DRL agents)
   |
   +--> event_bus.py (telemetry)
   |
   +--> database.py (WAL checkpoints)
   |
   v
gui.py / dashboard.html / telegram_bot.py
```

## Risk Invariants (still enforced)

1. Every order passes risk gate (loss protection, position size cap)
2. WAL checkpoint at most every N writes (Round 2)
3. Retry backoff on REST/WS (Round 3)
4. All exception paths now log (Round 4 hardening)

## Decision Log

- **D-001**: gui.py bare excepts → except Exception as e (M-001)
- **D-002**: Silent pass → logger.debug where logger in scope (M-002)
- **D-003**: WebSocket telemetry gets one minimal smoke test (gap)
- **D-004**: Documentation-first for circuit breaker; defer implementation to Round 5+
- **D-005**: .gitignore expanded; untracked XML removed (L-001)
