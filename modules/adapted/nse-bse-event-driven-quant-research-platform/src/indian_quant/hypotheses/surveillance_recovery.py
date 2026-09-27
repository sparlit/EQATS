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


"""Hypothesis 3: Surveillance Recovery — buy after ASM/GSM surveillance exit + price stabilization.

Signal: Stock was in ASM/GSM, now exited (status changed to EXITED), price stabilizing
Strength: surveillance_duration * 5 + days_since_exit * 3 + price_stability * 20
Universe: NSE stocks that were in ASM/GSM framework

Updated: Now queries surveillance_stocks/surveillance_history directly from PostgreSQL.
"""


import logging

import numpy as np
import pandas as pd
import sqlalchemy as sa

from indian_quant.features.delivery import prepare_frame
from indian_quant.hypotheses.base import BaseHypothesis, Signal
from indian_quant.hypotheses.registry import register_hypothesis

log = logging.getLogger(__name__)


@register_hypothesis
class SurveillanceRecovery(BaseHypothesis):
    name = "surveillance_recovery"
    description = "Buy after ASM/GSM surveillance exit + price stabilization. Stocks de-escalate and recover."
    max_positions = 7
    default_stop_pct = 0.07
    default_horizon_days = 10
    price_min = 10.0
    price_max = 5000.0
    min_turnover = 5_000_000.0
    market_cap_min = 100.0
    market_cap_max = 50000.0

    def _get_surveillance_stocks(self) -> dict[str, dict]:
        """Query current surveillance stocks from PostgreSQL."""
        try:
            from indian_quant.config.connections import get_engine

            engine = get_engine()
            with engine.connect() as conn:
                rows = conn.execute(
                    sa.text("""
                    SELECT symbol, framework, stage, stage_raw, first_seen_date, last_seen_date
                    FROM surveillance_stocks
                    WHERE status = 'ACTIVE'
                """)
                ).fetchall()
                result = {}
                for r in rows:
                    sym = r[0]
                    if sym not in result:
                        result[sym] = {
                            "frameworks": [],
                            "stages": {},
                            "first_seen": str(r[4]) if r[4] else None,
                            "last_seen": str(r[5]) if r[5] else None,
                        }
                    result[sym]["frameworks"].append(r[1])
                    result[sym]["stages"][r[1]] = r[2]
                return result
        except Exception:
            return {}

    def _get_exited_stocks(self, lookback_days: int = 30) -> list[str]:
        """Find stocks that exited surveillance in the last N days."""
        try:
            from indian_quant.config.connections import get_engine

            engine = get_engine()
            with engine.connect() as conn:
                rows = conn.execute(
                    sa.text("""
                    SELECT DISTINCT symbol
                    FROM surveillance_history
                    WHERE snapshot_date >= CURRENT_DATE - :lookback
                      AND symbol NOT IN (
                          SELECT symbol FROM surveillance_stocks WHERE status = 'ACTIVE'
                      )
                """),
                    {"lookback": lookback_days},
                ).fetchall()
                return [r[0] for r in rows]
        except Exception:
            return []

    def compute_signals(
        self,
        df: pd.DataFrame,
        *,
        signal_date: str | None = None,
        surveillance_data: dict | None = None,
    ) -> list[Signal]:
        """Compute surveillance recovery signals.

        Strategy:
        1. Stocks that recently EXITED surveillance → recovery plays
        2. Stocks in surveillance with improving fundamentals → value plays
        3. Higher stage = more liquidation pressure = bigger recovery potential
        """
        prepared = prepare_frame(df, min_rows=20)
        if prepared is None:
            return []

        frame = prepared.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values("date").reset_index(drop=True)

        if len(frame) < 10:
            return []

        # Price stabilization: low volatility, holding above recent low
        frame["ret_1d"] = frame["close"].pct_change()
        frame["volatility_10d"] = frame["ret_1d"].rolling(10, min_periods=5).std()
        frame["price_range_10d"] = (frame["close"].rolling(10).max() - frame["close"].rolling(10).min()) / frame[
            "close"
        ].rolling(10).mean()
        frame["price_above_low"] = frame["close"] > frame["close"].rolling(10).min() * 1.05

        # Stabilization: low volatility + price above recent low
        frame["stabilized"] = (frame["volatility_10d"] < 0.03) & frame["price_above_low"]

        # Signal requires stabilization + positive momentum
        mask = frame["stabilized"] & (frame["ret_1d"] > 0) & (frame["close"] > frame["close"].shift(5))

        # If we have surveillance data, use it to filter
        if surveillance_data:
            if not surveillance_data.get("exited", False):
                return []  # Only signal for stocks that exited surveillance

        if signal_date is not None:
            frame["_date_str"] = frame["date"].dt.strftime("%Y-%m-%d")
            mask = mask & (frame["_date_str"] == signal_date)
            if not mask.any():
                return []

        rows = frame[mask].copy()
        if rows.empty:
            return []

        signals: list[Signal] = []
        for _, row in rows.iterrows():
            strength = (
                min(row.get("volatility_10d", 0.05) * -500, 20)  # lower vol = higher strength
                + min(row.get("price_range_10d", 0.1) * -100, 15)  # tighter range = better
                + (20 if row.get("stabilized", False) else 0)
                + min(row.get("ret_1d", 0) * 500, 10)
            )
            strength = max(0, min(100, strength))

            stop = round(row["close"] * 0.93, 2)
            target = round(row["close"] * 1.15, 2)

            signals.append(
                Signal(
                    symbol=row.get("symbol", ""),
                    signal_date=str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10],
                    signal_type="surveillance_recovery",
                    strength=round(strength, 2),
                    entry_price=round(row["close"], 2),
                    stop_loss=stop,
                    target_price=target,
                    close=round(row["close"], 2),
                    vol_z=round(row.get("volatility_10d", 0) * 100, 2),
                    notes=f"vol={row.get('volatility_10d', 0):.4f}",
                )
            )

        return signals

    def compute_signals_batch(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        signal_date: str | None = None,
    ) -> list[Signal]:
        """Override to add surveillance-aware logic."""
        # Get surveillance data
        surv_stocks = self._get_surveillance_stocks()
        exited_stocks = self._get_exited_stocks(lookback_days=30)

        # Filter frames to only surveillance-relevant stocks
        relevant_frames = {}
        for sym, df in frames.items():
            if sym in surv_stocks or sym in exited_stocks:
                relevant_frames[sym] = df

        if not relevant_frames:
            return []

        # Compute signals with surveillance context
        all_signals: list[Signal] = []
        for symbol, df in relevant_frames.items():
            try:
                surv_data = None
                if symbol in exited_stocks:
                    surv_data = {"exited": True}
                elif symbol in surv_stocks:
                    surv_data = {
                        "exited": False,
                        "frameworks": surv_stocks[symbol]["frameworks"],
                        "stages": surv_stocks[symbol]["stages"],
                    }

                sigs = self.compute_signals(df, signal_date=signal_date, surveillance_data=surv_data)
                # Enrich notes with surveillance info
                for sig in sigs:
                    if symbol in surv_stocks:
                        fw = surv_stocks[symbol]["frameworks"]
                        stages = surv_stocks[symbol]["stages"]
                        sig.notes += f" | in_surveillance: {fw} {stages}"
                    elif symbol in exited_stocks:
                        sig.notes += " | recently_exited_surveillance"
                all_signals.extend(sigs)
            except Exception as e:
                log.warning(f"Signal computation failed for {symbol}: {e}")

        return all_signals
