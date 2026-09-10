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


"""Strict, auditable NSE-universe eligibility for the progressive scanner."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

from .corporate_data import market_cap_max_age_days

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class EligibilityResult:
    symbol: str
    eligible: bool
    reason_code: str
    stage: str
    actual_value: float | str | None = None
    required_value: float | str | None = None
    metrics: dict[str, float | str | bool] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_eligibility(
    symbol: str,
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, object] | None = None,
    restricted_reason: str | None = None,
    min_sessions: int = 260,
    min_price: float = 50.0,
    min_median_volume_20: float = 100_000.0,
    min_median_turnover_cr_20: float = 5.0,
    min_delivery_5: float = 35.0,
    min_delivery_20: float = 30.0,
    min_market_cap_cr: float = 1_000.0,
    require_market_cap: bool = True,
    min_promoter_holding_pct: float = 30.0,
    require_promoter_holding: bool = False,
    require_corporate_action_safety: bool = False,
    as_of_date: str | None = None,
    max_market_cap_age_days: int | None = None,
    max_promoter_holding_age_days: int = 120,
) -> EligibilityResult:
    ordered = frame.sort_values("trade_date").copy()
    metadata = metadata or {}

    def reject(stage: str, code: str, actual: object = None, required: object = None) -> EligibilityResult:
        return EligibilityResult(symbol, False, code, stage, actual, required)

    if ordered["trade_date"].duplicated().any():
        return reject("DATA_QUALITY", "DUPLICATE_DATES")
    data = ordered
    if len(data) < min_sessions:
        return reject("DATA_QUALITY", "INSUFFICIENT_HISTORY", len(data), min_sessions)
    prices = data[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if prices.isna().any().any() or (prices <= 0).any().any():
        return reject("DATA_QUALITY", "INVALID_PRICE")
    if (prices["high"] < prices[["open", "low", "close"]].max(axis=1)).any() or (
        prices["low"] > prices[["open", "high", "close"]].min(axis=1)
    ).any():
        return reject("DATA_QUALITY", "INVALID_OHLC")
    if "quality_status" in data and data["quality_status"].iloc[-1] not in {"VALID", "VALIDATED", "OK"}:
        return reject("DATA_QUALITY", "UNVALIDATED_LATEST_ROW", data["quality_status"].iloc[-1], "VALIDATED")

    series = str(metadata.get("series", "EQ") or "EQ").upper()
    if series != "EQ":
        return reject("TRADEABILITY", "NON_EQ_SERIES", series, "EQ")
    if metadata.get("active") is not None and not bool(metadata.get("active")):
        return reject("TRADEABILITY", "INACTIVE_SECURITY")
    if restricted_reason:
        return reject("REGULATORY", "RESTRICTED_SECURITY", restricted_reason, "NOT_RESTRICTED")

    close = float(prices["close"].iloc[-1])
    if close < min_price:
        return reject("LIQUIDITY", "LOW_PRICE", close, min_price)
    volume = pd.to_numeric(data["volume"], errors="coerce")
    median_volume = float(volume.tail(20).median())
    if pd.isna(median_volume) or median_volume < min_median_volume_20:
        return reject("LIQUIDITY", "LOW_MEDIAN_VOLUME", median_volume, min_median_volume_20)

    if "turnover_lacs" not in data:
        return reject("LIQUIDITY", "TURNOVER_DATA_MISSING", None, min_median_turnover_cr_20)
    turnover_cr = pd.to_numeric(data["turnover_lacs"], errors="coerce") / 100.0
    median_turnover = float(turnover_cr.tail(20).median())
    if pd.isna(median_turnover) or median_turnover < min_median_turnover_cr_20:
        return reject("LIQUIDITY", "LOW_MEDIAN_TURNOVER", median_turnover, min_median_turnover_cr_20)

    if "delivery_pct" not in data:
        return reject("PARTICIPATION", "DELIVERY_DATA_MISSING", None, min_delivery_20)
    delivery = pd.to_numeric(data["delivery_pct"], errors="coerce")
    delivery_5, delivery_20 = float(delivery.tail(5).mean()), float(delivery.tail(20).mean())
    if pd.isna(delivery_5) or delivery_5 < min_delivery_5:
        return reject("PARTICIPATION", "LOW_DELIVERY_5D", delivery_5, min_delivery_5)
    if pd.isna(delivery_20) or delivery_20 < min_delivery_20:
        return reject("PARTICIPATION", "LOW_DELIVERY_20D", delivery_20, min_delivery_20)

    market_cap = metadata.get("market_cap_cr")
    if require_market_cap and (market_cap is None or pd.isna(market_cap)):
        return reject("SIZE", "MARKET_CAP_DATA_MISSING", None, min_market_cap_cr)
    if market_cap is not None and pd.notna(market_cap) and float(market_cap) < min_market_cap_cr:
        return reject("SIZE", "LOW_MARKET_CAP", float(market_cap), min_market_cap_cr)
    cap_date = metadata.get("market_cap_as_of")
    cap_source = str(metadata.get("market_cap_source", "DIRECT_SNAPSHOT") or "DIRECT_SNAPSHOT")
    if require_market_cap and (cap_date is None or pd.isna(cap_date)):
        return reject("SIZE", "MARKET_CAP_DATE_MISSING", None, max_market_cap_age_days)
    if require_market_cap and as_of_date:
        age = (pd.Timestamp(as_of_date).normalize() - pd.Timestamp(cap_date).normalize()).days
        allowed_age = max_market_cap_age_days or market_cap_max_age_days(cap_source)
        if age < 0 or age > allowed_age:
            return reject("SIZE", "STALE_MARKET_CAP", age, allowed_age)

    promoter_holding = metadata.get("promoter_holding_pct")
    promoter_available_date = metadata.get("promoter_holding_available_date")
    if require_promoter_holding:
        if promoter_holding is None or pd.isna(promoter_holding):
            return reject("OWNERSHIP", "PROMOTER_HOLDING_DATA_MISSING", None, min_promoter_holding_pct)
        if promoter_available_date is None or pd.isna(promoter_available_date):
            return reject("OWNERSHIP", "PROMOTER_HOLDING_DATE_MISSING", None, max_promoter_holding_age_days)
        if as_of_date:
            promoter_age = (
                pd.Timestamp(as_of_date).normalize() - pd.Timestamp(promoter_available_date).normalize()
            ).days
            if promoter_age < 0 or promoter_age > max_promoter_holding_age_days:
                return reject("OWNERSHIP", "STALE_PROMOTER_HOLDING", promoter_age, max_promoter_holding_age_days)
        if float(promoter_holding) < min_promoter_holding_pct:
            return reject("OWNERSHIP", "LOW_PROMOTER_HOLDING", float(promoter_holding), min_promoter_holding_pct)

    pending_action = metadata.get("corporate_action_type")
    if require_corporate_action_safety and pending_action:
        return reject(
            "CORPORATE_ACTION",
            "MATERIAL_CORPORATE_ACTION_REVIEW",
            str(pending_action),
            "NO_MATERIAL_ACTION_IN_SAFETY_WINDOW",
        )

    return EligibilityResult(
        symbol,
        True,
        "ELIGIBLE",
        "COMPLETE",
        metrics={
            "close": close,
            "median_volume_20": median_volume,
            "median_turnover_cr_20": median_turnover,
            "delivery_5": delivery_5,
            "delivery_20": delivery_20,
            "market_cap_verified": market_cap is not None and pd.notna(market_cap),
            "market_cap_as_of": str(cap_date) if cap_date is not None else "",
            "market_cap_source": cap_source,
            "promoter_holding_pct": float(promoter_holding)
            if promoter_holding is not None and pd.notna(promoter_holding)
            else "",
            "promoter_holding_as_of": str(metadata.get("promoter_holding_as_of") or ""),
            "promoter_holding_available_date": str(promoter_available_date or ""),
            "promoter_holding_filing_id": str(metadata.get("promoter_holding_filing_id") or ""),
            "corporate_action_type": str(pending_action or ""),
            "corporate_action_ex_date": str(metadata.get("corporate_action_ex_date") or ""),
        },
    )
