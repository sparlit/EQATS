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


"""Ingest NSE data: raw store -> normalized parquet.

Bars come from the NSE archives CDN (UDiFF bhavcopy), which unlike the
quote APIs is not bot-blocked. Corporate actions and announcements come
through the nse-bse-mcp server when it is running.

Usage:
    python scripts/ingest.py --symbol RELIANCE --from 2025-01-01 --to 2026-08-20
    python scripts/ingest.py --symbol RELIANCE ... --source mcp      # chart API
    python scripts/ingest.py --symbol RELIANCE ... --no-events       # skip actions/announcements
"""


import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.ingestion import BhavcopyIngester, NseBseMcpClient, NseIngestionService
from indian_quant.instruments import default_calendar
from indian_quant.normalization import deduplicate_bars
from indian_quant.schemas import MarketBar, Timeframe
from indian_quant.storage import MetadataStore, ParquetStore, RawStore


def fetch_events(service: NseIngestionService | None, symbol: str, from_d: date, to_d: date):
    if service is None:
        return [], []
    try:
        actions = service.corporate_actions(symbol, from_d, to_d)
        announcements = service.corporate_announcements(symbol, from_d, to_d)
        return actions, announcements
    except Exception as exc:
        print(f"  events unavailable ({str(exc)[:120]}); continuing with bars only")
        return [], []


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest NSE data")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--source", choices=["bhavcopy", "mcp"], default="bhavcopy")
    parser.add_argument("--no-events", action="store_true", help="skip corporate actions/announcements")
    args = parser.parse_args()

    settings = load_settings(args.config)
    symbol = args.symbol.upper()
    from_d = date.fromisoformat(args.from_date)
    to_d = date.fromisoformat(args.to_date)

    raw = RawStore(settings.data_root / "raw")
    metadata = MetadataStore(settings.storage.metadata_dsn)
    store = ParquetStore(settings.data_root, settings.storage.parquet_compression)

    print(f"ingesting {symbol} bars [{args.from_date} .. {args.to_date}] via {args.source}")
    if args.source == "bhavcopy":
        ingester = BhavcopyIngester(raw)
        calendar = default_calendar()
        skipped = {"holidays": 0}

        def _is_trading(d: date) -> bool:
            if not calendar.is_trading_day(d):
                skipped["holidays"] += 1
                return False
            return True

        original_fetch = ingester.fetch_cm_zip

        def fetch_if_trading(day: date):
            if not _is_trading(day):
                return None, "calendar:holiday"
            return original_fetch(day)

        ingester.fetch_cm_zip = fetch_if_trading  # type: ignore[method-assign]
        bars = ingester.ingest_range(from_d, to_d, symbols={symbol})
        print(f"calendar skipped {skipped['holidays']} non-trading days")
    else:
        client = NseBseMcpClient(
            settings.mcp.base_url,
            timeout=settings.mcp.timeout_seconds,
            max_retries=settings.mcp.max_retries,
        )
        service = NseIngestionService(client, raw, metadata)
        bars = service.equity_historical(symbol, from_d, to_d)

    if not bars:
        print("no bars returned; check connectivity/date range")
        return 1

    try:
        existing = store.read_bars(layer="normalized", exchange="NSE", symbol=symbol)
        prev = [
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
            )
            for row in existing.itertuples(index=False)
        ]
        print(f"merging with {len(prev)} previously ingested bars")
    except FileNotFoundError:
        prev = []

    unique = deduplicate_bars(bars + prev)
    paths = store.write_bars(unique, layer="normalized")
    print(f"{len(unique)} bars -> {paths[0].parent}")

    if not args.no_events:
        mcp_url_ok = True
        try:
            client = NseBseMcpClient(
                settings.mcp.base_url,
                timeout=settings.mcp.timeout_seconds,
                max_retries=settings.mcp.max_retries,
            )
            client.initialize()
        except Exception:
            mcp_url_ok = False
        service = (
            NseIngestionService(
                NseBseMcpClient(settings.mcp.base_url, timeout=settings.mcp.timeout_seconds),
                raw,
                metadata,
            )
            if mcp_url_ok
            else None
        )
        actions, announcements = fetch_events(service, symbol, from_d - timedelta(days=30), to_d)
        if actions:
            df = pd.DataFrame([a.model_dump() for a in actions]).sort_values("ex_date")
            store.write_frame(df, layer="normalized", dataset="corporate_actions", exchange="NSE", name=symbol)
            print(f"{len(actions)} corporate actions -> normalized/corporate_actions/NSE/{symbol}.parquet")
        else:
            print("0 corporate actions")
        if announcements:
            adf = pd.DataFrame(
                [
                    {
                        "announcement_id": a.announcement_id,
                        "instrument_id": a.instrument_id,
                        "published_at": a.published_at,
                        "category": a.category,
                        "headline": a.headline,
                        "document_url": a.document_url,
                    }
                    for a in announcements
                ]
            ).sort_values("published_at")
            store.write_frame(adf, layer="normalized", dataset="announcements", exchange="NSE", name=symbol)
            print(f"{len(announcements)} announcements -> normalized/announcements/NSE/{symbol}.parquet")

    metadata.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
