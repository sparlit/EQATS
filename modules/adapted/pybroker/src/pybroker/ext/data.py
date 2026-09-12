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


r"""Contains extension classes."""

"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""

from datetime import datetime
from typing import Optional

import pandas as pd
import requests
from pybroker.common import DataCol, to_datetime
from pybroker.data import DataSource

_CANONICAL_COLUMNS = (
    DataCol.DATE.value,
    DataCol.SYMBOL.value,
    DataCol.OPEN.value,
    DataCol.HIGH.value,
    DataCol.LOW.value,
    DataCol.CLOSE.value,
    DataCol.VOLUME.value,
)

_AKSHARE_COLUMN_MAP = {
    "日期": DataCol.DATE.value,
    "开盘": DataCol.OPEN.value,
    "收盘": DataCol.CLOSE.value,
    "最高": DataCol.HIGH.value,
    "最低": DataCol.LOW.value,
    "成交量": DataCol.VOLUME.value,
    "date": DataCol.DATE.value,
    "open": DataCol.OPEN.value,
    "close": DataCol.CLOSE.value,
    "high": DataCol.HIGH.value,
    "low": DataCol.LOW.value,
}


def _to_tx_symbol(symbol: str) -> str:
    bare, _, exchange = symbol.partition(".")
    if exchange == "SH" or bare.startswith("6"):
        return f"sh{bare}"
    return f"sz{bare}"


def _fetch_akshare_symbol(
    symbol: str,
    simple_symbol: str,
    start_date_str: str,
    end_date_str: str,
    period: str,
    adjust: str,
) -> pd.DataFrame:
    try:
        import akshare
    except ImportError as exc:
        msg = "AKShare requires akshare. Install with: python -m pip install 'akshare>=1.17.50'"
        raise ImportError(msg) from exc

    try:
        return akshare.stock_zh_a_hist(
            symbol=simple_symbol,
            start_date=start_date_str,
            end_date=end_date_str,
            period=period,
            adjust=adjust,
        )
    except (ConnectionError, KeyError, requests.RequestException):
        if period != "daily":
            raise
        return akshare.stock_zh_a_hist_tx(
            symbol=_to_tx_symbol(symbol),
            start_date=start_date_str,
            end_date=end_date_str,
            adjust=adjust,
        )


class AKShare(DataSource):
    r"""Retrieves data from `AKShare <https://akshare.akfamily.xyz/>`_."""

    _tf_to_period = {
        "": "daily",
        "1day": "daily",
        "1week": "weekly",
    }

    def _fetch_data(
        self,
        symbols: frozenset[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str | None,
        adjust: str | None,
    ) -> pd.DataFrame:
        """:meta private:"""
        start_date_str = to_datetime(start_date).strftime("%Y%m%d")
        end_date_str = to_datetime(end_date).strftime("%Y%m%d")
        symbols_list = list(symbols)
        symbols_simple = [item.split(".")[0] for item in symbols_list]
        formatted_tf = self._format_timeframe(timeframe)
        if formatted_tf not in AKShare._tf_to_period:
            # Raised rather than silently returning zero bars, matching
            # YQuery: an hourly backtest against a daily-only source is a
            # misconfiguration, not an empty market.
            msg = (
                f"Unsupported timeframe: '{formatted_tf}'.\nSupported timeframes: {list(AKShare._tf_to_period.keys())}."
            )
            raise ValueError(msg)
        period = AKShare._tf_to_period[formatted_tf]
        frames = []
        for i in range(len(symbols_list)):
            temp_df = _fetch_akshare_symbol(
                symbol=symbols_list[i],
                simple_symbol=symbols_simple[i],
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                period=period,
                adjust=adjust if adjust is not None else "",
            )
            if temp_df.columns.empty:
                continue
            # Renamed per frame, not on the concatenated union: the EM
            # endpoint returns Chinese column names while the TX fallback
            # returns English ones, and renaming the union maps 日期 and
            # ``date`` onto one label -- duplicate columns that raise
            # "cannot assemble with duplicate keys" whenever the two schemas
            # mix across symbols in a single query. Renaming each frame also
            # keeps a legitimately empty response in the canonical schema
            # instead of leaking un-renamed columns to the caller.
            rename_map = _AKSHARE_COLUMN_MAP
            if DataCol.VOLUME.value not in temp_df.columns:
                # stock_zh_a_hist_tx pre-1.18.74 reported volume under
                # "amount". Since then it returns its own "volume" column and
                # "amount" is a distinct RMB turnover figure, so only remap
                # the legacy alias when a real volume column isn't already
                # present.
                rename_map = dict(_AKSHARE_COLUMN_MAP)
                rename_map["amount"] = DataCol.VOLUME.value
            temp_df = temp_df.rename(columns=rename_map)
            temp_df[DataCol.SYMBOL.value] = symbols_list[i]
            frames.append(temp_df)
        if not frames:
            return pd.DataFrame(columns=_CANONICAL_COLUMNS)
        result = pd.concat(frames, ignore_index=True)
        result[DataCol.DATE.value] = pd.to_datetime(result[DataCol.DATE.value])
        return result[list(_CANONICAL_COLUMNS)]


class YQuery(DataSource):
    r"""Retrieves data from Yahoo Finance using
    `Yahooquery <https://github.com/dpguthrie/yahooquery>`_\ ."""

    _tf_to_period = {
        "": "1d",
        "1hour": "1h",
        "1day": "1d",
        "5day": "5d",
        "1week": "1wk",
    }

    def __init__(self, proxies: dict | None = None):
        super().__init__()
        self.proxies = proxies

    def _fetch_data(
        self,
        symbols: frozenset[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str | None,
        adjust: bool | None,
    ) -> pd.DataFrame:
        """:meta private:"""
        try:
            from yahooquery import Ticker
        except ImportError as exc:
            msg = (
                "YQuery requires yahooquery in the same Python environment as "
                "your notebook kernel. Install with: "
                "python -m pip install 'yahooquery>=2.3.7'"
            )
            raise ImportError(msg) from exc

        show_yf_progress_bar = not self._logger._disabled and not self._logger._progress_bar_disabled
        ticker = Ticker(
            symbols,
            asynchronous=True,
            progress=show_yf_progress_bar,
            proxies=self.proxies,
        )
        timeframe = self._format_timeframe(timeframe)
        if timeframe not in self._tf_to_period:
            msg = f"Unsupported timeframe: '{timeframe}'.\nSupported timeframes: {list(self._tf_to_period.keys())}."
            raise ValueError(msg)
        df = ticker.history(
            start=start_date,
            end=end_date,
            interval=self._tf_to_period[timeframe],
            adj_ohlc=adjust,
        )
        if not isinstance(df, pd.DataFrame):
            # yahooquery returns a dict of per-symbol error strings when
            # every request fails; reaching for .columns on it raised a bare
            # AttributeError naming nothing.
            msg = f"yahooquery returned no data: {df!r}"
            raise ValueError(msg)
        if df.columns.empty or df.empty:
            # Returned in the canonical schema: an empty frame that keeps
            # symbol and date as MultiIndex levels fails the required-column
            # check downstream.
            return pd.DataFrame(columns=_CANONICAL_COLUMNS)
        df = df.reset_index()
        df[DataCol.DATE.value] = pd.to_datetime(df[DataCol.DATE.value])
        return df[
            [
                DataCol.SYMBOL.value,
                DataCol.DATE.value,
                DataCol.OPEN.value,
                DataCol.HIGH.value,
                DataCol.LOW.value,
                DataCol.CLOSE.value,
                DataCol.VOLUME.value,
            ]
        ]
