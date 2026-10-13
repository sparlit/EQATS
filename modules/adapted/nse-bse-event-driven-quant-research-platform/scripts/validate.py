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


"""Run the quality suite over normalized bars -> validated layer + report.

Applies corporate-action back-adjustment (splits/bonuses by ex-date) when an
actions dataset exists for the symbol.

Usage:
    python scripts/validate.py --symbol RELIANCE
    python scripts/validate.py --symbol RELIANCE --no-adjust
"""


import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import pyarrow.parquet as pq
from indian_quant.config import load_settings
from indian_quant.instruments import default_calendar
from indian_quant.normalization import apply_corporate_action_adjustment
from indian_quant.quality import run_quality_suite
from indian_quant.schemas import CorporateAction, CorporateActionType, MarketBar, Timeframe
from indian_quant.storage import MetadataStore, ParquetStore


def load_bars(df: pd.DataFrame) -> list[MarketBar]:
    return [
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


def load_actions(store: ParquetStore, symbol: str) -> list[CorporateAction]:
    try:
        df = store.read_frame(
            layer="normalized", dataset="corporate_actions", exchange="NSE", name=symbol
        )
    except FileNotFoundError:
        return []
    actions: list[CorporateAction] = []
    for row in df.to_dict("records"):
        for field in ("announcement_date", "record_date", "ex_date", "effective_date"):
            value = row.get(field)
            row[field] = (
                value.date()
                if isinstance(value, datetime)
                else (
                    date.fromisoformat(str(value))
                    if value and not isinstance(value, date)
                    else value
                )
            )
        actions.append(
            CorporateAction(
                instrument_id=row["instrument_id"],
                isin=row.get("isin"),
                action_type=CorporateActionType(row["action_type"]),
                announcement_date=row.get("announcement_date"),
                record_date=row.get("record_date"),
                ex_date=row.get("ex_date"),
                effective_date=row.get("effective_date"),
                ratio=row.get("ratio"),
                old_value=row.get("old_value"),
                new_value=row.get("new_value"),
                amount=row.get("amount"),
                source=str(row.get("source") or "NSE"),
                source_id=row.get("source_id"),
                document_url=row.get("document_url"),
            )
        )
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate normalized bars")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--no-adjust", action="store_true", help="skip corporate-action adjustment")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    symbol = args.symbol.upper()
    store = ParquetStore(settings.data_root, settings.storage.parquet_compression)
    df = store.read_bars(
        layer="normalized", exchange=args.exchange, symbol=symbol, timeframe=args.timeframe
    )
    bars = load_bars(df)

    adjusted_note = "unadjusted"
    actions = [] if args.no_adjust else load_actions(store, symbol)
    if not args.no_adjust:
        applicable = [
            a
            for a in actions
            if a.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS)
        ]
        if applicable:
            bars = apply_corporate_action_adjustment(bars, applicable)
            adjusted_note = f"adjusted by {len(applicable)} split/bonus action(s)"
        elif actions:
            adjusted_note = f"{len(actions)} action(s) on record, none price-affecting"

    report, unique = run_quality_suite(
        bars,
        dataset=f"{args.exchange}:{symbol}",
        calendar=default_calendar(),
        actions=actions or None,
        max_gap_days=settings.quality.max_gap_days,
    )
    metadata = MetadataStore(settings.storage.metadata_dsn)
    metadata.record_quality_report(dataset=report.dataset, report=report.to_dict())

    out_dir = settings.validated_dir / f"bars_{args.timeframe}" / args.exchange.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = pd.DataFrame([b.model_dump() for b in unique])
    pq.write_table(
        store._conform(payload),
        out_dir / f"{symbol}.parquet",
        compression=settings.storage.parquet_compression,
    )

    summary = {
        "dataset": report.dataset,
        "n_rows": report.n_rows,
        "n_errors": report.n_errors,
        "n_warnings": report.n_warnings,
        "adjustment": adjusted_note,
        "issues": [f"{i.severity}:{i.code}" for i in report.issues[:10]],
    }
    print(json.dumps(summary, indent=2))
    print(f"validated {len(unique)} rows -> {out_dir / (symbol + '.parquet')}")
    metadata.close()
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
