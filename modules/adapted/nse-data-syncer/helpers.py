"""Helper functions for the stock data syncer"""

import os
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
from .constants import DATA_MISMATCH_THRESHOLD, VALIDATION_RECORDS_COUNT


def get_project_root() -> Path:
    """Returns the project root directory."""
    return Path(__file__).parent.parent


def get_data_path(filename: str) -> Path:
    """Returns the full path to a file in the data directory."""
    return get_project_root() / "data" / filename


def validate_data_mismatch(
    symbol: str,
    df_validation: pd.DataFrame,
    last_records: dict[date, float]
) -> bool:
    """
    Validates fetched data against existing database records.
    Returns True if mismatch is detected (triggering full resync).
    """
    if df_validation.empty or not last_records:
        return False

    for date_obj, row in df_validation.iterrows():
        if date_obj in last_records:
            db_close = last_records[date_obj]
            new_close = row['Close']
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
    last_synced_date: Optional[date],
    is_full_resync: bool,
    df: Optional[pd.DataFrame]
) -> tuple[Optional[date], bool]:
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

