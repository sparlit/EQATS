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


from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_settings() -> dict:
    with open(ROOT / "config" / "settings.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def p(*parts) -> Path:
    return ROOT.joinpath(*parts)


def read_parquet_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        msg = f"Missing required file: {path}"
        raise FileNotFoundError(msg)
    return pd.read_parquet(path)


def write_parquet(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
