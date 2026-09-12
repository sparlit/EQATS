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


"""Volume and delivery participation metrics for NSE Scanner V2."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ParticipationResult:
    passed: bool
    score: float
    reasons: tuple[str, ...]
    metrics: dict[str, float]


def evaluate_participation(
    frame: pd.DataFrame,
    volume_window: int = 20,
    min_volume_multiple: float = 1.2,
    delivery_window: int = 20,
    min_delivery_multiple: float = 1.0,
) -> ParticipationResult:
    data = frame.sort_values("trade_date").copy()
    required = {"volume", "delivery_pct"}
    missing = required.difference(data.columns)
    if missing:
        return ParticipationResult(False, 0.0, (f"missing_columns:{','.join(sorted(missing))}",), {})
    if len(data) < max(volume_window, delivery_window) + 1:
        return ParticipationResult(False, 0.0, ("insufficient_history",), {})

    last = data.iloc[-1]
    avg_volume = data["volume"].shift(1).rolling(volume_window).mean().iloc[-1]
    avg_delivery = data["delivery_pct"].shift(1).rolling(delivery_window).mean().iloc[-1]

    volume_multiple = float(last["volume"] / avg_volume) if pd.notna(avg_volume) and avg_volume > 0 else 0.0
    delivery_multiple = (
        float(last["delivery_pct"] / avg_delivery)
        if pd.notna(avg_delivery) and avg_delivery > 0 and pd.notna(last["delivery_pct"])
        else 0.0
    )

    volume_ok = volume_multiple >= min_volume_multiple
    delivery_ok = delivery_multiple >= min_delivery_multiple
    score = min(60.0, 60.0 * volume_multiple / max(min_volume_multiple, 1e-9))
    score += min(40.0, 40.0 * delivery_multiple / max(min_delivery_multiple, 1e-9))

    reasons = (
        "volume_participation_confirmed" if volume_ok else "volume_participation_weak",
        "delivery_participation_confirmed" if delivery_ok else "delivery_participation_weak",
    )
    return ParticipationResult(
        passed=volume_ok and delivery_ok,
        score=float(min(100.0, score)),
        reasons=reasons,
        metrics={
            "volume_multiple": volume_multiple,
            "delivery_multiple": delivery_multiple,
            "average_volume": float(avg_volume) if pd.notna(avg_volume) else 0.0,
            "average_delivery_pct": float(avg_delivery) if pd.notna(avg_delivery) else 0.0,
        },
    )
