import logging
import os

# Configuration file for the Forex Scalper Bot

_log = logging.getLogger("config")

# 1. Operational Mode
# Set to True for running in testing / paper trading simulation. Set to False for Windows MT5 integration.
SIMULATION_MODE = False

# Safety setting. If False, the bot can trade on a Live / Real account.
DEMO_ACCOUNT_ONLY = True

# Path to local MT5 Terminal Executable (Windows)
MT5_TERMINAL_PATH = r"C:\Program Files\Alpari MT5\terminal64.exe"

# 2. Assets to Trade
# Fully expanded list including Majors, Minors, Metals (Gold, Silver), and Cryptos
SYMBOLS = [
    # --- Majors & Major Crosses ---
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    # --- Minors & Minor Crosses ---
    "EURGBP",
    "EURJPY",
    "EURCAD",
    "EURCHF",
    "EURNZD",
    "EURAUD",
    "GBPJPY",
    "GBPCAD",
    "GBPCHF",
    "GBPAUD",
    "GBPNZD",
    "AUDJPY",
    "NZDJPY",
    "CHFJPY",
    "CADJPY",
    "AUDCAD",
    "AUDNZD",
    "NZDCAD",
    # --- Metals ---
    "XAUUSD",
    "XAGUSD",
    # --- Cryptocurrencies ---
    "BTCUSD",
    "ETHUSD",
    "LTCUSD",
    "SOLUSD",
    "XRPUSD",
]

# Scalping timeframe (M1 = 1 Minute, M5 = 5 Minutes)
# In MT5 Python, these map to MT5 timeframe constants.
TIMEFRAME_NAME = "M1"

# 3. Risk and Money Management
RISK_PER_TRADE_PERCENT = 1.0  # Risk exactly 1% of equity per trade
MAX_DAILY_DRAWDOWN_PERCENT = (
    3.0  # Stop trading for the day if 3% of account balance is lost
)
MAX_CONCURRENT_TRADES = 20  # Max simultaneous open trades across all symbols (production safety limit)
RISK_REWARD_RATIO = 2.0  # Win target is 2.0x of the stop loss distance

# Trade Admission Expected Value Threshold
# SECURITY: Minimum expected net value (in price units) required for trade admission
# This prevents admission of trades with zero or fabricated edge calculations
# Default: 0.00001 (approximately 0.1 pips for standard forex pairs)
MIN_EXPECTED_NET_VALUE_THRESHOLD = 0.00001

# Advanced Risk Settings & Sub-Allocation Controls
ENABLE_SYMBOL_FLOATING_LOSS_GATE = True  # Protects against stacking losses on same symbol
GLOBAL_RISK_LIMIT_CAP_PERCENT = 100.0   # Max aggregate account risk percentage across all trades
DEDICATED_RISK_SUB_ALLOCATION_ENABLED = True  # Sub-allocates risk per active strategy/method
AUTO_RISK_MANAGEMENT = False            # Auto-tunes risk parameters based on account equity and regime
ATR_PERIOD = 14  # Period for Average True Range volatility calculation
ATR_MULTIPLIER_SL = 1.5  # Stop loss distance = 1.5 * ATR

# 3.1 Advanced Autonomy Filters & Protection Layers
MAX_SPREAD_PIPS = (
    3.0  # Max allowed spread in pips (prevents trading in illiquid expand times)
)
BLOCK_ROLLOVER_HOUR = True  # Blocks entries during broker rollover (22:00 - 23:00 GMT)
BLOCK_WEEKENDS = True  # Blocks weekend trading (Friday 21:00 - Sunday 21:00 GMT)
TRAILING_STOP_ENABLED = True  # Dynamic profit lock
TRAILING_STOP_ATR_MULT = 1.5  # Trailing distance = 1.5 * ATR

# 4. Strategy Selection and Tuning
# Supported active strategies: "TREND_FOLLOWING", "MEAN_REVERSION", "MACD_MOMENTUM", "VOTING_ENSEMBLE", "BREAKOUT", "CARRY_TRADE", "GRID_TRADE", "STAT_ARB", "ORB", "VSA", "MTF_CONFLUENCE", "SMC_ICT", "ORDER_FLOW", "MULTI_STRATEGY_CONCURRENT", "MULTI_HYBRID_PARALLEL", "AUTO"
ACTIVE_STRATEGY = "AUTO"

# Supported active trading styles: "SCALPING", "DAY_TRADING", "SWING_TRADING", "POSITION_TRADING", "AUTO"
TRADING_STYLE = "AUTO"

# --- BREAKOUT STRATEGY CONFIG ---
BREAKOUT_PERIOD = 20  # Lookback period for Donchian Channel breakout detection
SQUEEZE_RSI_MAX = 60  # Upper RSI limit for breakout squeeze filtering
SQUEEZE_RSI_MIN = 40  # Lower RSI limit for breakout squeeze filtering

# --- CARRY TRADE CONFIG ---
# Estimated simulated dynamic Swap/Rollover yield points (favors positive yield assets)
SWAP_LONG_POINTS = {
    "USDJPY": 12.5,  # High positive carry for buy
    "EURUSD": -4.2,  # Negative carry
    "GBPUSD": -3.1,
    "AUDUSD": 4.5,  # Positive carry
    "XAUUSD": -18.5,  # High negative storage fee
    "BTCUSD": 0.0,
    "ETHUSD": 0.0,
}
MIN_CARRY_YIELD_POINTS = (
    2.0  # Minimum positive swap points required to allow positive-carry bias trade
)

# --- GRID TRADE CONFIG ---
GRID_MAX_LEVELS = 5  # Max buy/sell layers in the grid matrix
GRID_SPACING_ATR_MULT = (
    1.2  # Spacing interval between grid layers expressed as a multiplier of ATR
)

# EMA / Trend / Pullback Strategy Parameters
EMA_LONG_PERIOD = 200  # Long-term trend filter
EMA_SHORT_PERIOD = 9  # Trigger fast EMA
EMA_MEDIUM_PERIOD = 21  # Trigger medium EMA
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 35  # Buy when RSI is low (pullback in uptrend)
RSI_SELL_THRESHOLD = 65  # Sell when RSI is high (pullback in downtrend)

# Bollinger Bands Mean Reversion Parameters
BB_PERIOD = 20
BB_STD_DEV = 2.0

# MACD Momentum Parameters
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 5. Database & Multi-Terminal Integration
DB_PATH = "scalper_brain.db"

# The Windows common folder path for sharing real-time state with the MQL5 EA (using FILE_COMMON)
# Default is current workspace, can be changed to Roaming/MetaQuotes/Terminal/Common/Files on Windows.
MT5_COMMON_FILES_PATH = os.environ.get("MT5_COMMON_PATH", ".")
if os.name == "nt" and "APPDATA" in os.environ:
    standard_mt5_common_path = os.path.join(
        os.environ["APPDATA"], "MetaQuotes", "Terminal", "Common", "Files"
    )
    try:
        os.makedirs(standard_mt5_common_path, exist_ok=True)
        MT5_COMMON_FILES_PATH = standard_mt5_common_path
    except Exception as e:
        _log.debug(
            "Cannot use standard MT5 common path %r, falling back to cwd: %s",
            standard_mt5_common_path,
            e,
        )

# 6. Telegram Notifications
TELEGRAM_ENABLED = False
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 7. Execution Loop
CHECK_INTERVAL_SECONDS = 5  # How often to check for candles and trade opportunities
