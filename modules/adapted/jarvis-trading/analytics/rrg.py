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
Relative Rotation Graph (RRG) — institutional sector/stock rotation view.

For each symbol we compute, relative to a benchmark (NIFTY):
  RS-Ratio    : smoothed relative strength, normalized around 100
  RS-Momentum : rate-of-change of RS-Ratio, normalized around 100

Plotting RS-Ratio (x) vs RS-Momentum (y) places each symbol in a quadrant:
  Leading (≥100,≥100) · Weakening (≥100,<100) · Lagging (<100,<100) · Improving (<100,≥100)
Symbols rotate clockwise Improving→Leading→Weakening→Lagging. The "tail" shows the
recent trajectory. Built from the closes cache + a fetched NIFTY benchmark series.
"""

import numpy as np
from loguru import logger

BENCH = "^NSEI"


def _zscore_tail(series: np.ndarray, lookback: int = 60) -> np.ndarray:
    """Normalize a series to a 100-centered RRG scale using a rolling window."""
    out = np.full_like(series, 100.0, dtype=float)
    for i in range(len(series)):
        lo = max(0, i - lookback + 1)
        win = series[lo : i + 1]
        sd = win.std()
        out[i] = 100.0 + (series[i] - win.mean()) / sd if sd > 1e-9 else 100.0
    return out


def compute_rrg(symbols: list[str], tail: int = 8) -> dict:
    """RS-Ratio / RS-Momentum tails for symbols vs NIFTY (from the closes cache)."""
    from data.closes import read_closes
    from data.fetcher import fetch_symbol_history

    data = read_closes().get("data", {})
    # benchmark series (fetch once; not in the stock universe cache)
    try:
        bdf = fetch_symbol_history(BENCH, period="8mo", interval="1d")
        bench = bdf["close"].dropna().to_numpy(dtype=float)
    except Exception as exc:
        logger.warning("RRG benchmark fetch failed: {}", exc)
        return {"available": False, "note": "Benchmark (NIFTY) unavailable."}

    points = []
    for sym in symbols:
        closes = data.get(sym if sym.endswith(".NS") else f"{sym}.NS")
        if not closes or len(closes) < 80:
            continue
        s = np.asarray(closes, dtype=float)
        n = min(len(s), len(bench))
        rs = s[-n:] / bench[-n:]  # price relative
        rs_ratio = _zscore_tail(rs, 60)
        # momentum = normalized 10-day ROC of the RS-Ratio
        roc = np.zeros_like(rs_ratio)
        roc[10:] = rs_ratio[10:] - rs_ratio[:-10]
        rs_mom = _zscore_tail(roc, 60)
        t = min(tail, len(rs_ratio))
        xs = [round(float(v), 2) for v in rs_ratio[-t:]]
        ys = [round(float(v), 2) for v in rs_mom[-t:]]
        x, y = xs[-1], ys[-1]
        quad = (
            "Leading"
            if x >= 100 and y >= 100
            else "Weakening"
            if x >= 100 and y < 100
            else "Lagging"
            if x < 100 and y < 100
            else "Improving"
        )
        points.append(
            {
                "symbol": sym.replace(".NS", ""),
                "x": x,
                "y": y,
                "quadrant": quad,
                "tail": list(zip(xs, ys, strict=False)),
            }
        )

    points.sort(key=lambda p: (p["x"] - 100) ** 2 + (p["y"] - 100) ** 2, reverse=True)
    return {
        "available": bool(points),
        "count": len(points),
        "points": [{**p, "tail": [[a, b] for a, b in p["tail"]]} for p in points],
    }
