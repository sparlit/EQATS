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


import numpy as np
import pandas as pd


def simple_moving_average(source: pd.Series, length: int) -> pd.Series:
    return source.rolling(length).mean()


def exponential_moving_average(source: pd.Series, length: int) -> pd.Series:
    return source.ewm(span=length, adjust=False).mean()


def wilders_moving_average(source: pd.Series, length: int) -> pd.Series:
    """
    Wilder's moving average using an SMA seed.

    The first output appears at position length - 1.
    """
    if length <= 0:
        msg = "length must be greater than zero"
        raise ValueError(msg)

    values = source.to_numpy(dtype=np.float64, copy=False)
    result = np.full(len(values), np.nan, dtype=np.float64)

    if len(values) < length:
        return pd.Series(result, index=source.index, name=source.name)

    initial_window = values[:length]

    if np.isnan(initial_window).any():
        msg = f"The first {length} source values must not contain NaN values"
        raise ValueError(msg)

    # Wilder's initial seed is an SMA.
    result[length - 1] = initial_window.mean()

    alpha = 1.0 / length

    for i in range(length, len(values)):
        if np.isnan(values[i]):
            result[i] = np.nan
        elif np.isnan(result[i - 1]):
            # Data gaps require a new seed; this implementation does not
            # silently bridge them.
            result[i] = np.nan
        else:
            result[i] = result[i - 1] + alpha * (values[i] - result[i - 1])

    return pd.Series(result, index=source.index, name=source.name)


def average_true_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
) -> pd.Series:
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return wilders_moving_average(tr, length)


def relative_strength_index(source: pd.Series, length: int = 14) -> pd.Series:
    delta = source.diff()

    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = wilders_moving_average(gain, length)
    avg_loss = wilders_moving_average(loss, length)

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def macd(
    source: pd.Series,
    fastlen: int = 12,
    slowlen: int = 26,
    siglen: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate the Moving Average Convergence Divergence (MACD).

    Parameters
    ----------
    source : pd.Series
        Input price series.
    fastlen : int, default 12
        Fast EMA period.
    slowlen : int, default 26
        Slow EMA period.
    siglen : int, default 9
        Signal EMA period.

    Returns
    -------
    tuple[pd.Series, pd.Series, pd.Series]
        (macd_line, signal_line, histogram)
    """
    fast_ma = exponential_moving_average(source, fastlen)
    slow_ma = exponential_moving_average(source, slowlen)
    macd_line = fast_ma - slow_ma
    signal_line = exponential_moving_average(macd_line, siglen)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def bollinger_bands(
    source: pd.Series,
    length: int = 20,
    mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    basis = simple_moving_average(source, length)
    dev = mult * source.rolling(length).std(ddof=0)

    upper = basis + dev
    lower = basis - dev

    return basis, upper, lower


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    factor: float = 3.0,
    atr_length: int = 10,
) -> tuple[pd.Series, pd.Series]:
    """
    Calculate the Supertrend indicator.

    Direction:
        1  = upward trend
        -1 = downward trend
    """
    if atr_length <= 0:
        msg = "atr_length must be greater than zero"
        raise ValueError(msg)

    if factor <= 0:
        msg = "factor must be greater than zero"
        raise ValueError(msg)

    index = close.index

    high_values = high.to_numpy(dtype=np.float64, copy=False)
    low_values = low.to_numpy(dtype=np.float64, copy=False)
    close_values = close.to_numpy(dtype=np.float64, copy=False)

    size = len(close_values)

    supertrend_values = np.full(size, np.nan, dtype=np.float64)
    direction_values = np.full(size, np.nan, dtype=np.float64)

    if size == 0:
        return (
            pd.Series(supertrend_values, index=index, name="supertrend"),
            pd.Series(direction_values, index=index, name="direction"),
        )

    # Calculate true range without constructing a temporary DataFrame.
    previous_close = np.empty(size, dtype=np.float64)
    previous_close[0] = np.nan
    previous_close[1:] = close_values[:-1]

    true_range = np.fmax.reduce(
        (
            high_values - low_values,
            np.abs(high_values - previous_close),
            np.abs(low_values - previous_close),
        )
    )

    atr_values = pd.Series(true_range, index=index).ewm(alpha=1.0 / atr_length, adjust=False).mean().to_numpy()

    midpoint = (high_values + low_values) * 0.5
    basic_upper = midpoint + factor * atr_values
    basic_lower = midpoint - factor * atr_values

    previous_final_upper = basic_upper[0]
    previous_final_lower = basic_lower[0]

    for i in range(1, size):
        if np.isnan(atr_values[i]):
            previous_final_upper = basic_upper[i]
            previous_final_lower = basic_lower[i]
            continue

        if basic_upper[i] < previous_final_upper or close_values[i - 1] > previous_final_upper:
            final_upper = basic_upper[i]
        else:
            final_upper = previous_final_upper

        if basic_lower[i] > previous_final_lower or close_values[i - 1] < previous_final_lower:
            final_lower = basic_lower[i]
        else:
            final_lower = previous_final_lower

        previous_direction = direction_values[i - 1]

        if np.isnan(previous_direction) or previous_direction == -1:
            if close_values[i] <= final_upper:
                supertrend_values[i] = final_upper
                direction_values[i] = -1
            else:
                supertrend_values[i] = final_lower
                direction_values[i] = 1
        elif close_values[i] >= final_lower:
            supertrend_values[i] = final_lower
            direction_values[i] = 1
        else:
            supertrend_values[i] = final_upper
            direction_values[i] = -1

        previous_final_upper = final_upper
        previous_final_lower = final_lower

    return (
        pd.Series(supertrend_values, index=index, name="supertrend"),
        pd.Series(direction_values, index=index, name="direction"),
    )
