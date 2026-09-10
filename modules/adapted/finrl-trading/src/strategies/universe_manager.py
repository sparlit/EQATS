import datetime
from typing import Optional

try:
    import pytz
except ImportError:
    pytz = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import pandas_market_calendars as mcal
except ImportError:
    mcal = None

try:
    from strategies.strategylogger import StrategyLogger
except ImportError:
    StrategyLogger = None

import random


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    if pytz is None:
        msg = "pytz is required for timezone handling"
        raise ImportError(msg)
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


class UniverseManager:
    """
    UniverseManager (Final Version, Logger-compatible)
    --------------------------------------------------
    * 自动从季度选股生成日度股票池
    * 不关心持仓
    * 只负责 in_universe 的判断
    * 事件日志兼容增强版 StrategyLogger
    """

    def __init__(
        self,
        stock_selection_df,
        col_map,
        trading_calendar,
        logger=None,
        backtest_start=None,
        backtest_end=None,
    ):
        self.logger = logger
        if pd is not None:
            self.trading_calendar = pd.DatetimeIndex(sorted(trading_calendar))
        else:
            self.trading_calendar = sorted(trading_calendar)

        # === save backtest start and end ===
        if pd is not None:
            self.backtest_start = pd.to_datetime(backtest_start) if backtest_start else None
            self.backtest_end = pd.to_datetime(backtest_end) if backtest_end else None
        else:
            self.backtest_start = backtest_start
            self.backtest_end = backtest_end

        # -----------------------------
        # map column names
        # -----------------------------
        df = stock_selection_df.copy()
        df = df.rename(columns={col_map["tic_name"]: "tic_name", col_map["trade_date"]: "trade_date"})
        if pd is not None:
            df["trade_date"] = pd.to_datetime(df["trade_date"])

        # === select backtest period ===
        if self.backtest_start is not None:
            df = df[df["trade_date"] >= self.backtest_start]

        if self.backtest_end is not None:
            df = df[df["trade_date"] <= self.backtest_end]

        # -----------------------------
        # build daily universe_df
        # -----------------------------
        self.universe_df = self._build_universe(df)

        # -----------------------------
        # build fast index
        # -----------------------------
        self.universe_map = self._build_fast_index(self.universe_df)

        # save yesterday's universe, for IN / OUT judgment
        self.prev_universe = set()

        # === log feedback ===
        if self.logger:
            self.logger.log_error(
                f"[UniverseManager] Loaded {len(self.universe_df)} daily rows, "
                f"backtest=[{self.backtest_start} ~ {self.backtest_end}]"
            )

    def _build_universe(self, df):
        """Build daily universe dataframe. To be implemented."""
        return df

    def _build_fast_index(self, universe_df):
        """Build fast lookup index. To be implemented."""
        return {}

    # ======
    # Additional methods would go here
