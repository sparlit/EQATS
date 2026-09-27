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


"""Fast data loader with Redis hot cache + PostgreSQL fallback.

Architecture:
    Request → Redis (sub-ms) → PostgreSQL (5ms) → parquet (slow, last resort)

Redis keys:
    signals:all      - all signals JSON (TTL=1h)
    signals:buys     - dz_hi_up signals JSON
    signals:avoids   - dz_hi_dn signals JSON
    signals:by_symbol - hash map: symbol → signal JSON
    signals:date     - latest signal date
    signals:count    - total signal count
"""


import json
from typing import Any

import pandas as pd
from indian_quant.web.prod_config import (
    ensure_schema,
    get_pg_engine,
    get_redis_client,
)


def _redis_get(key: str) -> str | None:
    try:
        r = get_redis_client()
        return r.get(key)
    except Exception:
        return None


def _redis_set(key: str, value: str, ttl: int = 3600) -> None:
    try:
        r = get_redis_client()
        r.set(key, value, ex=ttl)
    except Exception:
        pass


def _sanitize_nan(obj):
    """Recursively replace NaN/Inf floats with None for JSON safety."""
    import math

    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def get_latest_signals_cached() -> dict[str, Any]:
    """Fast: Redis → PostgreSQL → empty."""
    # 1) Try Redis
    cached = _redis_get("signals:all")
    if cached:
        signals = json.loads(cached)
        latest_date = signals[0]["signal_date"] if signals else ""
        buys = [s for s in signals if s.get("signal_type") == "dz_hi_up"]
        avoids = [s for s in signals if s.get("signal_type") == "dz_hi_dn"]
        return {
            "date": latest_date,
            "buys": buys,
            "avoids": avoids,
            "all": signals,
            "total_scanned": len(signals),
        }

    # 2) Fallback to PostgreSQL
    try:
        engine = get_pg_engine()
        ensure_schema()
        df = pd.read_sql("SELECT * FROM cached_signals", engine)
        if not df.empty:
            # Warm Redis for next time
            signals = df.to_dict(orient="records")
            _redis_set("signals:all", json.dumps(_sanitize_nan(signals), default=str))
            latest_date = df["signal_date"].max()
            today = df[df["signal_date"] == latest_date]
            buys = _sanitize_nan(today[today["signal_type"] == "dz_hi_up"].to_dict(orient="records"))
            avoids = _sanitize_nan(today[today["signal_type"] == "dz_hi_dn"].to_dict(orient="records"))
            return {
                "date": str(latest_date),
                "buys": buys,
                "avoids": avoids,
                "all": signals,
                "total_scanned": len(today),
            }
    except Exception:
        pass

    return {"date": "", "buys": [], "avoids": [], "all": [], "total_scanned": 0}


def get_signals_for_api(
    cap: str = "All",
    sort: str = "score",
    order: str = "desc",
    signal_type: str = "All",
    segment: str = "All",
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    """Fast paginated signals with server-side filter/sort.

    Returns dict with keys: signals, total, page, per_page, pages, date.
    """
    signals = get_latest_signals_cached()
    all_signals = signals.get("all", [])

    if not all_signals:
        return {"signals": [], "total": 0, "page": 1, "per_page": per_page, "pages": 0, "date": ""}

    # Compute scores if not present
    _ensure_scores(all_signals)

    # Filter by market cap (supports "SME" as a valid value)
    if cap and cap != "All":
        all_signals = [s for s in all_signals if s.get("market_cap_class") == cap]

    # Filter by segment (EQ/SME/All)
    if segment and segment != "All":
        all_signals = [s for s in all_signals if s.get("segment") == segment]

    # Filter by signal type
    if signal_type and signal_type != "All":
        all_signals = [s for s in all_signals if s.get("signal_type") == signal_type]

    # Sort
    reverse = order == "desc"
    if sort == "score":
        all_signals.sort(key=lambda s: s.get("_score", 0), reverse=reverse)
    elif sort == "deliv_z":
        all_signals.sort(key=lambda s: s.get("deliv_z") or 0, reverse=reverse)
    elif sort == "deliv_pct":
        all_signals.sort(key=lambda s: s.get("deliv_pct") or 0, reverse=reverse)
    elif sort == "ret_1d_pct":
        all_signals.sort(key=lambda s: s.get("ret_1d_pct") or 0, reverse=reverse)
    elif sort == "market_cap_cr":
        all_signals.sort(key=lambda s: s.get("market_cap_cr") or 0, reverse=reverse)
    elif sort == "rsi":
        all_signals.sort(key=lambda s: s.get("rsi") or 0, reverse=reverse)
    elif sort == "symbol":
        all_signals.sort(key=lambda s: s.get("symbol", ""), reverse=reverse)
    elif sort == "close":
        all_signals.sort(key=lambda s: s.get("close") or 0, reverse=reverse)

    total = len(all_signals)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    end = start + per_page

    # Return only needed fields for the table (minimize payload)
    import math

    fields = [
        "symbol",
        "exchange",
        "signal_type",
        "segment",
        "close",
        "deliv_pct",
        "deliv_z",
        "ret_1d_pct",
        "rsi",
        "entry_zone_low",
        "entry_zone_high",
        "stop_loss",
        "target_price",
        "market_cap_cr",
        "market_cap_class",
        "_score",
        "conviction_score",
        "kelly_fraction",
        # Fundamental fields
        "pe_trailing",
        "price_to_book",
        "roe",
        "debt_to_equity",
        "profit_margin",
        "revenue_growth",
        "dividend_yield",
        "sector",
        "industry",
        "company_name",
        "fundamental_score",
        # Institutional fields
        "fii_pct",
        "dii_pct",
        "promoter_pct",
        "pledge_pct",
        "institutional_score",
        # Professional composite
        "professional_score",
    ]
    page_signals = []
    for s in all_signals[start:end]:
        row = {f: s.get(f) for f in fields}
        for f in [
            "close",
            "deliv_pct",
            "deliv_z",
            "ret_1d_pct",
            "rsi",
            "entry_zone_low",
            "entry_zone_high",
            "stop_loss",
            "target_price",
            "market_cap_cr",
            "_score",
            "conviction_score",
            "kelly_fraction",
        ]:
            v = row.get(f)
            if v is not None:
                try:
                    v = float(v)
                    row[f] = None if math.isnan(v) else round(v, 2)
                except (ValueError, TypeError):
                    row[f] = None
        page_signals.append(row)

    return {
        "signals": page_signals,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "date": signals.get("date", ""),
    }


def _ensure_scores(signals: list[dict]) -> None:
    """Compute composite scores in-place if not already present. Sanitizes NaN."""
    import math

    def _safe(v):
        try:
            f = float(v)
            return None if math.isnan(f) or math.isinf(f) else f
        except (TypeError, ValueError):
            return None

    z_vals = []
    d_vals = []
    r_vals = []
    v_vals = []
    for s in signals:
        z = _safe(s.get("deliv_z"))
        d = _safe(s.get("deliv_pct"))
        r = _safe(s.get("ret_1d_pct"))
        v = _safe(s.get("vol_z"))
        z_vals.append(z if z is not None else 0)
        d_vals.append(d if d is not None else 0)
        r_vals.append(r if r is not None else 0)
        v_vals.append(v if v is not None else 0)

    if signals and "_score" in signals[0] and "conviction_score" in signals[0]:
        return

    z_min, z_max = min(z_vals), max(z_vals)
    d_min, d_max = min(d_vals), max(d_vals)
    r_min, r_max = min(r_vals), max(r_vals)
    v_min, v_max = min(v_vals), max(v_vals)

    z_range = z_max - z_min or 1
    d_range = d_max - d_min or 1
    r_range = r_max - r_min or 1
    v_range = v_max - v_min or 1

    for i, s in enumerate(signals):
        zn = (z_vals[i] - z_min) / z_range
        dn = (d_vals[i] - d_min) / d_range
        rn = (r_vals[i] - r_min) / r_range
        (v_vals[i] - v_min) / v_range
        s["_score"] = round(zn * 0.50 + dn * 0.30 + rn * 0.20, 4)

        # Conviction score: 40% deliv_z + 30% momentum + 20% volume + 10% technicals
        dz_n = min(abs(z_vals[i]) / 5.0, 1.0) * 0.40
        mom = min(max(r_vals[i] / 3.0, 0.0), 1.0) * 0.30
        vol = min(max(v_vals[i] / 2.0, 0.0), 1.0) * 0.20
        rsi = _safe(s.get("rsi")) or 50.0
        macd_h = _safe(s.get("macd_hist")) or _safe(s.get("macd")) or 0.0
        close = _safe(s.get("close")) or 0.0
        sma20 = _safe(s.get("sma_20")) or close
        tech = 0.0
        if 40 <= rsi <= 65:
            tech += 0.4
        elif 30 <= rsi <= 75:
            tech += 0.2
        if macd_h > 0:
            tech += 0.3
        if close > sma20 > 0:
            tech += 0.3
        tech *= 0.10
        s["conviction_score"] = round(dz_n + mom + vol + tech, 4)

        # Kelly fraction (half-Kelly, using default params)
        p = 0.43
        b = 250.0 / 165.0
        q = 1.0 - p
        full_kelly = (p * b - q) / b
        s["kelly_fraction"] = round(max(full_kelly * 0.5, 0.0), 6)


def get_cached_signal_for_symbol(symbol: str) -> dict[str, Any] | None:
    """Get cached signal for a single symbol. Redis hash → PG fallback."""
    sym = symbol.upper()

    # 1) Try Redis hash
    try:
        r = get_redis_client()
        raw = r.hget("signals:by_symbol", sym)
        if raw:
            return json.loads(raw)
    except Exception:
        pass

    # 2) PostgreSQL
    try:
        engine = get_pg_engine()
        df = pd.read_sql(
            "SELECT * FROM cached_signals WHERE symbol = :sym",
            engine,
            params={"sym": sym},
        )
        if not df.empty:
            return df.iloc[0].to_dict()
    except Exception:
        pass

    return None


def get_cached_signals_summary() -> dict[str, Any]:
    """Summary stats for dashboard cards."""
    # Redis fast path
    count = _redis_get("signals:count")
    date = _redis_get("signals:date")
    buys_raw = _redis_get("signals:buys")
    avoids_raw = _redis_get("signals:avoids")

    if count is not None:
        return {
            "date": date or "",
            "total": int(count),
            "buys": len(json.loads(buys_raw)) if buys_raw else 0,
            "avoids": len(json.loads(avoids_raw)) if avoids_raw else 0,
        }

    # PostgreSQL fallback
    try:
        engine = get_pg_engine()
        df = pd.read_sql("SELECT * FROM cached_signals", engine)
        if not df.empty:
            latest = df["signal_date"].max()
            today = df[df["signal_date"] == latest]
            return {
                "date": str(latest),
                "total": len(today),
                "buys": int((today["signal_type"] == "dz_hi_up").sum()),
                "avoids": int((today["signal_type"] == "dz_hi_dn").sum()),
            }
    except Exception:
        pass

    return {"total": 0, "buys": 0, "avoids": 0, "date": ""}
