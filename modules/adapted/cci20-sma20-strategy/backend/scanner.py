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
CCI/SMA Stock Scanner — Centralized Multi-User Edition.

Architecture:
  1. Resolves all unique tickers across:
     - Default system watchlists in watchlists/ directory (e.g. FandO, Nifty50)
     - All user-created watchlists in watchlist_items table
  2. Single-pass fetch: Downloads each unique ticker ONCE via yfinance.
  3. Indicator calculation: CCI(20), SMA(20), 1y/1m/1w Low anchors, and CCI history.
  4. Central cache: Upserts computed metrics into daily_stock_metrics table.
"""

import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from db.models import Base, DailyStockMetric, User, Watchlist, WatchlistItem
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

# ── DB session factory ─────────────────────────────────────────────────────────


def _make_session() -> Session:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL", "")
    if not raw:
        root_dir = os.path.dirname(_here)
        for env_file in [os.path.join(root_dir, ".env"), os.path.join(_here, ".env")]:
            if os.path.isfile(env_file):
                with open(env_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("DATABASE_URL_SYNC="):
                            raw = line.split("=", 1)[1].strip('"').strip("'")
                            break
                        if line.startswith("DATABASE_URL=") and not raw:
                            raw = line.split("=", 1)[1].strip('"').strip("'")

    if not raw:
        raw = "postgresql://neondb_owner:npg_G2UpfBLPQM1C@ep-crimson-night-azfkfjyr-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

    url = raw.replace("+asyncpg", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)  # idempotent — ensures tables exist
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── Ticker / watchlist readers ─────────────────────────────────────────────────


def _read_tickers(watchlist_path: str) -> list[str]:
    """Read tickers from a CSV file robustly."""
    try:
        df = pd.read_csv(watchlist_path)
        df.columns = [c.strip().strip('"').lower() for c in df.columns]
        if "ticker" in df.columns:
            raw = df["ticker"].tolist()
        else:
            df = pd.read_csv(watchlist_path, header=None)
            raw = df[0].tolist()
    except Exception as exc:
        print(f"Error reading watchlist {watchlist_path}: {exc}")
        return []

    tickers: list[str] = []
    for v in raw:
        if not isinstance(v, str):
            continue
        v = v.strip().strip('"')
        if not v or v.lower() == "ticker":
            continue
        if not v.endswith(".NS") and not v.endswith(".BO"):
            v += ".NS"
        tickers.append(v)
    return tickers


def _get_or_create_admin_user(session: Session) -> User:
    admin_sub = os.environ.get("ADMIN_COGNITO_SUB", "scanner-admin")
    user = session.execute(select(User).where(User.cognito_sub == admin_sub)).scalar_one_or_none()
    if not user:
        user = User(cognito_sub=admin_sub, email="scanner@local")
        session.add(user)
        session.flush()
        session.commit()
    return user


def sync_default_watchlists(watchlists_dir: str, session: Session, admin_user: User) -> dict[str, list[str]]:
    """Ensure default system watchlists from CSVs exist in watchlists & watchlist_items tables."""
    default_lists: dict[str, list[str]] = {}
    if not os.path.isdir(watchlists_dir):
        return default_lists

    for filename in sorted(os.listdir(watchlists_dir)):
        if filename.endswith(".csv"):
            name = os.path.splitext(filename)[0]
            file_path = os.path.join(watchlists_dir, filename)
            tickers = _read_tickers(file_path)
            if not tickers:
                continue
            default_lists[name] = tickers

            # Find or create admin watchlist
            wl = session.execute(
                select(Watchlist).where(Watchlist.user_id == admin_user.id, Watchlist.name == name)
            ).scalar_one_or_none()

            if not wl:
                wl = Watchlist(user_id=admin_user.id, name=name, is_public=True)
                session.add(wl)
                session.flush()

            # Ensure all tickers exist in watchlist_items
            existing_items = set(
                session.scalars(select(WatchlistItem.ticker).where(WatchlistItem.watchlist_id == wl.id)).all()
            )

            new_items = [WatchlistItem(watchlist_id=wl.id, ticker=t) for t in tickers if t not in existing_items]
            if new_items:
                session.add_all(new_items)
                session.flush()

    session.commit()
    return default_lists


# ── Centralized Single-Pass Scanner ─────────────────────────────────────────────

_DELISTED = False  # sentinel: download succeeded but returned no data → remove ticker


def scan_single_ticker(ticker_symbol: str):
    """Download OHLCV (~380 calendar days / ~260 trading days) and compute CCI(20) & SMA(20).

    Returns:
        dict   — success
        None   — transient failure (network/timeout); keep ticker
        False  — ticker is delisted / invalid; caller should remove it
    """
    try:
        end_date = datetime.date.today() + datetime.timedelta(days=1)
        start_date = end_date - datetime.timedelta(days=380)

        df = yf.download(ticker_symbol, start=start_date, end=end_date, interval="1d", progress=False, auto_adjust=True)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if df.empty:
            print(f"  DELISTED {ticker_symbol}: empty response")
            return _DELISTED  # remove from watchlist

        if len(df) < 252:
            print(f"  SKIP {ticker_symbol}: rows={len(df)}")
            return None  # keep — new listing or insufficient history

        df["SMA_20"] = df["Close"].rolling(window=20).mean()
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        sma_tp = typical_price.rolling(window=20).mean()
        mean_dev = typical_price.rolling(window=20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        df["CCI_20"] = (typical_price - sma_tp) / (0.015 * mean_dev)

        latest_price = float(df["Close"].iloc[-1])
        cci_20 = float(df["CCI_20"].iloc[-1])
        sma_20 = float(df["SMA_20"].iloc[-1])

        if any(np.isnan(v) for v in [latest_price, cci_20, sma_20]):
            print(f"  NaN  {ticker_symbol}")
            return None

        yearly_low = float(df["Low"].rolling(window=252).min().iloc[-1])
        monthly_low = float(df["Low"].rolling(window=21).min().iloc[-1])
        weekly_low = float(df["Low"].rolling(window=5).min().iloc[-1])

        pct_yearly = ((latest_price - yearly_low) / yearly_low) * 100
        pct_monthly = ((latest_price - monthly_low) / monthly_low) * 100
        pct_weekly = ((latest_price - weekly_low) / weekly_low) * 100

        cci_hist = [round(x, 1) if not np.isnan(x) else 0.0 for x in df["CCI_20"].iloc[-20:].tolist()]

        # Weekly CPR (Central Pivot Range) for swing traders
        # Use previous completed week's High/Low/Close
        try:
            weekly = df.resample("W").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
            if len(weekly) >= 2:
                prev = weekly.iloc[-2]  # previous completed week
                pivot = (prev["High"] + prev["Low"] + prev["Close"]) / 3
                bc = (prev["High"] + prev["Low"]) / 2
                tc = (2 * pivot) - bc
                cpr_width = abs(float(tc) - float(bc)) / float(prev["Close"]) * 100
                narrow_cpr = bool(cpr_width < 0.5)
            else:
                narrow_cpr = False
        except Exception:
            narrow_cpr = False

        return {
            "ticker": ticker_symbol,
            "close": round(latest_price, 4),
            "cci_20": round(cci_20, 4),
            "sma_20": round(sma_20, 4),
            "yearly_low": round(yearly_low, 4),
            "monthly_low": round(monthly_low, 4),
            "weekly_low": round(weekly_low, 4),
            "pct_from_y_low": round(pct_yearly, 4),
            "pct_from_m_low": round(pct_monthly, 4),
            "pct_from_w_low": round(pct_weekly, 4),
            "near_y_low": bool(pct_yearly <= 5.0),
            "near_m_low": bool(pct_monthly <= 5.0),
            "near_w_low": bool(pct_weekly <= 5.0),
            "cci_history": cci_hist,
            "narrow_cpr": narrow_cpr,
        }

    except Exception as exc:
        print(f"  ERROR {ticker_symbol}: {exc}")
        return None  # transient — keep ticker


def run_scanner(watchlists_dir: str, user_id=None):
    session = _make_session()
    admin_user = _get_or_create_admin_user(session)

    # 1. Sync default watchlists from CSVs
    print("Syncing default watchlists from CSVs...")
    sync_default_watchlists(watchlists_dir, session, admin_user)

    # 2. Collect ALL unique tickers across all watchlists in database
    db_tickers = session.scalars(select(WatchlistItem.ticker).distinct()).all()
    all_tickers = sorted(set(db_tickers))

    print("\n=======================================================")
    print(f"  Centralized Scanner Engine — {len(all_tickers)} Unique Tickers")
    print("=======================================================\n")

    today = datetime.date.today()
    saved_count = 0

    removed_count = 0

    for ticker in all_tickers:
        metrics = scan_single_ticker(ticker)

        if metrics is False:
            # Ticker returned empty data → delisted/invalid; purge from all watchlists
            try:
                session.execute(WatchlistItem.__table__.delete().where(WatchlistItem.ticker == ticker))
                session.commit()
                removed_count += 1
                print(f"  REMOVED {ticker} from all watchlists (delisted)")
            except Exception as exc:
                print(f"  DB Error removing {ticker}: {exc}")
                session.rollback()
            continue

        if metrics is None:
            continue

        # Check if record for today already exists
        existing = session.execute(
            select(DailyStockMetric).where(DailyStockMetric.ticker == ticker, DailyStockMetric.scan_date == today)
        ).scalar_one_or_none()

        if existing:
            existing.close = metrics["close"]
            existing.cci_20 = metrics["cci_20"]
            existing.sma_20 = metrics["sma_20"]
            existing.yearly_low = metrics["yearly_low"]
            existing.monthly_low = metrics["monthly_low"]
            existing.weekly_low = metrics["weekly_low"]
            existing.pct_from_y_low = metrics["pct_from_y_low"]
            existing.pct_from_m_low = metrics["pct_from_m_low"]
            existing.pct_from_w_low = metrics["pct_from_w_low"]
            existing.near_y_low = metrics["near_y_low"]
            existing.near_m_low = metrics["near_m_low"]
            existing.near_w_low = metrics["near_w_low"]
            existing.cci_history = metrics["cci_history"]
            existing.narrow_cpr = metrics["narrow_cpr"]
            existing.scanned_at = datetime.datetime.utcnow()
        else:
            rec = DailyStockMetric(
                ticker=metrics["ticker"],
                scan_date=today,
                close=metrics["close"],
                cci_20=metrics["cci_20"],
                sma_20=metrics["sma_20"],
                yearly_low=metrics["yearly_low"],
                monthly_low=metrics["monthly_low"],
                weekly_low=metrics["weekly_low"],
                pct_from_y_low=metrics["pct_from_y_low"],
                pct_from_m_low=metrics["pct_from_m_low"],
                pct_from_w_low=metrics["pct_from_w_low"],
                near_y_low=metrics["near_y_low"],
                near_m_low=metrics["near_m_low"],
                near_w_low=metrics["near_w_low"],
                cci_history=metrics["cci_history"],
                narrow_cpr=metrics["narrow_cpr"],
            )
            session.add(rec)

        saved_count += 1

        # Commit every iteration to return connection to pool.
        # This allows pool_pre_ping to detect dropped Neon DB connections.
        try:
            session.commit()
        except Exception as exc:
            print(f"DB Error for {ticker}: {exc}")
            session.rollback()

    session.close()
    print(f"\n[OK] Centralized scan complete. Saved: {saved_count} tickers. Removed (delisted): {removed_count}.")


# ── CLI entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Centralized Multi-User Stock Scanner")
    parser.add_argument("--watchlists", default=os.path.join(_here, "watchlists"))
    args = parser.parse_args()
    run_scanner(args.watchlists)
