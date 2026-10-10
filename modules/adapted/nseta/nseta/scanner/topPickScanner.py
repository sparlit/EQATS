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


# -*- coding: utf-8 -*-
import pandas as pd
from nseta.common.commons import *
from nseta.common.log import default_logger, tracelog
from nseta.resources.resources import resources
from nseta.scanner.intradayScanner import intradayScanner

__all__ = ["topPickScanner"]


class topPickScanner(intradayScanner):
    def __init__(self, scanner_type, stocks=None, indicator=None, background=False):
        if stocks is None:
            stocks = []
        super().__init__(scanner_type, stocks, "macd", background)
        self._period_1_signals = None

    @property
    def period_1_signals(self):
        return self._period_1_signals

    @tracelog
    def scan(self, option=None, periodicity="1", analyse=False):
        self.clear_cache(True, force_clear=False)
        super().scan(
            option="Confidence" if option is None else option,
            periodicity=periodicity,
            analyse=analyse,
        )

    def scan_background(
        self,
        scannerinstance,
        terminate_after_iter=0,
        wait_time=resources.scanner().background_scan_frequency_intraday,
    ):
        return super().scan_background(
            scannerinstance, terminate_after_iter=terminate_after_iter, wait_time=wait_time
        )

    def load_archived_scan_results(self):
        if self.period_1_signals is not None:
            return None, None
        else:
            return super().load_archived_scan_results()

    @tracelog
    def flush_signals(self, signaldf):
        if self.period_1_signals is None:
            self._period_1_signals = signaldf
            default_logger().debug(f"Period_1_signals:\n{signaldf}\n")
            self.stocks = signaldf.loc[:, "Symbol"].tolist()
            self.scan(self.option, periodicity="2")
            return False
        else:
            default_logger().debug(
                f"Period_1_signals:\n{self.period_1_signals.to_string(index=False)}\n"
            )
            default_logger().debug(f"Period_5_signals:\n{signaldf.to_string(index=False)}\n")
            intersected_rows = []
            intersected_df = None
            for _index, row in signaldf.iterrows():
                symbol_period_5 = row["Symbol"]
                signal_period_5 = row["Signal"]
                df = self.period_1_signals[
                    (self.period_1_signals["Symbol"] == symbol_period_5)
                    & (self.period_1_signals["Signal"] == signal_period_5)
                ]
                # Both period 1 and period 5 are aligned in recommendations
                if df is not None and len(df) > 0:
                    macd12 = df.loc[:, "macd(12)"].iloc[0]
                    macd9 = df.loc[:, "macdsignal(9)"].iloc[0]
                    notify(
                        symbol=symbol_period_5,
                        title="MACD aligned",
                        message=f"{self.scanner_type.name}: MACD aligned {macd12} / {macd9}",
                    )
                    if abs(abs(macd12) - abs(macd9)) <= 0.15:
                        notify(
                            symbol=symbol_period_5,
                            title="MACD alignment HIT",
                            message=f"{self.scanner_type.name}: MACD aligned just now: {macd12} / {macd9}",
                        )
                        df.loc[:, "Confidence"].iloc[0] = 100
                    intersected_rows.append(df)
            if len(intersected_rows) > 0:
                intersected_df = pd.concat(intersected_rows)
            return super().flush_signals(intersected_df)
