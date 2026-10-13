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


"""DuckDB research layer: SQL over parquet without moving data.

The research database contains only views pointing at parquet files plus
materialized query results. Large datasets stay in parquet.
"""


from pathlib import Path

import duckdb
import pandas as pd


class ResearchDB:
    def __init__(self, db_path: Path | str, data_root: Path | str) -> None:
        self.db_path = Path(db_path)
        self.data_root = Path(data_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._ensure_views()

    def _ensure_views(self) -> None:
        normalized = (self.data_root / "normalized").resolve()
        validated = (self.data_root / "validated").resolve()
        for name, root in (("normalized", normalized), ("validated", validated)):
            if root.exists():
                self._con.execute(
                    f"CREATE VIEW IF NOT EXISTS {name}_bars AS "
                    f"SELECT * FROM read_parquet('{root}/bars_*/**/*.parquet', "
                    f"filename=true, hive_partitioning=false)"
                )
        delivery = validated / "delivery"
        if delivery.exists():
            self._con.execute(
                f"CREATE VIEW IF NOT EXISTS delivery AS "
                f"SELECT * FROM read_parquet('{delivery}/**/*.parquet', filename=true)"
            )
        backtests = normalized / "backtests"
        if backtests.exists():
            self._con.execute(
                f"CREATE VIEW IF NOT EXISTS backtest_fills AS "
                f"SELECT * FROM read_parquet('{backtests}/*/fills.parquet', "
                f"filename=true)"
            )

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self._con.execute(sql, params or []).fetchdf()

    def query_arrow(self, sql: str):
        return self._con.execute(sql).fetch_arrow_table()

    def bar_summary(self, layer: str = "validated") -> pd.DataFrame:
        return self.query(
            f"""
            SELECT instrument_id, timeframe,
                   COUNT(*) AS n_bars,
                   MIN(timestamp) AS first_ts,
                   MAX(timestamp) AS last_ts,
                   MIN(low) AS min_low,
                   MAX(high) AS max_high
            FROM {layer}_bars
            GROUP BY instrument_id, timeframe
            ORDER BY instrument_id
            """
        )

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> ResearchDB:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
