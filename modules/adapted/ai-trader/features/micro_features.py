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
Microstructure Features
───────────────────────
Computed from tick / second-level data for the Microstructure Model.

From the docs (Elaborated Challenges doc):
  - bid-ask spread
  - order book imbalance
  - trade size spikes
  - volume bursts
  - tick momentum (order flow = buy_volume - sell_volume)

These signals are most useful **just before breakouts** and predict
very short-term pressure (next 2 minutes).

Training data: 5 days of tick history (growing daily).
"""

import numpy as np
import pandas as pd
from utils.logger import get_logger

logger = get_logger("micro_features")


def compute_micro_features(
    tick_df: pd.DataFrame,
    window_seconds: int = 30,
) -> pd.DataFrame:
    """
    Compute microstructure features from a tick DataFrame.

    Input columns: timestamp, symbol, price, volume,
                   bid_price, ask_price, bid_qty, ask_qty

    Returns one row per second with aggregated micro features.
    """
    if tick_df.empty:
        logger.warning("Empty tick DataFrame; no micro features to compute.")
        return pd.DataFrame()

    df = tick_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    # ── Per-tick raw features ─────────────────────────────────────────────────

    # Bid-ask spread
    df["_spread"] = df["ask_price"] - df["bid_price"]
    df["_spread"] = df["_spread"].clip(lower=0)

    # Order imbalance: (bid_qty - ask_qty) / (bid_qty + ask_qty)
    total_qty = (df["bid_qty"] + df["ask_qty"]).replace(0, np.nan)
    df["_imbalance"] = (df["bid_qty"] - df["ask_qty"]) / total_qty

    # Classify trades as buy/sell using tick rule
    # price >= ask → buyer initiated, price <= bid → seller initiated
    df["_is_buy"] = (df["price"] >= df["ask_price"]).astype(int)
    df["_buy_vol"] = df["volume"] * df["_is_buy"]
    df["_sell_vol"] = df["volume"] * (1 - df["_is_buy"])

    # ── Resample to 1-second bars ─────────────────────────────────────────────

    df = df.set_index("timestamp")

    agg = (
        df.resample("1s")
        .agg(
            {
                "symbol": "first",
                "price": "last",
                "_spread": "mean",
                "_imbalance": "mean",
                "volume": "sum",
                "_buy_vol": "sum",
                "_sell_vol": "sum",
            }
        )
        .dropna(subset=["symbol"])
    )

    agg = agg.rename(
        columns={
            "_spread": "bid_ask_spread",
            "_imbalance": "order_imbalance",
            "volume": "total_volume",
        }
    )

    # ── Rolling window features ───────────────────────────────────────────────

    w = window_seconds

    # Trade size spike: current volume vs rolling mean
    vol_ma = agg["total_volume"].rolling(window=w, min_periods=1).mean()
    agg["trade_size_spike"] = agg["total_volume"] / vol_ma.replace(0, np.nan)

    # Volume burst: rolling sum vs longer-term rolling sum
    vol_short = agg["total_volume"].rolling(window=10, min_periods=1).sum()
    vol_long = agg["total_volume"].rolling(window=w, min_periods=1).sum()
    agg["volume_burst"] = vol_short / vol_long.replace(0, np.nan)

    # Tick momentum: cumulative order flow over window
    agg["_net_flow"] = agg["_buy_vol"] - agg["_sell_vol"]
    agg["tick_momentum"] = agg["_net_flow"].rolling(window=w, min_periods=1).sum()

    # Normalize tick momentum by total volume in window
    total_in_window = agg["total_volume"].rolling(window=w, min_periods=1).sum()
    agg["tick_momentum"] = agg["tick_momentum"] / total_in_window.replace(0, np.nan)

    # ── Clean up ──────────────────────────────────────────────────────────────

    result = agg[
        [
            "symbol",
            "price",
            "bid_ask_spread",
            "order_imbalance",
            "trade_size_spike",
            "volume_burst",
            "tick_momentum",
        ]
    ].copy()

    result = result.reset_index()
    result = result.rename(columns={"index": "timestamp"})

    logger.info(f"Computed micro features: {len(result)} second-level rows.")
    return result


def compute_micro_features_for_symbol(
    tick_df: pd.DataFrame,
    symbol: str,
    window_seconds: int = 30,
) -> pd.DataFrame:
    """Convenience: filter ticks by symbol then compute micro features."""
    filtered = tick_df[tick_df["symbol"] == symbol]
    return compute_micro_features(filtered, window_seconds)
