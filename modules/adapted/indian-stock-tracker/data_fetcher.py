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


import datetime
import io

import pandas as pd

# Default list of symbols to track
# Each entry is a tuple: (symbol, type)
# Nifty 50 equities fetched from NSE
import requests
from data_sources import DEFAULT_SOURCES, fetch_with_fallback, resolve_name
from models import Asset, DailyPrice, get_session
from sqlalchemy.orm import Session


def get_nifty50_symbols():
    """
    Fetch Nifty 50 symbols from NSE India.
    Returns a list of symbols (without .NS suffix).
    """
    print("Fetching Nifty 50 symbols from NSE...")
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        nse_symbols = df["Symbol"].tolist()
        print(f"Successfully fetched {len(nse_symbols)} Nifty 50 symbols.")
        return nse_symbols
    except Exception as e:
        print(f"Failed to download Nifty 50 list from NSE: {e}")
        # Fallback: try to use NSESource if available
        try:
            from data_sources import NSESource

            # Note: NSESource.fetch_latest does not give us the list of symbols.
            # This is just to show we tried; we'll return empty list.
            print("NSESource available but cannot fetch constituent list; returning empty.")
            return []
        except ImportError:
            print("NSESource not available either.")
            return []


def is_trading_day(date: datetime.date) -> bool:
    """Check if a date is a weekday (Monday-Friday) - trading days only."""
    # Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
    return date.weekday() < 5


def get_default_symbols():
    """
    Get the complete list of default symbols to track.
    Returns Nifty 50 equities only (mutual funds tracked separately in mutual_funds.db).
    """
    # Get Nifty 50 symbols
    nifty50_symbols = get_nifty50_symbols()

    # Create equity symbols from Nifty 50 (append .NS suffix for yfinance)
    return [(f"{symbol}.NS", "equity") for symbol in nifty50_symbols]


# Get the default symbols
DEFAULT_SYMBOLS = get_default_symbols()


# Helper to ensure an asset record exists
def _resolve_sector(symbol: str, asset_type: str) -> str:
    """
    Resolve a sector for a symbol using the STOCK_SECTOR_MAP in index_data.

    The map keys are bare NSE tickers (e.g. ``RELIANCE``); assets in the DB
    are stored with ``.NS`` / ``.BO`` suffixes, so we strip those before
    looking up. Returns ``"Other"`` when no match is found.
    """
    if asset_type != "equity":
        return ""
    try:
        from index_data import STOCK_SECTOR_MAP

        bare = symbol.replace(".NS", "").replace(".BO", "")
        return STOCK_SECTOR_MAP.get(bare, "Other")
    except Exception:
        return "Other"


def get_or_create_asset(
    session: Session,
    symbol: str,
    name: str | None = None,
    exchange: str | None = None,
    sector: str | None = None,
    asset_type: str = "equity",
):
    asset = session.query(Asset).filter_by(symbol=symbol).first()
    # Backfill sector on existing rows that were created before sector was populated
    if asset and asset_type == "equity" and (not asset.sector or asset.sector.strip() == "" or asset.sector == "None"):
        asset.sector = _resolve_sector(symbol, asset_type)
        session.commit()
    if not asset:
        resolved_sector = sector or _resolve_sector(symbol, asset_type)
        asset = Asset(
            symbol=symbol, name=name or symbol, exchange=exchange or "NSE", sector=resolved_sector, type=asset_type
        )
        session.add(asset)
        session.commit()
    return asset


def backfill_asset_sectors():
    """
    One-shot helper: populate ``Asset.sector`` for all equity rows whose
    sector is empty. Safe to call multiple times — only updates empty rows.
    """
    session = get_session()
    try:
        assets = session.query(Asset).filter(Asset.type == "equity").all()
        updated = 0
        for asset in assets:
            if not asset.sector or asset.sector.strip() == "" or asset.sector == "None":
                asset.sector = _resolve_sector(asset.symbol, "equity")
                updated += 1
        if updated:
            session.commit()
        print(f"Backfilled sector for {updated} equity assets.")
    finally:
        session.close()


def fetch_and_store(symbols, sources=None):
    """
        Fetch daily price data for given symbols and store in SQLite DB.
    Symbols should be tuples: (symbol, type).
    For equities we store recent price history (last 60 days) for charting
    and analysis purposes.
    """
    session = get_session()
    for sym, sym_type in symbols:
        # Determine source list - only equities are tracked via DEFAULT_SOURCES
        srcs = DEFAULT_SOURCES
        try:
            # For equities, fetch and store recent historical price data (last 60 days)
            # Use YFinanceSource directly to get history, as it's most reliable for historical data
            from data_sources import YFinanceSource

            yf_source = YFinanceSource()
            history_records = yf_source.fetch_history(sym, limit=60)
            # If we couldn't get history with the original symbol, try without suffix
            if not history_records and (sym.endswith((".NS", ".BO"))):
                base_symbol = sym.replace(".NS", "").replace(".BO", "")
                history_records = yf_source.fetch_history(base_symbol, limit=60)

            if not history_records:
                print(f"No historical data for {sym} from any source")
                # Fallback to storing just the latest price for backward compatibility
                ohlcv = fetch_with_fallback(sym, srcs)
                if ohlcv is None:
                    print(f"No data for {sym} from any source")
                    continue

                date = ohlcv.date
                name = resolve_name(sym, srcs)
                asset = get_or_create_asset(session, sym, name=name, asset_type=sym_type)

                # Check if price for this date already exists
                exists = session.query(DailyPrice).filter_by(asset_id=asset.id, date=date).first()
                if exists:
                    continue

                price = DailyPrice(
                    asset_id=asset.id,
                    date=date,
                    open=ohlcv.open,
                    high=ohlcv.high,
                    low=ohlcv.low,
                    close=ohlcv.close,
                    adj_close=ohlcv.adj_close,
                    volume=ohlcv.volume,
                    is_holiday=False,
                )
                session.add(price)
                session.commit()
                print(f"Stored latest price data for {sym} on {date} (fallback)")
            else:
                # Store all historical price records
                name = resolve_name(sym, srcs)
                asset = get_or_create_asset(session, sym, name=name, asset_type=sym_type)
                stored = 0
                for ohlcv_record in history_records:
                    exists = session.query(DailyPrice).filter_by(asset_id=asset.id, date=ohlcv_record.date).first()
                    if exists:
                        continue
                    price = DailyPrice(
                        asset_id=asset.id,
                        date=ohlcv_record.date,
                        open=ohlcv_record.open,
                        high=ohlcv_record.high,
                        low=ohlcv_record.low,
                        close=ohlcv_record.close,
                        adj_close=ohlcv_record.adj_close,
                        volume=ohlcv_record.volume,
                        is_holiday=False,
                    )
                    session.add(price)
                    stored += 1
                session.commit()
                if stored:
                    print(f"Stored {stored} historical price records for {sym}")
        except Exception as e:
            print(f"Error fetching {sym}: {e}")
        session.close()


def detect_and_store_holidays(symbols, days_back=60):
    """
    Detect weekdays with no trading data (holidays) and insert placeholder rows.

    For each weekday in the last ``days_back`` days where no price data exists
    for ANY tracked stock, a placeholder DailyPrice row with ``is_holiday=True``
    is inserted for every tracked stock. This keeps the date range continuous
    so the UI calendar and API queries can distinguish real trading days from
    holidays/weekends.
    """
    session = get_session()
    try:
        today = datetime.date.today()
        cutoff = today - datetime.timedelta(days=days_back)

        # Gather all weekday dates in the range
        total_days = (today - cutoff).days + 1
        weekday_dates = [
            cutoff + datetime.timedelta(days=i)
            for i in range(total_days)
            if is_trading_day(cutoff + datetime.timedelta(days=i))
        ]

        # Find which weekday dates already have data for any stock
        existing_dates = {
            d
            for (d,) in session.query(DailyPrice.date)
            .filter(DailyPrice.date >= cutoff, DailyPrice.date <= today)
            .distinct()
            .all()
        }

        missing_trading_days = [d for d in weekday_dates if d not in existing_dates]
        if not missing_trading_days:
            print("No missing trading days detected — holidays already populated.")
            return

        # Insert holiday placeholders for all tracked stocks
        for sym, sym_type in symbols:
            asset = session.query(Asset).filter_by(symbol=sym).first()
            if asset is None:
                asset = get_or_create_asset(session, sym, asset_type=sym_type)
            existing = (
                session.query(DailyPrice)
                .filter_by(asset_id=asset.id)
                .filter(DailyPrice.date.in_(missing_trading_days))
                .all()
            )
            existing_dates_for_asset = {p.date for p in existing}
            for d in missing_trading_days:
                if d in existing_dates_for_asset:
                    continue
                session.add(
                    DailyPrice(
                        asset_id=asset.id,
                        date=d,
                        open=None,
                        high=None,
                        low=None,
                        close=None,
                        adj_close=None,
                        volume=0.0,
                        is_holiday=True,
                    )
                )
        session.commit()
        print(f"Inserted holiday placeholders for {len(missing_trading_days)} missing trading days.")
    finally:
        session.close()


if __name__ == "__main__":
    fetch_and_store(DEFAULT_SYMBOLS)
