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


import sqlite3
from datetime import date

import pandas as pd


class BacktestStore:
    """Read-only access to the cached price database the backtest runs against."""

    def __init__(self, db_path: str = "backtest_data.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)

    def get_trading_days(self, start: date, end: date) -> list[date]:
        """Every trading day between two dates.

        Taken from the Nifty index, so days the index didn't trade are excluded.
        """
        cur = self._conn.execute(
            "SELECT DISTINCT date FROM bars WHERE ticker='^NSEI' AND date>=? and date<=? ORDER BY date",
            (start.isoformat(), end.isoformat()),
        )
        return [date.fromisoformat(row[0]) for row in cur.fetchall()]

    def get_universe(self) -> list[str]:
        """Every stock ticker in the cache, excluding indices."""
        cur = self._conn.execute("SELECT DISTINCT ticker FROM bars WHERE ticker NOT LIKE '^%' ORDER BY ticker")
        return [row[0] for row in cur.fetchall()]

    def preload(self, warmup_start: date, end: date) -> dict[str, pd.DataFrame]:
        """Load all bars in one query, keyed by ticker.

        The backtest holds these in memory for the whole run — a per-day query
        would be far slower. `warmup_start` should precede the test window so
        indicators have history to work with.
        """
        df = pd.read_sql_query(
            "SELECT ticker, date, open, high, low, close, volume "
            "FROM bars WHERE date>=? AND date<=? ORDER BY ticker, date",
            self._conn,
            params=(warmup_start.isoformat(), end.isoformat()),
        )
        if df.empty:
            return {}
        df["date"] = pd.to_datetime(df["date"])
        df = df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
        )
        result = {}
        for ticker, group in df.groupby("ticker"):
            result[str(ticker)] = group.drop("ticker", axis=1).set_index("date").sort_index()
        return result

    def close(self):
        """Close the underlying connection."""
        self._conn.close()
