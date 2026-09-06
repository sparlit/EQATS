from __future__ import annotations

from typing import Any

import pandas as pd

from storage.db import append_trade, get_trades_df


def append_trade_log(trade: dict[str, Any]) -> None:
    """Persist a trade journal entry to storage."""
    append_trade(trade)


def load_trade_journal(limit: int = 100) -> pd.DataFrame:
    """Load the trade journal as a DataFrame."""
    return get_trades_df(limit=limit)
