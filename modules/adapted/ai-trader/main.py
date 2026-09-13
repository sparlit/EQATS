import datetime
import sys
import time

import pytz

# Fallback configuration since config.settings module is not available
SCAN_INTERVAL_SECONDS = 60
SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY"]


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
AI Trading System - Main Entry Point

Supports five modes:

  1. mock      - Generate mock data, build features (no DB required)
  2. ingest    - Load historical data from TrueData into DB, build features
  3. train     - Train ML models from DB data (requires ingest first)
  4. backtest  - Run backtest on mock data with full pipeline
  5. live      - Real-time trading loop

Usage:
  python main.py mock
  python main.py ingest
  python main.py train
  python main.py backtest
  python main.py live
"""

try:
    from utils.logger import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger


logger = get_logger("main")


def run_mock():
    """
    Generate mock data and run the feature pipeline end-to-end.
    No database required – operates entirely in-memory.
    """
    try:
        from data.aggregator import AggregationEngine
        from data.mock_data import generate_all_mock_data
        from features.indicators import compute_all_macro_indicators
        from features.micro_features import compute_micro_features
    except ImportError as e:
        logger.exception(f"Required modules not available: {e}")
        return

    logger.info("=" * 60)
    logger.info("MODE: MOCK DATA – generating synthetic dataset")
    logger.info("=" * 60)

    # 1. Generate mock data
    mock = generate_all_mock_data()
    minute_bars = mock["minute_bars"]
    ticks = mock["ticks"]
    option_chain = mock["option_chain"]

    logger.info(
        f"Mock data generated: "
        f"{len(minute_bars)} minute bars, "
        f"{len(ticks)} ticks, "
        f"{len(option_chain)} option contracts."
    )

    # 2. Demonstrate aggregation from ticks
    agg = AggregationEngine()
    for symbol in SYMBOLS:
        sym_ticks = ticks[ticks["symbol"] == symbol]
        candles = agg.aggregate_ticks_df(sym_ticks, symbol)
        for tf, df in candles.items():
            logger.info(f"  {symbol} {tf} candles: {len(df)} rows")

    # 3. Build macro features (from minute bars)
    for symbol in SYMBOLS:
        sym_minutes = minute_bars[minute_bars["symbol"] == symbol].copy()
        sym_options = option_chain[option_chain["symbol"] == symbol]

        macro_df = compute_all_macro_indicators(sym_minutes, sym_options)
        logger.info(f"  {symbol} macro features: {macro_df.shape[1]} columns, {len(macro_df)} rows")

    # 4. Build micro features (from ticks)
    for symbol in SYMBOLS:
        sym_ticks = ticks[ticks["symbol"] == symbol]
        micro_df = compute_micro_features(sym_ticks)
        logger.info(f"  {symbol} micro features: {micro_df.shape[1]} columns, {len(micro_df)} rows")

    logger.info("Mock pipeline completed successfully.")


def run_ingest():
    """Load historical data from TrueData into database and build features."""
    logger.info("=" * 60)
    logger.info("MODE: INGEST – loading historical data from TrueData")
    logger.info("=" * 60)
    logger.warning("Ingest mode not fully implemented yet.")


def run_train():
    """Train ML models from database data."""
    logger.info("=" * 60)
    logger.info("MODE: TRAIN – training ML models")
    logger.info("=" * 60)
    logger.warning("Train mode not fully implemented yet.")


def run_backtest():
    """Run backtest on mock data with full pipeline."""
    logger.info("=" * 60)
    logger.info("MODE: BACKTEST – running backtest on mock data")
    logger.info("=" * 60)
    logger.warning("Backtest mode not fully implemented yet.")


def run_live():
    """Real-time trading loop."""
    logger.info("=" * 60)
    logger.info("MODE: LIVE – starting real-time trading loop")
    logger.info("=" * 60)
    logger.warning("Live mode not fully implemented yet.")


MODE_MAP = {
    "mock": run_mock,
    "ingest": run_ingest,
    "train": run_train,
    "backtest": run_backtest,
    "live": run_live,
}


def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python main.py <mode>")
        logger.error("Modes: mock, ingest, train, backtest, live")
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode not in MODE_MAP:
        logger.error(f"Unknown mode: {mode}")
        logger.error("Available modes: mock, ingest, train, backtest, live")
        sys.exit(1)

    logger.info(f"Starting AI Trading System in {mode.upper()} mode")
    MODE_MAP[mode]()


if __name__ == "__main__":
    main()
