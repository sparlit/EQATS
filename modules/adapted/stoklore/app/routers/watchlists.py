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


from fastapi import APIRouter, HTTPException

from app.core import db
from app.schemas import (
    RenameWatchlistRequest,
    ReorderWatchlistsRequest,
    WatchlistListRequest,
    WatchlistRequest,
)

router = APIRouter(tags=["watchlists"])


@router.get("/api/watchlist")
def watchlist():
    return db.list_watchlist()


@router.put("/api/watchlist/{symbol}")
def set_watchlist(symbol: str, req: WatchlistRequest):
    name = req.list_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="list_name can't be empty")
    db.set_watchlist(symbol.upper(), name)
    return {"ok": True}


@router.delete("/api/watchlist/{symbol}")
def remove_watchlist(symbol: str, list_name: str | None = None):
    """Removes from one list, or from every list (used when deleting the stock) when omitted."""
    db.remove_from_watchlist(symbol.upper(), list_name)
    return {"ok": True}


@router.get("/api/watchlists")
def watchlist_names():
    return db.list_watchlist_names()


@router.post("/api/watchlists")
def create_watchlist_list(req: WatchlistListRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name can't be empty")
    db.create_watchlist(name)
    return {"ok": True}


@router.post("/api/watchlists/reorder")
def reorder_watchlist_list(req: ReorderWatchlistsRequest):
    db.reorder_watchlists(req.names)
    return {"ok": True}


@router.put("/api/watchlists/{name}")
def rename_watchlist_list(name: str, req: RenameWatchlistRequest):
    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name can't be empty")
    db.rename_watchlist(name, new_name)
    return {"ok": True}


@router.delete("/api/watchlists/{name}")
def delete_watchlist_list(name: str):
    if db.watchlist_symbols(name):
        raise HTTPException(
            status_code=400, detail=f"'{name}' still has stocks in it - move or remove them first"
        )
    db.delete_watchlist(name)
    return {"ok": True}
