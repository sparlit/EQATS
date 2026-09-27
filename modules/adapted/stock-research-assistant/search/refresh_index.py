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


from databricks import sql as dbsql
from databricks.ai_search.client import AISearchClient
from databricks.sdk import WorkspaceClient
from databricks.sdk.credentials_provider import runtime_native_auth

WAREHOUSE_ID = "377d26238d1c7b33"
CATALOG = "stock_research"
ENDPOINT_NAME = "stock-research-endpoint"
INDEX_NAME = f"{CATALOG}.gold.gold_context_chunks_index"


def refresh_snapshot_table():
    client = WorkspaceClient()
    conn = dbsql.connect(
        server_hostname=client.config.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: runtime_native_auth(client.config),
    )
    with conn, conn.cursor() as cur:
        cur.execute(
            f"CREATE OR REPLACE TABLE {CATALOG}.gold.gold_context_chunks_tbl "
            f"AS SELECT * FROM {CATALOG}.gold.gold_context_chunks"
        )
        # CREATE OR REPLACE drops and recreates the table, which resets table
        # properties -- CDF needs to be re-enabled every refresh for the
        # Delta Sync Index to pick up changes.
        cur.execute(
            f"ALTER TABLE {CATALOG}.gold.gold_context_chunks_tbl SET TBLPROPERTIES (delta.enableChangeDataFeed = true)"
        )
    print("Refreshed gold_context_chunks_tbl and re-enabled CDF")


def sync_index():
    client = AISearchClient()
    index = client.get_index(endpoint_name=ENDPOINT_NAME, index_name=INDEX_NAME)
    index.sync()
    print("Triggered index sync")


def main():
    refresh_snapshot_table()
    sync_index()


if __name__ == "__main__":
    main()
