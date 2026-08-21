# ELITE QUANTUM AUTONOMOUS TRADING SYSTEM (EAQTS VERSION 6.0)
## EAQTS VERSION 3.0
### Master Architecture, Engineering, AI, Trading, Risk, Execution, Data, Security, Validation and Autonomous Evolution Specification

---

# 0. DOCUMENT CONTROL

**System Name:** Elite Quantum Autonomous Trading System (EAQTS Version 6.0)
**Abbreviation:** EAQTS / EQATS
**Specification:** Version 3.0
**Status:** Authoritative Engineering Baseline
**Purpose:** Autonomous multi-asset algorithmic trading operating system

Version 3.0 is the consolidated master specification derived from EAQTS Versions 1.0, 2.0 and 2.1.
Version 3.0 supersedes Versions 1.0, 2.0 and 2.1 as the single authoritative design and implementation plan.

---

# 0.1 CONSOLIDATION AND AUTHORITY RULES

This document is the single consolidated EAQTS Version 3.0 engineering specification.
The source hierarchy used to produce this document is:
1. Version 2.1 — authoritative architectural and governance baseline.
2. Version 2.0 — retained where it contains capabilities or detail not fully represented in Version 2.1.
3. Version 1.0 — retained where it contains unique operational, dashboard, research, library, simulation, or implementation requirements not superseded by later architecture.

Where duplicate requirements existed, they have been consolidated into one requirement.
Where later versions strengthened an earlier requirement, the stronger later requirement is authoritative.
Where earlier requirements conflicted with safety, deterministic controls, lawful data access, realistic performance measurement, or production governance, the safer and later requirement prevails.

---

# 0.2 VERSION 3.0 DESIGN OBJECTIVE

EAQTS Version 3.0 is a single integrated autonomous trading operating system rather than a collection of independent features.

The architecture unifies:
- autonomous research;
- market-data ingestion;
- point-in-time historical reconstruction;
- data quality and lineage;
- market-state construction;
- multi-timeframe analysis;
- prediction and probability calibration;
- strategy discovery and governance;
- opportunity generation;
- portfolio optimization;
- deterministic risk control;
- deterministic safety enforcement;
- execution and routing;
- MT5 integration;
- broker/exchange abstraction;
- post-trade reconciliation;
- case-based learning;
- model and strategy governance;
- controlled self-improvement;
- resilience and self-healing;
- observability;
- security;
- auditability;
- high-performance computing;
- professional terminal/dashboard operation.

The system explicitly supports the decision to trade and the decision not to trade.

---

# 1. MISSION & AUTONOMY DEFINITION

Build a professional, autonomous, multi-asset trading operating system operating in a 100% hands-free configuration.

After startup, EAQTS autonomously performs:
```text
AUTHENTICATE
→ INITIALIZE
→ HEALTH CHECK
→ CONNECT
→ DISCOVER
→ INGEST
→ ANALYZE
→ PREDICT
→ SELECT
→ OPTIMIZE
→ RISK CHECK
→ SAFETY CHECK
→ EXECUTE
→ MONITOR
→ MANAGE
→ EXIT
→ RECONCILE
→ LEARN
→ EVALUATE
→ IMPROVE
→ REPEAT
```

Human input is not required for normal operation.

---

# 2. SYSTEM CONSTITUTION HIERARCHY

The entire system obeys the following immutable hierarchy:

```text
LEVEL 0 — LEGAL / EXCHANGE / BROKER CONSTRAINTS
        ↓
LEVEL 1 — SAFETY KERNEL (Invariants INV-001 to INV-015)
        ↓
LEVEL 2 — HARD PORTFOLIO RISK LIMITS
        ↓
LEVEL 3 — EXECUTION CONSTRAINTS
        ↓
LEVEL 4 — STRATEGY CONSTRAINTS
        ↓
LEVEL 5 — MODEL / AI RECOMMENDATIONS
        ↓
LEVEL 6 — RESEARCH / OPTIMIZATION PROPOSALS
```

Lower levels can never override higher levels. An AI model, strategy optimizer, reinforcement-learning agent, or self-evolution process must never modify or bypass Level 0-3 hard risk limits and safety kernel rules.

---

# 3. MASTER ARCHITECTURE & OPERATIONAL PLANES

EAQTS Version 3.0 unifies 9 specialized architectural planes:

1. **Control and Governance Plane:** Handles transactional configuration updates, validation signatures, and state rollbacks.
2. **Data Plane:** Coordinates normalized multi-venue quote ingestion, point-in-time (PIT) time-series queries, crossed market detection, and data sanity filters.
3. **Intelligence Plane:** Classifies dynamic market regimes, evaluates momentum/volatility vectors, and aligns ML predictions with technical signals.
4. **Strategy Plane:** Manages strategy lifecycles, licensing, multi-timeframe trend confluence, and dynamic voting ensemble weights.
5. **Opportunity & Risk Plane:** Reserves portfolio margin, computes Expected Net Value (ENV), and evaluates fractional Kelly 2.0 drawdown limits.
6. **Safety & Verification Plane:** Enforces deterministic system invariants (`INV-001` to `INV-015`) independent of LLM or predictive states prior to trade admission.
7. **Execution Plane:** Performs fat-finger protection checks, message rate throttling (<5 orders/10s), and self-trade prevention before order submission.
8. **Learning and Governance Plane:** Stores structured trade cases, tracks decision quality scores, and differentiates strategic SKILL from random LUCK.
9. **Operations and Resilience Plane:** Manages continuous 2-second position reconciliation, chaos injection containment, and the global safety state machine (`NORMAL`, `DEFENSIVE`, `HALTED`).

---

# 4. HARDWARE & OPERATING ENVIRONMENT

### 4.1 Minimum Required Configuration (Basic Paper/Simulated Trading)
- **CPU:** Dual-core 64-bit x86/ARM processor @ 2.0 GHz or higher.
- **RAM:** 4 GB System Memory.
- **Storage:** 2 GB Free Disk Space (SSD preferred for SQLite write throughput).
- **Network:** Broadband Internet Connection (minimum 5 Mbps with latency < 100ms to broker server).
- **Display:** 1280 x 720 minimum resolution (for Tkinter Terminal GUI execution).
- **OS:** Windows 10/11, Ubuntu Linux 20.04+, or macOS 12+.

### 4.2 Optimal Recommended Configuration (Institutional High-Frequency & Multi-Broker Execution)
- **CPU:** 8-core / 16-thread CPU (e.g., Intel Core i7/i9 or AMD Ryzen 7/9 hybrid-core architecture) to bypass Python GIL limitations via parallel `ProcessPoolExecutor` / `ThreadPoolExecutor` processes.
- **RAM:** 16 GB High-Speed DDR4/DDR5 Memory.
- **Storage:** 20 GB High-Speed NVMe M.2 SSD (for tick history, vector database, and high-frequency SQLite WAL logs).
- **Network:** Co-located VPS / Dedicated Server in Equinix LD4 (London) or NY4 (New Jersey) with 1 Gbps fiber uplink and ping latency < 2ms to broker gateway.
- **Display:** Dual 1920 x 1080 (Full HD) Monitors (for high-density multi-panel dashboard monitoring).
- **OS:** Windows Server 2022 / Windows 11 Pro 64-bit (for native MetaTrader 5 Windows API integration).

---

# 5. DETAILED SETUP & RUN GUIDE

### Step 1: Clone or Extract Codebase
```bash
git clone https://github.com/your-org/eqats-quantum-system.git
cd eqats-quantum-system
```

### Step 2: Activate Virtual Environment & Install Dependencies
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### Step 3: Run Verification Suite
Confirm all 31 unit, chaos, multi-agent, and release gate tests pass cleanly:
```bash
pytest -v
```

### Step 4: Launch Trading Client
```bash
python main.py
```

---

# 6. DASHBOARD & TERMINAL SHEET DIRECTORY (33 SHEETS)

The EQATS Quantum Terminal features 33 interactive sheets accessible via the global command bar, tab dropdown, or F-keys:

1. **MAIN <GO> (F2):** Multi-Asset Scanning Matrix displaying real-time LTP, spread, trend bias, win probability, and technical indicators.
2. **GP <GO> (F3):** Graphical Price Tracking chart displaying price levels, high/low envelopes, and spread pips.
3. **WEI <GO> (F4):** World Equity Indices & Global Market Overview monitoring S&P 500, Nasdaq, FTSE 100, Nikkei 225, and DAX.
4. **NEWS <GO> (F5):** Real-Time Macro News Stream & NLP Sentiment Classifier.
5. **ANR <GO> (F6):** Analyst Recommendation & Neural Metrics Panel displaying MLP loss curves and generative GPT forecasts.
6. **CHART <GO> (F10):** Interactive Candlestick FOSS Chart supporting all 21 MT5 timeframes (M1-MN1), crosshairs, and live equity curves.
7. **SESS <GO> (F11):** 24-Session GMT Market Timeline Tracker with countdown clocks and overlaps.
8. **DES <GO>:** Security Descriptions & Asset Specifications displaying contract sizes, tick values, and swap rates.
9. **YAS <GO>:** Yield Analysis & Carry Analytics computing clean prices, swap points, and carry yields.
10. **ECO <GO>:** Economic Indicators Release Calendar showing upcoming high-impact announcements.
11. **EMSX <GO>:** Execution Management & Routing Status displaying order book depth and dark pool routing switches.
12. **SET <GO>:** Dashboard Settings featuring sub-tabs for Themes (7 palettes), Custom Fonts/Sizes, Risk Parameters, Telegram Alerts, and WhatsApp API configuration.
13. **CFG <GO>:** Configuration & Permissions Control featuring sub-tabs for User Management (CRUD), Multi-Broker Gateway Database, and Granular RBAC Permissions/Engine Toggles.
14. **ING <GO>:** Data Ingestion Monitor displaying provider connection states, tick rates, latency, and feed quality scores.
15. **FEAT <GO>:** Feature Store displaying feature distributions and importance scores.
16. **STRAT <GO>:** Strategy Engine Dashboard showing active strategy scores and ensemble weights.
17. **RISK <GO>:** Risk Management Monitor tracking VaR, Expected Shortfall (CVaR), total leverage, and daily drawdown limits.
18. **ORD <GO>:** Order Manager featuring nested sub-tabs for Order Book, Trade Book, Multi-Leg Spread Orders, and Trigger Orders.
19. **LOG <GO>:** Real-Time Operations Console displaying filtered system telemetry and diagnostics.
20. **MON <GO>:** System Resource Monitor tracking host CPU utilization, RAM consumption, thread count, and network I/O.
21. **SEC <GO>:** Security & Audit Log displaying active sessions, authentication events, and audit trails.
22. **SAFE <GO>:** Overnight & Geopolitical Safety Panel monitoring gap risk, rollover hours, and weekend market closures.
23. **PF <GO>:** Portfolio Manager featuring nested sub-tabs for Position Book, Asset Holdings, and Funds Allocation.
24. **WATCH <GO>:** Interactive Watchlist displaying multi-asset heatmaps, MTF trend confluence grids, and probability rankings.
25. **MKT <GO>:** Market Overview featuring sub-tabs for Exchange Messages, Market Movers, Scanners, Fundamentals, and Corporate Actions.
26. **SYM <GO>:** Symbol Specification Manager detailing contract multipliers, stop levels, and lot increments.
27. **AIC <GO>:** AI / LLM Control Panel displaying local GPT parameters, vector memory status, and retraining controls.
28. **CRAWL <GO>:** Alternative Data & Web Crawler Status tracking scrape freshness and sentiment scores.
29. **TRADEBOOK <GO>:** Historical Trade Journal displaying settled tickets, PnL, and Trade Memory Reflection Protocol post-mortems.
30. **AGENT <GO> / SUPERVISOR <GO>:** AI System Supervisor Agent Panel displaying health scores, interventions, and audit reports.
31. **ECOSYSTEM <GO>:** Full System Visualizer displaying live work across all 6 Core Brain Agents, 4 Method Brains, 10 Strategy Brains, Risk/Lot Mechanism Brains, and Parallel Executors.
32. **TZCONV <GO>:** Forex Market Time Zone & Timeline Converter with interactive timezone selection (Kolkata, UTC, London, New York, Tokyo, Sydney), 12/24h toggles, live purple pointer needle, 4 session timeline bars, and liquidity volume curve.
33. **HELP <GO> (F1):** Comprehensive Operational Handbook containing tutorials, keyboard shortcut guides, emergency procedures, and FAQs.

---

# 7. CRITICAL SYSTEM INVARIANTS REGISTER

| Invariant | Invariant Name | Strict Boundary Condition | System Action on Violation |
| :--- | :--- | :--- | :--- |
| **`INV-001`** | Max Portfolio Risk Ceiling | Portfolio Total Risk <= 5.0% Account Equity | Blocks order submission; transitions to `DEFENSIVE`. |
| **`INV-002`** | Active Trade Count Limit | Concurrent Trades <= `MAX_CONCURRENT_TRADES` (10) | Rejects entry; logs capacity allocation max. |
| **`INV-003`** | Minimum Probability Gate | Signal Probability > 60.0% | Vetoes entry; logs low probability score. |
| **`INV-004`** | Pyramiding Profit Constraint | Existing position MUST be in net profit before adding lots | Blocks position expansion/pyramiding. |
| **`INV-005`** | Stop-Loss Normalization | Stop Loss >= Broker Minimum Stop Level (`trade_stops_level`) | Auto-adjusts SL distance to broker minimum. |
| **`INV-006`** | Spread Spikes Filter | Spread <= 3.5x Symbol Average Spread | Delays order submission until spread normalizes. |
| **`INV-007`** | Daily Loss Circuit Breaker | Daily Realized Loss <= 3.0% Initial Balance | Liquidates all positions; halts trading for 24h. |
| **`INV-008`** | Message Rate Governor | Submissions <= 5 orders per 10-second window | Throttles submission rate; queues order execution. |
| **`INV-009`** | Rollover Hour Lockout | Block trading between 22:00 - 23:00 GMT | Rejects order admission during bank rollover. |
| **`INV-010`** | Weekend FX Lockout | Block Forex/Metals during weekend closures | Permits *only* 24/7 Cryptocurrency symbols. |
| **`INV-011`** | Self-Trade Prevention | No opposite pending orders for same symbol/magic | Cancels conflicting pending order. |
| **`INV-012`** | Fat-Finger Size Cap | Single Lot Size <= 5.0 Lots Maximum | Clamps lot size to maximum allowed ceiling. |
| **`INV-013`** | Continuous Reconciliation | Database Trades == Broker Open Orders | Freezes execution; triggers position re-alignment. |
| **`INV-014`** | News NLP Veto Lockout | Veto trade if high-impact news sentiment opposes trade | Vetoes entry surrounding high-impact news. |
| **`INV-015`** | Intelligence Disagreement | Veto if Technical Trend and Neural Net predict opposite | Flags disagreement protocol; blocks trade admission. |

---

# 8. EMERGENCY ACTION PLAN (EAP)

```text
                             [EMERGENCY EVENT DETECTED]
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
      [SCENARIO A: DISCONNECT]  [SCENARIO B: DRAWDOWN]   [SCENARIO C: UNHANDLED]
                 │                       │                       │
      - State -> DEFENSIVE     - Auto-Liquidate Trades  - Click [🔒 PANIC LOCKDOWN]
      - Freeze New Entries     - State -> HALTED        - Prompts Secondary PIN
      - Retry Reconnect        - Lock Trading 24h       - Liquidates All Positions
      - Check VPS Network      - Audit Database Logs    - Freezes Engine & Exits
```

---
*Elite Quantum Autonomous Trading System (EAQTS) — Version 6.0 Master Specification Handbook*
