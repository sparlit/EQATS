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


"""Causal daily features and progressive setup classification.

This is a new research specification, not a port of a TradingView script.
All rolling levels exclude the current candle; pivots appear on confirmation.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from v2.indicators import atr, wma


@dataclass(frozen=True)
class ResearchConfig:
    turnover_cr: float = 1.0
    max_extension_atr: float = 1.25
    entry_area_atr: float = 0.5
    minimum_rr: float = 1.5
    max_stop_pct: float = 8.0
    breakout_volume: float = 1.2
    pivot_strength: int = 5
    stop_buffer_atr: float = 0.2


def confirmed_pivot(values: pd.Series, strength: int, *, low: bool) -> pd.Series:
    """The pivot at t-strength becomes known at t, never at its plotted date."""
    window = values.rolling(2 * strength + 1, min_periods=2 * strength + 1)
    extremum = window.min() if low else window.max()
    candidate = values.shift(strength)
    return candidate.where(candidate.eq(extremum)).ffill()


def features(
    frame: pd.DataFrame, config: ResearchConfig = ResearchConfig(), benchmark: pd.Series | None = None
) -> pd.DataFrame:
    d = frame.rename(columns={"date": "trade_date"}).copy()
    required = {"trade_date", "open", "high", "low", "close", "volume"}
    if required.difference(d):
        msg = f"Missing daily columns: {sorted(required.difference(d))}"
        raise ValueError(msg)
    d["trade_date"] = pd.to_datetime(d["trade_date"]).dt.normalize()
    d = d.sort_values("trade_date").reset_index(drop=True)
    if d.trade_date.duplicated().any():
        msg = "Duplicate symbol sessions"
        raise ValueError(msg)
    for col in required - {"trade_date"}:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    valid = (
        d[["open", "high", "low", "close", "volume"]].notna().all(axis=1)
        & d.low.gt(0)
        & d.volume.gt(0)
        & d.low.le(d[["open", "close"]].min(axis=1))
        & d.high.ge(d[["open", "close"]].max(axis=1))
    )
    # Invalid rows must not propagate into an apparently valid later setup.
    d["valid"] = valid
    d["history_ok"] = valid.rolling(112, min_periods=112).sum().eq(112)
    c = d.close
    for length in (9, 14, 21, 50, 200):
        d[f"ema{length}"] = c.ewm(span=length, adjust=False, min_periods=length).mean()
    base = wma(c, 55)
    d["hull"] = 2 * wma(base, 27) - wma(base, 55)
    d["atr"] = atr(d)
    d["ema_slope"] = (d.ema21 - d.ema21.shift(3)) / d.atr
    d["hull_slope"] = (d.hull - d.hull.shift(3)) / d.atr
    for length in (5, 10, 22, 44, 66):
        d[f"return{length}"] = c.pct_change(length, fill_method=None) * 100
    # Equal-length, non-overlapping momentum segments.
    d["acceleration5"] = d.return5 - (c.shift(5) / c.shift(10) - 1) * 100
    d["relative_strength22"] = np.nan
    if benchmark is not None:
        b = benchmark.copy()
        b.index = pd.to_datetime(b.index)
        aligned = d.trade_date.map(b)
        d["relative_strength22"] = d.return22 - aligned.pct_change(22, fill_method=None) * 100
    turnover = pd.to_numeric(d.get("turnover_lacs", pd.Series(np.nan, index=d.index)), errors="coerce") / 100
    d["turnover20_cr"] = turnover.rolling(20, min_periods=20).median()
    d["turnover5_cr"] = turnover.rolling(5, min_periods=5).median()
    d["turnover_warning"] = d.turnover5_cr.lt(d.turnover20_cr * 0.5)
    vol_base = d.volume.shift(1).rolling(20, min_periods=20).mean()
    d["relative_volume"] = d.volume / vol_base
    d["pullback_volume"] = d.volume.rolling(3).mean() / vol_base
    delivery = pd.to_numeric(d.get("delivery_pct", pd.Series(np.nan, index=d.index)), errors="coerce")
    delivery = delivery.where(delivery.between(0, 100))
    d["delivery5"] = delivery.rolling(5, min_periods=5).mean()
    d["delivery20"] = delivery.rolling(20, min_periods=20).mean()
    d["delivery_percentile60"] = delivery.rolling(60, min_periods=60).rank(pct=True)
    d["delivery_improving"] = d.delivery5.gt(d.delivery20)
    d["support"] = confirmed_pivot(d.low, config.pivot_strength, low=True)
    d["resistance"] = confirmed_pivot(d.high, config.pivot_strength, low=False)
    d["prior_high20"] = d.high.shift(1).rolling(20).max()
    d["prior_low20"] = d.low.shift(1).rolling(20).min()
    d["breakout"] = c.gt(d.prior_high20) & c.shift(1).le(d.prior_high20.shift(1))
    # A prior breakout's level persists for at most ten subsequent sessions.
    d["retest_level"] = d.prior_high20.where(d.breakout).shift(1).ffill(limit=9)
    d["close_location"] = (c - d.low) / (d.high - d.low).replace(0, np.nan)
    d["retest"] = (
        d.low.le(d.retest_level + 0.2 * d.atr)
        & d.low.ge(d.retest_level - 0.5 * d.atr)
        & c.gt(d.retest_level)
        & d.close_location.ge(0.65)
    )
    d["recovery"] = c.gt(d.ema21) & c.shift(1).le(d.ema21.shift(1)) & d.ema_slope.gt(d.ema_slope.shift(1))
    d["pullback"] = (
        d.ema21.gt(d.ema50)
        & d.ema_slope.gt(0)
        & d.low.le(d.ema21 + 0.5 * d.atr)
        & c.gt(d.support)
        & d.close_location.ge(0.6)
    )
    d["range_blocked"] = (
        (d.ema9 - d.ema50).abs().div(d.atr).lt(0.6) & d.ema_slope.abs().lt(0.15) & d.hull_slope.abs().lt(0.15)
    )
    d["deteriorating"] = c.lt(d.support) | (c.lt(d.hull) & d.hull_slope.lt(0) & d.ema_slope.lt(0))
    d["distance_ema_atr"] = (c - d.ema21) / d.atr
    d["distance_hull_atr"] = (c - d.hull) / d.atr
    d["setup"] = np.select(
        [
            d.deteriorating,
            d.range_blocked,
            d.retest,
            d.pullback,
            d.breakout,
            d.recovery,
            c.gt(d.ema21) & d.ema21.gt(d.ema50) & d.hull_slope.gt(0),
            c.gt(d.ema21) & d.ema_slope.gt(0),
        ],
        [
            "DETERIORATING",
            "RANGE BLOCKED",
            "RETEST",
            "HEALTHY PULLBACK",
            "BREAKOUT WATCH",
            "EARLY RECOVERY",
            "CONFIRMED TREND",
            "DEVELOPING",
        ],
        default="BASE FORMING",
    )
    zone = pd.concat(
        [d.support.where(d.support.lt(c)), d.ema21.where(d.ema21.lt(c)), d.hull.where(d.hull.lt(c))], axis=1
    ).max(axis=1)
    d["zone"] = zone.where(~d.retest, d.retest_level)
    d["zone_distance_atr"] = (c - d.zone) / d.atr
    d["extended"] = d.zone_distance_atr.gt(config.max_extension_atr) | ((c - d.open) / d.atr).gt(2)
    d["entry_location"] = np.select(
        [c.lt(d.support), d.extended, d.zone_distance_atr.le(config.entry_area_atr)],
        ["REJECT", "EXTENDED", "ENTRY AREA"],
        default="WAIT FOR RETEST",
    )
    # Stop anchor is confirmed structure or a proven retest, not an MA alone.
    d["stop"] = d.support.where(~d.retest, d.retest_level) - config.stop_buffer_atr * d.atr
    d["trigger"] = d.high + 0.05 * d.atr
    risk = d.trigger - d.stop
    d["stop_pct"] = risk / d.trigger * 100
    overhead = pd.concat(
        [d.resistance.where(d.resistance.gt(d.trigger)), d.prior_high20.where(d.prior_high20.gt(d.trigger))], axis=1
    ).min(axis=1)
    d["room_r"] = (overhead - d.trigger) / risk
    # Unknown resistance is explicitly unknown, not infinity or an automatic pass.
    d["room_known"] = overhead.notna()
    d["risk_ok"] = risk.gt(0.5 * d.atr) & risk.le(2.5 * d.atr) & d.stop_pct.le(config.max_stop_pct) & d.stop.gt(0)
    d["volume_ok"] = np.where(
        d.breakout,
        d.relative_volume.ge(config.breakout_volume),
        np.where(d.retest | d.pullback, d.pullback_volume.le(1.2), d.relative_volume.ge(0.7)),
    )
    d["maturity_bonus"] = d.ema50.gt(d.ema200).astype(int) * 5
    d["score"] = (
        d.ema_slope.gt(0).astype(int) * 15
        + d.hull_slope.gt(0).astype(int) * 15
        + d.ema21.gt(d.ema50).astype(int) * 10
        + d.acceleration5.gt(0).astype(int) * 10
        + d.relative_strength22.gt(0).astype(int) * 10
        + d.volume_ok.astype(int) * 10
        + d.delivery_improving.astype(int) * 5
        + d.maturity_bonus
        + d.retest.astype(int) * 10
        + d.pullback.astype(int) * 10
    )
    # Friday-labelled bars cannot be used Monday-Thursday. Holiday Fridays become
    # available the following session: conservative without an exchange calendar.
    weekly = d.set_index("trade_date").resample("W-FRI").agg({"close": "last", "high": "max", "low": "min"}).dropna()
    wc = weekly.close
    we21 = wc.ewm(span=21, adjust=False, min_periods=21).mean()
    we50 = wc.ewm(span=50, adjust=False, min_periods=50).mean()
    wb = wma(wc, 55)
    wh = 2 * wma(wb, 27) - wma(wb, 55)
    weekly["weekly_hull_available"] = wh.notna() & wh.shift(1).notna()
    weekly["weekly_permission"] = np.select(
        [
            we50.isna(),
            (wc.lt(we21) & we21.lt(we21.shift(1)) & wc.lt(weekly.low.shift(1).rolling(5).min())),
            wc.gt(we21) & we21.gt(we50),
            we21.gt(we21.shift(1)),
        ],
        ["DATA UNAVAILABLE", "HTF BLOCKED", "HTF STRONG", "HTF DEVELOPING"],
        default="HTF NEUTRAL",
    )
    weekly = weekly[["weekly_permission", "weekly_hull_available"]].reset_index()
    d = pd.merge_asof(d, weekly, on="trade_date", direction="backward")
    d["weekly_permission"] = d.weekly_permission.fillna("DATA UNAVAILABLE")
    d["weekly_hull_available"] = d.weekly_hull_available.fillna(False).astype(bool)
    return d


def candidate_mask(
    d: pd.DataFrame, scanner: str, variant: str = "daily_location", config: ResearchConfig = ResearchConfig()
) -> pd.Series:
    """Technical research cohorts, never equivalent to native scanner eligibility."""
    if scanner not in {"Hull", "V3", "Momentum Ladder", "Penny"}:
        msg = "Unknown scanner"
        raise ValueError(msg)
    if variant not in {"mature_control", "progressive", "with_weekly", "daily_location"}:
        msg = "Unknown research variant"
        raise ValueError(msg)
    eligible = d.history_ok & d.turnover20_cr.ge(config.turnover_cr)
    if scanner == "Penny":
        # Preserve the deployed Penny ready-tier data thresholds in this overlay.
        eligible &= (
            d.close.between(1, 49.99)
            & d.delivery5.ge(30)
            & d.delivery20.ge(25)
            & d.turnover5_cr.ge(1)
            & pd.Series(np.arange(len(d)) >= 259, index=d.index)
        )
    else:
        eligible &= d.close.ge(50)
    if variant == "mature_control":
        return (
            eligible
            & d.close.gt(d.ema50)
            & d.ema50.gt(d.ema200)
            & d.return22.gt(0)
            & d.return44.gt(0)
            & d.return66.gt(0)
            & d.relative_volume.ge(1.5)
            & d.hull_slope.gt(0)
            & d.risk_ok
        )
    setup = d.setup.isin(["RETEST", "HEALTHY PULLBACK", "BREAKOUT WATCH", "EARLY RECOVERY", "CONFIRMED TREND"])
    if scanner == "Momentum Ladder":
        setup |= d.setup.eq("DEVELOPING") & d.acceleration5.gt(0) & d.ema9.gt(d.ema14)
    mask = eligible & setup & ~d.deteriorating & ~d.range_blocked & d.volume_ok & d.risk_ok
    if variant in {"with_weekly", "daily_location"}:
        mask &= d.weekly_permission.isin(["HTF STRONG", "HTF DEVELOPING", "HTF NEUTRAL"])
    if variant == "daily_location":
        mask &= ~d.extended & d.room_known & d.room_r.ge(config.minimum_rr)
    return mask.fillna(False)
