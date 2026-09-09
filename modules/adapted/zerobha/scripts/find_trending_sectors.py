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


#!/usr/bin/env python3
"""
Find Trending Sectors Script.

Analyzes Nifty 500 stocks to identify top trending sectors based on relative strength
vs a benchmark index (Nifty 50 by default). Calculates both absolute and relative returns
across different time periods (1 week, 1 month, 3 months) and generates buy/sell signals
based on momentum patterns.
"""
import argparse
import concurrent.futures
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd
import yfinance as yf

# Configure logging with file:linenumber
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Weight configuration for different time periods
WEIGHT_1W = 0.5  # 50% weight for 1 week returns
WEIGHT_1M = 0.3  # 30% weight for 1 month returns
WEIGHT_3M = 0.2  # 20% weight for 3 month returns


@dataclass
class StockReturn:
    """Represents calculated returns for a single stock."""

    symbol: str
    industry: str
    return_1w: float | None
    return_1m: float | None
    return_3m: float | None
    weighted_return: float | None
    # Relative strength vs benchmark
    rs_1w: float | None
    rs_1m: float | None
    rs_3m: float | None
    weighted_rs: float | None


def calculate_returns(prices: pd.Series) -> tuple[float | None, float | None, float | None]:
    """
    Calculate 1-week, 1-month, and 3-month returns from price series.

    Args:
        prices: Series of closing prices indexed by date.

    Returns:
        Tuple of (1w_return, 1m_return, 3m_return) as percentages.
    """
    if prices.empty or len(prices) < 5:
        return None, None, None

    prices = prices.sort_index()
    current_price = prices.iloc[-1]

    # Calculate trading days for each period
    # Approximate trading days: 1 week ~5 days, 1 month ~22 days, 3 months ~66 days
    return_1w = None
    return_1m = None
    return_3m = None

    if len(prices) >= 5:
        price_1w_ago = prices.iloc[-min(5, len(prices) - 1)]
        return_1w = ((current_price - price_1w_ago) / price_1w_ago) * 100

    if len(prices) >= 22:
        price_1m_ago = prices.iloc[-min(22, len(prices) - 1)]
        return_1m = ((current_price - price_1m_ago) / price_1m_ago) * 100

    if len(prices) >= 66:
        price_3m_ago = prices.iloc[-min(66, len(prices) - 1)]
        return_3m = ((current_price - price_3m_ago) / price_3m_ago) * 100

    return return_1w, return_1m, return_3m
