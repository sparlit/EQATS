from __future__ import annotations

import pandas as pd


def max_open_positions(df: pd.DataFrame, max_positions: int = 2) -> pd.DataFrame:
    """Limit the number of open position candidates."""
    if df.empty:
        raise ValueError("DataFrame is empty")
    return df.head(max_positions).copy()
