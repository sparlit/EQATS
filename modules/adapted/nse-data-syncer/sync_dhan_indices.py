"""Sync NSE + BSE sectoral / thematic / benchmark indices into the indices /
index_daily_prices / index_performance tables using Dhan's historical
daily-candle API.

Covers the indices Yahoo Finance doesn't carry history for (all the newer
NIFTY_* thematic indices, Nifty Private Bank) plus the two broad indices
(Largemid 250, Smallcap 250) that were previously synced from yfinance but
only had a single day of history there. Also covers all 8 indices with
monthly options trading (5 NSE + 3 BSE) - see the "Monthly options
underlyings" section below.

Requires DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in web/.env. A fresh
24h access token is minted via Dhan's TOTP login flow at the start of every
run, so this needs no manual token refresh (unlike the web-UI-generated
token, which expires after 24h and requires a browser login to renew).
Same upsert pattern as sync_us_indices.py, safe to re-run daily. New indices
get a full history backfill; indices that already have data only re-fetch
the last INCREMENTAL_WINDOW_DAYS to keep daily runs cheap.
"""
import sys, os, time
import pandas as pd
import pyotp
import requests
from sqlalchemy import text
from datetime import datetime, timedelta
from dotenv import load_dotenv
from psycopg2.extras import execute_values

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, 'web', '.env'))
sys.path.append(base_dir)
from app.database import DatabaseManager

DHAN_CLIENT_ID = os.getenv('DHAN_CLIENT_ID')
DHAN_PIN = os.getenv('DHAN_PIN')
DHAN_TOTP_SECRET = os.getenv('DHAN_TOTP_SECRET')
DHAN_TOKEN_URL = 'https://auth.dhan.co/app/generateAccessToken'
DHAN_HISTORICAL_URL = 'https://api.dhan.co/v2/charts/historical'

# security_id -> (our symbol, display name)
# security_id comes from Dhan's instrument master (INSTRUMENT=INDEX,
# EXCH_ID=NSE or BSE - Dhan carries both exchanges' indices under the same
# "IDX_I" exchangeSegment, fetched identically regardless of EXCH_ID):
# https://images.dhan.co/api-data/api-scrip-master-detailed.csv
DHAN_INDICES = [
    # -- Sectoral / thematic (matches the TradingView sector watchlist) --
    (34,  'CNXREALTY',          'Nifty Realty'),
    (447, 'NIFTY_HEALTHCARE',   'Nifty Healthcare'),
    (29,  'CNXIT',              'Nifty IT'),
    (32,  'CNXPHARMA',          'Nifty Pharma'),
    (31,  'CNXMETAL',           'Nifty Metal'),
    (815, 'NIFTY_IND_TOURISM',  'Nifty India Tourism'),
    (43,  'CNXINFRA',           'Nifty Infrastructure'),
    (803, 'NIFTY_CAPITAL_MKT',  'Nifty Capital Markets'),
    (469, 'CNXFINANCE',         'Nifty Financial Services 25/50'),
    (470, 'NIFTY_OIL_AND_GAS',  'Nifty Oil and Gas'),
    (28,  'CNXFMCG',            'Nifty FMCG'),
    (15,  'NIFTYPVTBANK',       'Nifty Private Bank'),
    (41,  'CNXPSE',             'Nifty PSE'),
    (493, 'NIFTY_IND_DEFENCE',  'Nifty India Defence'),
    (491, 'NIFTY_EV',           'Nifty EV & New Age Auto'),
    (14,  'CNXAUTO',            'Nifty Auto'),
    (30,  'CNXMEDIA',           'Nifty Media'),
    (42,  'CNXENERGY',          'Nifty Energy'),
    (33,  'CNXPSUBANK',         'Nifty PSU Bank'),

    # -- Other major sector/thematic indices Dhan provides, not in the screenshot --
    (25,  'NIFTYBANK',          'Nifty Bank'),
    (27,  'FINNIFTY',           'Nifty Financial Services'),
    (44,  'CNXMNC',             'Nifty MNC'),
    (45,  'CNXCPSE',            'Nifty CPSE'),
    (46,  'CNXSERVICE',         'Nifty Services Sector'),
    (39,  'CNXCOMMODITIES',     'Nifty Commodities'),
    (40,  'CNXCONSUMPTION',     'Nifty Consumption'),
    (21,  'INDIAVIX',           'India VIX'),

    # -- Closes out NSE's official 16-index "Sectoral Indices" category
    # (was missing these 2 out of 16) --
    (495, 'CNXFINSEREXBNK',     'Nifty Financial Services Ex Bank'),
    (466, 'CNXCONSRDURBL',      'Nifty Consumer Durables'),

    # -- IPO / new-age economy indices --
    (816, 'NIFTY_IPO',                  'Nifty IPO'),
    (473, 'NIFTY_IND_DIGITAL',          'Nifty India Digital'),
    (822, 'NIFTY_NEW_AGE_CONSUMPTION',  'Nifty India New Age Consumption'),

    # -- Fix broad indices that only had 1 day of history via yfinance --
    (6,   'NIFTY_LARGEMID250.NS', 'Nifty Largemid 250'),
    (3,   'NIFTYSMLCAP250.NS',    'Nifty Smallcap 250'),

    # -- Broad NSE indices previously synced from yfinance (setup_indices.py /
    # sync_index_daily.py) - moved to Dhan so the whole "Daily Index Sync"
    # workflow has one consistent data source --
    (13,  '^NSEI',                'Nifty 50'),
    (1,   'NIFTYMIDCAP150.NS',    'Nifty Midcap 150'),
    (19,  '^CRSLDX',              'Nifty 500'),

    # -- Monthly options underlyings not yet covered above (5 NSE + 3 BSE,
    # last-Tuesday NSE / last-Thursday BSE monthly expiry) --
    (442, 'MIDCPNIFTY',           'Nifty Midcap Select'),
    (38,  'NIFTYNXT50',           'Nifty Next 50'),
    (51,  'SENSEX',               'BSE Sensex'),
    (69,  'BANKEX',               'BSE Bankex'),
    (83,  'SNSX50',               'BSE Sensex 50'),
]

# Symbols handled by the separate "US Market Daily Sync" workflow
# (scripts/sync_us_indices.py) - Dhan doesn't carry US indices at all (its
# IDX_I segment only covers NSE + BSE), so these stay on yfinance and must
# not be touched by this script.
US_ONLY_SYMBOLS = {'^GSPC', '^IXIC', '^DJI', '^RUT', '^RUI', '^VIX'}

HISTORY_START = '2011-01-01'
# Daily runs only need to re-fetch a recent window, not the full history -
# anchored to the last synced date (not "today") so any gap in cron runs,
# however long, still gets fully backfilled with no missing days.
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
    if 'accessToken' not in data:
        raise RuntimeError(f"Dhan token generation failed: {data.get('message', data)}")
    return data['accessToken']


def _read_shared_token():
    """Read the token minted once for the whole job by generate_dhan_token.py
    (see dhan_daily_sync.yml) - a file path, never an env var holding the raw
    value, since that would put a live account credential in a public repo's
    workflow config/logs."""
    token_file = os.getenv('DHAN_TOKEN_FILE')
    if not token_file or not os.path.exists(token_file):
        return None
    with open(token_file) as f:
        return f.read().strip() or None


def _is_invalid_token(resp: requests.Response) -> bool:
    """DH-906 means the access token itself was rejected - distinct from an
    index just having no data. Once this hits, every remaining request in
    the run is guaranteed to fail the same way (see the token-collision note
    above), so callers abort instead of grinding through the rest of
    DHAN_INDICES doomed and exiting 0 anyway."""
    try:
        return resp.json().get('errorCode') == 'DH-906'
    except ValueError:
        return False


def fetch_dhan_history(security_id: int, from_date: str, to_date: str, access_token: str, retries: int = 3) -> pd.DataFrame:
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": "IDX_I",
        "instrument": "INDEX",
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
                raise RuntimeError(
                    "Dhan access token invalid/expired mid-run (DH-906) - aborting "
                    "instead of silently failing every remaining request."
                )
            return pd.DataFrame()
        data = resp.json()
        if not data.get('timestamp'):
            return pd.DataFrame()

        df = pd.DataFrame({
            'date': pd.to_datetime(data['timestamp'], unit='s', utc=True).tz_convert('Asia/Kolkata').date,
            'open': data.get('open'),
            'high': data.get('high'),
            'low': data.get('low'),
            'close': data.get('close'),
            'volume': data.get('volume'),
        })
        df['date'] = pd.to_datetime(df['date'])
        # Dhan occasionally returns two rows for the same calendar date (seen on
        # NIFTY SMALLCAP 250, 2024-09-18) - keep the later one (has real volume).
        df = df.drop_duplicates(subset='date', keep='last').reset_index(drop=True)
        return df

    print("    Giving up after repeated rate-limit errors")
    return pd.DataFrame()


def upsert_index(session, symbol, name) -> int:
    row = session.execute(
        text("SELECT id FROM indices WHERE symbol = :s"), {'s': symbol}
    ).fetchone()
    if row:
        return row[0]
    row = session.execute(
        text("""
            INSERT INTO indices (symbol, name, is_active, created_at, updated_at)
            VALUES (:s, :n, 1, NOW(), NOW())
            RETURNING id
        """),
        {'s': symbol, 'n': name}
    ).fetchone()
    session.commit()
    return row[0]


def sync_prices(session, index_id: int, security_id: int, access_token: str) -> int:
    last_date = session.execute(
        text("SELECT MAX(date) FROM index_daily_prices WHERE index_id = :id"),
        {'id': index_id}
    ).scalar()

    if last_date:
        from_date = (last_date - timedelta(days=INCREMENTAL_WINDOW_DAYS)).strftime('%Y-%m-%d')
    else:
        from_date = HISTORY_START  # brand-new index - full backfill

    to_date = datetime.now().strftime('%Y-%m-%d')
    df = fetch_dhan_history(security_id, from_date, to_date, access_token)
    if df.empty:
        print(f"    No data from Dhan for security_id {security_id}")
        return 0

    records = []
    for _, row in df.iterrows():
        records.append((
            index_id,
            row['date'].strftime('%Y-%m-%d'),
            float(row['open']) if pd.notna(row['open']) else None,
            float(row['high']) if pd.notna(row['high']) else None,
            float(row['low']) if pd.notna(row['low']) else None,
            float(row['close']) if pd.notna(row['close']) else None,
            int(row['volume']) if pd.notna(row['volume']) else None,
        ))

    raw_conn = session.bind.raw_connection()
    try:
        cursor = raw_conn.cursor()
        execute_values(cursor, """
            INSERT INTO index_daily_prices
                (index_id, date, open_price, high_price, low_price, close_price, volume)
            VALUES %s
            ON CONFLICT (index_id, date) DO UPDATE SET
                open_price  = EXCLUDED.open_price,
                high_price  = EXCLUDED.high_price,
                low_price   = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume      = EXCLUDED.volume
        """, records, page_size=500)
        raw_conn.commit()
        cursor.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    return len(records)


def compute_performance(session, index_id: int):
    rows = session.execute(
        text("""
            SELECT date, close_price FROM index_daily_prices
            WHERE index_id = :id AND close_price IS NOT NULL
            ORDER BY date DESC LIMIT 2000
        """),
        {'id': index_id}
    ).fetchall()
    if not rows:
        return

    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    latest_price = df.iloc[-1]['close']
    latest_date = df.iloc[-1]['date']

    def pct(days):
        cutoff = latest_date - timedelta(days=days)
        ref = df[df['date'] <= cutoff]
        if ref.empty:
            return None
        ref_price = ref.iloc[-1]['close']
        return float(round((latest_price - ref_price) / ref_price * 100, 2)) if ref_price else None

    session.execute(text("""
        INSERT INTO index_performance
            (index_id, change_1w, change_1m, change_3m, change_6m, change_1y, change_3y, change_5y, updated_at)
        VALUES
            (:id, :w, :m1, :m3, :m6, :y1, :y3, :y5, NOW())
        ON CONFLICT (index_id) DO UPDATE SET
            change_1w  = :w,
            change_1m  = :m1,
            change_3m  = :m3,
            change_6m  = :m6,
            change_1y  = :y1,
            change_3y  = :y3,
            change_5y  = :y5,
            updated_at = NOW()
    """), {
        'id': index_id,
        'w': pct(7),
        'm1': pct(30),
        'm3': pct(90),
        'm6': pct(180),
        'y1': pct(365),
        'y3': pct(365 * 3),
        'y5': pct(365 * 5),
    })
    session.commit()


def main():
    if not DHAN_CLIENT_ID or not DHAN_PIN or not DHAN_TOTP_SECRET:
        print("DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not set in web/.env")
        sys.exit(1)

    print("=== Syncing NSE + BSE Indices from Dhan ===")
    access_token = _read_shared_token()
    if access_token:
        print("Using shared Dhan access token (minted once for this job)")
    else:
        access_token = generate_access_token()
        print("Generated fresh Dhan access token via TOTP")

    db = DatabaseManager()
    session = db.Session()
    try:
        for security_id, symbol, name in DHAN_INDICES:
            assert symbol not in US_ONLY_SYMBOLS, f"{symbol} belongs to sync_us_indices.py, not Dhan"
            print(f"\n{symbol} ({name}) [security_id={security_id}]")
            index_id = upsert_index(session, symbol, name)
            n = sync_prices(session, index_id, security_id, access_token)
            print(f"  Upserted {n} daily price rows")
            if n:
                compute_performance(session, index_id)
                row = session.execute(
                    text("SELECT change_1w, change_1m, change_1y FROM index_performance WHERE index_id = :id"),
                    {'id': index_id}
                ).fetchone()
                if row:
                    print(f"  Perf: 1W={row[0]}%  1M={row[1]}%  1Y={row[2]}%")
            time.sleep(0.5)  # be gentle with Dhan's rate limits
        print("\nDone.")
    finally:
        session.close()


if __name__ == '__main__':
    main()
