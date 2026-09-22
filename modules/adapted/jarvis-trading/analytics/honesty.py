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


"""
Signal Honesty — forward-test AXIOM's own screener picks.

For every historical pick (data/picks_history.json, appended daily by the
briefing workflow), measure the forward return 5/10/20 trading days after the
pick date using the OHLCV cache, and aggregate by grade. Answers: do A-grades
actually beat B/C — is the scorer worth trusting?
"""

import json
from pathlib import Path

import numpy as np
from loguru import logger

HISTORY = Path("data/picks_history.json")
HORIZONS = (5, 10, 20)


def signal_honesty() -> dict:
    from data.ohlcv_cache import get_cached_ohlcv

    try:
        hist = json.loads(HISTORY.read_text(encoding="utf-8")).get("history", {})
    except Exception as exc:
        logger.warning("picks history unavailable: {}", exc)
        return {"available": False, "note": "No picks history yet."}
    if not hist:
        return {"available": False, "note": "No picks history yet."}

    # closes per symbol, indexed by date string for O(1) date → position lookup
    frames: dict[str, tuple[list[str], np.ndarray]] = {}

    def closes_for(sym: str):
        if sym not in frames:
            df = get_cached_ohlcv(f"{sym}.NS")
            if df is None or df.empty:
                frames[sym] = ([], np.array([]))
            else:
                frames[sym] = ([d.strftime("%Y-%m-%d") for d in df.index], df["close"].to_numpy())
        return frames[sym]

    # grade -> horizon -> list of returns
    agg: dict[str, dict[int, list[float]]] = {}
    samples = 0
    for date, picks in hist.items():
        for p in picks:
            sym, grade = p.get("symbol"), (p.get("grade") or "?").upper()
            if not sym:
                continue
            dates, closes = closes_for(sym)
            if not dates:
                continue
            # entry = first trading day ON or AFTER the pick date
            i = np.searchsorted(np.array(dates), date)
            if i >= len(closes):
                continue
            entry = closes[i]
            if not entry:
                continue
            for h in HORIZONS:
                j = i + h
                if j >= len(closes):
                    continue
                ret = (closes[j] / entry - 1) * 100
                agg.setdefault(grade, {}).setdefault(h, []).append(float(ret))
                samples += 1

    grades = []
    for g in sorted(agg.keys()):
        row = {"grade": g}
        for h in HORIZONS:
            rets = agg[g].get(h, [])
            row[f"avg_{h}d"] = round(float(np.mean(rets)), 2) if rets else None
            row[f"win_{h}d"] = round(float(np.mean([r > 0 for r in rets]) * 100), 0) if rets else None
            row[f"n_{h}d"] = len(rets)
        grades.append(row)

    dates_sorted = sorted(hist.keys())
    return {
        "available": bool(grades),
        "grades": grades,
        "horizons": list(HORIZONS),
        "picks": sum(len(v) for v in hist.values()),
        "days": len(hist),
        "from": dates_sorted[0],
        "to": dates_sorted[-1],
        "samples": samples,
    }
