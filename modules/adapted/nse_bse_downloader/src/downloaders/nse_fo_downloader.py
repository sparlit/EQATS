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


"""NSE futures downloader using one date-aware schema pipeline."""

from datetime import date

import pandas as pd

from ..core.base_downloader import BaseDownloader
from ..core.config import Config
from ..core.exceptions import DataProcessingError
from ..services.canonical_data import normalize_nse_fo, public_fo, read_report
from ..services.source_resolver import price_source
from ..utils.memory_optimizer import MemoryOptimizer


class NSEFODownloader(BaseDownloader):
    """Download legacy/current NSE futures while retaining OI fields."""

    def __init__(self, config: Config):
        super().__init__("NSE", "FO", config)
        self.memory_optimizer = MemoryOptimizer()

    def build_url(self, target_date: date) -> str:
        return price_source("NSE", "FO", target_date).url

    def process_downloaded_data(
        self,
        file_data: bytes,
        file_date: date,
        delivery_data: bytes | None = None,
    ) -> pd.DataFrame | None:
        try:
            result = self.transform_data(read_report(file_data), file_date)
            self.logger.info(f"Processed NSE FO data for {file_date}: {len(result)} rows")
            return result
        except Exception as error:
            raise DataProcessingError(
                f"Error processing NSE FO data for {file_date}: {error}"
            ) from error

    def _extract_date_from_filename(self, filename: str) -> str | None:
        marker = "BhavCopy_NSE_FO_0_0_0_"
        if marker not in filename:
            return None
        start = filename.find(marker) + len(marker)
        value = filename[start : start + 8]
        return value if len(value) == 8 and value.isdigit() else None

    @staticmethod
    def int_to_roman(num: int) -> str:
        values = (
            (1000, "M"),
            (900, "CM"),
            (500, "D"),
            (400, "CD"),
            (100, "C"),
            (90, "XC"),
            (50, "L"),
            (40, "XL"),
            (10, "X"),
            (9, "IX"),
            (5, "V"),
            (4, "IV"),
            (1, "I"),
        )
        output = []
        for value, symbol in values:
            count, num = divmod(num, value)
            output.append(symbol * count)
        return "".join(output)

    def transform_data(self, df: pd.DataFrame, file_date: date) -> pd.DataFrame:
        try:
            with self.memory_optimizer.memory_monitor("nse_fo_transform"):
                source = price_source("NSE", "FO", file_date)
                normalized = normalize_nse_fo(df, file_date, era=source.era)
                result = public_fo(
                    normalized,
                    include_open_interest=self.get_download_option(
                        "include_fo_open_interest", True
                    ),
                )
                return self.memory_optimizer.optimize_dataframe(result)
        except Exception as error:
            raise DataProcessingError(f"Error transforming NSE FO data: {error}") from error

    async def _download_implementation(self, working_days: list[date]) -> bool:
        return await self._download_price_implementation(working_days)
