from __future__ import annotations

import pandas as pd


def rank_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """Rank screened candidates by score."""
    if df.empty:
        raise ValueError("Input DataFrame is empty")
    return df.sort_values(by="score", ascending=False).reset_index(drop=True)
