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


"""
Backtest Strategy Engine — Gate Variants

apply_gate(gate_id, signals_df) → filtered DataFrame

Precondition for ALL gates: in_universe == True
Additional filters stacked per gate definition in config.py.
"""

import pandas as pd
from backtest.strategies.config import GATE_DEFINITIONS


def apply_gate(gate_id: str, signals: pd.DataFrame) -> pd.DataFrame:
    """
    gate_id  : 'G1' through 'G5'
    signals  : full signals DataFrame for one Friday

    Returns  : filtered DataFrame — in_universe=True + gate conditions
    """
    assert gate_id in GATE_DEFINITIONS, f"Unknown gate_id: {gate_id}"

    # precondition — all gates
    df = signals[signals["in_universe"]].copy()
    n_start = len(df)

    # additional gate conditions
    for col, op, val in GATE_DEFINITIONS[gate_id]:
        assert col in df.columns, f"Gate column '{col}' not in signals"
        before = len(df)

        if op == "eq":
            df = df[df[col] == val]
        elif op == "gt":
            df = df[df[col] > val]
        elif op == "gte":
            df = df[df[col] >= val]
        elif op == "lt":
            df = df[df[col] < val]
        elif op == "lte":
            df = df[df[col] <= val]
        elif op == "not_in":
            df = df[~df[col].isin(val)]
        else:
            raise ValueError(f"Unknown operator: {op}")

        after = len(df)
        print(f"  [{gate_id}] {col} {op} {val}: {before} → {after}")

    print(f"  [{gate_id}] survivors: {n_start} → {len(df)}")
    return df.reset_index(drop=True)
