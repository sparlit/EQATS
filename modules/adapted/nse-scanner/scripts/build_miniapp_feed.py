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


#!/usr/bin/env python3
"""Build a public-safe, plain-language feed for the Telegram Mini App."""

import csv
import json
from datetime import UTC, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str, default):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def terminal_symbols() -> set[str]:
    path = ROOT / "corporate_data/normalized/security_lifecycle_events.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row.get("symbol", "").strip().upper()
            for row in csv.DictReader(handle)
            if row.get("terminal", "").strip().lower() in {"1", "true", "yes"}
        }


def etf_symbols() -> set[str]:
    """Return ETF symbols from durable metadata plus unambiguous NSE tickers.

    Generated reports can outlive a scanner-rule change.  The public feed must
    therefore enforce the same ETF boundary independently instead of waiting
    for the next scanner run to overwrite its artifacts.
    """
    symbols: set[str] = set()
    path = ROOT / "corporate_data/normalized/symbol_master.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                name = str(row.get("company_name") or "").upper()
                if "ETF" in name or "EXCHANGE TRADED FUND" in name:
                    symbols.add(str(row.get("symbol") or "").upper())
    # NSE ETF codes are usually explicit, but a few current products use a
    # provider/index abbreviation rather than the ETF suffix.
    explicit_prefixes = ("HDFCNIF", "HDFCPVT", "MOSMALL", "MOMENTUM")
    for source in (
        ROOT / "output/penny_microcap/daily.json",
        ROOT / "output/pine_hull_daily_run.json",
        ROOT / "output/v2_daily_run.json",
        ROOT / "output/old_nse_hull_daily.json",
    ):
        data = read_json(str(source.relative_to(ROOT)), {})
        for symbol in report_symbols(data):
            if symbol.endswith(("ETF", "BEES")) or symbol.startswith(explicit_prefixes):
                symbols.add(symbol)
    return symbols


def report_symbols(value) -> set[str]:
    """Extract symbol fields from a scanner report without string parsing."""
    if isinstance(value, dict):
        own = {str(value["symbol"]).upper()} if value.get("symbol") else set()
        return own | set().union(*(report_symbols(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(report_symbols(child) for child in value))
    return set()


def number(value):
    return value if isinstance(value, (int, float)) else None


def item(row: dict, scanner: str, stage: str) -> dict:
    metrics = row.get("metrics") or {}
    entry = number(row.get("entry"))
    return {
        "scanner": scanner,
        "symbol": str(row.get("symbol", "")).upper(),
        "stage": stage,
        "score": number(row.get("score")),
        "price": number(row.get("close", row.get("last_price", entry))),
        "entry_low": number(row.get("entry_low", entry)),
        "entry_high": number(row.get("entry_high", entry)),
        "stop": number(row.get("stop", row.get("initial_stop"))),
        "target1": number(row.get("target1")),
        "target2": number(row.get("target2")),
        "five_day_change": number(metrics.get("return_5d_pct")),
        "activity": number(metrics.get("turnover_ratio", row.get("volume_ratio"))),
    }


def penny_items(data: dict) -> list[dict]:
    labels = {
        "READY": "Watch for entry",
        "CONFIRMING": "Watchlist—wait for confirmation",
        "EARLY_RADAR": "Early watchlist",
        "CIRCUIT_LOCKED": "No entry—circuit risk",
        "EXTENDED": "Wait for pullback",
    }
    return [item(row, "penny", labels.get(row.get("state"), "Watch")) for row in data.get("candidates", [])]


def hull_items(data: dict) -> list[dict]:
    rows: list[dict] = []
    for row in data.get("created", []):
        rows.append(item(row, "hull", "New paper entry"))
    labels = {
        "READY": "Watch for entry",
        "EARLY": "Early watchlist",
        "EXTENDED": "Wait for pullback",
        "WEAK": "No action yet",
    }
    for row in data.get("watch", []):
        rows.append(item(row, "hull", labels.get(row.get("timing_state"), "Watch")))
    return rows


def v3_items(data: dict) -> list[dict]:
    labels = {
        "READY": "Watch for entry",
        "ACTION": "Watch for entry",
        "CONFIRMING": "Watchlist—wait for confirmation",
        "RADAR": "Early watchlist",
        "EARLY": "Early watchlist",
        "EXTENDED": "Wait for pullback",
        "WEAK": "No action yet",
    }
    rows = []
    for row in data.get("dashboard_candidates", []):
        stage = labels.get(
            row.get("timing_state"), labels.get(row.get("classification"), "Watchlist—wait for confirmation")
        )
        rows.append(item(row, "v3", stage))
    return rows


def ladder_items(data: dict) -> list[dict]:
    rows = []
    for row in data.get("shortlist", []):
        stage = "Watch for entry" if row.get("hull_state") == "READY" else "Watchlist—wait for confirmation"
        normalized = dict(row)
        normalized["score"] = row.get("discovery_score")
        if number(normalized.get("score")) is not None and normalized["score"] >= 75:
            rows.append(item(normalized, "ladder", stage))
    return rows


def _ranking_key(row: dict) -> tuple:
    """Rank by evidence first; upside and reward/risk only break close calls."""
    entry = row.get("entry_low") or row.get("price")
    stop, target = row.get("stop"), row.get("target2") or row.get("target1")
    upside = ((target / entry) - 1.0) if entry and target and target > entry else 0.0
    risk = (entry - stop) if entry and stop and stop < entry else 0.0
    reward_risk = ((target - entry) / risk) if risk and target else 0.0
    stage_priority = {
        "New paper entry": 6,
        "Open paper position": 6,
        "Watch for entry": 5,
        "Watchlist—wait for confirmation": 4,
        "Early watchlist": 3,
        "Wait for pullback": 2,
        "No action yet": 1,
        "No entry—circuit risk": 0,
    }.get(row.get("stage"), 0)
    return (-stage_priority, -(row.get("score") or 0), -min(upside, 1.0), -min(reward_risk, 10.0), row["symbol"])


def limit_per_scanner(rows: list[dict], maximum: int = 25) -> list[dict]:
    result = []
    for scanner in ("v3", "ladder", "hull", "penny"):
        ranked = sorted((row for row in rows if row["scanner"] == scanner), key=_ranking_key)
        result.extend(ranked[:maximum])
    return result


def main() -> int:
    terminal = terminal_symbols()
    etfs = etf_symbols()
    penny = read_json("output/penny_microcap/daily.json", {})
    hull = read_json("output/pine_hull_daily_run.json", {})
    v3 = read_json("output/v2_daily_run.json", {})
    ladder = read_json("output/old_nse_hull_daily.json", {})
    items = penny_items(penny) + hull_items(hull) + v3_items(v3) + ladder_items(ladder)
    items = [row for row in items if row["symbol"] and row["symbol"] not in terminal and row["symbol"] not in etfs]
    items = limit_per_scanner(items)
    feed = {
        "generated_at": datetime.now(UTC).isoformat(),
        "market_dates": {
            "v3": v3.get("trade_date"),
            "ladder": ladder.get("as_of_date"),
            "penny": penny.get("as_of_date"),
            "hull": hull.get("trade_date"),
        },
        "scanners": [
            {"id": "v3", "name": "NSE Scanner V3", "available": bool(v3.get("dashboard_candidates"))},
            {"id": "ladder", "name": "Momentum Ladder", "available": bool(ladder.get("shortlist"))},
            {"id": "hull", "name": "Hull Scanner", "available": bool(hull)},
            {"id": "penny", "name": "Penny Scanner", "available": bool(penny)},
        ],
        "items": items,
        "notice": "Paper tracking for research and education only. Not investment advice.",
        "display_rule": "Up to 25 higher-ranked opportunities per scanner. ETFs and terminal securities are excluded. Ladder requires a score of at least 75.",
    }
    target = ROOT / "docs/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mini App feed: {len(items)} visible rows; {len(terminal)} terminal and {len(etfs)} ETF symbols excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
