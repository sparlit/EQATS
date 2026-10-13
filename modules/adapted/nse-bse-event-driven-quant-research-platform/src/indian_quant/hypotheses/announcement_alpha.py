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


"""Hypothesis 4: Announcement Alpha — positive announcement + fundamentals.

Signal: Positive corporate announcement (results, board meeting, order, capex) + strong fundamentals
Strength: event_type_score * 25 + fundamental_score * 25 + price_reaction * 20 + volume * 15
Universe: NSE stocks with announcements in last 3 days
"""


import logging
from pathlib import Path

import numpy as np
import pandas as pd

from indian_quant.features.delivery import prepare_frame
from indian_quant.hypotheses.base import BaseHypothesis, Signal
from indian_quant.hypotheses.registry import register_hypothesis

log = logging.getLogger(__name__)

# Positive event types that should drive price (maps to NSE headline keywords)
POSITIVE_EVENTS = {
    "Financial Result Updates": 25,
    "Outcome of Board Meeting": 20,
    "Integrated Filing- Financial": 25,
    "Dividend": 15,
    "Buyback": 25,
    "Scheme of Arrangement": 20,
    "Credit Rating": 10,
    "Order": 20,
    "Investor Presentation": 15,
    "Press Release": 10,
    "Record Date": 5,
    "General Updates": 5,
}
# Fallback: scan headline text for these keywords
_KEYWORD_SCORES = {
    "result": 25,
    "dividend": 15,
    "buyback": 25,
    "order": 20,
    "capex": 20,
    "merger": 20,
    "acquisition": 20,
    "split": 15,
    "bonus": 15,
    "credit rating": 10,
}


@register_hypothesis
class AnnouncementAlpha(BaseHypothesis):
    name = "announcement_alpha"
    description = (
        "Buy on positive announcements (results, orders, capex) within seconds. Fundamental filter."
    )
    max_positions = 7
    default_stop_pct = 0.05
    default_horizon_days = 5
    price_min = 50.0
    price_max = 5000.0
    min_turnover = 10_000_000.0
    market_cap_min = 500.0
    market_cap_max = 50000.0

    def compute_signals(
        self,
        df: pd.DataFrame,
        *,
        signal_date: str | None = None,
        announcements: list[dict] | None = None,
    ) -> list[Signal]:
        """Compute announcement alpha signals.

        Args:
            df: Prepared frame with price data
            signal_date: Date to compute for
            announcements: List of recent announcements for this symbol
                e.g. [{"headline": "...", "category": "RESULTS", "published_at": "2026-09-04"}]
        """
        prepared = prepare_frame(df, min_rows=10)
        if prepared is None:
            return []

        frame = prepared.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values("date").reset_index(drop=True)

        if not announcements:
            return []

        # Filter to recent announcements (last 3 days)
        sig_dt = pd.Timestamp(signal_date) if signal_date else frame["date"].max()

        recent_anns = []
        for ann in announcements:
            try:
                ann_dt = pd.Timestamp(ann.get("published_at", ann.get("event_date", "")))
                if (sig_dt - ann_dt).days <= 3:
                    recent_anns.append(ann)
            except Exception:
                continue

        if not recent_anns:
            return []

        # Find price reaction days
        frame["ret_1d"] = frame["close"].pct_change()
        if "volume" in frame.columns:
            vol_avg = frame["volume"].rolling(20, min_periods=5).mean()
            frame["vol_ratio"] = frame["volume"] / vol_avg.replace(0, np.nan)
        else:
            frame["vol_ratio"] = 1.0

        # Positive price reaction + volume surge
        mask = (
            (frame["ret_1d"] > 0.01)  # 1%+ positive move
            & (frame["vol_ratio"] > 1.5)  # volume surge
        )

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
            # Best matching announcement
            scored = [(a, self._score_announcement(a.get("headline", ""))) for a in recent_anns]
            scored = [(a, s) for a, s in scored if s > 0]
            if not scored:
                continue
            best_ann, event_score = max(scored, key=lambda x: x[1])

            strength = (
                event_score
                + min(row.get("vol_ratio", 1), 3) * 15
                + min(row.get("ret_1d", 0) * 500, 20)
                + 15  # base for having announcement
            )
            strength = max(0, min(100, strength))

            stop = round(row["close"] * 0.95, 2)
            target = round(row["close"] * 1.10, 2)

            signals.append(
                Signal(
                    symbol=row.get("symbol", ""),
                    signal_date=str(row["date"].date())
                    if hasattr(row["date"], "date")
                    else str(row["date"])[:10],
                    signal_type="announcement_alpha",
                    strength=round(strength, 2),
                    entry_price=round(row["close"], 2),
                    stop_loss=stop,
                    target_price=target,
                    close=round(row["close"], 2),
                    vol_z=round(row.get("vol_ratio", 0), 2),
                    notes=f"event={best_ann.get('headline', '?')[:60]}",
                )
            )

        return signals

    def _load_announcements(self, symbol: str) -> list[dict]:
        """Load announcements from parquet files for a symbol."""
        ann_path = Path("data/normalized/announcements/NSE") / f"{symbol}.parquet"
        if not ann_path.exists():
            return []
        try:
            df = pd.read_parquet(ann_path)
            return df.to_dict("records")
        except Exception:
            return []

    def _score_announcement(self, headline: str) -> int:
        """Score an announcement headline against known positive events."""
        headline_lower = headline.lower()
        for keyword, score in _KEYWORD_SCORES.items():
            if keyword in headline_lower:
                return score
        return 0

    def compute_signals_batch(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        signal_date: str | None = None,
    ) -> list[Signal]:
        """Load announcements from parquet and compute signals."""
        all_signals: list[Signal] = []
        for symbol, df in frames.items():
            try:
                announcements = self._load_announcements(symbol)
                if not announcements:
                    continue
                sigs = self.compute_signals(
                    df, signal_date=signal_date, announcements=announcements
                )
                all_signals.extend(sigs)
            except Exception as e:
                log.warning(f"Signal computation failed for {symbol}: {e}")
        return all_signals
