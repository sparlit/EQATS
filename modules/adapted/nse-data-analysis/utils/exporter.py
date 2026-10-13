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


"""
exporter.py
===========
Converts screener results into a clean, stable JSON schema designed to be
consumed by external sites/apps (e.g. a separate technical-analysis website
combining this fundamental data into a techno-fundamental view).

Design goals for the schema:
- Stable field names (won't silently rename things between runs)
- Keyed by symbol for O(1) lookup by an external consumer
- Includes a top-level `generated_at` timestamp so consumers can judge freshness
  and a `schema_version` so breaking changes can be detected programmatically
- Numbers are plain JSON numbers (not numpy types, which aren't JSON-serializable)
- Includes both the raw metrics AND the derived score/rating, so an external
  technical-analysis site can either trust this app's scoring or recompute its
  own combined score from the raw ratios

Merge behavior (important):
- The daily Nifty 500 batch export REPLACES the whole file by default
  (write_export, source="batch").
- Individually-searched stocks (outside the batch universe, e.g. a small/recent
  listing not in Nifty 500) are tagged `"source": "manual_search"` and are
  PRESERVED across batch re-exports unless the batch itself re-fetches that same
  symbol — see `write_export(..., preserve_manual=True)`.
- Scheduled chunk runs (cron-driven, ~165 symbols at a time across the full
  NSE universe) tag entries `"source": "scheduled_chunk"` and MERGE just their
  slice of symbols into the existing file, leaving every other entry (from
  prior chunks, prior days, or manual searches) untouched — see
  `write_chunk_to_export`. This is distinct from write_export's full-replace
  behavior because a single chunk run only ever has a small fraction of the
  total universe in hand at once.
"""


import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA_VERSION = "1.0"


def _clean_value(v):
    """Convert numpy/pandas scalar types to native Python types; NaN/inf -> None."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        v = float(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if pd.isna(v) if not isinstance(v, (list, dict)) else False:
        return None
    return v


def _build_stock_entry(row: pd.Series, deep_entry: dict, source: str = "batch") -> dict:
    """
    Builds a single symbol's export entry from one row of the screener DataFrame
    plus its matching deep_data dict. Shared by the full-batch export, the
    single ad-hoc stock search, AND the scheduled chunk refresh, so the schema
    can never silently diverge between any of the three code paths.
    """
    result = deep_entry.get("result", {})
    trends = deep_entry.get("trends", {})
    dcf = deep_entry.get("dcf", {})
    graham = deep_entry.get("graham", {})

    return {
        "symbol": row.get("Symbol"),
        "company_name": _clean_value(row.get("Company")),
        "sector": _clean_value(row.get("Sector")),
        "industry": _clean_value(row.get("Industry")),
        "price": _clean_value(row.get("Price")),
        "ratios": {
            "pe": _clean_value(row.get("PE")),
            "pb": _clean_value(row.get("PB")),
            "roe_pct": _clean_value(row.get("ROE %")),
            "debt_to_equity": _clean_value(row.get("Debt/Equity")),
            "profit_margin_pct": _clean_value(row.get("Profit Margin %")),
        },
        "growth": {
            "revenue_cagr_pct": _clean_value(row.get("Revenue CAGR %")),
            "net_income_cagr_pct": _clean_value(row.get("Net Income CAGR %")),
            "margin_trend": _clean_value(row.get("Margin Trend")),
            "revenue_growth_consistency_pct": _clean_value(
                trends.get("revenue_growth_consistency")
            ),
            "years_of_data": _clean_value(trends.get("years_available")),
        },
        "valuation": {
            "dcf_fair_value": _clean_value(dcf.get("fair_value_per_share")),
            "graham_number": _clean_value(graham.get("graham_value")),
            "blended_fair_value": _clean_value(row.get("Blended Fair Value")),
            "estimated_upside_pct": _clean_value(row.get("Est. Upside %")),
            "valuation_models_used": _clean_value(row.get("Valuation Models Used")),
        },
        "fundamental_score": {
            "total": _clean_value(row.get("Score")),
            "rating": _clean_value(row.get("Rating")),
            "pillars": {
                "valuation": _clean_value(row.get("Valuation Pillar")),
                "profitability": _clean_value(row.get("Profitability Pillar")),
                "stability": _clean_value(row.get("Stability Pillar")),
                "growth": _clean_value(row.get("Growth Pillar")),
                "valuation_upside": _clean_value(row.get("Upside Pillar")),
            },
            "key_notes": result.get("notes", [])[:6] if result else [],
        },
        "source": source,  # "batch" | "manual_search" | "scheduled_chunk"
        "updated_at": datetime.now(UTC).isoformat(),
    }


def build_export_payload(
    df: pd.DataFrame, deep_data: dict, universe_label: str, source: str = "batch"
) -> dict:
    """
    Builds the full export dict (ready for json.dump) from the screener's
    session_state-equivalent inputs: the ranked DataFrame and the per-symbol
    deep_data dict (info/trends/dcf/graham/result) produced in app/main.py.
    """
    stocks = {}
    for _, row in df.iterrows():
        symbol = row["Symbol"]
        stocks[symbol] = _build_stock_entry(row, deep_data.get(symbol, {}), source=source)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "universe": universe_label,
        "stock_count": len(stocks),
        "data_source": "yfinance (Yahoo Finance, unofficial)",
        "disclaimer": (
            "Fundamental research data only, not investment advice. Scores and fair-value "
            "estimates are model outputs from limited public data. See README for methodology."
        ),
        "stocks": stocks,
    }
    return payload


def load_existing_export(path: str | Path = "data/exports/latest.json") -> dict | None:
    """Loads the current latest.json if it exists and is valid; returns None otherwise."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_export(
    df: pd.DataFrame,
    deep_data: dict,
    universe_label: str,
    output_path: str | Path = "data/exports/latest.json",
    preserve_manual: bool = True,
) -> Path:
    """
    Writes the JSON export to disk. Also writes a timestamped copy alongside
    `latest.json` (e.g. `2026-06-21.json`) so history is preserved if you want
    to track how scores evolve day over day.

    If `preserve_manual=True` (default), any stocks previously added via
    individual search (source="manual_search") that are NOT part of this
    batch's symbols are carried forward into the new file instead of being
    wiped out. If the batch happens to include a symbol that was previously
    manual, the fresh batch data wins (it's more complete: sector medians,
    peer ranking, etc).

    Note: this REPLACES the entire stocks dict (aside from the manual-search
    preservation above). It does NOT preserve "scheduled_chunk" entries the
    same way — if you run both write_export (full Nifty 500/50 batch) and the
    scheduled chunk refresh against the same latest.json, a write_export call
    will wipe out scheduled_chunk entries outside its own batch universe,
    same as it always did for any non-"manual_search" entry. If you're running
    the scheduled chunk refresh as your primary universe coverage, prefer
    write_chunk_to_export for ongoing updates and reserve write_export for
    full intentional re-baselines.
    """
    payload = build_export_payload(df, deep_data, universe_label, source="batch")

    output_path = Path(output_path)

    if preserve_manual:
        existing = load_existing_export(output_path)
        if existing and "stocks" in existing:
            batch_symbols = set(payload["stocks"].keys())
            for symbol, entry in existing["stocks"].items():
                if symbol not in batch_symbols and entry.get("source") == "manual_search":
                    payload["stocks"][symbol] = entry
            payload["stock_count"] = len(payload["stocks"])

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    dated_path = output_path.parent / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.json"
    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return output_path


def add_single_stock_to_export(
    row: pd.Series, deep_entry: dict, output_path: str | Path = "data/exports/latest.json"
) -> Path:
    """
    Adds (or updates) ONE stock's entry into the existing latest.json without
    touching anything else in the file. This is what the app's single-stock
    search calls when you look up a symbol outside the current batch universe
    (e.g. not in Nifty 500) — the result gets merged in immediately rather than
    waiting for the next scheduled batch run, and rather than being a UI-only
    result that disappears when you close the tab.

    Also called by scripts/fetch_single.py for the Cloudflare on-demand
    fallback (a symbol searched on the consuming site that isn't in latest.json
    yet triggers this same path via a GitHub Actions workflow_dispatch).

    Creates a fresh minimal file if latest.json doesn't exist yet.
    """
    output_path = Path(output_path)
    existing = load_existing_export(output_path)

    if existing is None or "stocks" not in existing:
        existing = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "universe": "Mixed (batch + manual searches)",
            "stock_count": 0,
            "data_source": "yfinance (Yahoo Finance, unofficial)",
            "disclaimer": (
                "Fundamental research data only, not investment advice. Scores and fair-value "
                "estimates are model outputs from limited public data. See README for methodology."
            ),
            "stocks": {},
        }

    symbol = row.get("Symbol")
    existing["stocks"][symbol] = _build_stock_entry(row, deep_entry, source="manual_search")
    existing["stock_count"] = len(existing["stocks"])
    # Note: top-level `generated_at` intentionally NOT bumped here — it should reflect
    # the last full batch run, not an individual addition. Each stock entry has its
    # own `updated_at` for that purpose.

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return output_path


def write_chunk_to_export(
    df: pd.DataFrame,
    deep_data: dict,
    output_path: str | Path = "data/exports/latest.json",
    universe_label: str = "NSE_ALL_CHUNKED",
) -> tuple[Path, int]:
    """
    Merges one scheduled chunk's worth of freshly-scored symbols into
    latest.json, leaving every other existing entry (from prior chunks, prior
    days, manual searches, or an earlier full batch run) completely untouched.

    Used by scripts/fetch_chunk.py, the cron-driven scheduled refresh that
    processes a rotating ~165-symbol slice of the full NSE universe
    (data/universe/equity_main.csv + equity_sme.csv) every ~90 minutes,
    instead of one giant multi-hour run across all ~2640 symbols at once.

    Why this is separate from add_single_stock_to_export:
    That function does one symbol at a time and re-reads/re-writes the whole
    file per call — fine for a single ad-hoc lookup, wasteful for a chunk of
    ~165 symbols every scheduled run (165 file read+write cycles instead of 1).
    This function takes the whole chunk's DataFrame + deep_data dict and does
    exactly one read and one write.

    Why this is separate from write_export:
    write_export() REPLACES the entire stocks dict (it's built for "I just
    re-scored the whole universe in one run"). A chunk run only has ~165 of
    ~2640 symbols this pass — replacing the whole file would wipe out the
    other ~2475 entries until their turn comes back around in the rotation,
    days later. This function merges just the given symbols in.

    Returns (output_path, count_of_symbols_written) — the count is useful for
    the calling script's own logging, since df.iterrows() could in principle
    contain rows with a missing/falsy Symbol that get silently skipped here.

    The top-level `generated_at` IS bumped here (unlike
    add_single_stock_to_export's single-symbol path) — a chunk run is a real
    (partial) refresh pass, not a one-off addition, so it's reasonable for
    consumers to see the dataset's overall freshness timestamp move forward
    as chunks complete throughout the day. `universe` is also updated to
    reflect that the file now reflects the chunked-rotation approach.
    """
    output_path = Path(output_path)
    existing = load_existing_export(output_path)

    if existing is None or "stocks" not in existing:
        existing = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "universe": universe_label,
            "stock_count": 0,
            "data_source": "yfinance (Yahoo Finance, unofficial)",
            "disclaimer": (
                "Fundamental research data only, not investment advice. Scores and fair-value "
                "estimates are model outputs from limited public data. See README for methodology."
            ),
            "stocks": {},
        }

    written = 0
    for _, row in df.iterrows():
        symbol = row.get("Symbol")
        if not symbol:
            continue
        existing["stocks"][symbol] = _build_stock_entry(
            row, deep_data.get(symbol, {}), source="scheduled_chunk"
        )
        written += 1

    existing["stock_count"] = len(existing["stocks"])
    existing["generated_at"] = datetime.now(UTC).isoformat()
    existing["universe"] = universe_label

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return output_path, written


def write_export_csv(df: pd.DataFrame, output_path: str | Path = "data/exports/latest.csv") -> Path:
    """
    Flat CSV alternative for consumers that prefer tabular data over nested JSON
    (e.g. quick spreadsheet imports, or simple scripts that don't want to parse JSON).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path
