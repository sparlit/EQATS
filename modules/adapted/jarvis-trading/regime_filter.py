from __future__ import annotations

import pandas as pd


def classify_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Placeholder for market regime classification."""
    if df.empty:
        raise ValueError("DataFrame is empty")
    df = df.copy()
    df["regime"] = "unknown"
    return df
