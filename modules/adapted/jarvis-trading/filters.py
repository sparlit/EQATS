from __future__ import annotations

import pandas as pd


def filter_by_volume(df: pd.DataFrame, min_volume: int) -> pd.DataFrame:
    """Filter securities by minimum average volume."""
    if df.empty:
        raise ValueError("DataFrame is empty")
    if "volume" not in df.columns:
        raise ValueError("DataFrame must contain 'volume' column")
    return df[df["volume"] >= min_volume].copy()
