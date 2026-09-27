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


from databricks.ai_search.client import AISearchClient

CATALOG = "stock_research"
ENDPOINT_NAME = "stock-research-endpoint"
SOURCE_TABLE = f"{CATALOG}.gold.gold_context_chunks_tbl"
INDEX_NAME = f"{CATALOG}.gold.gold_context_chunks_index"
EMBEDDING_MODEL = "databricks-gte-large-en"


def main():
    client = AISearchClient()

    try:
        client.create_endpoint(name=ENDPOINT_NAME, endpoint_type="STANDARD")
        print(f"Created endpoint {ENDPOINT_NAME}")
    except Exception as e:
        print(f"create_endpoint: {e} (may already exist, continuing)")

    try:
        client.create_delta_sync_index(
            endpoint_name=ENDPOINT_NAME,
            source_table_name=SOURCE_TABLE,
            index_name=INDEX_NAME,
            pipeline_type="TRIGGERED",
            primary_key="chunk_id",
            embedding_source_column="chunk_text",
            embedding_model_endpoint_name=EMBEDDING_MODEL,
        )
        print(f"Created index {INDEX_NAME}. Initial sync may take a few minutes.")
    except Exception as e:
        print(f"create_delta_sync_index: {e}")


if __name__ == "__main__":
    main()
