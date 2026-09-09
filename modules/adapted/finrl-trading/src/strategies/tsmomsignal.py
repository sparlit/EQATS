import datetime
import os
from collections.abc import Iterable
from typing import Dict, Optional

import pandas as pd
import pytz
from strategies.base_signal import BaseSignalEngine
from strategies.strategylogger import StrategyLogger


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    else:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
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


class TSMOMSignalEngine(BaseSignalEngine):
    """
    TS-MOM (Moskowitz et al., 2012)
    --------------------------------
    严格使用“月度价格”计算信号：
        ret_12m = P(t-1m) / P(t-12m) - 1
    信号是月度频率（M），最终会在 BaseSignalEngine 中扩展成 daily。
    """

    def __init__(
        self,
        strategy_name: str = "tsmom",
        col_map: dict | None = None,
        universe_mgr: object | None = None,
        logger: StrategyLogger | None = None,
        chunk_size: int = 200000,
        multi_file: bool = True,
        lookback_months: int = 12,
        neutral_band: float = 0.10,
        signal_start_date: str | None = None,
        signal_end_date: str | None = None,
        data_start_date: str | None = None,
        data_end_date: str | None = None,
    ):
        super().__init__(
            strategy_name=strategy_name,
            col_map=col_map,
            universe_mgr=universe_mgr,
            logger=logger,
            chunk_size=chunk_size,
            multi_file=multi_file,
            signal_start_date=signal_start_date,
            signal_end_date=signal_end_date,
            data_start_date=data_start_date,
            data_end_date=data_end_date,
        )

        self.lookback_months = lookback_months
        self.neutral_band = neutral_band

        if self.data_end_date is None:
            self.data_end_date = self.signal_end_date

        if self.logger:
            self.logger.log_error(
                f"[TSMOM INIT] signal=[{self.signal_start_date} ~ {self.signal_end_date}], "
                f"data=[{self.data_start_date} ~ {self.data_end_date}], "
                f"lookback_months={self.lookback_months}"
            )

    def get_signal_frequency(self) -> str:
        return "M"
