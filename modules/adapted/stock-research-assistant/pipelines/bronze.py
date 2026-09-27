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
Bronze layer: Auto Loader ingestion, no business logic.
"""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

CATALOG = spark.conf.get("catalog")
LANDING_SCHEMA = spark.conf.get("landing_schema", "landing")
LANDING_VOLUME = spark.conf.get("landing_volume", "raw_landing")
LANDING = f"/Volumes/{CATALOG}/{LANDING_SCHEMA}/{LANDING_VOLUME}"

# companies/fundamentals: one JSON object per file.
# prices/news: one JSON array per file -- multiLine lets Spark explode the
# array into one row per element instead of one row per file.
SOURCES = ["companies", "prices", "fundamentals", "news"]

for source in SOURCES:

    @dp.table(
        name=f"{CATALOG}.bronze.raw_{source}",
        comment=f"Raw {source} landed from ingestion, Auto Loader over the landing volume.",
    )
    def _ingest_source(source=source):
        return (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .option("cloudFiles.schemaLocation", f"{LANDING}/_schemas/{source}")
            .option("cloudFiles.inferColumnTypes", "true")
            .option("multiLine", "true")
            .load(f"{LANDING}/{source}")
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_file", F.col("_metadata.file_path"))
        )
