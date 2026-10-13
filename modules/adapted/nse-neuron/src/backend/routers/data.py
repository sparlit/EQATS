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
routers/data.py
━━━━━━━━━━━━━━━
GET /api/symbols?q=       — search NSE symbols
GET /api/historical/{sym} — historical OHLC for charting
"""
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from src.backend.services.nse_service import fetch_data, search_symbols

router = APIRouter()


@router.get("/symbols")
def symbols(q: str = Query(default="", min_length=1)):
    try:
        return {"symbols": search_symbols(q)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/historical/{symbol}")
def historical(symbol: str, days: int = 120):
    sym = symbol.upper().strip()
    try:
        # Snapshot the dataframe returned directly from fetch_data instead of
        # re-reading config.HISTORIC_DATA — the latter is a shared global that
        # a concurrent request/job could have already overwritten by now.
        _, _, hist_df = fetch_data(sym)
        if hist_df is None:
            raise HTTPException(status_code=404, detail="No data")

        cols = [
            c for c in ["date", "open", "high", "low", "close", "volume"] if c in hist_df.columns
        ]
        mandatory = [c for c in ["date", "high", "low", "close"] if c in cols]
        tail = hist_df[cols].tail(days).dropna(subset=mandatory)
        records = []
        for _, row in tail.iterrows():
            rec = {
                k: str(row[k]) if k == "date" else (float(row[k]) if pd.notna(row[k]) else None)
                for k in cols
            }
            records.append(rec)

        return {"symbol": sym, "data": records}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
