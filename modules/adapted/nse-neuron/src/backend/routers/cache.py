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
routers/cache.py
━━━━━━━━━━━━━━━━
Management endpoints for the per-symbol model weight cache.

GET    /api/models/cached                    — list every cached artifact
GET    /api/models/cached/{symbol}           — list cached artifacts for one symbol
DELETE /api/models/cached/{symbol}           — drop every cached model for a symbol
DELETE /api/models/cached/{symbol}/{model}   — drop one cached model
POST   /api/models/cached/purge              — remove expired artifacts
"""
from fastapi import APIRouter, HTTPException

import config
from utils import model_registry

router = APIRouter()


@router.get("/models/cached")
def list_cached():
    entries = model_registry.list_cached()
    return {
        "enabled": config.ENABLE_MODEL_CACHE,
        "max_stale_days": config.CACHE_MAX_STALE_DAYS,
        "max_age_days": config.CACHE_MAX_AGE_DAYS,
        "count": len(entries),
        "total_size_kb": round(sum(e["size_kb"] for e in entries), 1),
        "models": entries,
    }


@router.get("/models/cached/{symbol}")
def list_cached_for_symbol(symbol: str):
    sym = symbol.upper().strip()
    entries = [e for e in model_registry.list_cached() if e["symbol"] == sym]
    return {"symbol": sym, "count": len(entries), "models": entries}


@router.delete("/models/cached/{symbol}")
def delete_symbol(symbol: str):
    removed = model_registry.delete(symbol)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"No cached models for {symbol}")
    return {"deleted": removed, "symbol": symbol.upper()}


@router.delete("/models/cached/{symbol}/{model_name}")
def delete_one(symbol: str, model_name: str):
    removed = model_registry.delete(symbol, model_name)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"{symbol}/{model_name} not cached")
    return {"deleted": removed, "symbol": symbol.upper(), "model": model_name}


@router.post("/models/cached/purge")
def purge():
    removed = model_registry.purge_expired()
    return {"purged": removed, "max_age_days": config.CACHE_MAX_AGE_DAYS}
