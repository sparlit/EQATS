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


"""Full single-stock analysis from delivery parquet data."""


import json
from pathlib import Path
from typing import Any

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.features.delivery import add_features, prepare_frame, signal_mask


def get_stock_analysis(symbol: str, user_id: int | None = None) -> dict[str, Any] | None:
    """Compute full analysis for a single symbol from its delivery parquet."""
    settings = load_settings()
    nse_parquet = settings.normalized_dir / "delivery" / "NSE" / f"{symbol.upper()}.parquet"
    bse_parquet = settings.normalized_dir / "delivery" / "BSE" / f"{symbol.upper()}.parquet"
    parquet = nse_parquet if nse_parquet.exists() else bse_parquet
    if not parquet.exists():
        return None
    exchange = "NSE" if nse_parquet.exists() else "BSE"

    raw = pd.read_parquet(parquet)
    if raw.empty:
        return None

    frame = prepare_frame(raw, min_rows=min(20, len(raw)))
    if frame is None or frame.empty:
        return None

    frame = add_features(frame)
    if frame.empty:
        return None

    last = frame.iloc[-1]
    prev = frame.iloc[-2] if len(frame) > 1 else frame.iloc[-1]

    # Signal detection
    signals = signal_mask(frame, "dz_hi_up")
    signals_dn = signal_mask(frame, "dz_hi_dn")
    last_up = bool(signals.iloc[-1]) if len(signals) > 0 else False
    last_dn = bool(signals_dn.iloc[-1]) if len(signals_dn) > 0 else False
    signal_type = None
    if last_up:
        signal_type = "dz_hi_up"
    elif last_dn:
        signal_type = "dz_hi_dn"

    close = float(last["close"])
    atr = float(last.get("atr_14", close * 0.03)) if pd.notna(last.get("atr_14")) else close * 0.03

    # Recent series for charts (last 60 days)
    tail = frame.tail(60)
    price_dates = [str(d.date()) if hasattr(d, "date") else str(d)[:10] for d in pd.to_datetime(tail["date"])]
    price_closes = [round(float(v), 2) for v in tail["close"]]
    price_volumes = [int(v) if pd.notna(v) else 0 for v in tail.get("volume", [])]
    sma_20_series = [round(float(v), 2) if pd.notna(v) else None for v in tail.get("sma_20", [])]
    sma_50_series = [round(float(v), 2) if pd.notna(v) else None for v in tail.get("sma_50", [])]

    # Delivery z-score series (last 30 days)
    deliv_tail = frame.tail(30)
    deliv_z_series = [round(float(v), 2) if pd.notna(v) else None for v in deliv_tail.get("deliv_z", [])]
    deliv_pct_series = [round(float(v), 1) if pd.notna(v) else None for v in deliv_tail.get("deliv_pct", [])]
    deliv_dates = [str(d.date()) if hasattr(d, "date") else str(d)[:10] for d in pd.to_datetime(deliv_tail["date"])]

    # Recent suggestions (from PostgreSQL)
    recent_suggestions = []
    try:
        import sqlalchemy as sa
        from indian_quant.web.prod_config import get_pg_engine

        pg = get_pg_engine()
        with pg.connect() as conn:
            rows = (
                conn.execute(
                    sa.text(
                        "SELECT * FROM daily_suggestions WHERE symbol = :sym ORDER BY suggestion_date DESC LIMIT 10"
                    ),
                    {"sym": symbol.upper()},
                )
                .mappings()
                .fetchall()
            )
            recent_suggestions = [dict(r) for r in rows]
    except Exception:
        pass

    result = {
        "symbol": symbol.upper(),
        "exchange": exchange,
        "segment": str(last.get("segment", "EQ")),
        "latest_date": str(pd.to_datetime(last["date"]).date()),
        "latest_close": close,
        "prev_close": round(float(prev["close"]), 2),
        "ret_1d_pct": round((close / float(prev["close"]) - 1) * 100, 2) if float(prev["close"]) > 0 else 0,
        "signal_type": signal_type,
        "deliv_pct": round(float(last.get("deliv_pct", 0)), 1) if pd.notna(last.get("deliv_pct")) else None,
        "deliv_z": round(float(last.get("deliv_z", 0)), 2) if pd.notna(last.get("deliv_z")) else None,
        "vol_z": round(float(last.get("vol_z", 0)), 2) if pd.notna(last.get("vol_z")) else None,
        "hi_streak": int(last.get("hi_streak", 0)) if pd.notna(last.get("hi_streak")) else 0,
        "rsi": round(float(last.get("rsi", 0)), 1) if pd.notna(last.get("rsi")) else None,
        "macd": round(float(last.get("macd", 0)), 2) if pd.notna(last.get("macd")) else None,
        "macd_signal": round(float(last.get("macd_signal", 0)), 2) if pd.notna(last.get("macd_signal")) else None,
        "macd_hist": round(float(last.get("macd_hist", 0)), 2) if pd.notna(last.get("macd_hist")) else None,
        "sma_20": round(float(last.get("sma_20", 0)), 2) if pd.notna(last.get("sma_20")) else None,
        "sma_50": round(float(last.get("sma_50", 0)), 2) if pd.notna(last.get("sma_50")) else None,
        "atr_14": round(atr, 2),
        "entry_zone_low": round(close - atr * 0.5, 2),
        "entry_zone_high": round(close, 2),
        "stop_loss": round(close * 0.93, 2),
        "target_price": round(close * 1.05, 2),
        "price_dates": json.dumps(price_dates),
        "price_closes": json.dumps(price_closes),
        "price_volumes": json.dumps(price_volumes),
        "sma_20_series": json.dumps(sma_20_series),
        "sma_50_series": json.dumps(sma_50_series),
        "deliv_z_dates": json.dumps(deliv_dates),
        "deliv_z_series": json.dumps(deliv_z_series),
        "deliv_pct_series": json.dumps(deliv_pct_series),
        "recent_suggestions": recent_suggestions,
        "is_watched": False,
        "watchlist_notes": "",
    }

    # Check watchlist status
    if user_id is not None:
        try:
            from indian_quant.web.watchlist_store import WatchlistStore

            ws = WatchlistStore(db)
            result["is_watched"] = ws.is_watched(user_id, symbol)
            wl_id = ws.get_watchlist_id(user_id, symbol)
            if wl_id:
                cached = ws.get_signal_for_symbol(user_id, symbol)
                if cached:
                    result["cached_signal"] = cached
            ws.close()
        except Exception:
            pass

    return result
