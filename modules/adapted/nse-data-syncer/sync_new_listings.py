"""Discover and backfill brand-new NSE mainboard equity listings from Dhan,
and keep incrementally syncing them until the regular pipeline catches up.

The regular mainboard sync (app/main.py) sources its universe from
manually-refreshed CSVs (EQUITY_LIST_*.csv / ind_niftytotalmarket_list.csv),
which can lag behind very recent IPOs by days-to-weeks until someone
downloads a fresh list. This script closes that gap in two phases:

1. Discovery: diffs Dhan's live instrument master against the stocks
   already tracked in the DB, and for any genuinely new mainboard equity
   share it finds, backfills full OHLCV history from Dhan and computes
   performance metrics.
2. Catch-up: stocks discovered by phase 1 on a *previous* run stop being
   "new" (they're already in the stocks table), but if they're still
   absent from both CSVs, app/main.py's CSV-driven sync never picks them
   up either - they'd otherwise be stuck forever at their listing-day
   snapshot. This phase finds exactly that set (in `stocks`, still not in
   the CSVs) and incrementally re-syncs each one from its last synced
   date, so they keep getting fresh prices daily until someone refreshes
   the CSVs and the main pipeline takes over.

Both phases reuse the same DatabaseManager methods app/main.py itself uses
(insert_stock, insert_batch_daily_prices, update_performance_metrics), so
rows are shaped identically to the rest of the pipeline.

Phase 1 is scoped deliberately to *recent* listings only (first available
Dhan bar within RECENCY_WINDOW_DAYS) so it never silently sweeps in old,
thinly-traded stocks that the curated equity-list CSVs may have
intentionally excluded from momentum/VCP/swing-score universes. Phase 2
only ever touches stocks phase 1 (or the regular pipeline) already
decided were in scope, so it needs no separate recency check.

Requires DHAN_CLIENT_ID, DHAN_PIN and DHAN_TOTP_SECRET in web/.env - same
Dhan account already used by sync_dhan_indices.py / sync_sme_stocks.py.
"""
import sys, os, time
import pandas as pd
import pyotp
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, 'web', '.env'))
sys.path.append(base_dir)
from app.database import DatabaseManager
from app.utils import get_nse_symbols, load_full_equity_list
from app.helpers import get_data_path
from app.constants import CSV_FILENAME, FULL_EQUITY_LIST_FILENAME

DHAN_CLIENT_ID = os.getenv('DHAN_CLIENT_ID')
DHAN_PIN = os.getenv('DHAN_PIN')
DHAN_TOTP_SECRET = os.getenv('DHAN_TOTP_SECRET')
DHAN_TOKEN_URL = 'https://auth.dhan.co/app/generateAccessToken'
DHAN_HISTORICAL_URL = 'https://api.dhan.co/v2/charts/historical'
DHAN_SCRIP_MASTER_URL = 'https://images.dhan.co/api-data/api-scrip-master-detailed.csv'

HISTORY_START = '2010-01-01'
RECENCY_WINDOW_DAYS = 400  # only treat as a "new listing" if first Dhan bar is this recent


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


def load_mainboard_universe() -> pd.DataFrame:
    """Download Dhan's instrument master and filter to NSE mainboard equity shares.
    Returns columns: security_id, symbol, name, isin."""
    df = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
    eq = df[
        (df['EXCH_ID'] == 'NSE')
        & (df['SEGMENT'] == 'E')
        & (df['SERIES'] == 'EQ')
        & (df['INSTRUMENT_TYPE'] == 'ES')  # excludes ETFs/other instruments also tagged SERIES=EQ
    ].copy()
    eq = eq.rename(columns={
        'SECURITY_ID': 'security_id',
        'UNDERLYING_SYMBOL': 'symbol',
        'SYMBOL_NAME': 'name',
        'ISIN': 'isin',
    })[['security_id', 'symbol', 'name', 'isin']]
    eq = eq.dropna(subset=['symbol']).drop_duplicates(subset='symbol')
    return eq.reset_index(drop=True)


def _is_invalid_token(resp: requests.Response) -> bool:
    """DH-906 means the access token itself was rejected - distinct from a
    symbol just having no data. Once this hits, every remaining request in
    the run is guaranteed to fail the same way (see sync_dhan_indices.py's
    docstring on token collisions), so callers abort instead of grinding
    through hundreds more doomed requests and exiting 0 anyway."""
    try:
        return resp.json().get('errorCode') == 'DH-906'
    except ValueError:
        return False


def fetch_dhan_history(security_id: int, from_date: str, to_date: str, access_token: str, retries: int = 3) -> pd.DataFrame:
    """Returns a DataFrame with a 'Date'-named DatetimeIndex and Open/High/Low/Close/Volume
    columns - the exact shape DatabaseManager.insert_batch_daily_prices() expects."""
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
                raise RuntimeError(
                    "Dhan access token invalid/expired mid-run (DH-906) - aborting "
                    "instead of silently failing every remaining request."
                )
            return pd.DataFrame()
        data = resp.json()
        if not data.get('timestamp'):
            return pd.DataFrame()

        df = pd.DataFrame({
            'Date': pd.to_datetime(data['timestamp'], unit='s', utc=True).tz_convert('Asia/Kolkata').date,
            'Open': data.get('open'),
            'High': data.get('high'),
            'Low': data.get('low'),
            'Close': data.get('close'),
            'Volume': data.get('volume'),
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.drop_duplicates(subset='Date', keep='last').set_index('Date').sort_index()
        return df

    print("    Giving up after repeated rate-limit errors")
    return pd.DataFrame()


def find_new_symbols(universe: pd.DataFrame, db: DatabaseManager) -> pd.DataFrame:
    """Diff Dhan's mainboard universe against tracked stocks by ISIN, falling back to symbol."""
    session = db.Session()
    try:
        rows = session.execute(text("SELECT isin, nse_symbol FROM stocks")).fetchall()
    finally:
        session.close()
    known_isins = {r[0] for r in rows if r[0]}
    known_symbols = {r[1] for r in rows if r[1]}

    missing = universe[
        (~universe['isin'].isin(known_isins)) & (~universe['symbol'].isin(known_symbols))
    ]
    return missing.reset_index(drop=True)


def load_covered_symbols() -> set:
    """Symbols app/main.py's regular daily sync already covers (Nifty Total
    Market + the full equity list) - matches its own symbol-sourcing exactly
    (app/main.py:59-68, `--source default` and `--source remaining`)."""
    csv_symbols = set(get_nse_symbols(str(get_data_path(CSV_FILENAME))))
    full_list = load_full_equity_list(str(get_data_path(FULL_EQUITY_LIST_FILENAME)))
    return csv_symbols | set(full_list.keys())


def find_orphaned_tracked_symbols(universe: pd.DataFrame, covered: set, db: DatabaseManager) -> pd.DataFrame:
    """Stocks this script discovered (or that otherwise ended up in `stocks`)
    on a previous run, but that still aren't in either CSV app/main.py reads
    from - so its daily sync will never touch them. Without this, such a
    stock is stuck forever at its listing-day snapshot after phase 1 backfills
    it once. Matched against Dhan's universe by ISIN/symbol to get a
    security_id for the incremental fetch."""
    session = db.Session()
    try:
        rows = session.execute(text("""
            SELECT s.id, s.nse_symbol, s.isin, MAX(dp.date) AS last_date
            FROM stocks s
            LEFT JOIN daily_prices dp ON dp.stock_id = s.id
            WHERE s.is_active = true
            GROUP BY s.id, s.nse_symbol, s.isin
        """)).fetchall()
    finally:
        session.close()

    orphaned_ids = {r.id: r for r in rows if r.nse_symbol not in covered}
    if not orphaned_ids:
        return pd.DataFrame(columns=['security_id', 'symbol', 'name', 'isin', 'stock_id', 'last_date'])

    by_isin = {r.isin: sid for sid, r in orphaned_ids.items() if r.isin}
    by_symbol = {r.nse_symbol: sid for sid, r in orphaned_ids.items() if r.nse_symbol}

    matched = []
    for u in universe.itertuples(index=False):
        sid = by_isin.get(u.isin) or by_symbol.get(u.symbol)
        if sid is not None:
            matched.append({
                'security_id': u.security_id, 'symbol': u.symbol, 'name': u.name, 'isin': u.isin,
                'stock_id': sid, 'last_date': orphaned_ids[sid].last_date,
            })
    return pd.DataFrame(matched)


def sync_incremental(db: DatabaseManager, stock_id: int, symbol: str, security_id: int,
                      last_date, access_token: str) -> int:
    from_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d') if last_date else HISTORY_START
    to_date = datetime.now().strftime('%Y-%m-%d')
    if last_date and from_date > to_date:
        return 0

    df = fetch_dhan_history(int(security_id), from_date, to_date, access_token)
    time.sleep(0.5)  # be gentle with Dhan's rate limits
    if df.empty:
        return 0

    db.insert_batch_daily_prices({symbol: stock_id}, {symbol: df})
    db.update_performance_metrics(stock_id)
    return len(df)


def main():
    if not DHAN_CLIENT_ID or not DHAN_PIN or not DHAN_TOTP_SECRET:
        print("DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not set in web/.env")
        sys.exit(1)

    print("=== Syncing new/orphaned NSE mainboard listings from Dhan ===")
    universe = load_mainboard_universe()
    print(f"Dhan mainboard universe: {len(universe)} equity shares")

    db = DatabaseManager()
    covered = load_covered_symbols()
    missing = find_new_symbols(universe, db)
    orphaned = find_orphaned_tracked_symbols(universe, covered, db)
    print(f"Found {len(missing)} untracked symbol(s), {len(orphaned)} previously-discovered "
          f"symbol(s) still awaiting CSV catch-up")

    if missing.empty and orphaned.empty:
        print("Nothing to sync.")
        return

    access_token = _read_shared_token()
    if access_token:
        print("Using shared Dhan access token (minted once for this job)")
    else:
        access_token = generate_access_token()
        print("Generated fresh Dhan access token via TOTP")

    # -- Phase 1: discover brand-new listings, full backfill --
    to_date = datetime.now().strftime('%Y-%m-%d')
    recency_cutoff = datetime.now() - timedelta(days=RECENCY_WINDOW_DAYS)

    added = 0
    for row in missing.itertuples(index=False):
        df = fetch_dhan_history(int(row.security_id), HISTORY_START, to_date, access_token)
        time.sleep(0.5)  # be gentle with Dhan's rate limits

        if df.empty:
            continue

        first_date = df.index.min()
        if first_date < recency_cutoff:
            # Untracked, but not a recent listing - out of scope for this script
            continue

        stock_id = db.insert_stock(row.symbol, {'name': row.name, 'isin': row.isin})
        if not stock_id:
            continue

        db.insert_batch_daily_prices({row.symbol: stock_id}, {row.symbol: df})
        db.update_performance_metrics(stock_id)
        added += 1
        print(f"  + {row.symbol} ({row.name}) - listed {first_date.date()}, {len(df)} rows")

    # -- Phase 2: catch up previously-discovered stocks still missing from the CSVs --
    caught_up = 0
    for row in orphaned.itertuples(index=False):
        n = sync_incremental(db, row.stock_id, row.symbol, row.security_id, row.last_date, access_token)
        if n:
            caught_up += 1
            print(f"  ~ {row.symbol}: +{n} rows (catch-up)")

    print(f"\nDone. Added {added} newly-listed mainboard stock(s), "
          f"caught up {caught_up} previously-orphaned stock(s).")


if __name__ == '__main__':
    main()
