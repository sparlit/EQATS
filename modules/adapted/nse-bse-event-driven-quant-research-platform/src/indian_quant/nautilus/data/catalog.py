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


"""Bridge between the platform parquet lake and the Nautilus ParquetDataCatalog."""


from pathlib import Path

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from indian_quant.nautilus.instruments.mapping import (
    bar_type_for,
    identity_to_nautilus_equity,
    market_bar_to_nautilus,
)
from indian_quant.schemas import InstrumentIdentity, MarketBar, Timeframe


class CatalogBridge:
    """Writes canonical instruments/bars into a Nautilus catalog and reads them back."""

    def __init__(self, catalog_path: Path | str) -> None:
        self.catalog_path = Path(catalog_path)
        self.catalog_path.mkdir(parents=True, exist_ok=True)
        self.catalog = ParquetDataCatalog(str(self.catalog_path))

    def write_instrument(self, identity: InstrumentIdentity) -> None:
        self.catalog.write_data([identity_to_nautilus_equity(identity)])

    def write_bars(self, bars: list[MarketBar], identity: InstrumentIdentity) -> str:
        if not bars:
            return ""
        bt = bar_type_for(identity, bars[0].timeframe.value)
        nautilus_bars = [market_bar_to_nautilus(b, bt) for b in bars]
        self.catalog.write_data(nautilus_bars)
        return str(bt)

    def read_bars(self, nautilus_instrument_id: str, timeframe: str = "1d") -> list:

        tf = Timeframe(timeframe)
        agg_name = tf.nautilus_aggregation
        step = int(timeframe.rstrip("m")) if agg_name == "MINUTE" else 1
        bt_str = f"{nautilus_instrument_id.upper()}-{step}-{agg_name}-LAST-EXTERNAL"
        return self.catalog.bars(bar_types=[bt_str])

    def read_instruments(self) -> list:
        return self.catalog.instruments()

    def summary(self) -> pd.DataFrame:
        rows = []
        for inst in self.catalog.instruments():
            rows.append({"instrument_id": str(inst.id), "asset_class": str(type(inst).__name__)})
        return pd.DataFrame(rows)


def sync_validated_to_catalog(
    *,
    validated_dir: Path | str,
    catalog_path: Path | str,
    exchange: str = "NSE",
    symbols: list[str] | None = None,
    timeframe: str = "1d",
) -> dict[str, str]:
    """Push validated canonical bars into the Nautilus catalog.

    Returns mapping of canonical instrument_id -> nautilus bar_type string.
    """
    import pyarrow.parquet as pq

    from indian_quant.schemas import Exchange, InstrumentIdentity, MarketBar, Segment

    validated_dir = Path(validated_dir)
    bridge = CatalogBridge(catalog_path)
    written: dict[str, str] = {}
    pattern_root = validated_dir / f"bars_{timeframe}" / exchange.upper()
    if not pattern_root.exists():
        return written
    for path in sorted(pattern_root.glob("*.parquet")):
        symbol = path.stem
        if symbols and symbol not in symbols:
            continue
        df = pq.read_table(path).to_pandas()
        if df.empty:
            continue
        identity = InstrumentIdentity(
            instrument_id=f"{exchange.upper()}_EQ|{symbol}",
            exchange=Exchange(exchange.upper()),
            segment=Segment.EQ,
            symbol=symbol,
            isin=None,
        )
        bridge.write_instrument(identity)
        bars = [
            MarketBar(
                instrument_id=row.instrument_id,
                exchange=row.exchange,
                timestamp=row.timestamp.to_pydatetime(),
                timeframe=Timeframe(row.timeframe),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                source=str(row.source),
                adjustment_status=row.adjustment_status,
                quality_status=row.quality_status,
            )
            for row in df.itertuples(index=False)
        ]
        bt = bridge.write_bars(bars, identity)
        written[identity.instrument_id] = bt
    return written


__all__ = ["CatalogBridge", "sync_validated_to_catalog"]
