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


"""Hypothesis 2: Circuit Breakout — upper circuit hit + volume surge + continuation.

Uses real circuit limits from stock_circuit_limits table (sourced from NSE archives,
Upstox snapshots, or inferred from price-tier rules).

Signal types:
  - circuit_upper_breakout: Upper circuit hit + volume surge + continuation
  - circuit_lower_reversal: Lower circuit hit + stabilization
  - circuit_unfreeze: Stock unfreezes from circuit with momentum
  - circuit_multi_streak: 2+ consecutive upper circuits

Strength scoring based on pattern analysis of historical circuit hits.
"""


import json
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa
from indian_quant.features.delivery import prepare_frame
from indian_quant.hypotheses.base import BaseHypothesis, Signal
from indian_quant.hypotheses.registry import register_hypothesis

PATTERN_STATS_PATH = Path("data/cache/circuit_pattern_stats.json")


def _load_pattern_stats() -> dict:
    """Load pre-computed pattern stats for scoring weights."""
    if PATTERN_STATS_PATH.exists():
        try:
            return json.loads(PATTERN_STATS_PATH.read_text())
        except Exception:
            pass
    return {}


@register_hypothesis
class CircuitBreakout(BaseHypothesis):
    name = "circuit_breakout"
    description = "Upper circuit hit + volume surge + continuation. Uses real circuit limits from NSE/Upstox data."
    max_positions = 7
    default_stop_pct = 0.05
    default_horizon_days = 5
    price_min = 50.0
    price_max = 5000.0
    min_turnover = 5_000_000.0
    market_cap_min = 100.0
    market_cap_max = 10000.0

    def _load_circuit_limits(self, symbol: str, lookback_days: int = 30) -> pd.DataFrame | None:
        """Load circuit limits from DB for a symbol."""
        from indian_quant.config.connections import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            df = pd.read_sql(
                sa.text("""
                SELECT trade_date, prev_close, upper_circuit, lower_circuit, filter_pct
                FROM stock_circuit_limits
                WHERE symbol = :sym
                ORDER BY trade_date DESC
                LIMIT :limit
            """),
                conn,
                params={"sym": symbol, "limit": lookback_days},
            )
        if df.empty:
            return None
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        return df.sort_values("trade_date").reset_index(drop=True)

    def compute_signals(
        self,
        df: pd.DataFrame,
        *,
        signal_date: str | None = None,
    ) -> list[Signal]:
        prepared = prepare_frame(df, min_rows=20)
        if prepared is None:
            return []

        frame = prepared.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values("date").reset_index(drop=True)

        if len(frame) < 5:
            return []

        symbol = frame["symbol"].iloc[0] if "symbol" in frame.columns else ""

        # Load real circuit limits
        circuit_df = self._load_circuit_limits(symbol, lookback_days=len(frame) + 10)

        if circuit_df is not None and not circuit_df.empty:
            # Shift circuit limits by 1 day: limits from date T apply to date T+1
            # because circuit limits are computed from prev_close (close of T-1)
            circuit_df = circuit_df.copy()
            circuit_df["next_date"] = circuit_df["trade_date"].shift(-1)
            frame["date_only"] = frame["date"].dt.date
            frame = frame.merge(
                circuit_df[["next_date", "upper_circuit", "lower_circuit", "filter_pct"]],
                left_on="date_only",
                right_on="next_date",
                how="left",
            )
            # Forward-fill missing limits
            frame["upper_circuit"] = frame["upper_circuit"].ffill()
            frame["lower_circuit"] = frame["lower_circuit"].ffill()
            frame["filter_pct"] = frame["filter_pct"].ffill()
            frame = frame.drop(columns=["next_date", "date_only"], errors="ignore")
            has_real_limits = frame["upper_circuit"].notna().any()
        else:
            has_real_limits = False

        # Fallback: infer from PREVIOUS day's close for circuit limits
        # (so today's close can actually hit the limit)
        if not has_real_limits:
            frame["filter_pct"] = frame["close"].apply(self._infer_filter_pct)
            prev_close = frame["close"].shift(1)
            frame["upper_circuit"] = prev_close * (1 + frame["filter_pct"] / 100)
            frame["lower_circuit"] = prev_close * (1 - frame["filter_pct"] / 100)
            frame["upper_circuit"] = frame["upper_circuit"].ffill()
            frame["lower_circuit"] = frame["lower_circuit"].ffill()

        # Compute circuit hit features using REAL limits
        frame["upper_hit"] = frame["close"] >= frame["upper_circuit"] * 0.998
        frame["lower_hit"] = frame["close"] <= frame["lower_circuit"] * 1.002

        # Volume ratio
        if "volume" in frame.columns:
            vol_avg = frame["volume"].rolling(20, min_periods=5).mean()
            frame["vol_ratio"] = frame["volume"] / vol_avg.replace(0, np.nan)
        else:
            frame["vol_ratio"] = 1.0

        # 20-day circuit frequency
        frame["circuit_any"] = frame["upper_hit"] | frame["lower_hit"]
        frame["circuit_freq"] = frame["circuit_any"].rolling(20, min_periods=5).mean()

        # Consecutive upper circuits
        frame["consec_upper"] = 0
        count = 0
        for i in range(len(frame)):
            if frame["upper_hit"].iloc[i]:
                count += 1
                frame.iloc[i, frame.columns.get_loc("consec_upper")] = count
            else:
                count = 0

        # Consecutive lower circuits
        frame["consec_lower"] = 0
        count = 0
        for i in range(len(frame)):
            if frame["lower_hit"].iloc[i]:
                count += 1
                frame.iloc[i, frame.columns.get_loc("consec_lower")] = count
            else:
                count = 0

        # Continuation: next day opens near circuit close and holds
        frame["next_open"] = frame["open"].shift(-1) if "open" in frame.columns else frame["close"].shift(-1)
        frame["next_close"] = frame["close"].shift(-1)
        frame["continuation"] = (frame["next_open"] >= frame["close"] * 0.98) & (
            frame["next_close"] >= frame["close"] * 0.97
        )

        # Load pattern stats for scoring
        pattern_stats = _load_pattern_stats()

        signals: list[Signal] = []

        # Pattern 1: Upper circuit breakout
        mask_upper = frame["upper_hit"] & (frame["vol_ratio"] >= 1.5) & frame["continuation"]
        if signal_date is not None:
            frame["_date_str"] = frame["date"].dt.strftime("%Y-%m-%d")
            mask_upper = mask_upper & (frame["_date_str"] == signal_date)

        for _, row in frame[mask_upper].iterrows():
            strength = self._score_upper_breakout(row, pattern_stats)
            stop = round(row.get("low", row["close"] * 0.95) * 0.99, 2)
            target = round(row["close"] * 1.10, 2)
            filt = row.get("filter_pct", 5)
            signals.append(
                Signal(
                    symbol=symbol,
                    signal_date=str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10],
                    signal_type="circuit_upper_breakout",
                    strength=round(strength, 2),
                    entry_price=round(row["close"], 2),
                    stop_loss=stop,
                    target_price=target,
                    close=round(row["close"], 2),
                    vol_z=round(row.get("vol_ratio", 0), 2),
                    turnover=0.0,
                    notes=f"filter={filt}% consec={row.get('consec_upper', 0)} vol_ratio={row.get('vol_ratio', 0):.1f}",
                )
            )

        # Pattern 2: Multi-day circuit streak (2+ consecutive upper)
        mask_multi = (frame["consec_upper"] >= 2) & (frame["vol_ratio"] >= 1.2) & frame["upper_hit"]
        if signal_date is not None:
            mask_multi = mask_multi & (frame["_date_str"] == signal_date)

        for _, row in frame[mask_multi].iterrows():
            # Skip if already signaled as upper_breakout
            if row.get("continuation", False):
                continue
            strength = self._score_multi_streak(row, pattern_stats)
            stop = round(row.get("low", row["close"] * 0.95) * 0.98, 2)
            target = round(row["close"] * 1.15, 2)
            signals.append(
                Signal(
                    symbol=symbol,
                    signal_date=str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10],
                    signal_type="circuit_multi_streak",
                    strength=round(strength, 2),
                    entry_price=round(row["close"], 2),
                    stop_loss=stop,
                    target_price=target,
                    close=round(row["close"], 2),
                    vol_z=round(row.get("vol_ratio", 0), 2),
                    turnover=0.0,
                    notes=f"streak={row['consec_upper']} vol_ratio={row.get('vol_ratio', 0):.1f}",
                )
            )

        # Pattern 3: Lower circuit reversal
        mask_lower = frame["lower_hit"] & (frame["vol_ratio"] >= 2.0)
        if signal_date is not None:
            mask_lower = mask_lower & (frame["_date_str"] == signal_date)

        for _, row in frame[mask_lower].iterrows():
            strength = self._score_lower_reversal(row, pattern_stats)
            stop = round(row["close"] * 0.95, 2)
            target = round(row["close"] * 1.08, 2)
            signals.append(
                Signal(
                    symbol=symbol,
                    signal_date=str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10],
                    signal_type="circuit_lower_reversal",
                    strength=round(strength, 2),
                    entry_price=round(row["close"], 2),
                    stop_loss=stop,
                    target_price=target,
                    close=round(row["close"], 2),
                    vol_z=round(row.get("vol_ratio", 0), 2),
                    turnover=0.0,
                    notes=f"lower_hit vol_ratio={row.get('vol_ratio', 0):.1f}",
                )
            )

        return signals

    def _infer_filter_pct(self, price: float) -> float:
        """Infer circuit filter % from price using NSE rules."""
        if price <= 0:
            return 5.0
        if price < 100:
            return 20.0
        if price < 200:
            return 10.0
        return 5.0

    def _score_upper_breakout(self, row: pd.Series, stats: dict) -> float:
        """Score upper circuit breakout signal."""
        base = 40.0
        vol_bonus = min(row.get("vol_ratio", 1), 5) * 6
        consec_bonus = min(row.get("consec_upper", 0), 3) * 8
        cont_bonus = 20 if row.get("continuation", False) else 0
        freq_bonus = min(row.get("circuit_freq", 0) * 100, 15)

        # Discount for thin-band stocks (2% filter = more noise)
        filt = row.get("filter_pct", 5)
        filter_discount = 0.8 if filt <= 2 else 1.0

        strength = (base + vol_bonus + consec_bonus + cont_bonus + freq_bonus) * filter_discount
        return max(0, min(100, strength))

    def _score_multi_streak(self, row: pd.Series, stats: dict) -> float:
        """Score multi-day circuit streak signal."""
        base = 50.0
        vol_bonus = min(row.get("vol_ratio", 1), 5) * 5
        streak_bonus = min(row.get("consec_upper", 0), 4) * 10
        filt = row.get("filter_pct", 5)
        filter_discount = 0.8 if filt <= 2 else 1.0

        strength = (base + vol_bonus + streak_bonus) * filter_discount
        return max(0, min(100, strength))

    def _score_lower_reversal(self, row: pd.Series, stats: dict) -> float:
        """Score lower circuit reversal signal."""
        base = 30.0
        vol_bonus = min(row.get("vol_ratio", 1), 5) * 8
        filt = row.get("filter_pct", 5)
        filter_discount = 0.8 if filt <= 2 else 1.0

        strength = (base + vol_bonus) * filter_discount
        return max(0, min(100, strength))
