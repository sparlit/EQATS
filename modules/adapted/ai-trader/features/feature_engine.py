import datetime

import pytz


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
Feature Engine
──────────────
Orchestrates the two-model feature pipeline:

  1. Macro Features  (from 1m candles)  → features_macro table
  2. Micro Features  (from tick data)   → features_micro table

From the docs (Elaborated Challenges):
  Historical 1m data (6 months) → Macro ML Model
  Tick data (5 days + ongoing)  → Microstructure Model
  Both outputs                  → Final trade decision
"""

from typing import Optional

import pandas as pd
from features.indicators import compute_all_macro_indicators
from features.micro_features import compute_micro_features
from utils.logger import get_logger

from config.settings import FEATURE_COLUMNS_MACRO, FEATURE_COLUMNS_MICRO
from database.db import read_sql, write_df

logger = get_logger("feature_engine")


def build_macro_features(
    symbol: str,
    option_chain_df: pd.DataFrame | None = None,
    limit: int = 0,
    enrich_options: bool = True,
) -> pd.DataFrame:
    """
    Build macro feature set from 1-minute candles.
    Reads from minute_candles table, computes all indicators,
    writes to features_macro table, and returns the DataFrame.

    If enrich_options=True and no option_chain_df is provided,
    automatically builds a time-aligned option chain from the DB
    and merges PCR, OI change, OI skew, etc. into the index data.
    """
    query = "SELECT * FROM minute_candles WHERE symbol = :symbol ORDER BY timestamp"
    df = read_sql(query, {"symbol": symbol})

    if df.empty:
        logger.warning(f"No minute candles found for {symbol}.")
        return pd.DataFrame()

    if limit > 0:
        df = df.tail(limit)

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Auto-enrich with option chain data if available
    if option_chain_df is None and enrich_options:
        try:
            from features.option_chain_builder import enrich_index_with_options

            df = enrich_index_with_options(df)
            logger.info("Enriched index with option chain features.")
        except Exception as e:
            logger.warning(f"Option chain enrichment failed: {e}")

    # Compute all macro indicators
    df = compute_all_macro_indicators(df, option_chain_df)

    # Select feature columns + OHLCV (needed for backtest SL/target simulation)
    ohlcv_cols = ["timestamp", "symbol", "open", "high", "low", "close", "volume", "vwap"]
    available_cols = ohlcv_cols + [c for c in FEATURE_COLUMNS_MACRO if c in df.columns]
    available_cols = list(dict.fromkeys(c for c in available_cols if c in df.columns))
    features_df = df[available_cols].copy()

    # Persist to DB
    try:
        write_df(features_df, "features_macro", if_exists="replace")
        logger.info(f"Wrote {len(features_df)} macro feature rows for {symbol}.")
    except Exception as e:
        logger.exception(f"Failed to write macro features: {e}")

    return features_df


def build_micro_features(
    symbol: str,
    tick_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build micro feature set from tick data.
    If tick_df is provided, use it directly. Otherwise read from DB.
    Writes to features_micro table and returns the DataFrame.
    """
    if tick_df is None or tick_df.empty:
        query = "SELECT * FROM tick_data WHERE symbol = :symbol ORDER BY timestamp"
        tick_df = read_sql(query, {"symbol": symbol})

    if tick_df.empty:
        logger.warning(f"No tick data found for {symbol}.")
        return pd.DataFrame()

    # Compute micro features
    features_df = compute_micro_features(tick_df)

    if features_df.empty:
        return features_df

    # Persist to DB (include 'price' for label generation downstream)
    available_cols = ["timestamp", "symbol", "price"] + [c for c in FEATURE_COLUMNS_MICRO if c in features_df.columns]
    available_cols = [c for c in available_cols if c in features_df.columns]
    out = features_df[available_cols].copy()

    try:
        write_df(out, "features_micro", if_exists="replace")
        logger.info(f"Wrote {len(out)} micro feature rows for {symbol}.")
    except Exception as e:
        logger.exception(f"Failed to write micro features: {e}")

    return out


def build_all_features(
    symbol: str,
    option_chain_df: pd.DataFrame | None = None,
    tick_df: pd.DataFrame | None = None,
) -> dict:
    """
    Build both macro and micro features for a symbol.
    Returns {"macro": DataFrame, "micro": DataFrame}.
    """
    macro = build_macro_features(symbol, option_chain_df)
    micro = build_micro_features(symbol, tick_df)

    logger.info(f"Features built for {symbol}: {len(macro)} macro rows, {len(micro)} micro rows.")
    return {"macro": macro, "micro": micro}


def build_feature_dataset():
    """
    Legacy compatibility wrapper.
    Builds macro features for all configured symbols.
    """
    from config.settings import SYMBOLS

    for symbol in SYMBOLS:
        build_macro_features(symbol)
