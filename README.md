# ELITE AUTONOMOUS QUANTUM TRADING SYSTEM (EAQTS)
## AUTHORITATIVE TECHNICAL DOCUMENTATION, OPERATIONAL GUIDE, AND VERIFICATION HANDBOOK

Welcome to the canonical technical handbook for the **Elite Autonomous Quantum Trading System (EAQTS)**—a professional, hedge-fund-grade quantitative trading operating system designed to run under the strict **Version 2.4 Master Specification**. EAQTS operates in a fully autonomous, hands-free configuration, interfacing natively with MetaTrader 5 (MT5) on Windows and high-fidelity simulated paper-trading environments on Unix/Linux sandboxes.

---

## 🚀 1. DETAILED PROJECT REPORT & INSIGHTS

### 1.1 Architectural Philosophy
EAQTS does not assume perfect prediction, perfect data, perfect liquidity, or perfect execution. Instead, the platform is engineered under the **Non-Perfect System Principle**, meaning it optimizes for bounded, deterministic, and fail-safe recovery rather than assumed perfection.

The system relies on a **strictly sequenced, multi-plane, event-driven architecture** consisting of 9 specialized, thread-safe operational planes:
1. **Control and Governance Plane:** Handles transactional configuration updates, validation signatures, and rollback capabilities.
2. **Data Plane:** Coordinates normalized pricing ingestion, point-in-time (PIT) queries with zero look-ahead bias, and reasonableness checks.
3. **Intelligence Plane:** Classifies market regimes and aligns machine learning predictions with technical signals.
4. **Strategy Plane:** Manages strategy lifecycles, licenses, and multi-timeframe confluences.
5. **Opportunity & Risk Plane:** Reserves capital, calculates Expected Net Value (ENV), and evaluates Kelly 2.0 drawdown thresholds.
6. **Safety & Verification Plane:** Enforces the core deterministic safety Kernel independent of LLM states, executing strict trade admissions.
7. **Execution Plane:** Performs fat-finger, message rate, and self-trade checks prior to routing.
8. **Learning and Governance Plane:** Maintains structured cases, decision quality scores, and attributes performance to strategic SKILL vs. positive random LUCK.
9. **Operations and Resilience Plane:** Performs continuous position reconciliation and manages the global safety state machine.

### 1.2 Core Quantitative Edge & Insights
- **Statistical Regime Adaptation:** Rather than executing static indicators, the platform tracks market dynamics in real-time. If the trend intensity metrics categorize the market as `"TRENDING"`, oscillator indicators are disabled to avoid "catching falling knives," while momentum and breakout strategies are dynamically scaled up.
- **Predictive AI Backpropagation:** A custom-built Multi-Layer Perceptron (MLP) neural network operates as a technically biased veto filter. If a technical buy trigger occurs but the AI next-candle probability is bearish, the system autonomously vetoes the entry.
- **Zero Look-Ahead Point-in-Time (PIT) Queries:** To completely prevent backtest look-ahead contamination, our historical queries leverage strictly monotonic availability-time checks.
- **Continuous Multi-Layer Reconciliation:** To prevent ghost orders or orphan positions on the broker terminal, the system matches SQLite states against the broker active order collection on every tick. Any discrepancy freezes further risk and initiates recovery.

---

## 🗺️ 2. SYSTEM WORKFLOW & DATA PATHS

The operational flow of a single system tick adheres strictly to the **Unified Governing Control Chain**:

```text
                  [1. OBSERVE & INGEST]
                   Reads rates/tick arrays
                             │
                  [2. DATA SANITY CHECK]
              Crossed market / spread checks
                             │
                 [3. BUILD MARKET STATE]
             Regime detection & Indicators
                             │
                [4. ML PREDICTIVE VETO]
              Neural backpropagation test
                             │
                [5. OPPORTUNITY SCORING]
                Expected Net Value (ENV)
                             │
               [6. CONTINUOUS RECONCILE]
              Matches database vs broker
                             │
                 [7. SAFETY INVARIANTS]
             INV-001 through INV-015 check
                             │
                [8. TRADE ADMISSION]
               Final authority barrier
                             │
               [9. EXECUTION SAFETY]
             Rate-limits & fat-finger check
                             │
                  [10. ORDER ROUTING]
               Dispatches to MT5 / Sim
                             │
                   [11. POST-EXECUTION]
                Trailing stops / Case log
```

---

## 📋 3. REQUIREMENTS & ENVIRONMENT

### 3.1 Pre-Requirements (System Dependencies)
Before setting up the project, verify that the following system environments and components are available:

- **Operating System:**
  - *Sovereign Production:* Windows 10/11 or Windows Server (required for native MetaTrader 5 Terminal integration).
  - *Verification & Research:* Ubuntu Linux, macOS, or any POSIX-compliant sandbox (uses the built-in high-fidelity Simulator Connector).
- **Python Runtime:** Python `3.10`, `3.11`, or `3.12` (64-bit).
- **MetaTrader 5 Client:** Configured to allow "Algo Trading" and "WebRequest" connections if trading in live/demo mode.
- **Hardware Profile:** Dual-core CPU minimum (hybrid-core architecture recommended for gil-bypassing parallel scanners), 4GB RAM, 500MB free disk space.

### 3.2 Post-Requirements (Telemetry and Dashboards)
- **Web Browser:** Google Chrome, Mozilla Firefox, or Microsoft Edge to open the self-refreshing live analytical dashboard `dashboard.html`.
- **Text Editor:** VS Code or notepad to inspect `scalper_state.txt` or system log files.

---

## 🔧 4. DETAILED & PRECISE SETUP GUIDE (HOW-TO)

### Step 1: Clone or Extract the Repository
Deploy the code files into your local directory.
```bash
cd D:\forexscalpper
```

### Step 2: Install Python Dependencies
Install the required quantitative library stack using `pip`:
```bash
pip install -r requirements.txt
```

### Step 3: Run the Programmatic Test and Compliance Suite
Always execute the verification suites to confirm local system readiness:
```bash
pytest
```
*Verification success outputs:*
```text
======================= 20 passed, 30 warnings in 1.06s ========================
```

### Step 4: Configure the Bot (`config.py`)
Open `config.py` in your text editor to customize parameters:
- To run paper trading on **any machine (Linux, macOS, Windows)**, set:
  ```python
  SIMULATION_MODE = True
  ```
- To run live or demo trading on **Windows MT5**, set:
  ```python
  SIMULATION_MODE = False
  DEMO_ACCOUNT_ONLY = True  # Set to False to trade real live capital
  ```

### Step 5: Launch the Trading Client
Start the platform:
```bash
python main.py
```
- If a desktop environment is available, the stunning **Tkinter Bloomberg Professional Terminal GUI** will launch automatically.
- If a headless or CLI terminal is detected, the program will fall back gracefully to **Classic Console Mode** with real-time logging.

---

## ❓ 5. DETAILED FAQ

#### Q: How does the system trade Forex on weekends when traditional markets are closed?
**A:** EAQTS incorporates weekday-centric interbank session mapping. If the active session is recognized as `"WEEKEND"`, the system dynamically filters out all Forex and metal pairs, permitting *only* active cryptocurrency symbols (BTC, ETH, LTC, SOL, XRP) to trade continuously.

#### Q: How does the "Safe-by-Disagreement" protocol protect capital?
**A:** If technical indicators suggest a `"BUY"` trend, but the MLP Neural Network outputs a bearish next-candle probability ($< 0.50$), the system flags a state disagreement. This triggers invariant violation `INV-015` and blocks trade admission, preventing entries against market momentum.

#### Q: Can I run this on Linux?
**A:** Yes! When `SIMULATION_MODE = True` in `config.py`, the system activates a high-fidelity market simulator with simulated spreads, slippage, latency, and margin processing, completely bypassing any Windows MT5 dependencies.

---

## 🚨 6. ERROR CODES, CAUSES, AND REMEDIES

EAQTS implements highly verbose, self-explanatory error mappings across the execution boundary to ensure quick diagnoses.

| Error Code | Common Cause | Quantitative Remedy |
| :--- | :--- | :--- |
| **`INV-001`** | Portfolio risk exceeds risk ceilings. | Close high-risk positions or reduce the `RISK_PER_TRADE_PERCENT` variable in `config.py`. |
| **`INV-002`** | Simultaneous trade count exceeds limit. | Wait for open trades to hit SL/TP, or increase `MAX_CONCURRENT_TRADES`. |
| **`INV-013`** | Position discrepancy between DB and Broker. | Trigger **Emergency Position Re-alignment** (sync DB or manually liquidate orphan orders). |
| **`INV-015`** | Intelligence and prediction systems disagree. | No action required. This is a normal defensive risk freeze; trading resumes when signals align. |
| **`5004`** | MQL5 File Open error on restricted folders. | Toggle `InpUseCommonFolder` inside your MetaTrader 5 Expert Advisor HUD. |
| **`10016`** | Invalid stop-loss levels during trailing. | EAQTS automatically normalizes trailing stops relative to minimum broker stop levels (`trade_stops_level`). |
| **`RATE_LIMIT_HALT`**| Message submission exceeds 5 orders/10s. | Wait 10 seconds for the message rate window to clear. System will auto-reset state to `NORMAL`. |

---

## 🛑 7. EMERGENCY ACTION PLAN (EAP)

In the event of a critical system anomaly, adhere to the following emergency workflows:

### Scenario A: Severe Broker Disconnection Outage
1. The operations plane will immediately transition the safety state machine to `"DEFENSIVE"`.
2. All new trade admissions are strictly frozen.
3. The platform initiates a continuous reconnection loop. No user intervention is required.
4. If reconnection is unsuccessful for over 5 minutes, close the main terminal process and verify your network router or VPS provider status.

### Scenario B: Unexpected Drawdown Circuit Breaker Triggered
1. If floating or realized losses exceed `MAX_DAILY_DRAWDOWN_PERCENT` (default: 3.0%), the system raises a critical alert.
2. The safety state machine transitions to `"HALTED"`.
3. All open positions are **autonomously liquidated** on the spot to preserve remain capital.
4. Trading is locked for the remainder of the day. Inspect `SYSTEM_VERIFICATION_REPORT.md` and database trades to analyze performance.

### Scenario C: Unresolved Position Reconciliation Mismatch
1. If the database and broker terminal show conflicting trades, the system raises invariant violation `INV-013` and locks new entries.
2. Under the Bloomberg Terminal GUI, go to the `SET` or `RISK` tab to force a database re-sync.
3. If the discrepancy remains, manually liquidate the conflicting positions on MetaTrader 5 and restart the python core application.

---

## 📖 8. QUANTITATIVE GLOSSARY

- **Brier Score:** A mathematical function measuring the accuracy of probabilistic predictions. Lower scores indicate better-calibrated models.
- **Conditional Value at Risk (CVaR):** Also known as Expected Shortfall (ES). Represents the average loss of an investment portfolio in the worst 5% of cases.
- **Drawdown Hysteresis:** A mathematical lag buffer preventing the system from rapidly toggling safety states when dancing right on a drawdown limit boundary.
- **Kelly 2.0 Sizing:** Our proprietary position-sizing formula that dynamically scales fractional Kelly recommendations downward based on volatility and Expected Shortfall limits.
- **Point-in-Time (PIT):** Data processed exactly as it was known at the historical execution timestamp, completely eliminating future information leaks (look-ahead bias).
- **Regime Transition:** The statistical shift of a market from a range-bound state to a strong trend state.

---

## 🛠️ 9. HELP COMMANDS & ADVANCED NAVIGATION

EAQTS features a complete command line system modeled on professional Bloomberg Terminals. Command formats follow: `[TICKER] [MODULE]`.

- **`MAIN <GO>` (Shortcut F1):** Display multi-asset scanning matrices and technical indicator metrics.
- **`PORT <GO>` (Shortcut F2):** Perform real-time Mean-Variance Sharpe optimization on active assets.
- **`MCTS <GO>` (Shortcut F3):** Run Monte Carlo random walks to calculate portfolio Value at Risk (VaR).
- **`NEWS <GO>` (Shortcut F4):** Access live NLP headlines and prevailing macro sentiment rankings.
- **`CHART <GO>` (Shortcut F10):** Open interactive canvas candlesticks, current quotes, and account equity graphs.
- **`SESS <GO>` (Shortcut F11):** View GMT countdown countdowns across 12 overlapping currency markets.
