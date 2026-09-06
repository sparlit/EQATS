from __future__ import annotations

import pandas as pd


def validate_dataframe(df: pd.DataFrame, required_columns: list[str]) -> None:
    if df.empty:
        raise ValueError("DataFrame is empty")
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")


def ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: int = 2) -> pd.DataFrame:
    """Return Bollinger Bands values."""
    basis = series.rolling(window=period, min_periods=period).mean()
    deviation = series.rolling(window=period, min_periods=period).std()
    upper = basis + (deviation * std_dev)
    lower = basis - (deviation * std_dev)
    return pd.DataFrame({"bb_middle": basis, "bb_upper": upper, "bb_lower": lower})


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    validate_dataframe(df, ["high", "low", "close"])
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(span=period, adjust=False, min_periods=period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Return MACD line and signal line."""
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate the Average Directional Index."""
    return adx_full(df, period)["adx"]


def adx_full(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Return ADX, DI+, and DI- as a DataFrame with columns adx, di_plus, di_minus."""
    validate_dataframe(df, ["high", "low", "close"])
    up_move = df["high"].diff()
    down_move = df["low"].diff().abs()
    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - df["close"].shift()).abs(), (df["low"] - df["close"].shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr_series = tr.ewm(span=period, adjust=False, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False, min_periods=period).mean() / atr_series)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False, min_periods=period).mean() / atr_series)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx_series = dx.ewm(span=period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"adx": adx_series, "di_plus": plus_di, "di_minus": minus_di})
