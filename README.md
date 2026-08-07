# Autonomous Forex Scalper Bot with "The Brain" Decision Engine

This is a professional, autonomous Forex, metals, and crypto scalping bot configured to interface with **MetaTrader 5 (MT5)** on Windows. It is designed to be highly profitable, completely autonomous, and exceptionally safe.

The bot features a beautiful **Tkinter Desktop GUI Dashboard** to monitor balances, see active positions, view live indicator scans for all assets, and easily start/stop the autonomous trading loop with click controls!

Because you are new to trading, the bot defaults to a high-fidelity **Paper Trading Simulator Mode** so you can watch, learn, and test the system completely risk-free before connecting to your real MT5 terminal!

---

## 🚀 Key Features

1. **Tkinter Desktop GUI Dashboard (`gui.py`):**
   - Displays real-time account parameters (Balance, Equity, running concurrent trade count).
   - Scrollable visual matrix table containing all monitored assets (major/minor currency pairs, metals, and cryptocurrencies) with live ticks, trends, RSI values, and detailed plain-English justifications of holding or executing.
   - Simple action buttons to Toggle Simulation Mode, Start, and Stop the bot smoothly.

2. **"The Brain" Decision Engine (`brain.py` & `indicators.py`):**
   - **Trend Filter (200 EMA):** The bot will only take BUY trades in an uptrend (price > 200 EMA) and only SELL trades in a downtrend (price < 200 EMA).
   - **Timing Indicators (9 EMA, 21 EMA, RSI):** Precise entries on pullback deviations. It triggers a buy signal when momentum crosses up and RSI shows oversold levels within an uptrend.
   - **Volatility Protection (ATR):** Dynamically calculates Stop Loss (SL) and Take Profit (TP) levels based on current market noise (Average True Range) for custom risk-to-reward metrics.
   - **Detailed State Explanations:** Explains exactly why it is in "HOLD" state for each asset (e.g., *"UPTrend. Waiting for: RSI 46.6 not oversold (<=35)"*) so you can learn market timings in real-time.

3. **Expanded Symbols Coverage:**
   - Prepopulated and ready to scan **all major/minor forex currency pairs, gold, silver, and major cryptocurrencies** (EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD, USDCAD, EURJPY, EURCAD, GBPJPY, GBPCAD, XAUUSD, XAGUSD, BTCUSD, ETHUSD, SOLUSD, LTCUSD, etc.).

4. **Capital & Risk Management Safeguards:**
   - **Dynamic Lot Sizing:** Automatically calculates contract sizes based on asset types (Forex standard lots, Metal oz contracts, Cryptos) so a single trade **never risks more than 1%** of your equity.
   - **Daily Loss Circuit Breaker:** Stops trading for the day if total losses exceed **3%** of your starting balance.
   - **Max Position Capping:** Controls maximum simultaneous open positions across different currency pairs.
   - **Demo Account Safeguard:** Blockades live account trading unless explicitly enabled.

5. **High-Fidelity Market Simulator (`connector.py`):**
   - Automatically runs a comprehensive market simulation when `SIMULATION_MODE = True` (or if you are running on a non-Windows OS). Perfect for test-running!

6. **Self-Updating Web Dashboard (`dashboard.html`):**
   - On every loop tick, writes an interactive, auto-refreshing dashboard HTML file you can view on any browser on your computer.

---

## 🛠️ Code Architecture

- **`config.py`**: All parameter configurations (risks, indicators, assets, simulation, Telegram settings).
- **`database.py`**: SQLite database functions for trade and metrics tracking.
- **`indicators.py`**: High-performance mathematical algorithms for trend and oscillator indicators.
- **`brain.py`**: Decision-making calculations, lot sizing, and natural-language justifications.
- **`connector.py`**: Abstract interface and implementations for MT5 and the Market Simulator.
- **`telegram_bot.py`**: Standard message notifications.
- **`main.py`**: The central execution loop coordinating ticks, positions, and safety rules.
- **`test_scalper.py`**: Diagnostic unit and integration tests.

---

## 💻 How to Run the Bot

### Step 1: Pre-requisites
Make sure you have Python 3 installed.

```bash
pip install -r requirements.txt
```
*(If on Windows, you can also install MetaTrader 5 module: `pip install MetaTrader5`)*

### Step 2: Running in Paper Trading (Simulation) Mode
1. Ensure `SIMULATION_MODE = True` in `config.py`.
2. Start the autonomous loop:
   ```bash
   python3 main.py
   ```
3. Watch the bot analyze the trends, explain its logic, open mock orders, and automatically manage profits/losses!

### Step 3: Connecting to your Live Windows MT5
1. Open your MetaTrader 5 application on your Windows machine.
2. Ensure you are logged into your **Demo Account** (Highly recommended first!).
3. Edit `config.py` and set:
   ```python
   SIMULATION_MODE = False
   ```
4. Run the script:
   ```bash
   python main.py
   ```
5. The bot will automatically initialize, connect directly to your MT5, and handle trading autonomously!

---

## 🔬 Running Tests
Run the standard test runner to verify indicators, connectors, and database routines:
```bash
python3 -m unittest test_scalper.py
```
