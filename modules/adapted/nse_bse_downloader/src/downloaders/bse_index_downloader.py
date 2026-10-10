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


"""BSE index downloader using the shared validated price pipeline."""

from datetime import date

import pandas as pd

from ..core.base_downloader import BaseDownloader
from ..core.config import Config
from ..core.exceptions import DataProcessingError
from ..services.canonical_data import normalize_bse_index, read_report
from ..services.source_resolver import first_available, price_source
from ..utils.memory_optimizer import MemoryOptimizer


class BSEIndexDownloader(BaseDownloader):
    """Download BSE index reports and publish the seven-column contract."""

    #: Declared once in source_resolver so the combined-file builder can apply
    #: the same floor.  Clamping only this downloader's dates, as before, left
    #: every earlier BSE EQ date waiting for an index component that never
    #: existed.  The clamp itself now lives in ``BaseDownloader``, which
    #: applies it to every segment with a known floor rather than to this one.
    FIRST_AVAILABLE_DATE = first_available("BSE", "INDEX")

    def __init__(self, config: Config):
        super().__init__("BSE", "INDEX", config)
        self.memory_optimizer = MemoryOptimizer()

    def build_url(self, target_date: date) -> str:
        return price_source("BSE", "INDEX", target_date).url

    def process_downloaded_data(
        self,
        file_data: bytes,
        file_date: date,
        delivery_data: bytes | None = None,
    ) -> pd.DataFrame | None:
        try:
            result = self.transform_data(read_report(file_data), file_date)
            self.logger.info(f"Processed BSE Index data for {file_date}: {len(result)} rows")
            return result
        except Exception as error:
            raise DataProcessingError(
                f"Error processing BSE Index data for {file_date}: {error}"
            ) from error

    def transform_data(self, df: pd.DataFrame, file_date: date) -> pd.DataFrame:
        try:
            with self.memory_optimizer.memory_monitor("bse_index_transform"):
                result = normalize_bse_index(df, file_date)
                return self.memory_optimizer.optimize_dataframe(result)
        except Exception as error:
            raise DataProcessingError(f"Error transforming BSE Index data: {error}") from error

    async def _download_implementation(self, working_days: list[date]) -> bool:
        return await self._download_price_implementation(working_days)
