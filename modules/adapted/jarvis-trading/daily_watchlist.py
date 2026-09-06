from __future__ import annotations

import pandas as pd


def generate_daily_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    """Generate a daily watchlist from screened candidates."""
    if df.empty:
        return df.copy()
    return df.copy()
