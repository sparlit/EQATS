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


"""Hypothesis 1: Delivery Momentum — delivery z-score spike + positive returns.

Signal: deliv_z >= 2 AND ret_1d >= 0.5%
Strength: weighted(deliv_z * 15, ret_1d * 1000, turnover_z * 10, conviction)
Universe: ₹100-500, NSE EQ, ₹1Cr+ turnover, cluster entries
"""


import numpy as np
import pandas as pd

from indian_quant.features.delivery import (
    add_features,
    cluster_entry_mask,
    prepare_frame,
    signal_mask,
)
from indian_quant.hypotheses.base import BaseHypothesis, Signal
from indian_quant.hypotheses.registry import register_hypothesis


@register_hypothesis
class DeliveryMomentum(BaseHypothesis):
    name = "delivery_momentum"
    description = (
        "Delivery z-score spike with positive returns — high-delivery days predict continuation"
    )
    max_positions = 7
    default_stop_pct = 0.07
    default_horizon_days = 10
    price_min = 100.0
    price_max = 500.0
    min_turnover = 10_000_000.0

    def compute_signals(
        self,
        df: pd.DataFrame,
        *,
        signal_date: str | None = None,
    ) -> list[Signal]:
        """Compute delivery momentum signals from a prepared frame.

        Expects df with columns: date, symbol, close, deliv_pct, volume,
        optionally rsi, macd, macd_signal, sma_20, atr_14.
        """
        prepared = prepare_frame(df, min_rows=40)
        if prepared is None:
            return []

        frame = add_features(prepared)

        # Basic signal mask (no tech filters — confirmed harmful in backtest)
        mask = signal_mask(frame, "dz_hi_up", z_min=2.0)

        # Filter to signal_date if specified
        if signal_date is not None:
            frame["_date_str"] = frame["date"].dt.strftime("%Y-%m-%d")
            mask = mask & (frame["_date_str"] == signal_date)
            if not mask.any():
                return []

        # Cluster: first day only (applied after date filter)
        mask = cluster_entry_mask(mask)

        if not mask.any():
            return []

        rows = frame[mask].copy()

        # Compute turnover and its z-score for strength
        if "volume" in rows.columns:
            rows["turnover_val"] = rows["close"] * rows["volume"]
            vol_mean = rows["turnover_val"].rolling(20, min_periods=5).mean()
            vol_std = rows["turnover_val"].rolling(20, min_periods=5).std().replace(0, np.nan)
            rows["turnover_z"] = ((rows["turnover_val"] - vol_mean) / vol_std).fillna(0)
        else:
            rows["turnover_val"] = 0.0
            rows["turnover_z"] = 0.0

        signals: list[Signal] = []
        for _, row in rows.iterrows():
            # Strength: weighted combination
            strength = (
                min(row.get("deliv_z", 0), 5) * 15
                + min(row.get("ret_1d", 0) * 1000, 10)
                + min(row.get("turnover_z", 0), 3) * 10
                + min(row.get("conviction_score", 0) if "conviction_score" in row.index else 0, 1)
                * 20
            )
            strength = max(0, min(100, strength))

            # ATR-based stop and target
            atr = row.get("atr_14", row["close"] * 0.03)
            stop = round(row["close"] - 2 * atr, 2)
            target = round(row["close"] + 3 * atr, 2)

            signals.append(
                Signal(
                    symbol=row.get("symbol", ""),
                    signal_date=str(row["date"].date())
                    if hasattr(row["date"], "date")
                    else str(row["date"])[:10],
                    signal_type="dz_hi_up",
                    strength=round(strength, 2),
                    entry_price=round(row["close"], 2),
                    stop_loss=stop,
                    target_price=target,
                    close=round(row["close"], 2),
                    deliv_z=round(row.get("deliv_z", 0), 2),
                    vol_z=round(row.get("vol_z", 0), 2),
                    rsi=round(row.get("rsi", 0), 2),
                    macd_hist=round(row.get("macd", 0) - row.get("macd_signal", 0), 4),
                    turnover=round(row.get("turnover_val", 0), 0),
                    market_cap_cr=round(row.get("market_cap_cr", 0), 0)
                    if "market_cap_cr" in row.index
                    else 0,
                )
            )

        return signals
