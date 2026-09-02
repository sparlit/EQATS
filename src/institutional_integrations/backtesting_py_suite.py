"""
Backtesting.py Suite (EQATS Institutional Adaptation)
Adapted from kernc/backtesting.py (lib.py, backtesting.py)

Provides:
- Signal Utilities: crossover, cross, barssince
- Multi-Timeframe Helper: resample_apply
- SignalStrategy Engine: Vectorized & bar-by-bar signal-based trade manager
- TrailingStrategy Engine: Dynamic trailing stop-loss manager (ATR / percentage)
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union
import numpy as np
try:
    import pandas as pd
except ImportError:
    pd = None

def crossover(series1: Union[Sequence[float], Any], series2: Union[Sequence[float], Any]) -> bool:
    """Return True if series1 just crossed above series2 at the last element."""
    s1 = np.asarray(series1)
    s2 = np.asarray(series2)
    if len(s1) < 2 or len(s2) < 2:
        return False
    return bool(s1[-2] <= s2[-2] and s1[-1] > s2[-1])

def cross(series1: Union[Sequence[float], Any], series2: Union[Sequence[float], Any]) -> bool:
    """Return True if series1 and series2 crossed each other (above or below) at the last element."""
    return crossover(series1, series2) or crossover(series2, series1)

def barssince(condition: Union[Sequence[bool], Any], default: int=999999) -> int:
    """Return the number of bars since `condition` was last True."""
    cond = np.asarray(condition)
    if not np.any(cond):
        return default
    true_indices = np.where(cond)[0]
    return int(len(cond) - 1 - true_indices[-1])


def resample_apply(rule: str,
                   func: Callable[..., Any],
                   series_or_df: Any,
                   *args: Any,
                   **kwargs: Any) -> Any:
    """Resample OHLCV data to higher timeframe, apply function, and reindex back to original timeline without lookahead bias."""
    if not isinstance(series_or_df.index, (pd.DatetimeIndex, pd.PeriodIndex)):
        raise ValueError('Series/DataFrame must have a DatetimeIndex or PeriodIndex for resampling.')
    resampled = series_or_df.resample(rule).last()
    applied = func(resampled, *args, **kwargs)
    if isinstance(applied, (pd.Series, pd.DataFrame)):
        aligned = applied.reindex(series_or_df.index, method='ffill')
        return aligned
    return applied

@dataclass
class BacktestTradeSignal:
    direction: str
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    reason: str = ''

class SignalStrategy:
    """Signal-driven strategy engine converting entry/exit signals into actionable trade decisions."""

    def __init__(self, entry_signal_threshold: float=0.5) -> None:
        self.threshold = entry_signal_threshold

    def evaluate_signal(self, current_price: float, signal_value: float, atr: float=0.0) -> BacktestTradeSignal:
        """Evaluates a raw numerical signal value (+1.0 = Buy, -1.0 = Sell, 0.0 = Hold/Close)."""
        if signal_value >= self.threshold:
            stop = current_price - 2.0 * atr if atr > 0 else None
            tp = current_price + 4.0 * atr if atr > 0 else None
            return BacktestTradeSignal('BUY', current_price, stop_loss=stop, take_profit=tp, reason='Signal above threshold')
        elif signal_value <= -self.threshold:
            stop = current_price + 2.0 * atr if atr > 0 else None
            tp = current_price - 4.0 * atr if atr > 0 else None
            return BacktestTradeSignal('SELL', current_price, stop_loss=stop, take_profit=tp, reason='Signal below negative threshold')
        elif signal_value == 0.0:
            return BacktestTradeSignal('CLOSE', current_price, reason='Exit signal received')
        return BacktestTradeSignal('HOLD', current_price, reason='Signal neutral')

class TrailingStrategy:
    """Dynamic Trailing Stop-Loss Strategy Engine."""

    def __init__(self, n_atr: float=2.0, pct_trail: Optional[float]=None) -> None:
        self.n_atr = n_atr
        self.pct_trail = pct_trail

    def update_trailing_stop(self, position_type: str, current_price: float, extreme_price: float, current_sl: Optional[float], atr: float=0.0) -> float:
        """Calculates and updates trailing stop-loss level."""
        if position_type.upper() == 'BUY':
            if self.pct_trail is not None and self.pct_trail > 0:
                trail_sl = extreme_price * (1.0 - self.pct_trail)
            elif atr > 0:
                trail_sl = extreme_price - self.n_atr * atr
            else:
                trail_sl = current_price * 0.98
            if current_sl is None:
                return trail_sl
            return max(current_sl, trail_sl)
        elif position_type.upper() == 'SELL':
            if self.pct_trail is not None and self.pct_trail > 0:
                trail_sl = extreme_price * (1.0 + self.pct_trail)
            elif atr > 0:
                trail_sl = extreme_price + self.n_atr * atr
            else:
                trail_sl = current_price * 1.02
            if current_sl is None:
                return trail_sl
            return min(current_sl, trail_sl)
        return current_sl if current_sl is not None else current_price
