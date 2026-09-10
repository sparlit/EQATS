# -*- coding: utf-8 -*-
"""
Data Store Module
================

Manages data persistence and caching:
- Local database storage
- Incremental data updates
- Cache management
- Data versioning
"""

import contextlib
import json
import logging
import os
import pickle
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
import pytz

from src.data.trading_calendar import (
    consolidate_date_ranges,
    get_missing_trading_days,
    get_trading_days_set,
)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

logger = logging.getLogger(__name__)


def is_ist_market_session_active(dt: datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.now(ist)
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


class DataStore:
    """Data store for managing persistent data storage."""

    def __init__(self, base_dir: str | None = None):
        """
        Initialize data store.

        Args:
            base_dir: Base directory for data storage (uses config.data.base_dir if None)
        """
        # Use config settings if base_dir not provided
        if base_dir is None:
            try:
                from src.config.settings import get_config

                config = get_config()
                base_dir = config.data.base_dir
            except Exception as e:
                logger.warning(f"Failed to load config, using default 'data': {e}")
                base_dir = "data"

        self.base_dir = Path(base_dir)
        self.processed_dir = self.base_dir / "processed"
        self.db_path = self.base_dir / "finrl_trading.db"

        # Create directories
        for dir_path in [self.base_dir, self.processed_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create price data table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    timeframe TEXT DEFAULT '1d',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timestamp, timeframe)
                )
            """)

            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_data_symbol_timestamp 
                ON price_data(symbol, timestamp)
            """)

            # Create metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()