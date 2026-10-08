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


import os
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta

# ── Config ────────────────────────────────────────
SUFFIX = ".NS"
END_DATE = date.today()
FULL_START = END_DATE - relativedelta(months=15)
SLEEP_SECS = 2
MKTCAP_FLOOR = 500
ADTV_FLOOR = 10
ADTV_WINDOW = 63
MAX_RETRIES = 2
EMPTY_GAP_DAYS = 7
MKT_CLOSE_HOUR = 15
MKT_CLOSE_MIN = 30
BATCH_SIZE = 20

PRICES_PATH = Path("data/prices.parquet")
METADATA_PATH = Path("data/universe_metadata.parquet")
ADTV_PATH = Path("data/adtv.parquet")
UNIVERSE_DIR = Path("universe")
SYMBOLS_CSV = Path("nifty500_symbols.csv")
LAST_RUN_PATH = Path("data/last_run_date.txt")
FAILED_PATH = Path("data/failed_symbols_{}.csv".format(END_DATE.strftime("%Y%m%d")))

# ── Pipeline mode ─────────────────────────────────
STAGE6_MODE = os.environ.get("STAGE6_MODE", "rebalance").lower()


def market_closed_today():
    now_ist = pd.Timestamp.now(tz="Asia/Kolkata")
    close_time = now_ist.normalize() + pd.Timedelta(hours=MKT_CLOSE_HOUR, minutes=MKT_CLOSE_MIN)
    return now_ist >= close_time


def classify_empty(fetch_start):
    gap_days = (END_DATE - fetch_start).days
    if gap_days <= EMPTY_GAP_DAYS:
        return "UP_TO_DATE"
    return "NO_DATA"


def fetch_symbol_info(symbol):
    ticker_str = f"{symbol}{SUFFIX}"
    try:
        info = yf.Ticker(ticker_str).info
        return info, None, None
    except Exception as e:
        return {}, "INFO_ERROR", str(e)


def fetch_ohlcv_batch(symbols, fetch_start):
    """
    Batch price fetch for a list of symbols with the same fetch_start.
    Returns long-format DataFrame, list of missing symbols, failure type, error message.
    """
    tickers_ns = [f"{s}{SUFFIX}" for s in symbols]
    start_str = fetch_start.strftime("%Y-%m-%d")
    end_str = END_DATE.strftime("%Y-%m-%d")

    try:
        raw = yf.download(
            tickers_ns,
            start=start_str,
            end=end_str,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return pd.DataFrame(), symbols, "DOWNLOAD_ERROR", str(e)

    if raw.empty:
        return (
            pd.DataFrame(),
            symbols,
            classify_empty(fetch_start),
            "yfinance returned empty dataframe",
        )

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns.names = ["field", "ticker"]
        df = raw.stack(level="ticker", future_stack=True).reset_index()
        df.columns = df.columns.str.strip().str.lower()
        df = df.rename(columns={"ticker": "symbol"})
    else:
        df = raw.reset_index()
        df.columns = df.columns.str.strip().str.lower()
        df["symbol"] = tickers_ns[0]

    df["symbol"] = df["symbol"].str.replace(SUFFIX, "", regex=False).str.upper()
    df["date"] = pd.to_datetime(df["date"])
    df = df[
        [c for c in ["symbol", "date", "open", "high", "low", "close", "volume"] if c in df.columns]
    ]
    df = df[df["volume"] != 0]
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])

    returned_syms = set(df["symbol"].unique())
    missing = [s for s in symbols if s not in returned_syms]
    return df, missing, None, None


def flush_batch(batch_symbols, fetch_start, new_price_rows, failed_symbols):
    """Fire a batch download and handle results."""
    if not batch_symbols:
        return
    print(f"  BATCH: {len(batch_symbols)} tickers from {fetch_start}")
    df, missing, failure, errmsg = fetch_ohlcv_batch(batch_symbols, fetch_start)
    if not df.empty:
        new_price_rows.append(df)
        print("    OK: {} tickers, {} rows".format(df["symbol"].nunique(), len(df)))
    for sym in missing:
        status = classify_empty(fetch_start)
        if status == "UP_TO_DATE":
            print(f"    {sym}: UP_TO_DATE")
        else:
            failed_symbols[sym] = {
                "failure_type": status,
                "error_message": errmsg or "yfinance returned empty",
                "attempts": 1,
            }
            print(f"    {sym}: {status}")
    if failure == "DOWNLOAD_ERROR" and df.empty:
        for sym in batch_symbols:
            if sym not in failed_symbols:
                failed_symbols[sym] = {
                    "failure_type": failure,
                    "error_message": errmsg,
                    "attempts": 1,
                }
    time.sleep(SLEEP_SECS)


# ── Step 0: Load symbols ──────────────────────────
print("=" * 60)
print("NSE Factor Engine - Universe & Liquidity")
print(f"Run Date : {END_DATE}")
print("=" * 60)

print("\n[0/5] Loading symbol list...")
if not SYMBOLS_CSV.exists():
    raise FileNotFoundError(f"Symbol list not found at {SYMBOLS_CSV}")
df_sym = pd.read_csv(SYMBOLS_CSV)
df_sym.columns = df_sym.columns.str.strip().str.lower()
SYMBOLS = df_sym["symbol"].tolist()
print(f"      {len(SYMBOLS)} symbols loaded from {SYMBOLS_CSV}")
print(f"      Pipeline mode : {STAGE6_MODE.upper()}")

# ── Step 0b: Check last run date ──────────────────
skip_price_fetch = False
if LAST_RUN_PATH.exists():
    last_run = LAST_RUN_PATH.read_text().strip()
    if last_run == END_DATE.strftime("%Y-%m-%d"):
        print(
            f"\n      Run already completed today (last_run_date = {last_run}). Nothing to do. Exiting."
        )
        import sys

        sys.exit(0)
    else:
        print(f"      Last run date : {last_run} -- proceeding")
else:
    print("      No last run date found -- first run")

# ── Step 1: Load existing prices ──────────────────
print("\n[1/5] Checking existing prices...")
if PRICES_PATH.exists():
    existing_prices = pd.read_parquet(PRICES_PATH)
    existing_prices["date"] = pd.to_datetime(existing_prices["date"])
    last_dates = existing_prices.groupby("symbol")["date"].max()
    print(f"      Existing prices : {existing_prices.shape[0]} rows | {len(last_dates)} symbols")
else:
    existing_prices = pd.DataFrame()
    last_dates = pd.Series(dtype="datetime64[ns]")
    print("      No existing prices -- full 15M fetch for all qualifying symbols")

# ── Monitor mode: load cached metadata ────────────
if STAGE6_MODE in ("monitor", "mid_month"):
    if METADATA_PATH.exists():
        cached_meta_df = pd.read_parquet(METADATA_PATH)
        cached_meta_map = cached_meta_df.set_index("symbol").to_dict("index")
        print(
            f"      Monitor/mid_month mode: {len(cached_meta_map)} cached metadata records loaded"
        )
    else:
        print(
            "      Monitor mode requested but no existing metadata found -- falling back to rebalance"
        )
        STAGE6_MODE = "rebalance"
        cached_meta_map = {}
else:
    cached_meta_map = {}

# ── Step 2: Info fetch + batch price fetch ────────
metadata_rows = []
new_price_rows = []
failed_symbols = {}


def compute_fetch_start(symbol):
    if symbol in last_dates.index:
        return (last_dates[symbol] + pd.Timedelta(days=1)).date(), "INCR"
    return FULL_START, "FULL"


if not skip_price_fetch:
    print(f"\n[2/5] Processing {len(SYMBOLS)} symbols...")
    if not market_closed_today():
        print("      NOTE: Current IST time is before market close (3:30 PM).")
        print("            Today's data not yet available -- fetching up to last trading day.")
    print(f"      Mode: {STAGE6_MODE.upper()} | Market cap gate: >= Rs {MKTCAP_FLOOR} Cr\n")

    pending_batches = defaultdict(list)

    for idx, symbol in enumerate(SYMBOLS, 1):
        made_info_call = False
        try:
            fetch_start, mode = compute_fetch_start(symbol)
            use_cache = (STAGE6_MODE == "monitor") and (symbol in cached_meta_map)

            if use_cache:
                # ── Monitor mode: use cached metadata ─────────────────
                cached = cached_meta_map[symbol]
                mktcap_cr = cached.get("market_cap_cr", 0) or 0
                metadata_rows.append(
                    {
                        "symbol": symbol,
                        "company_name": cached.get("company_name"),
                        "industry": cached.get("industry"),
                        "market_cap_cr": mktcap_cr,
                    }
                )

                if fetch_start > END_DATE:
                    print(
                        f"  [{idx:03d}] {symbol:20s} Rs {mktcap_cr:>10,.0f} Cr  UP TO DATE (cached)"
                    )
                    continue

                if fetch_start == END_DATE and not market_closed_today():
                    print(
                        f"  [{idx:03d}] {symbol:20s} Rs {mktcap_cr:>10,.0f} Cr  UP TO DATE pre-close (cached)"
                    )
                    continue

            else:
                # ── Rebalance mode or new symbol: fetch .info ──────────
                made_info_call = True

                if fetch_start > END_DATE:
                    info, failure, errmsg = fetch_symbol_info(symbol)
                    if failure:
                        failed_symbols[symbol] = {
                            "failure_type": failure,
                            "error_message": errmsg,
                            "attempts": 1,
                        }
                        print(f"  [{idx:03d}] {symbol:20s} INFO_ERROR : {errmsg}")
                        time.sleep(SLEEP_SECS)
                        continue
                    mktcap = info.get("marketCap") or info.get("nonDilutedMarketCap", 0) or 0
                    mktcap_cr = round(mktcap / 1e7, 0)
                    metadata_rows.append(
                        {
                            "symbol": symbol,
                            "company_name": info.get("longName"),
                            "industry": info.get("sector"),
                            "market_cap_cr": mktcap_cr,
                        }
                    )
                    print(f"  [{idx:03d}] {symbol:20s} Rs {mktcap_cr:>10,.0f} Cr  UP TO DATE")
                    time.sleep(SLEEP_SECS)
                    continue

                if fetch_start == END_DATE and not market_closed_today():
                    info, failure, errmsg = fetch_symbol_info(symbol)
                    if failure:
                        failed_symbols[symbol] = {
                            "failure_type": failure,
                            "error_message": errmsg,
                            "attempts": 1,
                        }
                        print(f"  [{idx:03d}] {symbol:20s} INFO_ERROR : {errmsg}")
                        time.sleep(SLEEP_SECS)
                        continue
                    mktcap = info.get("marketCap") or info.get("nonDilutedMarketCap", 0) or 0
                    mktcap_cr = round(mktcap / 1e7, 0)
                    metadata_rows.append(
                        {
                            "symbol": symbol,
                            "company_name": info.get("longName"),
                            "industry": info.get("sector"),
                            "market_cap_cr": mktcap_cr,
                        }
                    )
                    print(
                        f"  [{idx:03d}] {symbol:20s} Rs {mktcap_cr:>10,.0f} Cr  UP TO DATE (pre-close)"
                    )
                    time.sleep(SLEEP_SECS)
                    continue

                info, failure, errmsg = fetch_symbol_info(symbol)
                if failure:
                    failed_symbols[symbol] = {
                        "failure_type": failure,
                        "error_message": errmsg,
                        "attempts": 1,
                    }
                    print(f"  [{idx:03d}] {symbol:20s} INFO_ERROR : {errmsg}")
                    time.sleep(SLEEP_SECS)
                    continue
                mktcap = info.get("marketCap") or info.get("nonDilutedMarketCap", 0) or 0
                mktcap_cr = round(mktcap / 1e7, 0)
                metadata_rows.append(
                    {
                        "symbol": symbol,
                        "company_name": info.get("longName"),
                        "industry": info.get("sector"),
                        "market_cap_cr": mktcap_cr,
                    }
                )

            # ── mktcap gate ───────────────────────────────────────────
            if mktcap_cr < MKTCAP_FLOOR:
                print(f"  [{idx:03d}] {symbol:20s} Rs {mktcap_cr:>10,.0f} Cr  SKIPPED")
                if made_info_call:
                    time.sleep(SLEEP_SECS)
                continue

            # ── Queue for batch price fetch ───────────────────────────
            pending_batches[fetch_start].append(symbol)
            print(f"  [{idx:03d}] {symbol:20s} Rs {mktcap_cr:>10,.0f} Cr  {mode} queued")

            if len(pending_batches[fetch_start]) >= BATCH_SIZE:
                flush_batch(
                    pending_batches.pop(fetch_start), fetch_start, new_price_rows, failed_symbols
                )

        except Exception as e:
            failed_symbols[symbol] = {
                "failure_type": "INFO_ERROR",
                "error_message": str(e),
                "attempts": 1,
            }
            print(f"  [{idx:03d}] {symbol:20s} ERROR : {str(e)}")

        if made_info_call:
            time.sleep(SLEEP_SECS)

    # Flush remaining partial batches
    print("\n  Flushing remaining partial batches...")
    for fetch_start, batch_syms in pending_batches.items():
        flush_batch(batch_syms, fetch_start, new_price_rows, failed_symbols)

    # ── Retry loop ────────────────────────────────
    if failed_symbols:
        print(f"\n-- RETRY: {len(failed_symbols)} failed symbols --")
        for attempt in range(1, MAX_RETRIES + 1):
            if not failed_symbols:
                break
            print(f"\n  Retry attempt {attempt} of {MAX_RETRIES}...")
            still_failing = {}

            for symbol, rec in failed_symbols.items():
                fetch_info = rec["failure_type"] == "INFO_ERROR"
                fetch_start, _ = compute_fetch_start(symbol)

                if fetch_info:
                    info, failure, errmsg = fetch_symbol_info(symbol)
                    if failure:
                        rec["attempts"] += 1
                        rec["error_message"] = errmsg
                        still_failing[symbol] = rec
                        print("  {:20s} INFO_ERROR (attempt {})".format(symbol, rec["attempts"]))
                        time.sleep(SLEEP_SECS)
                        continue
                    mktcap = info.get("marketCap") or info.get("nonDilutedMarketCap", 0) or 0
                    mktcap_cr = round(mktcap / 1e7, 0)
                    metadata_rows.append(
                        {
                            "symbol": symbol,
                            "company_name": info.get("longName"),
                            "industry": info.get("sector"),
                            "market_cap_cr": mktcap_cr,
                        }
                    )

                df, missing, failure, errmsg = fetch_ohlcv_batch([symbol], fetch_start)
                if failure == "UP_TO_DATE" or (not missing and df.empty):
                    print(f"  {symbol:20s} UP TO DATE on retry")
                    time.sleep(SLEEP_SECS)
                    continue
                if failure in ("NO_DATA", "DOWNLOAD_ERROR") or missing:
                    rec["attempts"] += 1
                    rec["failure_type"] = failure or "NO_DATA"
                    rec["error_message"] = errmsg or "yfinance returned empty"
                    still_failing[symbol] = rec
                    print(
                        "  {:20s} {} (attempt {})".format(
                            symbol, rec["failure_type"], rec["attempts"]
                        )
                    )
                    time.sleep(SLEEP_SECS)
                    continue
                new_price_rows.append(df)
                print(f"  {symbol:20s} SUCCESS on retry {attempt}")
                time.sleep(SLEEP_SECS)

            failed_symbols = still_failing

    # ── Save / clear failed symbols ───────────────
    if failed_symbols:
        failed_df = pd.DataFrame([{"symbol": s, **v} for s, v in failed_symbols.items()])
        failed_df.to_csv(FAILED_PATH, index=False)
        print(f"\n  {len(failed_symbols)} symbols still failing -- saved to {FAILED_PATH}")
    else:
        if FAILED_PATH.exists():
            FAILED_PATH.unlink()

else:
    print("\n[2/5] Price fetch skipped -- loading existing metadata...")
    if METADATA_PATH.exists():
        metadata_rows = pd.read_parquet(METADATA_PATH).to_dict("records")

# ── Step 3: Save metadata ─────────────────────────
print("\n[3/5] Saving metadata...")
metadata = pd.DataFrame(metadata_rows).drop_duplicates(subset=["symbol"], keep="last")
metadata.to_parquet(METADATA_PATH, index=False)
print(f"      universe_metadata.parquet : {len(metadata)} rows")

# ── Step 4: Merge & save prices ───────────────────
print("\n[4/5] Saving prices...")
if new_price_rows:
    new_prices = pd.concat(new_price_rows, ignore_index=True)
    if not existing_prices.empty:
        combined = pd.concat([existing_prices, new_prices], ignore_index=True)
    else:
        combined = new_prices
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)
    combined.to_parquet(PRICES_PATH, index=False)
    print(f"      prices.parquet : {combined.shape[0]} rows")
else:
    combined = existing_prices
    print("      No new price rows to add")

# ── Step 5: Compute ADTV & build universe ─────────
print("\n[5/5] Computing ADTV and building universe snapshot...")

combined["date"] = pd.to_datetime(combined["date"])
combined["daily_value"] = combined["close"] * combined["volume"]

adtv_rows = []
for symbol, grp in combined.groupby("symbol"):
    grp = grp.sort_values("date").copy()
    grp["adtv_63_cr"] = (
        grp["daily_value"].rolling(window=ADTV_WINDOW, min_periods=1).mean() / 1e7
    ).round(2)
    adtv_rows.append(grp[["symbol", "date", "adtv_63_cr"]])

adtv = pd.concat(adtv_rows, ignore_index=True)
adtv.to_parquet(ADTV_PATH, index=False)
print(f"      adtv.parquet : {adtv.shape[0]} rows")

latest_adtv = (
    adtv.sort_values("date").groupby("symbol").last().reset_index()[["symbol", "adtv_63_cr"]]
)

universe = metadata.merge(latest_adtv, on="symbol", how="left")
universe["passes_mktcap"] = universe["market_cap_cr"] >= MKTCAP_FLOOR
universe["passes_adtv"] = universe["adtv_63_cr"] >= ADTV_FLOOR
universe["in_universe"] = universe["passes_mktcap"] & universe["passes_adtv"]

UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
universe_path = UNIVERSE_DIR / "universe_{}.parquet".format(END_DATE.strftime("%d%m%Y"))
universe.to_parquet(universe_path, index=False)
print(
    "      {} : {} rows | {} in universe".format(
        universe_path.name, len(universe), universe["in_universe"].sum()
    )
)

# ── Update last run date ──────────────────────────
if not failed_symbols:
    LAST_RUN_PATH.write_text(END_DATE.strftime("%Y-%m-%d"))
    print(f"\n      last_run_date.txt updated : {END_DATE}")
else:
    print(f"\n      last_run_date.txt NOT updated -- {len(failed_symbols)} symbols still failing")

# ── Summary ───────────────────────────────────────
print("\n" + "=" * 60)
print("SUMMARY")
print(f"  Total symbols       : {len(SYMBOLS)}")
print("  In universe         : {}".format(universe["in_universe"].sum()))
print(f"  Failed after retries: {len(failed_symbols)}")
if failed_symbols:
    print(f"  Failed symbols      : {list(failed_symbols.keys())}")
print("=" * 60)
