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


"""Build market cap data for all stocks using bulk API methods.

Fallback order:
  1. niftyindices.com CSVs      — instant bulk, 450 NSE index stocks
  2. BSE listSecurities()       — 3 bulk calls, ~2,582 BSE stocks
  3. NSE pr_bhavcopy()          — 1 download, ~3,155 NSE stocks
  4. NSE getDetailedScripData() — per-stock fallback for remaining
  5. yfinance parallel          — final catch-all
  6. Classify by SEBI thresholds

Usage:
    python scripts/build_market_cap.py
"""


import csv
import io
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx
from indian_quant.features.market_cap import (
    LARGE_CAP_MIN,
    MCAP_FILE,
    MID_CAP_MIN,
    SMALL_CAP_MIN,
    classify_by_value,
    save_mcap_cache,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

INDEX_URLS = {
    "NIFTY 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "NIFTY Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "NIFTY Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


# ---------------------------------------------------------------------------
# Phase 1: niftyindices.com CSVs (instant)
# ---------------------------------------------------------------------------


def fetch_index_symbols() -> dict[str, set[str]]:
    """Download index constituent CSVs and extract symbols."""
    client = httpx.Client(timeout=15.0, follow_redirects=True)
    index_symbols: dict[str, set[str]] = {}

    for index_name, url in INDEX_URLS.items():
        try:
            resp = client.get(url, headers=HEADERS)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            symbols = {
                row.get("Symbol", "").strip() for row in reader if row.get("Symbol", "").strip()
            }
            index_symbols[index_name] = symbols
            logger.info(f"  {index_name}: {len(symbols)} symbols")
        except Exception as e:
            logger.warning(f"  {index_name}: FAILED ({e})")
            index_symbols[index_name] = set()

    client.close()
    return index_symbols


# ---------------------------------------------------------------------------
# Phase 2: BSE bulk — listSecurities() returns ALL stocks with market cap
# ---------------------------------------------------------------------------


def fetch_bse_bulk() -> tuple[dict[str, dict], dict[str, dict]]:
    """Fetch ALL BSE stocks with market cap via listSecurities bulk calls.

    Returns two dicts:
      - by_symbol: symbol -> {market_cap_cr, isin, bse_group}
      - by_isin: isin -> {market_cap_cr, symbol, bse_group}
    """
    from bse import BSE

    by_symbol: dict[str, dict] = {}
    by_isin: dict[str, dict] = {}
    bse = BSE(download_folder="/tmp/bse_mcap_bulk")

    for group in ["A", "B", "Z", "M", "XT", "T", "MT", "P", "MS", "R", "X"]:
        try:
            stocks = bse.listSecurities(segment="Equity", status="Active", group=group)
            hits = 0
            for s in stocks:
                symbol = s.get("scrip_id", "")
                mcap_str = s.get("Mktcap", "")
                isin = s.get("ISIN_NUMBER", "")
                if symbol and mcap_str and mcap_str not in ("", "0", "0.00"):
                    try:
                        mcap_cr = round(float(mcap_str), 2)
                        entry = {
                            "market_cap_cr": mcap_cr,
                            "isin": isin,
                            "bse_group": group,
                        }
                        by_symbol[symbol] = entry
                        if isin:
                            by_isin[isin] = {**entry, "symbol": symbol}
                        hits += 1
                    except (ValueError, TypeError):
                        pass
            logger.info(f"  BSE Group {group}: {len(stocks)} stocks, {hits} with market cap")
        except Exception as e:
            logger.warning(f"  BSE Group {group}: FAILED ({e})")

    bse.exit()
    logger.info(f"  BSE bulk total: {len(by_symbol)} stocks with market cap")
    return by_symbol, by_isin


# ---------------------------------------------------------------------------
# Phase 3: NSE pr_bhavcopy — single download, mcap CSV for all NSE stocks
# ---------------------------------------------------------------------------


def fetch_nse_pr_bhavcopy() -> dict[str, dict]:
    """Fetch NSE market cap from PR bhavcopy mcap CSV."""
    from nse import NSE

    results: dict[str, dict] = {}
    nse = NSE(download_folder="/tmp/nse_mcap_pr", server=True)

    # Try recent trading days (skip weekends)
    for days_back in range(1, 10):
        dt = datetime.now() - timedelta(days=days_back)
        if dt.weekday() >= 5:  # skip weekends
            continue
        try:
            zipped = nse.pr_bhavcopy(dt)
            logger.info(f"  NSE PR bhavcopy for {dt.date()}: {zipped}")

            with ZipFile(zipped) as zf:
                for name in zf.namelist():
                    if "mcap" in name.lower():
                        with zf.open(name) as f:
                            content = f.read().decode("utf-8")
                            reader = csv.DictReader(io.StringIO(content))
                            for row in reader:
                                # Strip whitespace from all keys and values
                                row = {k.strip(): v.strip() for k, v in row.items()}
                                symbol = row.get("Symbol", "")
                                mcap_raw = row.get("Market Cap(Rs.)", "")
                                series = row.get("Series", "")

                                if symbol and mcap_raw and series == "EQ":
                                    try:
                                        mcap_cr = round(float(mcap_raw) / 1e7, 2)
                                        if mcap_cr > 0:
                                            results[symbol] = {
                                                "market_cap_cr": mcap_cr,
                                                "isin": "",
                                            }
                                    except (ValueError, TypeError):
                                        pass
                        logger.info(f"  NSE mcap: {len(results)} stocks with market cap")
                        nse.exit()
                        return results
        except Exception as e:
            logger.info(f"  NSE PR bhavcopy {dt.date()}: {type(e).__name__}: {e}")
            continue

    nse.exit()
    logger.info(f"  NSE PR bhavcopy: {len(results)} stocks")
    return results


# ---------------------------------------------------------------------------
# Phase 4: NSE API fallback — per-stock for remaining misses
# ---------------------------------------------------------------------------


def fetch_nse_api_fallback(
    symbols: list[str],
    save_fn=None,
) -> dict[str, float]:
    """Fetch market cap from NSE API for individual stocks."""
    from nse import NSE

    results: dict[str, float] = {}
    failed = 0

    with NSE(download_folder="/tmp/nse_mcap_api", server=True) as nse:
        for i, sym in enumerate(symbols):
            try:
                data = nse.getDetailedScripData(sym)
                if data is None:
                    failed += 1
                    continue
                equity = data.get("equityResponse", [{}])
                if not equity or not isinstance(equity, list):
                    failed += 1
                    continue
                eq = equity[0]
                if eq is None:
                    failed += 1
                    continue
                trade_info = eq.get("tradeInfo")
                if trade_info is None:
                    failed += 1
                    continue
                mcap = trade_info.get("totalMarketCap")
                if mcap and mcap > 0:
                    results[sym] = round(mcap / 1e7, 2)
            except Exception:
                failed += 1

            if (i + 1) % 200 == 0:
                logger.info(
                    f"  NSE API: {i + 1}/{len(symbols)} done, {len(results)} hits, {failed} failed"
                )
            if save_fn and (i + 1) % 500 == 0:
                save_fn(results)
            time.sleep(0.35)

    logger.info(f"  NSE API: {len(results)}/{len(symbols)} fetched, {failed} failed")
    return results


# ---------------------------------------------------------------------------
# Phase 5: yfinance fallback
# ---------------------------------------------------------------------------


def _fetch_yfinance_mcap(sym: str) -> tuple[str, float | None]:
    """Fetch market cap from yfinance for one symbol."""
    try:
        import yfinance as yf

        t = yf.Ticker(f"{sym}.NS")
        info = t.info
        mcap = info.get("marketCap")
        if mcap and mcap > 0:
            return sym, round(mcap / 1e7, 2)
        return sym, None
    except Exception:
        return sym, None


def fetch_yfinance_bulk(symbols: list[str], max_workers: int = 10) -> dict[str, float]:
    """Fetch market cap for remaining symbols from yfinance in parallel."""
    results: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_yfinance_mcap, sym): sym for sym in symbols}
        done = 0
        for future in as_completed(futures):
            sym, mcap = future.result()
            done += 1
            if mcap is not None:
                results[sym] = mcap
            if done % 200 == 0:
                logger.info(f"  yfinance: {done}/{len(symbols)} done, {len(results)} hits")

    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def save_intermediate(
    symbols_data: dict,
    nifty50: set,
    midcap150: set,
    smallcap250: set,
    nse_bhav: dict,
    nse_mcap_fallback: dict,
    bse_bulk_by_isin: dict,
    yf_mcap: dict,
) -> None:
    """Save intermediate results so progress is not lost on interrupt."""
    results: dict[str, dict] = {}
    for sym_info in symbols_data.values():
        symbol = sym_info.get("symbol", "")
        exchange = sym_info.get("exchange", "NSE")
        isin = sym_info.get("isin", "")
        segment = sym_info.get("segment", "EQ")
        key = f"{exchange}|{symbol}"

        mcap_cr = None
        source = "unknown"
        tier = "Other"

        if symbol in nifty50:
            tier = "Large Cap"
            mcap_cr = LARGE_CAP_MIN
            source = "index"
        elif symbol in midcap150:
            tier = "Mid Cap"
            mcap_cr = MID_CAP_MIN
            source = "index"
        elif symbol in smallcap250:
            tier = "Small Cap"
            mcap_cr = SMALL_CAP_MIN
            source = "index"
        elif symbol in nse_bhav:
            mcap_cr = nse_bhav[symbol]["market_cap_cr"]
            tier = classify_by_value(mcap_cr)
            source = "nse_pr"
        elif symbol in nse_mcap_fallback:
            mcap_cr = nse_mcap_fallback[symbol]
            tier = classify_by_value(mcap_cr)
            source = "nse_api"
        elif isin and isin in bse_bulk_by_isin:
            mcap_cr = bse_bulk_by_isin[isin]["market_cap_cr"]
            tier = classify_by_value(mcap_cr)
            source = "bse_bulk"
        elif symbol in yf_mcap:
            mcap_cr = yf_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "yfinance"

        # Override to SME for SME-segment stocks
        if segment == "SME":
            tier = "SME"

        results[key] = {
            "market_cap_cr": round(mcap_cr, 2) if mcap_cr else None,
            "market_cap_class": tier,
            "segment": segment,
            "source": source,
        }

    save_mcap_cache(results)
    classes = {}
    for v in results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
    logger.info(f"  Intermediate save: {len(results)} stocks, {json.dumps(classes)}")


def load_universe() -> dict[str, dict]:
    """Load universe registry."""
    reg_file = Path("data/universe/registry.json")
    if not reg_file.exists():
        logger.error("registry.json not found")
        return {}
    data = json.loads(reg_file.read_text())
    return data.get("symbols", {})


def main() -> int:
    start_total = time.time()

    symbols_data = load_universe()
    if not symbols_data:
        return 1

    nse_symbols = [v["symbol"] for v in symbols_data.values() if v.get("exchange") == "NSE"]
    bse_symbols = [v["symbol"] for v in symbols_data.values() if v.get("exchange") == "BSE"]
    logger.info(f"Universe: {len(nse_symbols)} NSE, {len(bse_symbols)} BSE")

    # Load existing cache
    results_cache = {}
    if MCAP_FILE.exists():
        results_cache = json.loads(MCAP_FILE.read_text())
        logger.info(f"Loaded existing cache: {len(results_cache)} entries")

    # Phase 1: Index classification (instant)
    logger.info("\n=== Phase 1: NSE index constituents ===")
    index_symbols = fetch_index_symbols()
    nifty50 = index_symbols.get("NIFTY 50", set())
    midcap150 = index_symbols.get("NIFTY Midcap 150", set())
    smallcap250 = index_symbols.get("NIFTY Smallcap 250", set())
    classified_by_index = nifty50 | midcap150 | smallcap250
    logger.info(f"  Index-classified: {len(classified_by_index)} stocks")

    # Phase 2: BSE bulk (3 API calls)
    logger.info("\n=== Phase 2: BSE listSecurities (bulk) ===")
    bse_start = time.time()
    bse_bulk_by_sym, bse_bulk_by_isin = fetch_bse_bulk()
    bse_time = time.time() - bse_start
    logger.info(f"  BSE bulk done in {bse_time:.0f}s")

    # Save intermediate after BSE bulk
    save_intermediate(symbols_data, nifty50, midcap150, smallcap250, {}, {}, bse_bulk_by_isin, {})

    # Phase 3: NSE pr_bhavcopy (1 download)
    logger.info("\n=== Phase 3: NSE pr_bhavcopy (bulk) ===")
    nse_start = time.time()
    nse_bhav = fetch_nse_pr_bhavcopy()
    nse_time = time.time() - nse_start
    logger.info(f"  NSE bhavcopy done in {nse_time:.0f}s")

    # Save intermediate after NSE bhavcopy
    save_intermediate(
        symbols_data, nifty50, midcap150, smallcap250, nse_bhav, {}, bse_bulk_by_isin, {}
    )

    # Phase 4: NSE API fallback for remaining misses
    classified_nse = set(classified_by_index) | set(nse_bhav.keys())
    remaining_nse = [s for s in nse_symbols if s not in classified_nse]

    # Filter out ETFs/REITs/SME that NSE API won't find
    # Keep only EQ series stocks (regular equity)
    nse_mcap_fallback = {}
    if remaining_nse:
        logger.info(f"\n=== Phase 4: NSE API fallback ({len(remaining_nse)} stocks) ===")
        nse_fallback_start = time.time()
        nse_mcap_fallback = fetch_nse_api_fallback(remaining_nse)
        nse_fallback_time = time.time() - nse_fallback_start
        logger.info(f"  NSE API fallback done in {nse_fallback_time:.0f}s")

        # Save intermediate after NSE API fallback
        save_intermediate(
            symbols_data,
            nifty50,
            midcap150,
            smallcap250,
            nse_bhav,
            nse_mcap_fallback,
            bse_bulk_by_isin,
            {},
        )

    # Phase 5: yfinance for final misses
    all_classified = classified_nse | set(nse_mcap_fallback.keys())
    bse_classified = set(bse_bulk_by_isin.keys())
    remaining_yf = [
        s for s in nse_symbols + bse_symbols if s not in all_classified and s not in bse_classified
    ]

    yf_mcap = {}
    if remaining_yf:
        logger.info(f"\n=== Phase 5: yfinance fallback ({len(remaining_yf)} stocks) ===")
        yf_start = time.time()
        yf_mcap = fetch_yfinance_bulk(remaining_yf, max_workers=10)
        yf_time = time.time() - yf_start
        logger.info(f"  yfinance done in {yf_time:.0f}s, {len(yf_mcap)} hits")

    # Build final classification
    logger.info("\n=== Building classification ===")
    results: dict[str, dict] = {}

    for sym_info in symbols_data.values():
        symbol = sym_info.get("symbol", "")
        exchange = sym_info.get("exchange", "NSE")
        isin = sym_info.get("isin", "")
        segment = sym_info.get("segment", "EQ")
        key = f"{exchange}|{symbol}"

        mcap_cr = None
        source = "unknown"
        tier = "Other"

        if symbol in nifty50:
            tier = "Large Cap"
            mcap_cr = LARGE_CAP_MIN
            source = "index"
        elif symbol in midcap150:
            tier = "Mid Cap"
            mcap_cr = MID_CAP_MIN
            source = "index"
        elif symbol in smallcap250:
            tier = "Small Cap"
            mcap_cr = SMALL_CAP_MIN
            source = "index"
        elif symbol in nse_bhav:
            mcap_cr = nse_bhav[symbol]["market_cap_cr"]
            tier = classify_by_value(mcap_cr)
            source = "nse_pr"
        elif symbol in nse_mcap_fallback:
            mcap_cr = nse_mcap_fallback[symbol]
            tier = classify_by_value(mcap_cr)
            source = "nse_api"
        elif isin and isin in bse_bulk_by_isin:
            mcap_cr = bse_bulk_by_isin[isin]["market_cap_cr"]
            tier = classify_by_value(mcap_cr)
            source = "bse_bulk"
        elif symbol in yf_mcap:
            mcap_cr = yf_mcap[symbol]
            tier = classify_by_value(mcap_cr)
            source = "yfinance"

        # Override to SME for SME-segment stocks
        if segment == "SME":
            tier = "SME"

        results[key] = {
            "market_cap_cr": round(mcap_cr, 2) if mcap_cr else None,
            "market_cap_class": tier,
            "segment": segment,
            "source": source,
        }

    save_mcap_cache(results)

    # Summary
    classes: dict[str, int] = {}
    sources: dict[str, int] = {}
    for v in results.values():
        cls = v.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
        src = v.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    total_time = time.time() - start_total
    logger.info("\n=== Summary ===")
    logger.info(f"Total time: {total_time:.0f}s ({total_time / 60:.1f}min)")
    logger.info(f"Classification: {json.dumps(classes, indent=2)}")
    logger.info(f"Sources: {json.dumps(sources, indent=2)}")
    logger.info(f"Saved to {MCAP_FILE}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
