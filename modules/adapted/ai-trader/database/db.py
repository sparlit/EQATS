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


import pandas as pd
from sqlalchemy import create_engine, text
from utils.logger import logger

from config.settings import DB_URL

engine = create_engine(DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)


def get_engine():
    return engine


def get_connection():
    return engine.connect()


def execute_sql(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        conn.commit()
        return result


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params)


def write_df(df: pd.DataFrame, table: str, if_exists: str = "append"):
    df.to_sql(table, engine, if_exists=if_exists, index=False, method="multi")


def upsert_candles(df: pd.DataFrame, table: str = "minute_candles"):
    """Insert candles, ignoring rows that already exist (by timestamp+symbol)."""
    if df.empty:
        return 0
    from sqlalchemy import MetaData, Table
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    meta = MetaData()
    meta.reflect(bind=engine, only=[table])
    tbl = meta.tables[table]
    rows = df.to_dict(orient="records")
    inserted = 0
    with engine.begin() as conn:
        for chunk_start in range(0, len(rows), 500):
            chunk = rows[chunk_start : chunk_start + 500]
            stmt = pg_insert(tbl).values(chunk).on_conflict_do_nothing(index_elements=["timestamp", "symbol"])
            result = conn.execute(stmt)
            inserted += result.rowcount
    return inserted


def init_db():
    """Run the schema.sql to initialize all tables and hypertables."""
    import os

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    with engine.connect() as conn:
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.warning(f"Schema statement skipped: {e}")
        conn.commit()
    logger.info("Database schema initialized.")
