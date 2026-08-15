# ELITE QUANTUM AUTONOMOUS TRADING SYSTEM (EQATS)
## AUTHORITATIVE TECHNICAL DOCUMENTATION, OPERATIONAL GUIDE, AND MASTER SYSTEM HANDBOOK

Welcome to the canonical handbook for the **Elite Quantum Autonomous Trading System (EQATS)**—a hedge-fund-grade quantitative trading operating system built under the strict **Version 2.4 Master Specification**. EQATS operates in a 100% autonomous, hands-free configuration, interfacing natively with MetaTrader 5 (MT5) on Windows and high-fidelity simulated paper-trading environments on Linux/Unix sandboxes.

---

## 📊 1. DETAILED PROJECT REPORT & ARCHITECTURAL INSIGHTS

### 1.1 Architectural Philosophy & Non-Perfect System Principle
EQATS does not assume perfect market prediction, perfect data feeds, zero slippage, or uninterrupted network connectivity. Instead, the platform is engineered under the **Non-Perfect System Principle**, optimizing for bounded, deterministic, and fail-safe recovery rather than unrealizable perfection.

The system relies on a **multi-plane, thread-safe, event-driven architecture** consisting of 9 specialized operational planes:
1. **Control and Governance Plane:** Handles transactional configuration updates, cryptographic validation signatures, and state rollbacks.
2. **Data Plane:** Coordinates normalized multi-venue quote ingestion, point-in-time (PIT) time-series queries, crossed market detection, and data sanity filters.
3. **Intelligence Plane:** Classifies dynamic market regimes, evaluates momentum/volatility vectors, and aligns ML predictions with technical indicators.
4. **Strategy Plane:** Manages strategy lifecycles, licensing, multi-timeframe trend confluence, and dynamic voting ensemble weights.
5. **Opportunity & Risk Plane:** Reserves portfolio margin, computes Expected Net Value (ENV), and evaluates fractional Kelly 2.0 drawdown limits.
6. **Safety & Verification Plane:** Enforces deterministic system invariants (`INV-001` to `INV-015`) independent of LLM or predictive states prior to trade admission.
7. **Execution Plane:** Performs fat-finger protection checks, message rate throttling (<5 orders/10s), and self-trade prevention before order submission.
8. **Learning and Governance Plane:** Stores structured trade cases, tracks decision quality scores, and differentiates strategic SKILL from random LUCK.
9. **Operations and Resilience Plane:** Manages continuous 2-second position reconciliation, chaos injection containment, and the global safety state machine (`NORMAL`, `DEFENSIVE`, `HALTED`).

### 1.2 Agentic Multi-Brain AI Architecture
EQATS separates quantitative intelligence into autonomous, specialized AI brains:
- **Research Brain:** Scans macro trends, web research, alternative feeds, and academic finance literature.
- **Analyst Brain:** Conducts multi-timeframe technical, order-flow, market-structure, and sentiment evaluations.
- **Prediction Brain:** Multi-Layer Perceptron (MLP) neural network and local Generative Pre-trained Transformer (`QuantumLocalGPT`) generating next-candle directional probabilities and financial narrative reports.
- **Strategy Brain:** Evaluates 50+ strategy profiles (Trend Following, Mean Reversion, Breakout, ICT/SMC, Statistical Arbitrage, Carry Trade, MTF Confluence) and tallies regime-weighted votes.
- **Risk Brain:** Holds absolute veto authority over trade submission, enforcing portfolio VaR, Expected Shortfall (CVaR), and correlation exposure limits.
- **Execution Brain:** Routes orders, manages trailing stops, monitors execution slippage, and executes partial fills/reconciliations.
- **AI System Supervisor Agent (`supervisor_agent.py`):** Continuously audits composite health across Data, Execution, Risk, and Model planes, triggering autonomous state degradation on health drops (<60%).

---

## 💻 2. HARDWARE REQUIREMENTS

### 2.1 Minimum Required Configuration (Basic Paper/Simulated Trading)
- **CPU:** Dual-core 64-bit x86/ARM processor @ 2.0 GHz or higher.
- **RAM:** 4 GB System Memory.
- **Storage:** 2 GB Free Disk Space (SSD preferred for SQLite write throughput).
- **Network:** Broadband Internet Connection (minimum 5 Mbps with latency < 100ms to broker server).
- **Display:** 1280 x 720 minimum resolution (for Tkinter Terminal GUI execution).
- **OS:** Windows 10/11, Ubuntu Linux 20.04+, or macOS 12+.

### 2.2 Optimal Recommended Configuration (Institutional High-Frequency & Multi-Broker Execution)
- **CPU:** 8-core / 16-thread CPU (e.g., Intel Core i7/i9 or AMD Ryzen 7/9 hybrid-core architecture) to bypass Python GIL limitations via parallel `ProcessPoolExecutor` processes.
- **RAM:** 16 GB High-Speed DDR4/DDR5 Memory.
- **Storage:** 20 GB High-Speed NVMe M.2 SSD (for tick history, vector database, and high-frequency SQLite WAL logs).
- **Network:** Co-located VPS / Dedicated Server in Equinix LD4 (London) or NY4 (New Jersey) with 1 Gbps fiber uplink and ping latency < 2ms to broker gateway.
- **Display:** Dual 1920 x 1080 (Full HD) Monitors (for high-density multi-panel dashboard monitoring).
- **OS:** Windows Server 2022 / Windows 11 Pro 64-bit (for native MetaTrader 5 Windows API integration).

---

## 📋 3. INSTALLATION PREREQUISITES & POST-INSTALLATION VERIFICATION

### 3.1 Pre-Installation Requirements
Ensure the following tools and runtimes are installed on the host OS prior to deployment:
1. **Python 3.10, 3.11, or 3.12 (64-bit):** Add Python to system `PATH`.
2. **Git Version Control:** Required to pull updates and manage local code branches.
3. **MetaTrader 5 Windows Terminal (Optional for Live/Demo Broker Mode):**
   - Installed and logged into your broker account.
   - Enable "Allow Algo Trading" in `Tools -> Options -> Expert Advisors`.
   - Enable "Allow WebRequest for listed URL".
4. **C++ Build Tools / PyO3 (Optional):** Required if compiling native C++/Rust performance extensions.

### 3.2 Post-Installation Prerequisites & Readiness Verification
After deploying the codebase, execute post-installation verification:
- Verify SQLite database table auto-creation by running `python -c "import database; database.init_db()"`.
- Verify multi-broker connection parameters and cryptographic salt digests.
- Confirm full release gate signoff by running `pytest`.

---

## 🔧 4. DETAILED SETUP GUIDE (HOW-TO INSTALL)

### Step 1: Clone or Extract Codebase
```bash
git clone https://github.com/your-org/eqats-quantum-system.git
cd eqats-quantum-system
```

### Step 2: Create and Activate Python Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Required Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Run Verification Suite
Confirm all 20 unit, chaos, and institutional release gate tests pass cleanly:
```bash
pytest -v
```
*Expected Output:*
```text
============================== 20 passed in 0.44s ==============================
```

---

## 🚀 5. HOW-TO RUN

### 5.1 Standard GUI Launch Mode (Desktop GUI Environment)
To launch EQATS with the full Tkinter EQATS Quantum Terminal GUI:
```bash
python main.py
```
*The client performs operator authentication (`QUANT_OPERATOR`), verifies database tables, initializes the AI Supervisor Agent, and launches the dashboard.*

### 5.2 Headless / CLI Console Mode (Linux VPS / Server Service Execution)
If executing on a headless Linux VPS without a desktop display manager (`DISPLAY` absent), EQATS automatically detects the headless environment and falls back to **Classic Console Telemetry Mode**:
```bash
python main.py
```
To run as a persistent background daemon on Linux:
```bash
nohup python main.py > system_output.log 2>&1 &
```

### 5.3 Simulation Mode vs Native MetaTrader 5 Mode
To switch execution modes, open `config.py`:
- **Paper Trading / Sandbox Mode (Linux / macOS / Windows):**
  ```python
  SIMULATION_MODE = True
  ```
- **Live / Demo Broker Trading (Windows MT5 Terminal):**
  ```python
  SIMULATION_MODE = False
  DEMO_ACCOUNT_ONLY = True  # Set to False to trade live real capital
  ```

---

## ⚙️ 6. HOW-TO MAINTAIN & OPERATIONAL MAINTENANCE GUIDE

### 6.1 Database Maintenance & Backups
SQLite database tables are stored in `config.DB_PATH` (default: `scalper_records.db`).
- **Weekly Backup:**
  ```bash
  sqlite3 scalper_records.db ".backup 'backups/scalper_backup_$(date +%Y%m%d).db'"
  ```
- **Database WAL Vacuuming:** Periodically compress and reclaim disk space:
  ```bash
  sqlite3 scalper_records.db "VACUUM; PRAGMA optimize;"
  ```

### 6.2 Model Retraining & Vector Memory Pruning
The local MLP Neural Network and local GPT memory buffer continuously absorb tick outcomes. To re-train or reset weights:
- Open the `AIC` tab on the GUI and click `[🧠 RETRAIN MODELS]`.
- Or delete `quantum_llm_weights.json` to trigger clean weight initialization on startup.

### 6.3 Log Management & Telemetry Rotation
System logs are written to `sys.stdout` and piped to the bottom console widget and `scalper_state.txt`.
- Archived log files in `logs/` older than 30 days can be pruned safely.

---

## 🖥️ 7. DETAILED APPLICATION WALK-THROUGH (31 TERMINAL TABS)

The EQATS Quantum Terminal features 31 dedicated, interactive screens accessible via the global command bar, tab dropdown, or F-key shortcuts:

1. **MAIN <GO> (Shortcut F2):** Multi-Asset Scanning Matrix displaying real-time LTP, spread, trend bias, win probability, and technical indicators.
2. **GP <GO> (Shortcut F3):** Graphical Price Tracking chart displaying price levels, high/low envelopes, and spread pips.
3. **WEI <GO> (Shortcut F4):** World Equity Indices & Global Market Overview monitoring S&P 500, Nasdaq, FTSE 100, Nikkei 225, and DAX.
4. **NEWS <GO> (Shortcut F5):** Real-Time Macro News Stream & NLP Sentiment Classifier analyzing market headlines for bullish/bearish bias.
5. **ANR <GO> (Shortcut F6):** Analyst Recommendation & Neural Metrics Panel displaying MLP loss curves, model accuracy, and generative GPT forecasts.
6. **CHART <GO> (Shortcut F10):** Interactive Candlestick FOSS Chart supporting all 21 MT5 timeframes (M1-MN1), mouse zooming/scaling, crosshairs, and live equity trajectory graphs.
7. **SESS <GO> (Shortcut F11):** 24-Session GMT Market Timeline Tracker displaying 3 vertical rows (Passed, Active, Upcoming) with countdown clocks and overlaps.
8. **DES <GO>:** Security Descriptions & Asset Specifications displaying contract sizes, tick values, margin requirements, and swap rates.
9. **YAS <GO>:** Yield Analysis & Carry Analytics computing clean prices, swap points, and carry yields across spot contracts.
10. **ECO <GO>:** Economic Indicators Release Calendar showing upcoming high-impact central bank announcements (NFP, CPI, FOMC).
11. **EMSX <GO>:** Execution Management & Routing Status displaying order book depth, dark pool routing switches, and B-Pipe network status.
12. **SET <GO>:** Dashboard Settings featuring sub-tabs for Themes (7 palettes), Custom Fonts/Sizes, Risk Parameters, Telegram Alerts, and WhatsApp API configuration.
13. **CFG <GO>:** Configuration & Permissions Control featuring sub-tabs for User Management (CRUD), Multi-Broker Gateway Database, and Granular RBAC Permissions/Engine Toggles.
14. **ING <GO>:** Data Ingestion Monitor displaying provider connection states, tick rates, latency, dropped packet counters, and feed quality scores.
15. **FEAT <GO>:** Feature Store displaying feature distributions, feature importance scores, and model correlation statistics.
16. **STRAT <GO>:** Strategy Engine Dashboard showing active strategy scores, voting ensemble weights, and strategy lifecycle statuses.
17. **RISK <GO>:** Risk Management Monitor tracking Value at Risk (VaR), Expected Shortfall (CVaR), total leverage, and daily drawdown limits.
18. **ORD <GO>:** Order Manager featuring nested sub-tabs for Order Book, Trade Book, Multi-Leg Spread Orders, and Conditional Trigger Orders.
19. **LOG <GO>:** Real-Time Operations Console displaying filtered system telemetry, diagnostics, and error messages.
20. **MON <GO>:** System Resource Monitor tracking host CPU utilization, RAM consumption, thread count, and network I/O latency.
21. **SEC <GO>:** Security & Audit Log displaying active login sessions, authentication events, MFA status, and audit trails.
22. **SAFE <GO>:** Overnight & Geopolitical Safety Panel monitoring gap risk, rollover hours, weekend market closures, and news veto locks.
23. **PF <GO>:** Portfolio Manager featuring nested sub-tabs for Position Book, Asset Holdings, and Funds / Equity Allocation.
24. **WATCH <GO>:** Interactive Watchlist displaying multi-asset heatmaps, MTF trend confluence grids, and real-time probability rankings across all tradeable symbols.
25. **MKT <GO>:** Market Overview featuring nested sub-tabs for Exchange Messages, Market Movers, Scanners, Fundamentals, and Corporate Actions.
26. **SYM <GO>:** Symbol Specification Manager detailing asset class rules, contract multipliers, stop levels, and minimum lot increments.
27. **AIC <GO>:** AI / LLM Control Panel displaying local GPT parameters, vector memory status, inference latency, and model retraining controls.
28. **CRAWL <GO>:** Alternative Data & Web Crawler Status tracking scrape freshness, parsed entities, and alternative data sentiment scores.
29. **TRADEBOOK <GO>:** Historical Trade Journal displaying closed tickets, execution prices, realized PnL, slippage, and maximum adverse excursion (MAE).
30. **HELP <GO> (Shortcut F1):** Comprehensive Operational Handbook containing tutorials, keyboard shortcut guides, emergency procedures, and FAQs.
31. **AGENT / SUPERVISOR <GO>:** AI System Supervisor Agent Panel displaying real-time composite health scores (Data, Execution, Risk, Model), active interventions, forced audit controls, and downloadable audit reports.
32. **DEEP MARKET SENTIMENT:** Specialized NLP Sentiment Analysis sheet parsing multi-source financial news stories.
33. **STOCK MARKET PREDICTOR:** Specialized Predictive Analytics sheet rendering ensemble regression forecast curves and OHLC boundaries.

---

## 🚨 8. EMERGENCY ACTION PLAN (EAP)

In the event of a critical system anomaly, follow these standardized Emergency Actions:

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

### 8.1 Scenario A: Severe Broker Disconnection Outage
1. The Operations Plane immediately transitions safety state to `"DEFENSIVE"`.
2. All new order submissions are strictly frozen.
3. System initiates an automated exponential-backoff reconnection loop.
4. If disconnected > 5 minutes, operator should click `[⏸ PAUSE ADMISSION]` or inspect broker VPS connectivity.

### 8.2 Scenario B: Drawdown Circuit Breaker Triggered
1. If daily loss exceeds `MAX_DAILY_DRAWDOWN_PERCENT` (3.0%), the system raises a critical invariant alert (`INV-001`).
2. Safety state transitions to `"HALTED"`.
3. All open positions are **autonomously liquidated** immediately to lock in remaining capital.
4. Trading is locked for the remainder of the trading session.

### 8.3 Scenario C: Manual Panic Lockdown Execution
If an unhandled anomaly occurs:
1. Click the red **`[🔒 PANIC LOCKDOWN]`** button on the dashboard controls bar.
2. Confirm the emergency confirmation prompt.
3. EQATS will instantly:
   - Liquidate all active orders across all symbols.
   - Cancel all pending orders.
   - Transition safety state to `DEFENSIVE`.
   - Pause the autonomous trading loop.

---

## 🛡️ 9. CRITICAL SYSTEM INVARIANTS REGISTER

The Safety & Verification Plane enforces 15 inviolable mathematical invariants (`INV-001` through `INV-015`) on every tick prior to trade admission:

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

## ❓ 10. COMPREHENSIVE FAQ

#### Q1: Is human manual decision-making required during live operation?
**A:** No. EQATS is engineered as a 100% autonomous auto-trading platform. Once started via `[▶ START TRADING]`, the system independently collects data, detects active market sessions, scans symbols, evaluates indicators, predicts outcomes, sizes lots, submits orders, manages trailing stops, and logs outcomes without human input.

#### Q2: How does the multi-broker database work?
**A:** Under the `CFG` screen ("Multi-Broker Gateway Credentials"), operators can register multiple broker connection profiles (Server, Account ID, Password, Leverage, Environment). Active credentials are stored encrypted in SQLite using salt-based SHA-256 digests and XOR-Base64 ciphering. Operators can switch active primary gateways with a single click (`[⚡ SET ACTIVE GATEWAY]`).

#### Q3: How does the system handle trading on weekends?
**A:** EQATS continuously calculates global session hours. On weekends when traditional Forex and Metal exchanges are closed, `INV-010` automatically filters out FX symbols while keeping 24/7 Cryptocurrencies (BTC, ETH, LTC, SOL, XRP) active and tradeable.

#### Q4: How do I exit the application cleanly?
**A:** Click the **`[❌ EXIT SYSTEM]`** button on the dashboard control bar. Confirm the exit dialog. EQATS will safely stop all background threads, disconnect market feeds, close database connections, destroy GUI windows, and terminate the process.

---

## 📖 11. QUANTITATIVE GLOSSARY & ERROR CODES REFERENCE

### 11.1 Quantitative Glossary
- **Brier Score:** A mathematical metric measuring the accuracy of probabilistic forecasts. Lower values indicate better-calibrated prediction models.
- **Expected Net Value (ENV):** The calculated mathematical expectancy of a trade candidate combining probability of win, average reward, average loss, spread cost, and estimated slippage.
- **Fractional Kelly Sizing:** A position-sizing algorithm that dynamically scales lot sizes based on win probability and reward-to-risk ratio, scaled downward by 0.25 (Quarter-Kelly) for capital preservation.
- **Point-in-Time (PIT):** Time-series data structured strictly as it was known at the historical execution timestamp, preventing future data leakage or look-ahead bias.
- **Value at Risk (VaR):** Statistical technique measuring the maximum potential portfolio loss over a given time horizon at a 99% confidence level.

### 11.2 Error Codes & Remedies Table

| Error Code / Log Symbol | Root Cause | Operator Remedy |
| :--- | :--- | :--- |
| **`INV-001_FAIL`** | Total portfolio risk exceeds 5.0% equity ceiling. | Close high-risk open positions or lower risk % in `SET` tab. |
| **`INV-013_MISMATCH`**| SQLite database trade records do not match broker open orders. | Click `[🔄 RESET ENGINES]` or re-sync database in `SET` tab. |
| **`RATE_LIMIT_HALT`**| Message submission rate exceeded 5 orders / 10 seconds. | System automatically throttles order queue for 10s and resumes. |
| **`AUTH_PIN_DENIED`**| Incorrect secondary security PIN entered for `CFG` or `SET` tab access. | Enter valid operator PIN (default: `741295` or `admin`). |
| **`ERR_MT5_5004`** | MQL5 file open permission error on restricted terminal paths. | Toggle `InpUseCommonFolder` parameter in MT5 EA HUD settings. |

---

## ⌨️ 12. TERMINAL KEYBOARD SHORTCUTS & HELP COMMANDS

Navigate the EQATS Quantum Terminal effortlessly using the global command bar (`[COMMAND] <GO>`) or keyboard shortcuts:

- **`<F1>` / `HELP <GO>`:** Open Operational Handbook and system manuals.
- **`<F2>` / `MAIN <GO>`:** Open Multi-Asset Scans Matrix dashboard.
- **`<F3>` / `GP <GO>`:** Open Graphical Price Tracking line chart.
- **`<F4>` / `WEI <GO>`:** Open World Equity Indices overview.
- **`<F5>` / `NEWS <GO>`:** Open Macro News Stream and NLP Sentiment analyzer.
- **`<F6>` / `ANR <GO>`:** Open Neural Model Accuracy & Generative Financial Report screen.
- **`<F7>` / `PORT <GO>`:** Open Mean-Variance Sharpe Portfolio Optimizer.
- **`<F8>` / `MCTS <GO>`:** Open Monte Carlo Value at Risk (VaR) Simulator.
- **`<F9>` / `VDS <GO>`:** Open Volume Depth & DOM Analytics screen.
- **`<F10>` / `CHART <GO>`:** Open Interactive Candlestick Chart Canvas.
- **`<F11>` / `SESS <GO>`:** Open 24-Session GMT Timeline Tracker.
- **`CFG <GO>`:** Open Configuration, User Management & Multi-Broker Control Tab.
- **`SET <GO>`:** Open Settings, Themes, Fonts, and Telegram/WhatsApp Notification Tab.
- **`AGENT <GO>` / `SUPERVISOR <GO>`:** Open AI System Supervisor Agent Dashboard.

---
*Elite Quantum Autonomous Trading System (EQATS) — Version 2.4 Master Specification Handbook*
