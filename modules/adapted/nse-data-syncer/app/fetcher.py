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


from datetime import timedelta

import pandas as pd
import yfinance as yf


def fetch_stock_data(symbol, start_date=None):
    """
    Fetches daily OHLCV data from Yahoo Finance.

    Args:
        symbol (str): The NSE symbol (without suffix).
        start_date (date): The start date for fetching data. If None, fetches max available history.

    Returns:
        pd.DataFrame: DataFrame with Date index and OHLCV columns.
    """
    # Add .NS suffix for NSE
    yf_symbol = f"{symbol}.NS"

    try:
        ticker = yf.Ticker(yf_symbol)

        if start_date:
            # yfinance start is inclusive, but we want data AFTER the last synced date.
            # So if we have a last synced date, we should ask for start = last_synced + 1 day.
            # However, the caller will handle the logic of "next day".
            # Here we strictly respect the passed start_date.
            df = ticker.history(start=start_date, auto_adjust=True)
        else:
            df = ticker.history(period="max", auto_adjust=True)

        if df.empty:
            return pd.DataFrame()

        # Clean up data
        # Keep only OHLCV
        df = df[["Open", "High", "Low", "Close", "Volume"]]

        # Ensure index is datetime date
        df.index = df.index.date
        df.index.name = "Date"

        return df

    except Exception as e:
        print(f"Error fetching data for {yf_symbol}: {e}")
        return pd.DataFrame()


def fetch_batch_data(symbols, start_date=None):
    """
    Fetches daily OHLCV data for multiple symbols in a single request.

    Args:
        symbols (list): List of NSE symbols (without suffix).
        start_date (date): The start date for fetching data.

    Returns:
        dict: Dictionary mapping symbol -> DataFrame.
    """
    if not symbols:
        return {}

    yf_symbols = [f"{s}.NS" for s in symbols]

    try:
        # Fetch data
        # threads=True enables parallel downloads
        # If start_date is None, use period="max"
        kwargs = {"group_by": "ticker", "auto_adjust": True, "threads": True, "progress": False}

        if start_date:
            kwargs["start"] = start_date
        else:
            kwargs["period"] = "max"

        df = yf.download(yf_symbols, **kwargs)

        if df.empty:
            return {}

        result = {}

        # If only one symbol is requested, yfinance might not return MultiIndex
        # But typically with list input it tries to.
        # However, checking columns levels is safer.

        if len(symbols) == 1:
            symbol = symbols[0]
            # If standard dataframe (not MultiIndex columns)
            if isinstance(df.columns, pd.Index) and not isinstance(df.columns, pd.MultiIndex):
                clean_df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                clean_df.index = clean_df.index.date
                clean_df.index.name = "Date"
                result[symbol] = clean_df
                return result

        # Handle MultiIndex DataFrame
        for symbol in symbols:
            yf_sym = f"{symbol}.NS"
            try:
                if yf_sym not in df.columns:
                    continue

                stock_df = df[yf_sym].copy()

                # Check if we have valid data (Close price shouldn't be NaN)
                stock_df = stock_df.dropna(subset=["Close"])

                if stock_df.empty:
                    continue

                # Ensure columns exist
                required_cols = ["Open", "High", "Low", "Close", "Volume"]
                if not all(col in stock_df.columns for col in required_cols):
                    continue

                stock_df = stock_df[required_cols]
                stock_df.index = stock_df.index.date
                stock_df.index.name = "Date"

                result[symbol] = stock_df

            except Exception:
                # print(f"Error processing {symbol}: {e}")
                continue

        return result

    except Exception as e:
        print(f"Error fetching batch data: {e}")
        return {}


def fetch_current_market_caps(symbols):
    """
    Fetches current market cap for a list of symbols.
    Returns: dict {symbol: market_cap}
    """
    if not symbols:
        return {}

    results = {}

    # yfinance Tickers is not very efficient for properties.
    # But accessing .fast_info is fast for individual Ticker.
    # However, creating 2000 Ticker objects might take a moment.
    # Let's try batching or simple iteration.

    print(f"Fetching market caps for {len(symbols)} symbols...")

    # Using Tickers for concurrent info fetching if possible?
    # yfinance doesn't easily support bulk info fetch.
    # We iterate.

    for sym in symbols:
        yf_sym = f"{sym}.NS"
        try:
            # fast_info is much faster than .info
            # It returns an object with keys like 'marketCap'
            ticker = yf.Ticker(yf_sym)
            mcap = ticker.fast_info.market_cap

            if mcap and mcap > 0:
                results[sym] = mcap
        except Exception:
            continue

    return results
