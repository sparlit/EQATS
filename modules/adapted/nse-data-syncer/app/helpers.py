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


"""Helper functions for the stock data syncer"""

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .constants import DATA_MISMATCH_THRESHOLD, VALIDATION_RECORDS_COUNT


def get_project_root() -> Path:
    """Returns the project root directory."""
    return Path(__file__).parent.parent


def get_data_path(filename: str) -> Path:
    """Returns the full path to a file in the data directory."""
    return get_project_root() / "data" / filename


def validate_data_mismatch(symbol: str, df_validation: pd.DataFrame, last_records: dict[date, float]) -> bool:
    """
    Validates fetched data against existing database records.
    Returns True if mismatch is detected (triggering full resync).
    """
    if df_validation.empty or not last_records:
        return False

    for date_obj, row in df_validation.iterrows():
        if date_obj in last_records:
            db_close = last_records[date_obj]
            new_close = row["Close"]
            if db_close == 0:
                continue
            diff = abs(db_close - new_close) / db_close
            if diff > DATA_MISMATCH_THRESHOLD:
                print(
                    f"  Mismatch detected for {symbol} on {date_obj}: "
                    f"DB={db_close}, New={new_close}. Triggering full resync."
                )
                return True
    return False


from typing import Optional


def determine_fetch_strategy(
    last_synced_date: date | None, is_full_resync: bool, df: pd.DataFrame | None
) -> tuple[date | None, bool]:
    """
    Determines the start date and whether to fetch data.
    Returns (start_date, should_fetch)
    """
    if is_full_resync:
        return None, True

    if df is not None:
        return None, False

    if last_synced_date:
        return last_synced_date + timedelta(days=1), True

    return None, True  # New stock, fetch all
