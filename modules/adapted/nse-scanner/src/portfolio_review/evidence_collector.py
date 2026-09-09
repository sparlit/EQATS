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


"""Build review evidence from files already produced by the NSE scanner.

This module deliberately performs no web scraping and no LLM calls. Missing data is
reported explicitly so downstream models cannot treat absence as a positive signal.
"""


import json
from datetime import date
from pathlib import Path
from typing import Any

TECHNICAL_FIELDS = (
    "close",
    "score",
    "streak",
    "sl",
    "t1",
    "t2",
    "rsi",
    "daily_hull_status",
    "weekly_hull_status",
    "kama_rising",
    "hull_distance_atr",
    "return_1m_pct",
    "return_3m_pct",
    "acc_days",
    "dist_days",
    "obv_dir",
    "del_trend",
    "sector",
)


def _read_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _scanner_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stocks = payload.get("stocks", [])
    if isinstance(stocks, dict):
        stocks = list(stocks.values())
    if not isinstance(stocks, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        symbol = str(stock.get("symbol", "")).strip().upper()
        if symbol:
            result[symbol] = stock
    return result


def collect_evidence(
    queue_item: dict[str, Any],
    scanner_path: str | Path = "telegram_last_scan.json",
) -> dict[str, Any]:
    symbol = str(queue_item.get("symbol", "")).strip().upper()
    position = queue_item.get("position", {})
    if not isinstance(position, dict):
        position = {}

    scanner_payload = _read_json(scanner_path)
    scanner_stock = _scanner_index(scanner_payload).get(symbol, {})
    technical = {key: scanner_stock[key] for key in TECHNICAL_FIELDS if key in scanner_stock}

    limitations: list[str] = []
    if not scanner_stock:
        limitations.append("Current scanner snapshot was not available for this symbol")
    if not technical:
        limitations.append("No verified technical fields were available")

    # V1 does not infer financial quality from technical strength.
    limitations.extend(
        [
            "Quarterly financial statements were not supplied",
            "Promoter holding and pledge were not verified",
            "Management quality and valuation were not verified",
        ]
    )

    return {
        "symbol": symbol,
        "evidence_date": date.today().isoformat(),
        "evidence_status": "TECHNICAL_ONLY" if technical else "FAILED",
        "position": position,
        "technical": technical,
        "fundamentals": {},
        "management": {},
        "verified_sources": [str(scanner_path)] if scanner_stock else [],
        "data_limitations": limitations,
    }
