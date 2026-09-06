import warnings
import pandas as pd
import yfinance as yf

_OHLCV_FIELDS = frozenset({"Close", "Open", "High", "Low", "Volume", "Adj Close"})


def safe_yf_download(ticker, period: str | None = None, interval: str = "1d", **kwargs) -> pd.DataFrame:
    """Download prices from yfinance with its warnings and progress bar silenced.

    Always uses adjusted prices. Accepts one ticker or a list.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        kw: dict = dict(interval=interval, progress=False, auto_adjust=True, **kwargs)
        if period is not None:
            kw["period"] = period
        return yf.download(ticker, **kw)


def extract_ticker_df(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """
    Extract a single ticker's DataFrame from a yfinance download.
    - Batch (ticker, field) MultiIndex: extracts the ticker's slice; None if ticker missing
    - Single-ticker (field, ticker) MultiIndex: flattens to plain column names
    - Flat DataFrame: returns as-is
    """
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw

    level0 = set(raw.columns.get_level_values(0))

    if ticker in level0:
        # Batch download — ticker is at level 0
        df = raw[ticker].copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df

    if level0 & _OHLCV_FIELDS:
        # Field names are at level 0 — new yfinance batch format (fields at 0, tickers at 1)
        # OR a single-ticker download with the same layout.
        level1 = set(raw.columns.get_level_values(1))
        if ticker in level1:
            return raw.xs(ticker, level=1, axis=1).copy()
        return None

    # Ticker not present in this batch download
    return None
