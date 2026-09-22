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
Relative Strength calculator.
Measures stock performance vs Nifty 50 using Minervini-weighted formula.
"""

import pandas as pd
import yfinance as yf


def calculate_relative_strength(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None = None,
) -> dict:
    """
    Calculate Minervini-weighted relative strength vs Nifty 50.

    RS = 0.40 × (3-month return) + 0.20 × (6-month return)
       + 0.20 × (9-month return) + 0.20 × (12-month return)

    Args:
        stock_df: DataFrame with 'Close' column, at least 252 rows preferred.
        benchmark_df: DataFrame with 'Close' for Nifty 50.
                      If None, fetches ^NSEI data.

    Returns:
        dict with rs_value, score, and period returns.
    """
    close = stock_df["Close"]
    current = float(close.iloc[-1])

    periods = {
        "3m": min(63, len(close) - 1),
        "6m": min(126, len(close) - 1),
        "9m": min(189, len(close) - 1),
        "12m": min(252, len(close) - 1),
    }

    stock_returns = {}
    for label, days in periods.items():
        if days > 0:
            past = float(close.iloc[-days - 1])
            stock_returns[label] = (current - past) / past * 100 if past > 0 else 0.0
        else:
            stock_returns[label] = 0.0

    # Benchmark returns
    bench_returns = {"3m": 0.0, "6m": 0.0, "9m": 0.0, "12m": 0.0}
    if benchmark_df is not None and len(benchmark_df) > 0:
        bench_close = benchmark_df["Close"]
        bench_current = float(bench_close.iloc[-1])
        for label, days in periods.items():
            days = min(days, len(bench_close) - 1)
            if days > 0:
                past = float(bench_close.iloc[-days - 1])
                bench_returns[label] = (bench_current - past) / past * 100 if past > 0 else 0.0

    # Excess returns
    excess = {k: stock_returns[k] - bench_returns[k] for k in stock_returns}

    # Minervini weighted RS
    rs_value = 0.40 * excess["3m"] + 0.20 * excess["6m"] + 0.20 * excess["9m"] + 0.20 * excess["12m"]

    score = _score_rs(rs_value)

    return {
        "rs_value": round(rs_value, 2),
        "score": round(score, 1),
        "stock_returns": {k: round(v, 2) for k, v in stock_returns.items()},
        "benchmark_returns": {k: round(v, 2) for k, v in bench_returns.items()},
        "excess_returns": {k: round(v, 2) for k, v in excess.items()},
    }


def _score_rs(rs: float) -> float:
    """Score relative strength on 0-100 scale."""
    if rs > 50:
        return 95
    if rs > 30:
        return 80
    if rs > 15:
        return 65
    if rs > 5:
        return 50
    if rs > 0:
        return 35
    return 15
