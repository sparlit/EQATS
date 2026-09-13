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


"""Read-only shared-market adapter and Old NSE discovery ranking."""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DiscoveryResult:
    as_of_date: str
    eligible: int
    shortlist: pd.DataFrame
    rejected: dict[str, int]


def load_market_data(db_path: str | Path, as_of: str | None = None) -> pd.DataFrame:
    """Read common price snapshots only; do not import V2/V3 code or state."""
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table = "daily_prices_v2" if "daily_prices_v2" in tables else "daily_prices"
        date_col = "trade_date" if table == "daily_prices_v2" else "date"
        query = f"SELECT * FROM {table}" + (f" WHERE {date_col}<=?" if as_of else "")
        frame = pd.read_sql_query(query, conn, params=[as_of] if as_of else None)
    frame = frame.rename(columns={date_col: "trade_date"})
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.sort_values(["symbol", "trade_date"])


def discover(prices: pd.DataFrame, top_n: int = 25) -> DiscoveryResult:
    """Find momentum beginning through acceleration, structure and participation.

    Positive 1M/3M returns are deliberately not hard gates: a stock emerging
    from a sound base can surface before its backward-looking return is strong.
    """
    rows, rejected = [], {"insufficient_history": 0, "low_price": 0, "low_volume": 0}
    for symbol, frame in prices.groupby("symbol"):
        data = frame.sort_values("trade_date")
        if len(data) < 67:
            rejected["insufficient_history"] += 1
            continue
        close = pd.to_numeric(data["close"], errors="coerce")
        volume = pd.to_numeric(data["volume"], errors="coerce")
        if close.iloc[-1] < 50:
            rejected["low_price"] += 1
            continue
        if volume.tail(20).mean() < 50_000:
            rejected["low_volume"] += 1
            continue
        returns = [close.iloc[-1] / close.iloc[-1 - window] - 1 for window in (22, 44, 66)]
        ret5 = float(close.iloc[-1] / close.iloc[-6] - 1.0)
        prior5 = float(close.iloc[-6] / close.iloc[-11] - 1.0)
        ret10 = float(close.iloc[-1] / close.iloc[-11] - 1.0)
        prior10 = float(close.iloc[-11] / close.iloc[-21] - 1.0)
        ema20 = close.ewm(span=20, adjust=False).mean()
        prior_high = float(close.shift(1).tail(20).max())
        volume_base = float(volume.shift(1).tail(20).median())
        volume_ratio = float(volume.tail(5).mean() / volume_base) if volume_base > 0 else 0.0
        range20 = float((close.tail(20).max() - close.tail(20).min()) / max(close.tail(20).min(), 0.01))
        higher_low = bool(close.tail(10).min() >= close.iloc[-20:-10].min())
        near_breakout = bool(close.iloc[-1] >= prior_high * 0.97)
        ema_reclaim = bool(close.iloc[-1] >= ema20.iloc[-1] and ema20.iloc[-1] >= ema20.iloc[-4])
        hull_proxy_up = bool(close.rolling(10).mean().iloc[-1] >= close.rolling(10).mean().iloc[-3])
        high = pd.to_numeric(data.get("high", close), errors="coerce")
        low = pd.to_numeric(data.get("low", close), errors="coerce")
        prior_close = close.shift(1)
        true_range = pd.concat([high - low, (high - prior_close).abs(), (low - prior_close).abs()], axis=1).max(axis=1)
        atr14 = float(true_range.tail(14).mean()) if true_range.notna().any() else 0.0
        signals = {
            "price_accelerating": ret5 > prior5 or ret10 > prior10,
            "relative_strength_accelerating": ret5 > returns[0] * 5.0 / 22.0,
            "ema20_reclaimed": ema_reclaim,
            "trend_turning_up": hull_proxy_up,
            "participation_improving": volume_ratio >= 1.2,
            "higher_low_or_tight_base": higher_low or range20 <= 0.12,
            "near_breakout": near_breakout,
        }
        if sum(signals.values()) < 4:
            continue
        rows.append(
            {
                "symbol": str(symbol),
                "as_of_date": data["trade_date"].iloc[-1].date().isoformat(),
                "momentum_1m": returns[0],
                "momentum_2m": returns[1],
                "momentum_3m": returns[2],
                "return_5d": ret5,
                "prior_return_5d": prior5,
                "price_acceleration": ret5 - prior5,
                "rs_acceleration": ret5 - returns[0] * 5.0 / 22.0,
                "base_quality": float(higher_low) + float(range20 <= 0.12),
                "volume_ratio": volume_ratio,
                "trend_transition": float(ema_reclaim) + float(hull_proxy_up),
                "breakout_proximity": float(near_breakout),
                "close": float(close.iloc[-1]),
                "atr14": atr14,
                "early_signal_count": sum(signals.values()),
                "early_signals": tuple(name for name, passed in signals.items() if passed),
                "volume_20d": float(volume.tail(20).mean()),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return DiscoveryResult("", 0, result, rejected)
    result["discovery_score"] = (
        result["rs_acceleration"].rank(pct=True) * 25
        + result["price_acceleration"].rank(pct=True) * 20
        + result["base_quality"].clip(upper=2) / 2 * 15
        + (result["volume_ratio"].clip(upper=1.5) / 1.5) * 15
        + result["trend_transition"].clip(upper=2) / 2 * 15
        + result["breakout_proximity"] * 10
    ).round(2)
    result = result.sort_values(["discovery_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    result["discovery_rank"] = result.index + 1
    return DiscoveryResult(str(result["as_of_date"].iloc[0]), len(result), result.head(top_n), rejected)
