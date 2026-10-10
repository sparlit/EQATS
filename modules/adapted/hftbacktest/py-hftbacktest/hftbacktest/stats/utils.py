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


import warnings

import polars as pl

SECONDS_PER_DAY = 24 * 60 * 60


def get_num_samples_per_day(timestamp: pl.Series) -> float:
    interval = timestamp.diff()
    if (interval[1:-1] != interval[2:]).sum() > 0:
        warnings.warn(
            "The sampling interval is not consistent. Use resample().", UserWarning, stacklevel=2
        )
    sampling_interval = (timestamp[1] - timestamp[0]).total_seconds()
    return SECONDS_PER_DAY / sampling_interval


def get_total_days(timestamp: pl.Series) -> float:
    return (timestamp[-1] - timestamp[0]).total_seconds() / SECONDS_PER_DAY


def monthly(df: pl.DataFrame) -> list[pl.DataFrame]:
    return df.with_columns(pl.col("timestamp").dt.strftime("%Y%m").alias("dt")).partition_by("dt")


def daily(df: pl.DataFrame) -> list[pl.DataFrame]:
    return df.with_columns(pl.col("timestamp").dt.strftime("%Y%m%d").alias("dt")).partition_by("dt")


def hourly(df: pl.DataFrame) -> list[pl.DataFrame]:
    return df.with_columns(pl.col("timestamp").dt.strftime("%Y%m%d:%H").alias("dt")).partition_by(
        "dt"
    )


def resample(df: pl.DataFrame, frequency: str) -> pl.DataFrame:
    agg_cols = []
    for col in df.columns:
        if col == "timestamp":
            continue
        elif col == "trading_value_" or col == "trading_volume_" or col == "num_trades_":
            agg_cols.append(pl.col(col).sum())
        else:
            agg_cols.append(pl.col(col).last())
    return df.group_by_dynamic("timestamp", every=frequency).agg(*agg_cols)
