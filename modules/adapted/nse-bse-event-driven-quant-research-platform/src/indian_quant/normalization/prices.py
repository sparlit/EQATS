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


"""Normalization: raw records -> canonical contracts with clean semantics."""


from datetime import UTC, datetime, timedelta

import pandas as pd

from indian_quant.schemas import AdjustmentStatus, CorporateAction, MarketBar, Timeframe


def to_utc(ts: datetime) -> datetime:
    """Normalize any timestamp to timezone-aware UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def ist_session_close_utc(day: datetime) -> datetime:
    """NSE cash session close 15:30 IST expressed in UTC."""
    ist = day.astimezone(UTC) + timedelta(hours=5, minutes=30)
    close_ist = ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return (close_ist - timedelta(hours=5, minutes=30)).astimezone(UTC)


def deduplicate_bars(bars: list[MarketBar]) -> list[MarketBar]:
    seen: set[tuple[str, str, int]] = set()
    out: list[MarketBar] = []
    for bar in sorted(bars, key=lambda b: b.timestamp):
        key = (bar.instrument_id, bar.timeframe.value, int(bar.timestamp.timestamp()))
        if key not in seen:
            seen.add(key)
            out.append(bar)
    return out


def apply_corporate_action_adjustment(
    bars: list[MarketBar],
    actions: list[CorporateAction],
) -> list[MarketBar]:
    """Back-adjust prices for splits/bonuses using ex-dates.

    Bars strictly before an ex-date are scaled by the action's adjustment
    ratio. Dividends are recorded but not applied by default (total-return
    handling is a research-layer decision).
    """
    by_instrument: dict[str, list[CorporateAction]] = {}
    for action in actions:
        if action.action_type in ("SPLIT", "BONUS"):
            by_instrument.setdefault(action.instrument_id, []).append(action)

    adjusted: list[MarketBar] = []
    for bar in bars:
        factor = 1.0
        for action in by_instrument.get(bar.instrument_id, []):
            ex = action.ex_date or action.effective_date
            if ex is None:
                continue
            ex_dt = datetime(ex.year, ex.month, ex.day, tzinfo=UTC)
            if bar.timestamp < ex_dt:
                factor *= action.adjustment_ratio()
        if factor == 1.0:
            adjusted.append(bar)
            continue
        adjusted.append(
            MarketBar(
                instrument_id=bar.instrument_id,
                exchange=bar.exchange,
                timestamp=bar.timestamp,
                timeframe=bar.timeframe,
                open=round(bar.open * factor, 4),
                high=round(bar.high * factor, 4),
                low=round(bar.low * factor, 4),
                close=round(bar.close * factor, 4),
                volume=round(bar.volume / factor, 2) if factor else bar.volume,
                open_interest=bar.open_interest,
                source=bar.source,
                source_timestamp=bar.source_timestamp,
                ingestion_timestamp=bar.ingestion_timestamp,
                raw_hash=bar.raw_hash,
                adjustment_status=AdjustmentStatus.FULLY_ADJUSTED,
                quality_status=bar.quality_status,
            )
        )
    return adjusted


def resample_bars(df: pd.DataFrame, target: Timeframe) -> pd.DataFrame:
    """Resample a daily/minute OHLCV frame to a coarser canonical timeframe."""
    if "timestamp" not in df.columns:
        raise ValueError("frame must have a timestamp column")
    out = df.set_index("timestamp").sort_index()
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    resampled = out.resample(target.pandas_freq).agg(agg).dropna(subset=["close"])
    resampled["timeframe"] = target.value
    return resampled.reset_index()
