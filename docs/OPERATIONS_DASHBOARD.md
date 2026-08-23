# Operations Dashboard Guide — EQATS Quantum Terminal (`gui.py`) — EAQTS Version 6.0

## Overview

The `gui.py` desktop GUI is the primary operational command terminal for the **Elite Quantum Autonomous Trading System (EAQTS / EQATS Version 6.0)**. Built in Tkinter, it provides a multi-sheet desktop interface for real-time market monitoring, algorithmic strategy selection, neural network telemetry, risk controls, and emergency manual overrides.

```
+-------------------------------------------------------------------------------+
| EAQTS: ELITE QUANTUM TRADING SYSTEM <GO>            [ SIMULATION / MT5 LIVE ] |
| Command Bar: EAQTS > MAIN <GO>          [F2 MAIN] [F3 GP] [F4 WEI] ...       |
+-------------------------------------------------------------------------------+
| ACTIVE SESSIONS   > Tokyo FX | London FX | New York FX                         |
| CLOSED <= 4H      > Wellington FX                                             |
| UPCOMING SESSIONS > Sydney ASX (01:42:10)                                     |
+-------------------------------------------------------------------------------+
| 1) BALANCE   | 2) EQUITY   | 3) ACTIVE  | 4) SESSION | 5) PERF   | 6) PnL     |
| $10,000.00   | $10,000.00  | 0 / 10     | London FX  | WR: 62%   | +$250.00   |
+-------------------------------------------------------------------------------+
| [ Central Switchable Display Sheet Frame ]                                    |
| (MAIN, GP, WEI, NEWS, ANL, PORT, MCTS, VDS, CHART, SESS, MKT, WATCH, etc.)    |
+-------------------------------------------------------------------------------+
| [ REAL-TIME SYSTEM DIAGNOSTICS & TELEMETRY STREAM CONSOLE ]                   |
+-------------------------------------------------------------------------------+
| ▶ START TRADING | 🛑 STOP BOT | ⚡ CLOSE ALL | ⏸ PAUSE | 🔒 PANIC | 🔄 RESET   |
+-------------------------------------------------------------------------------+
```

---

## Command Navigation & F-Key Quick Links

Operators navigate the terminal by typing command codes into the `EAQTS >` input box and pressing `<GO>` (or `Enter`), or by using function key shortcuts:

| Shortcut Key | Terminal Code | Sheet Name & Operational Function |
|---|---|---|
| **F2** | `MAIN <GO>` | Scans Matrix & Active Running Positions Terminal |
| **F3** | `GP <GO>` | Graphical Price Chart & Quote Intelligence Card |
| **F4** | `WEI <GO>` | World Exchange & Equity Indices Tracking Board (DXY, SPX, BTC) |
| **F5** | `NEWS <GO>` | Live Global Macro Headlines & NLP Sentiment Scores |
| **F6** | `ANL <GO>` | Consensus Analyst Recommendations & Neural Network MLP State |
| **F7** | `PORT <GO>` | Markowitz Portfolio Allocator & Mean-Variance Sharpe Solver |
| **F8** | `MCTS <GO>` | Monte Carlo Risk Engine (95% VaR & Expected Shortfall) |
| **F9** | `VDS <GO>` | Vector Database Hidden Layer Activations & L2 Search |
| **F10** | `CHART <GO>` | Interactive Candlestick Chart & Performance Curve |
| **F11** | `SESS <GO>` | Multi-Session World Timelines & Overlap Detectors |
| **F1** | `HELP <GO>` | Operational Manual & Full Terminal Directory |

### Additional Terminal Sheets
- `SET <GO>` / `CFG <GO>`: System Settings, Broker DB CRUD & Multi-Broker Credentials *(Protected by Secondary PIN)*.
- `WATCH <GO>`: Interactive Symbols Watchlist with fixed sticky header and MTF heatmap.
- `MKT <GO>`: Integrated Market Scanners, Movers & 13 Specialized Sub-Tabs.
- `TRADEBOOK <GO>`: Settled Closed Trades Ledger & Trade Memory Protocol.
- `AGENT <GO>`: AI System Supervisor Agent Governance & Audit Logs.
- `ECOSYSTEM <GO>`: Full Multi-Agent Parallel Architecture Visualizer.
- `SENTIMENT <GO>`: Deep NLP News Sentiment Analyzer & SEC Filing Parser.
- `PREDICTOR <GO>`: Stock Market Predictor with Next-Candle Forecast Curves.
- `DOM <GO>`: Level 2 Depth of Market Order Book & Footprint Volume Delta.
- `WHALE <GO>`: Crypto On-Chain Large Transfer Tracker & Funding Rates.
- `BACKTEST <GO>`: Event-Driven Walk-Forward Backtesting Workspace.
- `OPTIONS <GO>`: Black-Scholes Greeks & Market Maker Gamma Exposure (GEX).
- `REGIME <GO>`: Markov Regime-Switching Autoregressive Volatility Model.
- `TZCONV <GO>`: Forex Market Time Zone & Timeline Converter (Kolkata, UTC, NY, etc.).

---

## Market Screen (`MKT <GO>`) — 13 Specialized Sub-Tabs

The `MKT <GO>` screen features a 2-row navigation bar providing single-click access to 13 market analytics sub-tabs:

1. **1. Messages**: Exchange System Alerts, B-Pipe Heartbeats, and FIX Quote Requests.
2. **2. Movers**: Highest Price Change Movers, Net Changes, and Regime Momentum.
3. **3. Scanners**: Real-Time ATR Volatility, RSI Oversold/Overbought, and Bollinger Squeezes.
4. **4. Fundamentals**: Corporate Issuer Details, Market Caps, Coupon Yields, and SEC Filing Links.
5. **5. Corp Actions**: Validator Upgrades, Margin Resets, and Central Bank Rate Decisions.
6. **6. Market Hours**: Active Global Market Sessions, UTC Intervals, and Volume Profiles.
7. **7. Correlation**: 8x8 Currency Correlation Matrix across FX Majors.
8. **8. Risk-On/Off**: Global Risk-On / Risk-Off Sentiment Meter and Market Proxies.
9. **9. Gain & Loss**: Drawdown Recovery Percentage Calculator (Break-even gain solver).
10. **10. Pip Value**: Pip Value Calculator across Standard, Mini, and Micro Lot Sizes.
11. **11. Pivots**: Multi-System Pivot Point Calculator (Standard Floor, Fibonacci, Camarilla).
12. **12. Position Size**: Position Size Calculator based on Account Equity & Risk %.
13. **13. Regulation**: Global Forex Regulatory Organizations Directory (CFTC, FCA, ASIC, CySEC, FINMA, JFSA).

---

## Emergency Safety Controls & Manual Overrides

The bottom control bar provides immediate manual override actions for risk management:

- **▶ START TRADING**: Spawns the background coordinator thread to begin autonomous market scans and trade executions.
- **🛑 STOP BOT**: Gracefully pauses the autonomous trading loop while leaving open positions intact.
- **⚡ CLOSE ALL**: Instantly liquidates all running open positions across all active symbols.
- **⏸ PAUSE ADMISSION**: Freezes new trade order submissions and transitions safety state to `DEFENSIVE`.
- **🔒 PANIC LOCKDOWN**: Emergency action that liquidates all open orders, freezes admissions, transitions state to `DEFENSIVE`, and stops the trading loop.
- **🔄 RESET ENGINES**: Re-initializes strategy brain buffers, clears indicator caches, and runs a supervisor safety audit.
- **🗔 DETACH TAB**: Opens the active terminal sheet in a standalone floating window for multi-monitor workspaces.
- **❌ EXIT SYSTEM**: Stops all background processes, closes broker connections, and terminates the application cleanly.

---

## Operator Authentication & Security

1. **Primary Login Gateway**:
   On application launch, `_show_login_dialog()` opens a full-screen Matrix digital rain gateway. Operators authenticate using:
   - Operator Username (e.g. `QUANT_OPERATOR`)
   - Gateway Password
   - Secondary MFA PIN (e.g. `123456`)
   Authentication is validated against salt-hashed SHA-256 digests stored in SQLite (`users` table).

2. **Secondary PIN Protection**:
   Accessing configuration sheets (`SET <GO>`, `CFG <GO>`) triggers `_prompt_secondary_pin()`, requiring secondary authorization before displaying sensitive broker API keys, database credentials, or risk parameter overrides.

---

## Diagnostics Console & Telemetry

The bottom console panel displays a timestamped, scrollable stream of real-time diagnostics, including:
- Heartbeat connection status
- Cognitive scan cycle outputs
- System Constitution Hierarchy evaluations
- Circuit breaker trip notifications
- Trade admission approvals and rejections
