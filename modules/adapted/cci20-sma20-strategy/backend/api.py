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
FastAPI application — Centralized Multi-User Edition.

Features:
  • All routes require Cognito JWT authentication (except /health).
  • Multi-user watchlists with Share IDs (sh_a8f9c2) for sharing and syncing.
  • User subscription management for shared watchlists.
  • Zero-compute GET /results/{watchlist} querying centralized daily_stock_metrics.
  • Trigger Scanner Lambda asynchronously via POST /scan.
"""

import json
import logging
import os
import sys
import uuid
from typing import TYPE_CHECKING, List, Optional

import boto3
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select

_backend_dir = os.path.dirname(__file__)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from auth import ADMIN_COGNITO_SUB, get_admin_user, get_current_user
from db.connection import get_db
from db.models import DailyStockMetric, User, UserSubscription, Watchlist, WatchlistItem, generate_share_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SCANNER_LAMBDA_NAME = os.environ.get("SCANNER_LAMBDA_NAME", "")
_raw_origins = os.environ.get(
    "CORS_ORIGINS",
    "https://jandginvestment.github.io,http://localhost:4200",
)
CORS_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ── Pydantic Request Models ───────────────────────────────────────────────────


class CreateWatchlistRequest(BaseModel):
    name: str
    description: str | None = None
    tickers: list[str] | None = []
    is_public: bool | None = False


class AddTickerRequest(BaseModel):
    ticker: str


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CCI/SMA Scanner API — Centralized Edition",
    version="2.5.0",
    default_response_class=ORJSONResponse,
    root_path="/Prod",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── Health ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness + DB connectivity check."""
    try:
        await db.execute(select(func.now()))
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {exc}")


# ── Me ─────────────────────────────────────────────────────────────────────────


@app.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "created_at": current_user.created_at,
        "is_admin": current_user.cognito_sub == ADMIN_COGNITO_SUB,
    }


# ── Admin ──────────────────────────────────────────────────────────────────────


@app.get("/admin/users")
async def get_all_users(admin: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """Admin only: List all users."""
    res = await db.execute(select(User).order_by(User.created_at.desc()))
    users = res.scalars().all()

    result = []
    for u in users:
        # Get count of owned watchlists
        wl_res = await db.execute(select(func.count(Watchlist.id)).where(Watchlist.user_id == u.id))
        wl_count = wl_res.scalar()

        result.append(
            {
                "id": str(u.id),
                "email": u.email,
                "created_at": u.created_at,
                "cognito_sub": u.cognito_sub,
                "watchlists_count": wl_count,
            }
        )
    return result


@app.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, admin: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """Admin only: Delete a user and cascade delete their data."""
    if user_id == str(admin.id):
        raise HTTPException(400, "Cannot delete yourself")

    res = await db.execute(select(User).where(User.id == user_id))
    user_to_delete = res.scalar_one_or_none()

    if not user_to_delete:
        raise HTTPException(404, "User not found")

    if user_to_delete.cognito_sub == ADMIN_COGNITO_SUB:
        raise HTTPException(403, "Cannot delete the admin user")

    await db.delete(user_to_delete)
    await db.commit()
    return {"status": "deleted", "user_id": user_id}


# ── Watchlists & Subscriptions ─────────────────────────────────────────────────


@app.get("/watchlists")
async def get_watchlists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all watchlists owned by or subscribed to by the user."""
    # Owned lists
    owned_res = await db.execute(select(Watchlist).where(Watchlist.user_id == current_user.id).order_by(Watchlist.name))
    owned = owned_res.scalars().all()

    # Subscribed lists
    sub_res = await db.execute(
        select(Watchlist)
        .join(UserSubscription, UserSubscription.watchlist_id == Watchlist.id)
        .where(UserSubscription.user_id == current_user.id)
        .order_by(Watchlist.name)
    )
    subscribed = sub_res.scalars().all()

    result = []
    for wl in owned:
        result.append(
            {
                "id": str(wl.id),
                "name": wl.name,
                "description": wl.description,
                "share_id": wl.share_id,
                "is_owner": True,
                "created_at": wl.created_at,
            }
        )
    for wl in subscribed:
        if not any(r["id"] == str(wl.id) for r in result):
            result.append(
                {
                    "id": str(wl.id),
                    "name": wl.name,
                    "description": wl.description,
                    "share_id": wl.share_id,
                    "is_owner": False,
                    "created_at": wl.created_at,
                }
            )
    return result


@app.post("/watchlists", status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    req: CreateWatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new personal watchlist with an auto-generated share_id."""
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Watchlist name cannot be empty")

    existing = await db.execute(
        select(Watchlist).where(
            Watchlist.user_id == current_user.id,
            Watchlist.name == name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Watchlist '{name}' already exists")

    wl = Watchlist(
        user_id=current_user.id,
        name=name,
        description=req.description,
        is_public=req.is_public or False,
        share_id=generate_share_id(),
    )
    db.add(wl)
    await db.flush()

    if req.tickers:
        items = []
        for t in req.tickers:
            t = t.strip()
            if t:
                if not t.endswith(".NS") and not t.endswith(".BO"):
                    t += ".NS"
                items.append(WatchlistItem(watchlist_id=wl.id, ticker=t))
        if items:
            db.add_all(items)
            await db.flush()

    await db.commit()
    return {
        "id": str(wl.id),
        "name": wl.name,
        "share_id": wl.share_id,
        "item_count": len(req.tickers or []),
    }


@app.post("/watchlists/{watchlist_id}/items")
async def add_item_to_watchlist(
    watchlist_id: str,
    req: AddTickerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a ticker symbol to an owned watchlist."""
    wl = await _get_owned_watchlist(watchlist_id, current_user, db)
    ticker = req.ticker.strip()
    if not ticker:
        raise HTTPException(400, "Ticker symbol required")
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker += ".NS"

    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.ticker == ticker,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "exists", "ticker": ticker}

    item = WatchlistItem(watchlist_id=wl.id, ticker=ticker)
    db.add(item)
    await db.commit()
    return {"status": "added", "ticker": ticker, "watchlist_id": str(wl.id)}


@app.delete("/watchlists/{watchlist_id}/items/{ticker}")
async def remove_item_from_watchlist(
    watchlist_id: str,
    ticker: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a ticker symbol from an owned watchlist."""
    wl = await _get_owned_watchlist(watchlist_id, current_user, db)
    symbol = ticker.strip()
    if not symbol.endswith(".NS") and not symbol.endswith(".BO"):
        symbol += ".NS"

    item_res = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.ticker == symbol,
        )
    )
    item = item_res.scalar_one_or_none()
    if item:
        await db.delete(item)
        await db.commit()
    return {"status": "removed", "ticker": symbol}


@app.get("/watchlists/share/{share_id}")
async def get_watchlist_by_share_id(
    share_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Preview a shared watchlist by share_id."""
    res = await db.execute(select(Watchlist).where(Watchlist.share_id == share_id))
    wl = res.scalar_one_or_none()
    if not wl:
        raise HTTPException(404, "Invalid share_id or watchlist not found")

    items_res = await db.execute(select(WatchlistItem.ticker).where(WatchlistItem.watchlist_id == wl.id))
    tickers = items_res.scalars().all()

    return {
        "id": str(wl.id),
        "name": wl.name,
        "description": wl.description,
        "share_id": wl.share_id,
        "tickers": list(tickers),
    }


@app.post("/watchlists/subscribe/{share_id}")
async def subscribe_to_watchlist(
    share_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subscribe to a shared watchlist using share_id."""
    res = await db.execute(select(Watchlist).where(Watchlist.share_id == share_id))
    wl = res.scalar_one_or_none()
    if not wl:
        raise HTTPException(404, "Invalid share_id or watchlist not found")

    if wl.user_id == current_user.id:
        return {"status": "already_owned", "name": wl.name, "share_id": wl.share_id}

    sub_res = await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id == current_user.id,
            UserSubscription.watchlist_id == wl.id,
        )
    )
    if sub_res.scalar_one_or_none():
        return {"status": "already_subscribed", "name": wl.name, "share_id": wl.share_id}

    sub = UserSubscription(user_id=current_user.id, watchlist_id=wl.id)
    db.add(sub)
    await db.commit()
    return {"status": "subscribed", "name": wl.name, "share_id": wl.share_id}


# ── Centralized Results Query ───────────────────────────────────────────────────


@app.get("/results/{watchlist_identifier}")
async def get_results(
    watchlist_identifier: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return scan results for a watchlist (identified by name, id, or share_id).
    Queries daily_stock_metrics cache table using a high-speed SQL JOIN.
    """
    wl = await _resolve_watchlist(watchlist_identifier, current_user, db)

    # Fetch latest metrics date
    latest_date_res = await db.execute(select(func.max(DailyStockMetric.scan_date)))
    latest_date = latest_date_res.scalar()

    if not latest_date:
        raise HTTPException(404, "No stock metric scans available yet — run a scan first")

    # SQL JOIN: watchlist_items ──► daily_stock_metrics
    query = (
        select(DailyStockMetric)
        .join(WatchlistItem, WatchlistItem.ticker == DailyStockMetric.ticker)
        .where(
            WatchlistItem.watchlist_id == wl.id,
            DailyStockMetric.scan_date == latest_date,
        )
        .order_by(DailyStockMetric.ticker)
    )
    res = await db.execute(query)
    rows = res.scalars().all()

    return {
        "watchlist": wl.name,
        "share_id": wl.share_id,
        "scanned_at": latest_date.isoformat(),
        "results": [
            {
                "ticker": r.ticker,
                "close": float(r.close) if r.close is not None else None,
                "cci_20": float(r.cci_20) if r.cci_20 is not None else None,
                "sma_20": float(r.sma_20) if r.sma_20 is not None else None,
                "yearly_low_pct": float(r.pct_from_y_low) if r.pct_from_y_low is not None else None,
                "monthly_low_pct": float(r.pct_from_m_low) if r.pct_from_m_low is not None else None,
                "weekly_low_pct": float(r.pct_from_w_low) if r.pct_from_w_low is not None else None,
                "yearly_low": float(r.yearly_low) if r.yearly_low is not None else None,
                "monthly_low": float(r.monthly_low) if r.monthly_low is not None else None,
                "weekly_low": float(r.weekly_low) if r.weekly_low is not None else None,
                "cci_history": r.cci_history or [],
                "narrow_cpr": bool(r.narrow_cpr) if r.narrow_cpr is not None else False,
            }
            for r in rows
            if r.close is not None and r.cci_20 is not None and r.sma_20 is not None
        ],
    }


# ── Scan Trigger ───────────────────────────────────────────────────────────────


@app.post("/scan")
async def trigger_scan(current_user: User = Depends(get_current_user)):
    """Invoke the Scanner Lambda asynchronously (fire-and-forget)."""
    if not SCANNER_LAMBDA_NAME:
        raise HTTPException(503, "SCANNER_LAMBDA_NAME not configured")
    try:
        client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "ap-southeast-1"))
        payload = {"user_id": str(current_user.id), "cognito_sub": current_user.cognito_sub}
        client.invoke(
            FunctionName=SCANNER_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )
        return {"status": "scan started", "triggered_by": current_user.email}
    except Exception as exc:
        logger.exception("Failed to invoke Scanner Lambda")
        raise HTTPException(500, str(exc))


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_owned_watchlist(watchlist_id: str, user: User, db: AsyncSession) -> Watchlist:
    if watchlist_id.isdigit():
        stmt = select(Watchlist).where(Watchlist.id == int(watchlist_id), Watchlist.user_id == user.id)
    else:
        stmt = select(Watchlist).where(Watchlist.name == watchlist_id, Watchlist.user_id == user.id)

    res = await db.execute(stmt)
    wl = res.scalar_one_or_none()
    if not wl:
        raise HTTPException(404, f"Watchlist '{watchlist_id}' not found or not owned by user")
    return wl


async def _resolve_watchlist(identifier: str, user: User, db: AsyncSession) -> Watchlist:
    """Resolve watchlist by Integer ID, Share ID, or Name."""
    # 1. By Integer ID
    if identifier.isdigit():
        res = await db.execute(select(Watchlist).where(Watchlist.id == int(identifier)))
        wl = res.scalar_one_or_none()
        if wl:
            return wl

    # 2. By Share ID
    if identifier.startswith("sh_"):
        res = await db.execute(select(Watchlist).where(Watchlist.share_id == identifier))
        wl = res.scalar_one_or_none()
        if wl:
            return wl

    # 3. By Name (owned or public)
    res = await db.execute(
        select(Watchlist).where(Watchlist.name == identifier, or_(Watchlist.user_id == user.id, Watchlist.is_public))
    )
    wl = res.scalar_one_or_none()
    if wl:
        return wl

    raise HTTPException(404, f"Watchlist '{identifier}' not found")
