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
Gold layer: BI-ready aggregates and unified context chunks for AI Search.
"""
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = spark.conf.get("catalog")


@dp.materialized_view(
    name=f"{CATALOG}.gold.gold_price_daily_agg",
    comment="Daily price snapshot per ticker with day-over-day % change and notable-move flag (>3% absolute move).",
)
def gold_price_daily_agg():
    prices = spark.read.table(f"{CATALOG}.silver.price_snapshots")
    window = Window.partitionBy("ticker").orderBy("date")

    return (
        prices.withColumn("prev_close", F.lag("close").over(window))
        .withColumn(
            "daily_change_pct",
            F.when(
                F.col("prev_close").isNotNull() & (F.col("prev_close") != 0),
                F.round((F.col("close") - F.col("prev_close")) / F.col("prev_close") * 100, 2),
            ),
        )
        .withColumn(
            "is_notable_move",
            F.when(F.abs(F.col("daily_change_pct")) > 3.0, F.lit(True)).otherwise(F.lit(False)),
        )
        .select(
            "ticker",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "prev_close",
            "daily_change_pct",
            "is_notable_move",
        )
    )


@dp.materialized_view(
    name=f"{CATALOG}.gold.gold_context_chunks",
    comment="Unified text chunks (company profiles + news) for AI Search semantic retrieval.",
    table_properties={"delta.enableChangeDataFeed": "true"},
)
def gold_context_chunks():
    companies = spark.read.table(f"{CATALOG}.silver.companies")
    news = spark.read.table(f"{CATALOG}.silver.news_articles")

    company_chunks = companies.select(
        F.col("ticker").alias("chunk_id"),
        F.lit("company_profile").alias("content_type"),
        F.col("ticker"),
        F.col("company_name").alias("title"),
        F.concat_ws(
            " | ",
            F.col("company_name"),
            F.concat(F.lit("Sector: "), F.col("sector")),
            F.col("profile"),
            F.concat(F.lit("Market cap: "), F.col("market_cap").cast("string")),
            F.concat(F.lit("Trailing P/E: "), F.col("trailing_pe").cast("string")),
        ).alias("chunk_text"),
        F.lit("seed_watchlist").alias("source"),
        F.current_timestamp().alias("chunk_created_at"),
        F.concat(
            F.lit("https://www.nseindia.com/get-quotes/equity?symbol="),
            F.regexp_replace(F.col("ticker"), r"\.NS$", ""),
        ).alias("source_uri"),
    )

    news_chunks = news.select(
        F.col("article_id").alias("chunk_id"),
        F.lit("news").alias("content_type"),
        F.lit(None).cast("string").alias("ticker"),
        F.col("title"),
        F.concat_ws(" | ", F.col("title"), F.col("summary")).alias("chunk_text"),
        F.col("source"),
        F.col("_ingested_at").alias("chunk_created_at"),
        F.col("link").alias("source_uri"),
    )

    return company_chunks.unionByName(news_chunks)
