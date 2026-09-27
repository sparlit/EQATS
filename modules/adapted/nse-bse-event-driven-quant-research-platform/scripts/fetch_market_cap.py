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


"""Fetch market cap for all universe symbols via yfinance.

Saves to data/universe/market_cap.json for fast lookup by classify_signals.

Usage:
    python scripts/fetch_market_cap.py [--batch 50] [--force]
"""


import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.features.market_cap import MCAP_FILE, classify_by_value, save_mcap_cache


def load_universe() -> list[dict]:
    """Load universe registry."""
    reg_file = Path("data/universe/registry.json")
    if not reg_file.exists():
        print("ERROR: data/universe/registry.json not found. Run universe_build.py first.")
        return []
    data = json.loads(reg_file.read_text())
    symbols = data.get("symbols", {})
    # symbols is a dict keyed by symbol name
    if isinstance(symbols, dict):
        return list(symbols.values())
    return symbols


def fetch_market_cap_batch(symbols: list[str], exchange: str) -> dict[str, dict]:
    """Fetch market cap for a batch of symbols via yfinance."""
    import yfinance as yf

    results = {}
    suffix = ".NS" if exchange == "NSE" else ".BO"

    # yfinance supports batch download
    tickers = [f"{s}{suffix}" for s in symbols]
    try:
        yf.download(tickers, period="1d", group_by="ticker", progress=False, threads=True)
        for sym in symbols:
            ticker = f"{sym}{suffix}"
            try:
                if len(tickers) == 1:
                    info = yf.Ticker(ticker).info
                else:
                    # For batch, we need individual Ticker calls for info
                    info = yf.Ticker(ticker).info
                mcap = info.get("marketCap")
                if mcap and isinstance(mcap, (int, float)) and mcap > 0:
                    mcap_cr = round(mcap / 1e7, 2)
                    results[f"{exchange}|{sym}"] = {
                        "market_cap_cr": mcap_cr,
                        "market_cap_class": classify_by_value(mcap_cr),
                    }
                else:
                    results[f"{exchange}|{sym}"] = {
                        "market_cap_cr": None,
                        "market_cap_class": "Unknown",
                    }
            except Exception:
                results[f"{exchange}|{sym}"] = {
                    "market_cap_cr": None,
                    "market_cap_class": "Unknown",
                }
    except Exception as e:
        print(f"  Batch download failed: {e}")
        # Fallback: individual fetches
        for sym in symbols:
            try:
                info = yf.Ticker(f"{sym}{suffix}").info
                mcap = info.get("marketCap")
                if mcap and isinstance(mcap, (int, float)) and mcap > 0:
                    mcap_cr = round(mcap / 1e7, 2)
                    results[f"{exchange}|{sym}"] = {
                        "market_cap_cr": mcap_cr,
                        "market_cap_class": classify_by_value(mcap_cr),
                    }
                else:
                    results[f"{exchange}|{sym}"] = {
                        "market_cap_cr": None,
                        "market_cap_class": "Unknown",
                    }
            except Exception:
                results[f"{exchange}|{sym}"] = {
                    "market_cap_cr": None,
                    "market_cap_class": "Unknown",
                }

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch market cap for all universe symbols")
    parser.add_argument("--batch", type=int, default=50, help="symbols per batch")
    parser.add_argument("--force", action="store_true", help="re-fetch even if cached")
    args = parser.parse_args()

    universe = load_universe()
    if not universe:
        return 1

    # Load existing cache
    existing = {}
    if MCAP_FILE.exists() and not args.force:
        try:
            existing = json.loads(MCAP_FILE.read_text())
            print(f"Loaded {len(existing)} cached entries")
        except Exception:
            pass

    # Group by exchange
    nse_symbols = [s["symbol"] for s in universe if s.get("exchange") == "NSE"]
    bse_symbols = [s["symbol"] for s in universe if s.get("exchange") == "BSE" and s.get("dual_listed") is not True]

    print(f"Universe: {len(nse_symbols)} NSE, {len(bse_symbols)} BSE-only")
    print(f"Already cached: {len(existing)}")

    # Filter out already cached
    if not args.force:
        nse_todo = [s for s in nse_symbols if f"NSE|{s}" not in existing]
        bse_todo = [s for s in bse_symbols if f"BSE|{s}" not in existing]
    else:
        nse_todo = nse_symbols
        bse_todo = bse_symbols

    print(f"To fetch: {len(nse_todo)} NSE, {len(bse_todo)} BSE")

    # Fetch in batches
    all_results = dict(existing)
    t0 = time.time()

    for exchange, symbols in [("NSE", nse_todo), ("BSE", bse_todo)]:
        if not symbols:
            continue
        print(f"\nFetching {exchange} ({len(symbols)} symbols)...", flush=True)
        for i in range(0, len(symbols), args.batch):
            batch = symbols[i : i + args.batch]
            results = fetch_market_cap_batch(batch, exchange)
            all_results.update(results)
            fetched = sum(1 for v in results.values() if v["market_cap_cr"] is not None)
            print(
                f"  {i + len(batch)}/{len(symbols)} done, {fetched} with market cap ({time.time() - t0:.0f}s)",
                flush=True,
            )
            # Rate limit: yfinance free tier
            time.sleep(0.5)

    # Save
    save_mcap_cache(all_results)

    # Summary
    classes = {}
    with_mcap = 0
    for v in all_results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
        if v.get("market_cap_cr") is not None:
            with_mcap += 1

    print(f"\n{'=' * 50}")
    print(f"Total: {len(all_results)} symbols, {with_mcap} with market cap")
    print(f"Classification: {json.dumps(classes, indent=2)}")
    print(f"Saved to: {MCAP_FILE}")
    print(f"Time: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
