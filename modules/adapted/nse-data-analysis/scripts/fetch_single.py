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
scripts/fetch_single.py
========================
Headless, single-symbol counterpart to scripts/export_daily.py — and the
exact same code path as the Streamlit app's "Single Stock Search" tab
(app/main.py), just without the UI around it.

Purpose: when an external consumer (the Cloudflare /api/fundamentals function)
asks for a symbol that ISN'T in data/exports/latest.json (e.g. outside the
current Nifty 500 batch, or a stock that's new since the last batch run), this
script fetches + scores + values that one symbol via utils.analyzer.analyze_stock()
— the same function app/main.py's single-stock tab calls — and merges it into
latest.json via exporter.add_single_stock_to_export(), tagged source="manual_search".

This is meant to be triggered by a GitHub Actions workflow_dispatch with a
`symbol` input (see .github/workflows/fetch_single.yml), NOT run interactively.

Note: like the Streamlit single-stock tab, this has no sector peer group, so
the Valuation and Valuation Upside pillars fall back to absolute thresholds
only (see analyze_stock's docstring / main.py's UI caption for the same
caveat). That's an accepted, existing limitation of single-symbol lookups,
not something introduced by this script.

Usage:
    python scripts/fetch_single.py RELIANCE
    python scripts/fetch_single.py --symbol RELIANCE --output data/exports/latest.json

Exit codes:
    0 = success, symbol written to export
    1 = fetch or analysis failed (bad/delisted symbol, yfinance error, etc.)
    2 = usage error
"""


import argparse
import logging
import sys
from pathlib import Path

# Allow running as `python scripts/fetch_single.py` from repo root without
# needing the package installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.analyzer import analyze_stock
from utils.data_fetcher import YFinanceSource
from utils.exporter import add_single_stock_to_export

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_single")


def fetch_and_merge_one(symbol: str, output_path: str = "data/exports/latest.json"):
    """
    Fetches, analyzes, and merges exactly one symbol into latest.json.
    Returns the analysis dict ({"row": ..., "deep": ...}) on success.
    Raises RuntimeError on fetch failure or analysis failure, with a message
    suitable for logging/surfacing to the caller (mirrors the two failure
    branches in app/main.py's single-stock tab: fr.ok check, then analysis
    is None check).
    """
    source = YFinanceSource()
    # use_cache=False: an on-demand lookup triggered specifically because the
    # symbol was missing should fetch fresh, not reuse a stale/partial cache
    # entry from some earlier failed attempt.
    fr = source.fetch(symbol, use_cache=False)

    if not fr.ok:
        raise RuntimeError(f"Fetch failed for {symbol}: {fr.error}")

    analysis = analyze_stock(symbol, fr)  # no sector medians — standalone lookup, same as main.py
    if analysis is None:
        raise RuntimeError(f"Fetch succeeded but analysis failed unexpectedly for {symbol}")

    add_single_stock_to_export(
        row=analysis["row"],
        deep_entry=analysis["deep"],
        output_path=output_path,
    )
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", nargs="?", help="NSE symbol, e.g. RELIANCE (no .NS suffix)")
    parser.add_argument("--symbol", dest="symbol_flag", help="Alternative way to pass the symbol")
    parser.add_argument(
        "--output",
        default="data/exports/latest.json",
        help="Path to latest.json (default: data/exports/latest.json)",
    )
    args = parser.parse_args()

    symbol = (args.symbol_flag or args.symbol or "").strip().upper().replace(".NS", "")
    if not symbol:
        log.error("No symbol provided. Usage: python scripts/fetch_single.py SYMBOL")
        return 2

    log.info(f"Analyzing {symbol} (on-demand single-symbol fetch)...")

    try:
        analysis = fetch_and_merge_one(symbol, output_path=args.output)
    except Exception as e:
        log.error(str(e))
        return 1

    row = analysis["row"]
    log.info(
        f"{symbol}: score={row.get('Score')} rating={row.get('Rating')} "
        f"-> merged into {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
