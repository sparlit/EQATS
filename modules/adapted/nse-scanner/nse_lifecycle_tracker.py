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


"""Persistent lifecycle state for multi-horizon NSE scanner candidates."""


import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

STATE_FILE = Path("scan_lifecycle.json")


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": 1, "stocks": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data.get("stocks"), dict) else {"version": 1, "stocks": {}}
    except (OSError, ValueError, TypeError):
        return {"version": 1, "stocks": {}}


def _save_state(state: dict, scan_date: str) -> None:
    state["last_updated"] = scan_date
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def apply_lifecycle(results_df: pd.DataFrame, scan_date) -> pd.DataFrame:
    """Promote qualifying fresh setups while preserving direct long-horizon ideas."""
    if results_df.empty:
        return results_df

    scan_date = str(scan_date)
    state = _load_state()
    stocks = state["stocks"]

    for _, row in results_df.iterrows():
        symbol = str(row["symbol"]).strip()
        base_horizon = str(row.get("horizon", "WATCH"))
        action = str(row.get("action", "WATCH"))
        record = stocks.get(symbol, {})

        if not record:
            record = {
                "first_seen_date": scan_date,
                "stage_since": scan_date,
                "days_tracked": 0,
                "origin": "LIFECYCLE" if base_horizon == "NEW_1M_SETUP" else "DIRECT",
                "stage": base_horizon,
            }

        record["days_tracked"] = int(record.get("days_tracked", 0)) + 1
        record["last_seen_date"] = scan_date

        if action in ("AVOID", "EXIT_ALERT"):
            stage = "EXIT_ALERT"
        elif record["origin"] == "LIFECYCLE":
            days = record["days_tracked"]
            trend_6m = float(row.get("return_6m", 0)) > 0 and bool(row.get("ma50_above_ma200", False))
            trend_12m = float(row.get("return_12m", 0)) > 0 and trend_6m
            if days >= 120 and trend_12m:
                stage = "CORE_12M"
            elif days >= 60 and trend_6m:
                stage = "CARRY_3_6M"
            elif days >= 15:
                stage = "CARRY_1_3M"
            else:
                stage = "NEW_1M_SETUP"
        else:
            stage = base_horizon

        if record.get("stage") != stage:
            record["stage"] = stage
            record["stage_since"] = scan_date
        stocks[symbol] = record

    # Keep inactive records as an audit trail, but mark them after 30 days away.
    today = datetime.strptime(scan_date, "%Y-%m-%d").date()
    for record in stocks.values():
        try:
            last_seen = datetime.strptime(record.get("last_seen_date", scan_date), "%Y-%m-%d").date()
            if (today - last_seen).days > 30 and record.get("stage") != "EXIT_ALERT":
                record["stage"] = "INACTIVE"
        except ValueError:
            continue

    _save_state(state, scan_date)

    enriched = results_df.copy()
    for idx, row in enriched.iterrows():
        record = stocks[str(row["symbol"]).strip()]
        enriched.at[idx, "horizon"] = record["stage"]
        enriched.at[idx, "lifecycle_origin"] = record["origin"]
        enriched.at[idx, "first_seen_date"] = record["first_seen_date"]
        enriched.at[idx, "stage_since"] = record["stage_since"]
        enriched.at[idx, "days_tracked"] = record["days_tracked"]
    return enriched
