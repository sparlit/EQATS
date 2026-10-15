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


import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from fast_csv_loader import csv_loader

ohlc_dct = {
    "Open": "first",
    "High": "max",
    "Low": "min",
    "Close": "last",
    "Volume": "sum",
}


class DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def load_json(fpath: Path):
    return json.loads(fpath.read_text(encoding="utf-8-sig"))


def write_json(fpath: Path, data):
    fpath.write_text(
        json.dumps(data, indent=2, cls=DateEncoder),
        encoding="utf-8",
    )


def get_dataframe(
    fpath: Path,
    period: int,
    tf: Literal["daily", "weekly"] = "daily",
    columns: list[str] | None = None,
    toDate: datetime | None = None,
) -> pd.DataFrame:
    candle_count = period * 5 if tf == "weekly" else period

    df = csv_loader(fpath, candle_count, end_date=toDate, use_columns=columns)

    if tf == "weekly":
        if columns:
            # Guard against non existent keys and remove columns not required.
            dct = {k: ohlc_dct[k] for k in columns if k in ohlc_dct}
        else:
            dct = ohlc_dct

        return df.resample("W", label="left").apply(dct).iloc[-period:]

    return df.iloc[-period:]
