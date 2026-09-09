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


"""Sync NSE SME (Small and Medium Enterprise board) stock OHLCV into the
sme_stocks / sme_daily_prices / sme_performance tables using Dhan's
historical daily-candle API.

Deliberately kept separate from stocks/daily_prices - SME is a distinct
board with different listing/trading rules, not to be mixed with the main
equity universe. Yahoo Finance has weak historical coverage for SME
names; Dhan has real, deep history back to actual listing dates (verified:
OMFURN has 967 days back to its 2017-10-12 listing).

The universe (which SME stocks to track) is resolved live from Dhan's own
instrument master (EXCH_ID=NSE, SEGMENT=E, SERIES in SM/ST/SZ) rather than
a static downloaded CSV - self-updating as new SME companies list, no
manual re-download needed (this is the same staleness trap the old BSE
sector CSV fell into - avoided here on purpose).

Requires DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in web/.env - same
account/credentials already used by sync_dhan_indices.py, no new secrets.
Same upsert pattern and incremental-window logic as sync_dhan_indices.py:
new stocks get a full history backfill; stocks that already have data
only re-fetch the last INCREMENTAL_WINDOW_DAYS to keep daily runs cheap.
"""
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import pyotp
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)
from app.database import DatabaseManager

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_PIN = os.getenv("DHAN_PIN")
DHAN_TOTP_SECRET = os.getenv("DHAN_TOTP_SECRET")
DHAN_TOKEN_URL = "https://auth.dhan.co/app/generateAccessToken"
DHAN_HISTORICAL_URL = "https://api.dhan.co/v2/charts/historical"
DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

SME_SERIES = {"SM", "ST", "SZ"}

HISTORY_START = "2010-01-01"
INCREMENTAL_WINDOW_DAYS = 90


def generate_access_token() -> str:
    """Mint a fresh 24h access token via Dhan's TOTP login flow (no browser needed).

    Note: Dhan rate-limits this to once every 2 minutes per account.
    """
    totp_code = pyotp.TOTP(DHAN_TOTP_SECRET).now()
    resp = requests.post(
        DHAN_TOKEN_URL,
        params={
            "dhanClientId": DHAN_CLIENT_ID,
            "pin": DHAN_PIN,
            "totp": totp_code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "accessToken" not in data:
        msg = f"Dhan token generation failed: {data.get('message', data)}"
        raise RuntimeError(msg)
    return data["accessToken"]


def _read_shared_token():
    """Read the token minted once for the whole job by generate_dhan_token.py
    (see dhan_daily_sync.yml) - a file path, never an env var holding the raw
    value, since that would put a live account credential in a public repo's
    workflow config/logs."""
    token_file = os.getenv("DHAN_TOKEN_FILE")
    if not token_file or not os.path.exists(token_file):
        return None
    with open(token_file) as f:
        return f.read().strip() or None


def load_sme_universe() -> pd.DataFrame:
    """Download Dhan's instrument master and filter to NSE SME-board equities.
    Returns columns: security_id, symbol, name, isin, series."""
    df = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
    sme = df[(df["EXCH_ID"] == "NSE") & (df["SEGMENT"] == "E") & (df["SERIES"].isin(SME_SERIES))].copy()
    sme = sme.rename(
        columns={
            "SECURITY_ID": "security_id",
            "UNDERLYING_SYMBOL": "symbol",
            "SYMBOL_NAME": "name",
            "ISIN": "isin",
            "SERIES": "series",
        }
    )[["security_id", "symbol", "name", "isin", "series"]]
    sme = sme.dropna(subset=["symbol"]).drop_duplicates(subset="symbol")
    return sme.reset_index(drop=True)


def _is_invalid_token(resp: requests.Response) -> bool:
    """DH-906 means the access token itself was rejected - distinct from a
    symbol just having no data. Once this hits, every remaining request in
    the run is guaranteed to fail the same way (see sync_dhan_indices.py's
    docstring on token collisions), so callers abort instead of grinding
    through hundreds more doomed requests and exiting 0 anyway."""
    try:
        return resp.json().get("errorCode") == "DH-906"
    except ValueError:
        return False


def fetch_dhan_history(
    security_id: int, from_date: str, to_date: str, access_token: str, retries: int = 3
) -> pd.DataFrame:
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "expiryCode": 0,
        "oi": False,
        "fromDate": from_date,
        "toDate": to_date,
    }
    headers = {
        "Content-Type": "application/json",
        "access-token": access_token,
        "client-id": DHAN_CLIENT_ID,
    }

    for attempt in range(1, retries + 1):
        resp = requests.post(DHAN_HISTORICAL_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code == 429:
            time.sleep(2 * attempt)
            continue
        if resp.status_code != 200:
            print(f"    HTTP {resp.status_code}: {resp.text[:300]}")
            if _is_invalid_token(resp):
                msg = (
                    "Dhan access token invalid/expired mid-run (DH-906) - aborting "
                    "instead of silently failing every remaining request."
                )
                raise RuntimeError(msg)
            return pd.DataFrame()
        data = resp.json()
        if not data.get("timestamp"):
            return pd.DataFrame()

        df = pd.DataFrame(
            {
                "date": pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").date,
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "close": data.get("close"),
                "volume": data.get("volume"),
            }
        )
        df["date"] = pd.to_datetime(df["date"])
        return df.drop_duplicates(subset="date", keep="last").reset_index(drop=True)

    print("    Giving up after repeated rate-limit errors")
    return pd.DataFrame()


def upsert_sme_stock(session, symbol, name, isin, security_id, series) -> int:
    row = session.execute(text("SELECT id FROM sme_stocks WHERE symbol = :s"), {"s": symbol}).fetchone()
    if row:
        session.execute(
            text("""
            UPDATE sme_stocks SET name = :n, isin = :i, security_id = :sid, series = :sr, updated_at = NOW()
            WHERE id = :id
        """),
            {"n": name, "i": isin, "sid": security_id, "sr": series, "id": row[0]},
        )
        session.commit()
        return row[0]
    row = session.execute(
        text("""
            INSERT INTO sme_stocks (symbol, name, isin, security_id, series, is_active, created_at, updated_at)
            VALUES (:s, :n, :i, :sid, :sr, true, NOW(), NOW())
            RETURNING id
        """),
        {"s": symbol, "n": name, "i": isin, "sid": security_id, "sr": series},
    ).fetchone()
    session.commit()
    return row[0]


def sync_prices(session, sme_stock_id: int, security_id: int, access_token: str) -> int:
    last_date = session.execute(
        text("SELECT MAX(date) FROM sme_daily_prices WHERE sme_stock_id = :id"), {"id": sme_stock_id}
    ).scalar()

    if last_date:
        from_date = (last_date - timedelta(days=INCREMENTAL_WINDOW_DAYS)).strftime("%Y-%m-%d")
    else:
        from_date = HISTORY_START  # brand-new stock - full backfill

    to_date = datetime.now().strftime("%Y-%m-%d")
    df = fetch_dhan_history(security_id, from_date, to_date, access_token)
    if df.empty:
        return 0

    records = []
    for _, row in df.iterrows():
        records.append(
            (
                sme_stock_id,
                row["date"].strftime("%Y-%m-%d"),
                float(row["open"]) if pd.notna(row["open"]) else None,
                float(row["high"]) if pd.notna(row["high"]) else None,
                float(row["low"]) if pd.notna(row["low"]) else None,
                float(row["close"]) if pd.notna(row["close"]) else None,
                int(row["volume"]) if pd.notna(row["volume"]) else None,
            )
        )

    raw_conn = session.bind.raw_connection()
    try:
        cursor = raw_conn.cursor()
        execute_values(
            cursor,
            """
            INSERT INTO sme_daily_prices
                (sme_stock_id, date, open_price, high_price, low_price, close_price, volume)
            VALUES %s
            ON CONFLICT (sme_stock_id, date) DO UPDATE SET
                open_price  = EXCLUDED.open_price,
                high_price  = EXCLUDED.high_price,
                low_price   = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume      = EXCLUDED.volume
        """,
            records,
            page_size=500,
        )
        raw_conn.commit()
        cursor.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    return len(records)


def compute_performance(session, sme_stock_id: int):
    rows = session.execute(
        text("""
            SELECT date, close_price FROM sme_daily_prices
            WHERE sme_stock_id = :id AND close_price IS NOT NULL
            ORDER BY date DESC LIMIT 2000
        """),
        {"id": sme_stock_id},
    ).fetchall()
    if not rows:
        return

    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    latest_price = df.iloc[-1]["close"]
    latest_date = df.iloc[-1]["date"]

    def pct(days):
        cutoff = latest_date - timedelta(days=days)
        ref = df[df["date"] <= cutoff]
        if ref.empty:
            return None
        ref_price = ref.iloc[-1]["close"]
        return float(round((latest_price - ref_price) / ref_price * 100, 2)) if ref_price else None

    session.execute(
        text("""
        INSERT INTO sme_performance
            (sme_stock_id, change_1w, change_1m, change_3m, change_6m, change_1y, change_3y, change_5y, updated_at)
        VALUES
            (:id, :w, :m1, :m3, :m6, :y1, :y3, :y5, NOW())
        ON CONFLICT (sme_stock_id) DO UPDATE SET
            change_1w  = :w,
            change_1m  = :m1,
            change_3m  = :m3,
            change_6m  = :m6,
            change_1y  = :y1,
            change_3y  = :y3,
            change_5y  = :y5,
            updated_at = NOW()
    """),
        {
            "id": sme_stock_id,
            "w": pct(7),
            "m1": pct(30),
            "m3": pct(90),
            "m6": pct(180),
            "y1": pct(365),
            "y3": pct(365 * 3),
            "y5": pct(365 * 5),
        },
    )
    session.commit()


def main():
    if not DHAN_CLIENT_ID or not DHAN_PIN or not DHAN_TOTP_SECRET:
        print("DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not set in web/.env")
        sys.exit(1)

    print("=== Syncing NSE SME Stocks from Dhan ===")
    universe = load_sme_universe()
    print(f"Universe: {len(universe)} SME stocks from Dhan's instrument master")

    access_token = _read_shared_token()
    if access_token:
        print("Using shared Dhan access token (minted once for this job)")
    else:
        access_token = generate_access_token()
        print("Generated fresh Dhan access token via TOTP")

    db = DatabaseManager()
    session = db.Session()
    try:
        total_rows = 0
        for i, row in enumerate(universe.itertuples(index=False), start=1):
            sme_stock_id = upsert_sme_stock(session, row.symbol, row.name, row.isin, int(row.security_id), row.series)
            n = sync_prices(session, sme_stock_id, int(row.security_id), access_token)
            total_rows += n
            if n:
                compute_performance(session, sme_stock_id)
            if i % 50 == 0:
                print(f"  Processed {i}/{len(universe)}...")
            time.sleep(0.5)  # be gentle with Dhan's rate limits
        print(f"\nDone. Upserted {total_rows} price rows across {len(universe)} SME stocks.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
