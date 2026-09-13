from __future__ import annotations

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


"""Read-only walk-forward screen-return validation using stored EOD snapshots."""

import pandas as pd

from .features import latest_features
from .scoring import score


def run(prices: pd.DataFrame, *, holding_sessions: int = 20, sample_step: int = 120, top_n: int = 25) -> dict:
    """Measure forward close returns for qualified screens without downloads.

    This is deliberately labelled a screen-return proxy: it does not claim to
    model fills, stops, slippage, or executable P&L.
    """
    dates = sorted(pd.to_datetime(prices["trade_date"]).dropna().unique())
    rows: list[dict] = []
    for index in range(320, len(dates) - holding_sessions, sample_step):
        as_of = dates[index]
        history = prices[pd.to_datetime(prices["trade_date"]) <= as_of]
        scored = score(latest_features(history))
        qualified = scored[scored["qualified"]].nlargest(top_n, "primary_score")
        future_date = dates[index + holding_sessions]
        for _, candidate in qualified.iterrows():
            symbol_prices = prices[
                (prices["symbol"] == candidate["symbol"]) & (pd.to_datetime(prices["trade_date"]) == future_date)
            ]
            if symbol_prices.empty:
                continue
            forward_close = float(pd.to_numeric(symbol_prices.iloc[-1]["close"], errors="coerce"))
            if forward_close > 0:
                rows.append(
                    {
                        "as_of_date": pd.Timestamp(as_of).date().isoformat(),
                        "symbol": candidate["symbol"],
                        "score": float(candidate["primary_score"]),
                        "horizon": candidate["primary_horizon"],
                        "forward_return_pct": round((forward_close / float(candidate["close"]) - 1) * 100, 4),
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"status": "INSUFFICIENT_HISTORY", "method": "screen_return_proxy", "observations": 0, "rows": []}
    return {
        "status": "COMPLETE",
        "method": "screen_return_proxy_not_execution_backtest",
        "holding_sessions": holding_sessions,
        "observations": len(frame),
        "samples": int(frame["as_of_date"].nunique()),
        "mean_forward_return_pct": round(float(frame["forward_return_pct"].mean()), 3),
        "median_forward_return_pct": round(float(frame["forward_return_pct"].median()), 3),
        "win_rate_pct": round(float((frame["forward_return_pct"] > 0).mean() * 100), 2),
        "rows": frame.to_dict(orient="records"),
    }
