import os

# Configuration file for the Forex Scalper Bot

# 1. Operational Mode
# Set to True for running in testing / paper trading simulation. Set to False for Windows MT5 integration.
SIMULATION_MODE = True

# Safety setting. If False, the bot can trade on a Live / Real account.
DEMO_ACCOUNT_ONLY = True

# 2. Assets to Trade
# Fully expanded list including Majors, Minors, Metals (Gold, Silver), and Cryptos
SYMBOLS = [
    # --- Majors & Major Crosses ---
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    # --- Minors & Minor Crosses ---
    "EURGBP", "EURJPY", "EURCAD", "EURCHF", "EURNZD", "EURAUD",
    "GBPJPY", "GBPCAD", "GBPCHF", "GBPAUD", "GBPNZD",
    "AUDJPY", "NZDJPY", "CHFJPY", "CADJPY", "AUDCAD", "AUDNZD", "NZDCAD",
    # --- Metals ---
    "XAUUSD", "XAGUSD",
    # --- Cryptocurrencies ---
    "BTCUSD", "ETHUSD", "LTCUSD", "SOLUSD", "XRPUSD"
]

# Scalping timeframe (M1 = 1 Minute, M5 = 5 Minutes)
# In MT5 Python, these map to MT5 timeframe constants.
TIMEFRAME_NAME = "M1"

# 3. Risk and Money Management
RISK_PER_TRADE_PERCENT = 1.0       # Risk exactly 1% of equity per trade
MAX_DAILY_DRAWDOWN_PERCENT = 3.0   # Stop trading for the day if 3% of account balance is lost
MAX_CONCURRENT_TRADES = 3          # Max simultaneous open trades across all symbols
RISK_REWARD_RATIO = 2.0            # Win target is 2.0x of the stop loss distance
ATR_PERIOD = 14                    # Period for Average True Range volatility calculation
ATR_MULTIPLIER_SL = 1.5            # Stop loss distance = 1.5 * ATR

# 4. Strategy Selection and Tuning
# Supported active strategies: "TREND_FOLLOWING", "MEAN_REVERSION", "MACD_MOMENTUM", "VOTING_ENSEMBLE"
ACTIVE_STRATEGY = "VOTING_ENSEMBLE"

# EMA / Trend / Pullback Strategy Parameters
EMA_LONG_PERIOD = 200              # Long-term trend filter
EMA_SHORT_PERIOD = 9               # Trigger fast EMA
EMA_MEDIUM_PERIOD = 21             # Trigger medium EMA
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 35             # Buy when RSI is low (pullback in uptrend)
RSI_SELL_THRESHOLD = 65            # Sell when RSI is high (pullback in downtrend)

# Bollinger Bands Mean Reversion Parameters
BB_PERIOD = 20
BB_STD_DEV = 2.0

# MACD Momentum Parameters
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 5. Database Settings
DB_PATH = "scalper_brain.db"

# 6. Telegram Notifications
TELEGRAM_ENABLED = False
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 7. Execution Loop
CHECK_INTERVAL_SECONDS = 15        # How often to check for candles and trade opportunities
