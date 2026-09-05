from __future__ import annotations

import pandas as pd


def score_universe(df: pd.DataFrame) -> pd.DataFrame:
    """Assign a score to each candidate symbol."""
    if df.empty:
        raise ValueError("Input DataFrame is empty")
    df = df.copy()
    df["score"] = 0
    return df
