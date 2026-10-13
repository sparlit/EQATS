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


def process_historical_data(data, interval):
    """Process raw historical data into a pandas DataFrame.

    Args:
        data (list): Raw data from the API (list of dicts with time, open, high, low, close, volume).
        interval (str): Data interval to determine if cutoff time should be applied.

    Returns:
        pandas.DataFrame: Processed historical data.
    """
    df = pd.DataFrame(data)

    # Rename columns to standard OHLCV format
    df = df.rename(
        columns={
            "time": "Timestamp",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    # Convert timestamp from milliseconds to datetime
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="ms", utc=True)
    df["Timestamp"] = df["Timestamp"].dt.tz_localize(None)
    df = df[["Timestamp", "Open", "High", "Low", "Close", "Volume"]]

    # Apply cutoff time only for intraday intervals
    intraday_intervals = ["1m", "5m", "10m", "15m", "30m", "1h"]
    if interval in intraday_intervals:
        cutoff_time = pd.Timestamp("15:29:59").time()
        df = df[df["Timestamp"].dt.time <= cutoff_time]

    df.set_index("Timestamp", inplace=True)
    return df
