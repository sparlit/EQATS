from __future__ import annotations

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


import logging
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING

import pandas as pd
from fast_csv_loader import csv_loader

if TYPE_CHECKING:
    from pathlib import Path

    from .dtypes import Timeframe

logger = logging.getLogger("MarketDataLoader")

csv_loader = lru_cache(maxsize=10)(csv_loader)


class EODFileLoader:
    """Load OHLC stock data or market breadth indicator data."""

    timeframes: dict[Timeframe, str] = {
        "d": "D",
        "w": "W-SUN",
        "m": "ME",
        "q": "QE",
    }

    def __init__(
        self,
        timeframe: Timeframe,
        data_path: Path,
        breadth_filepath: Path,
        end_date: datetime | None = None,
        period: int = 160,
        index_name: str = "nifty 500",
    ) -> None:
        """Initialize for stock mode.

        Args:
            timeframe: One of 'd', 'w', 'm', 'q'
            data_path: Directory containing {symbol}.csv files
            end_date: Optional end date filter
            period: Number of candles to return (for daily) or multiplier for higher TFs
        """
        # Breadth mode specific
        self.breadth_df: pd.DataFrame | None = None
        self.breadth_filepath = breadth_filepath
        self.index_file = data_path / f"{index_name.lower()}.csv"

        if not self.index_file.exists():
            raise FileNotFoundError(self.index_file)

        self.tf: str = timeframe
        self.offset_str: str = self.timeframes[timeframe]
        self.end_date: datetime | None = end_date
        self.date_format: str = "%Y-%m-%d"
        self.data_path: Path = data_path

        self.default_tf = "d"

        self.ohlc_dict = {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }

        self.chunk_size: int = 1024 * 6

        if timeframe == self.default_tf:
            self.period: int = period
        elif timeframe == "w":
            self.period = 7 * period
            self.chunk_size = 19456
        elif timeframe == "m":
            days = 7 if self.default_tf == "w" else 1
            self.period = 30 * period // days
        elif timeframe == "q":
            self.period = 90 * period

    def load_breadth_indicators(self) -> pd.DataFrame:
        """
        Load all breadth indicators
        """
        if self.breadth_df is not None:
            return self.breadth_df
        # Load data

        index_df = csv_loader(
            self.index_file,
            period=self.period,
            end_date=self.end_date,
            chunk_size=self.chunk_size,
            date_format=self.date_format,
            use_columns=("Date", "Close"),
        )

        ind_df = csv_loader(
            self.breadth_filepath,
            period=self.period,
            end_date=self.end_date,
            chunk_size=self.chunk_size,
            date_format=self.date_format,
            use_columns=(
                "Date",
                "PCT_50",
                "PCT_200",
                "NET_NEW_HIGHS",
                "AD_LINE",
                "MCCLELLAN_OSC",
            ),
        )

        # Merge
        df = pd.merge(index_df, ind_df, on="Date", how="inner")

        # Resample if higher timeframe
        if self.tf != self.default_tf and not df.empty:
            df = df.resample(self.offset_str).last().dropna()

        self.breadth_df = df

        return df

    def load(self, symbol: str) -> pd.DataFrame | None:
        """
        Load data for a single symbol.

        Args:
            symbol: Stock symbol name

        Returns:
            DataFrame with OHLC data, or None if not found
        """
        file = self.data_path / f"{symbol.lower()}.csv"

        if not file.exists():
            # Check for SME
            file = self.data_path / f"{symbol.lower()}_sme.csv"
            if not file.exists():
                logger.warning(f"File not found: {symbol}")
                return None

        if self.tf in ("m", "q"):
            return self._process_monthly(file)

        try:
            df = csv_loader(
                file,
                period=self.period,
                end_date=self.end_date,
                chunk_size=self.chunk_size,
                date_format=self.date_format,
            )
        except IndexError:
            return None
        except Exception as e:
            logger.warning(f"{symbol}: Error loading file - {e!r}")
            return None

        if self.tf == self.default_tf or df.empty:
            return df

        return df.resample(self.offset_str).agg(self.ohlc_dict).dropna()

    def _process_monthly(self, file: Path) -> pd.DataFrame:
        """Load and resample to monthly/quarterly."""
        df = pd.read_csv(
            file,
            index_col=[0],
            parse_dates=[0],
            date_format=self.date_format,
        )
        df = df.loc[: self.end_date].iloc[-self.period :] if self.end_date else df.iloc[-self.period :]

        return df.resample(self.offset_str).agg(self.ohlc_dict).dropna()
