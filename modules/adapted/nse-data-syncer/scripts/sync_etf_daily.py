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


"""Sync NSE ETF OHLCV into the etfs / etf_daily_prices / etf_performance
tables using Dhan's historical daily-candle API.

The universe (which symbols count as ETFs) is resolved live from Dhan's own
instrument master rather than a static downloaded CSV (data/MW-ETF-*.csv) -
self-updating as new ETFs list, no manual re-download needed. NSE ETF/mutual
fund units carry ISIN prefix 'INF' (regular equity shares are 'INE' - this is
the NSDL/CDSL ISIN numbering standard, not something that drifts); combined
with EXCH_ID=NSE, SEGMENT=E, SERIES=EQ this reproduces the old manually
curated CSV list exactly (328/328 matched) while also picking up 14 ETFs
listed since the last CSV snapshot. Dhan's own INSTRUMENT_TYPE='ETF' tag is
NOT used alone as the filter - it's occasionally wrong (e.g. INFRABEES is
mistagged 'MF') - the ISIN rule is the reliable one.

Same discovery + incremental-window pattern as sync_sme_stocks.py /
sync_new_listings.py: new ETFs get a full history backfill; ETFs that
already have data only re-fetch the last INCREMENTAL_WINDOW_DAYS to keep
daily runs cheap.

Requires DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in web/.env - same
Dhan account already used by sync_dhan_indices.py, no new secrets.
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


def load_etf_universe() -> pd.DataFrame:
    """Download Dhan's instrument master and filter to NSE-listed ETFs.
    Returns columns: security_id, symbol, name, isin, series."""
    df = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
    etf = df[
        (df["EXCH_ID"] == "NSE")
        & (df["SEGMENT"] == "E")
        & (df["SERIES"] == "EQ")
        & (df["ISIN"].astype(str).str.startswith("INF"))
    ].copy()
    etf = etf.rename(
        columns={
            "SECURITY_ID": "security_id",
            "UNDERLYING_SYMBOL": "symbol",
            "DISPLAY_NAME": "name",
            "ISIN": "isin",
            "SERIES": "series",
        }
    )[["security_id", "symbol", "name", "isin", "series"]]
    etf = etf.dropna(subset=["symbol"]).drop_duplicates(subset="symbol")
    return etf.reset_index(drop=True)


def _is_invalid_token(resp: requests.Response) -> bool:
    """DH-906 means the access token itself was rejected - distinct from a
    symbol just having no data (the case the below-50% check exists for).
    Once this hits, every remaining request in the run is guaranteed to fail
    the same way, so callers abort immediately instead of grinding through
    hundreds more doomed requests before the aggregate check below catches it."""
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


def upsert_etf(session, symbol, name, isin, security_id, series) -> int:
    row = session.execute(text("SELECT id FROM etfs WHERE symbol = :s"), {"s": symbol}).fetchone()
    if row:
        # Only refresh the Dhan-sourced identity fields - never clobber
        # underlying_asset/nav, which may hold better hand-curated data
        # from the original CSV-based population.
        session.execute(
            text("""
            UPDATE etfs SET name = :n, isin = :i, security_id = :sid, series = :sr, updated_at = NOW()
            WHERE id = :id
        """),
            {"n": name, "i": isin, "sid": security_id, "sr": series, "id": row[0]},
        )
        session.commit()
        return row[0]
    row = session.execute(
        text("""
            INSERT INTO etfs (symbol, name, isin, security_id, series, is_active, created_at, updated_at)
            VALUES (:s, :n, :i, :sid, :sr, 1, NOW(), NOW())
            RETURNING id
        """),
        {"s": symbol, "n": name, "i": isin, "sid": security_id, "sr": series},
    ).fetchone()
    session.commit()
    print(f"  + new ETF discovered: {symbol} ({name})")
    return row[0]


def sync_prices(session, etf_id: int, security_id: int, access_token: str) -> int:
    last_date = session.execute(
        text("SELECT MAX(date) FROM etf_daily_prices WHERE etf_id = :id"), {"id": etf_id}
    ).scalar()

    if last_date:
        from_date = (last_date - timedelta(days=INCREMENTAL_WINDOW_DAYS)).strftime("%Y-%m-%d")
    else:
        from_date = HISTORY_START  # brand-new ETF - full backfill

    to_date = datetime.now().strftime("%Y-%m-%d")
    df = fetch_dhan_history(security_id, from_date, to_date, access_token)
    if df.empty:
        return 0

    records = []
    for _, row in df.iterrows():
        records.append(
            (
                etf_id,
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
            INSERT INTO etf_daily_prices
                (etf_id, date, open_price, high_price, low_price, close_price, volume)
            VALUES %s
            ON CONFLICT (etf_id, date) DO UPDATE SET
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


def main():
    if not DHAN_CLIENT_ID or not DHAN_PIN or not DHAN_TOTP_SECRET:
        print("DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not set in web/.env")
        sys.exit(1)

    print("=== Syncing NSE ETFs from Dhan ===")
    universe = load_etf_universe()
    print(f"Universe: {len(universe)} ETFs from Dhan's instrument master")

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
        symbols_with_data = 0
        for i, row in enumerate(universe.itertuples(index=False), start=1):
            etf_id = upsert_etf(session, row.symbol, row.name, row.isin, int(row.security_id), row.series)
            n = sync_prices(session, etf_id, int(row.security_id), access_token)
            total_rows += n
            if n:
                symbols_with_data += 1
                db.update_etf_performance_metrics(etf_id)
            if i % 50 == 0:
                print(f"  Processed {i}/{len(universe)}...")
            time.sleep(0.5)  # be gentle with Dhan's rate limits
        print(
            f"\nDone. Upserted {total_rows} price rows across {len(universe)} ETFs "
            f"({symbols_with_data} symbols got at least one new row)."
        )

        # On any normal trading day, nearly every ETF should get exactly one new
        # row (today's close). A run where hardly anyone did - even though every
        # individual fetch_dhan_history() failure is swallowed as "just no new
        # data" rather than raised - means something systemic happened (Dhan's
        # EOD data not published yet when this ran, a transient outage, a wrong
        # security_id, etc). That's exactly what happened on 2026-08-17: every
        # ETF's sync silently no-opped, the job exited 0, and nobody noticed
        # until the /etf-live-strategy page was still showing Monday's picks on
        # Tuesday morning. Fail loudly instead of quietly no-opping.
        if len(universe) >= 50 and symbols_with_data < len(universe) * 0.5:
            print(
                f"\nERROR: only {symbols_with_data}/{len(universe)} ETFs got new data - "
                f"expected close to all of them. Treating this as a failed run."
            )
            sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
