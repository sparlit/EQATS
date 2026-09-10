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


import contextlib
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timezone
from pathlib import Path

import pandas as pd
import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_PLAN_ID = os.getenv("RAZORPAY_PLAN_ID")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

required = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SERVICE_KEY": SUPABASE_SERVICE_KEY,
    "RAZORPAY_KEY_ID": RAZORPAY_KEY_ID,
    "RAZORPAY_KEY_SECRET": RAZORPAY_KEY_SECRET,
    "RAZORPAY_PLAN_ID": RAZORPAY_PLAN_ID,
    "RAZORPAY_WEBHOOK_SECRET": RAZORPAY_WEBHOOK_SECRET,
}
missing = [name for name, value in required.items() if not value]
if missing:
    raise RuntimeError("Missing environment variables: " + ", ".join(missing))

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = FastAPI(title="NSE Quant Trading API", version="2.0.0")

# Local React + deployed frontend support.
allowed_origins = [x.strip() for x in FRONTEND_URL.split(",") if x.strip()]
if "http://localhost:5173" not in allowed_origins:
    allowed_origins.append("http://localhost:5173")
if "http://127.0.0.1:5173" not in allowed_origins:
    allowed_origins.append("http://127.0.0.1:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT = Path("output")

REPORTS = {
    "All Scores": "all_scores.csv",
    "Next-Day Candidates": "next_day_candidates.csv",
    "Swing Candidates": "swing_candidates.csv",
    "Historical Setup Stats": "historical_setup_stats.csv",
    "Position Selection": "position_selection.csv",
    "High-Priority Overlap": "high_priority_overlap.csv",
}

PREMIUM_REPORTS = {
    "Next-Day Candidates",
    "High-Priority Overlap",
}

FREE_REPORTS = [name for name in REPORTS if name not in PREMIUM_REPORTS]


def read_report(name: str) -> pd.DataFrame:
    filename = REPORTS.get(name)
    if not filename:
        raise HTTPException(status_code=404, detail="Unknown report")
    path = OUTPUT / filename
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, low_memory=False)
        df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]
        return df
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read report: {exc}",
        )


def records(df: pd.DataFrame):
    """
    Convert a DataFrame to JSON-safe Python records.

    Important: `df.where(pd.notna(df), None)` alone does NOT reliably replace
    NaN values in numeric columns because pandas keeps the column's float dtype.
    Converting to object dtype first ensures missing values become real None
    values, which FastAPI can serialize as JSON null.
    """
    if df.empty:
        return []

    clean = df.astype(object).where(pd.notna(df), None)

    # Also normalize any remaining non-JSON numeric values.
    result = []
    for row in clean.to_dict(orient="records"):
        safe_row = {}
        for key, value in row.items():
            if value is None:
                safe_row[key] = None
                continue

            try:
                # Handles float NaN / +/-Infinity.
                if isinstance(value, float):
                    if pd.isna(value) or value in (float("inf"), float("-inf")):
                        safe_row[key] = None
                        continue

                # Convert pandas/numpy scalar values to native Python values.
                if hasattr(value, "item"):
                    value = value.item()

                # Final NaN check after scalar conversion.
                if isinstance(value, float) and pd.isna(value):
                    value = None

            except (TypeError, ValueError):
                pass

            safe_row[key] = value

        result.append(safe_row)

    return result


def symbol_column(df: pd.DataFrame):
    if df.empty:
        return None
    candidates = [
        "SYMBOL",
        "Symbol",
        "symbol",
        "STOCK",
        "Stock",
        "TICKER",
        "Ticker",
        "SECURITY",
        "Security",
    ]
    for column in candidates:
        if column in df.columns:
            return column
    for column in df.columns:
        upper = str(column).upper()
        if "SYMBOL" in upper or "TICKER" in upper:
            return column
    return None


def bearer_token(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token")
    return token


def authenticated_user(authorization: str | None):
    token = bearer_token(authorization)
    try:
        result = supabase.auth.get_user(token)
        user = getattr(result, "user", None)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        return user
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {exc}",
        )


def current_subscription(user_id: str):
    try:
        result = (
            supabase.table("subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Subscription lookup failed: {exc}",
        )


def subscription_is_active(subscription):
    if not subscription:
        return False
    status = str(subscription.get("status", "")).lower()
    return status in {"active", "authenticated"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "nse-quant-api"}


# ------------------------- React REPORT API -------------------------


@app.get("/api/reports")
def api_reports(authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    subscription = current_subscription(user.id)
    paid = subscription_is_active(subscription)

    result = []
    for name in REPORTS:
        is_premium = name in PREMIUM_REPORTS
        if is_premium and not paid:
            result.append(
                {
                    "name": name,
                    "premium": True,
                    "locked": True,
                    "count": None,
                    "rows": [],
                }
            )
            continue

        df = read_report(name)
        result.append(
            {
                "name": name,
                "premium": is_premium,
                "locked": False,
                "count": len(df),
                "rows": records(df),
            }
        )

    return {
        "authenticated": True,
        "premium": paid,
        "subscription": subscription,
        "reports": result,
    }


@app.get("/api/reports/{report_name}")
def api_report(
    report_name: str,
    authorization: str | None = Header(default=None),
):
    user = authenticated_user(authorization)
    name = report_name
    if name not in REPORTS:
        # Support URL-decoded report names and a few common aliases.
        aliases = {
            "all-scores": "All Scores",
            "next-day-candidates": "Next-Day Candidates",
            "swing-candidates": "Swing Candidates",
            "historical-setup-stats": "Historical Setup Stats",
            "position-selection": "Position Selection",
            "high-priority-overlap": "High-Priority Overlap",
        }
        name = aliases.get(report_name.lower(), report_name)

    if name not in REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")

    subscription = current_subscription(user.id)
    if name in PREMIUM_REPORTS and not subscription_is_active(subscription):
        raise HTTPException(
            status_code=403,
            detail="Premium subscription required for this report",
        )

    df = read_report(name)
    return {
        "name": name,
        "premium": name in PREMIUM_REPORTS,
        "count": len(df),
        "columns": list(df.columns),
        "rows": records(df),
    }


@app.get("/api/stocks/{symbol}")
def api_stock(
    symbol: str,
    authorization: str | None = Header(default=None),
):
    user = authenticated_user(authorization)
    target = symbol.strip().upper()
    if not target:
        raise HTTPException(status_code=400, detail="Stock symbol is required")

    found = []
    overview = {}

    for name in FREE_REPORTS:
        df = read_report(name)
        sc = symbol_column(df)
        if not sc or df.empty:
            continue

        mask = df[sc].astype(str).str.strip().str.upper().eq(target)
        matches = df.loc[mask]
        if matches.empty:
            continue

        row = matches.iloc[0]
        for key in [
            "CMP",
            "PRICE",
            "LTP",
            "CURRENT_PRICE",
            "BIAS",
            "SIGNAL",
            "CONFIDENCE",
            "SCORE",
            "SWING_SCORE",
            "POSITION_SCORE",
            "HISTORICAL_SCORE",
            "TREND",
            "TRADE_MODE",
            "PRIMARY_DRIVER",
            "INVALIDATION",
        ]:
            if key in row.index and key not in overview:
                value = row[key]
                overview[key] = None if pd.isna(value) else value

        found.append(
            {
                "report": name,
                "premium": False,
                "count": len(matches),
                "rows": records(matches),
            }
        )

    # Premium report metadata is visible only to paid users.
    subscription = current_subscription(user.id)
    paid = subscription_is_active(subscription)

    for name in PREMIUM_REPORTS:
        df = read_report(name)
        sc = symbol_column(df)
        if not sc or df.empty:
            continue
        mask = df[sc].astype(str).str.strip().str.upper().eq(target)
        matches = df.loc[mask]
        if matches.empty:
            continue
        found.append(
            {
                "report": name,
                "premium": True,
                "locked": not paid,
                "count": len(matches) if paid else None,
                "rows": records(matches) if paid else [],
            }
        )

    return {
        "symbol": target,
        "signal": overview.get("SIGNAL") or overview.get("BIAS"),
        "overview": overview,
        "reports": found,
        "premium": paid,
    }


@app.get("/api/subscription")
def api_subscription(authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    subscription = current_subscription(user.id)
    return {
        "authenticated": True,
        "active": subscription_is_active(subscription),
        "subscription": subscription,
    }


# ------------------------- EXISTING PAYMENT LOGIC -------------------------


@app.post("/create-subscription")
async def create_subscription(request: Request):
    body = await request.json()
    user_id = body.get("user_id")

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        user_response = supabase.auth.admin.get_user_by_id(user_id)
        if not user_response:
            raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to verify user: {exc}",
        )

    try:
        existing = supabase.table("subscriptions").select("*").eq("user_id", user_id).limit(1).execute()
        if existing.data:
            current = existing.data[0]
            if current.get("status") in ["active", "authenticated", "pending"]:
                return {
                    "success": True,
                    "existing": True,
                    "subscription_id": current.get("razorpay_subscription_id"),
                    "status": current.get("status"),
                }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Subscription lookup failed: {exc}",
        )

    try:
        subscription = razorpay_client.subscription.create(
            {
                "plan_id": RAZORPAY_PLAN_ID,
                "total_count": 12,
                "quantity": 1,
                "customer_notify": 1,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Razorpay error: {exc}")

    subscription_id = subscription["id"]

    try:
        record = {
            "user_id": user_id,
            "status": subscription.get("status", "created"),
            "plan_name": "NSE Quant Trading Monthly",
            "amount": 100,
            "razorpay_subscription_id": subscription_id,
        }
        supabase.table("subscriptions").insert(record).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(f"Subscription was created in Razorpay but could not be stored in Supabase: {exc}"),
        )

    return {
        "success": True,
        "subscription_id": subscription_id,
        "plan_id": RAZORPAY_PLAN_ID,
        "status": subscription.get("status", "created"),
        "amount": 100,
        "currency": "INR",
    }


@app.post("/razorpay-webhook")
async def razorpay_webhook(request: Request):
    payload = await request.body()
    received_signature = request.headers.get("X-Razorpay-Signature")

    if not received_signature:
        raise HTTPException(status_code=400, detail="Missing Razorpay signature")

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_name = event.get("event", "")

    if event_name == "subscription.authenticated":
        await process_subscription_event(event, "authenticated")
    elif event_name in {"subscription.activated", "subscription.charged"}:
        await process_subscription_event(event, "active")
    elif event_name == "subscription.cancelled":
        await process_subscription_event(event, "cancelled")
    elif event_name == "subscription.completed":
        await process_subscription_event(event, "completed")
    elif event_name == "subscription.pending":
        await process_subscription_event(event, "pending")

    return {"received": True, "event": event_name}


async def process_subscription_event(event, new_status):
    payload = event.get("payload", {})
    subscription_entity = payload.get("subscription", {}).get("entity", {})
    subscription_id = subscription_entity.get("id")

    if not subscription_id:
        return

    result = (
        supabase.table("subscriptions").select("*").eq("razorpay_subscription_id", subscription_id).limit(1).execute()
    )
    if not result.data:
        return

    existing = result.data[0]
    update_data = {
        "status": new_status,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    payment_entity = payload.get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    if payment_id:
        update_data["razorpay_payment_id"] = payment_id

    start_at = subscription_entity.get("start_at")
    if start_at:
        with contextlib.suppress(Exception):
            update_data["start_date"] = datetime.fromtimestamp(int(start_at), tz=UTC).isoformat()

    end_at = subscription_entity.get("end_at")
    if end_at:
        with contextlib.suppress(Exception):
            update_data["end_date"] = datetime.fromtimestamp(int(end_at), tz=UTC).isoformat()

    supabase.table("subscriptions").update(update_data).eq("id", existing["id"]).execute()
