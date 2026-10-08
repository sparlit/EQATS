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
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


def execute_request_with_retry(req, max_retries=5, initial_backoff=2):
    """
    Execute an urllib request with exponential backoff for transient issues.
    """
    for attempt in range(1, max_retries + 1):
        try:
            # Set a timeout for the connection to avoid hanging indefinitely
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except Exception as e:
            is_transient = True
            # If it's an HTTPError, check the status code
            if isinstance(e, urllib.error.HTTPError):
                # Client errors (except 429) are usually not transient, so do not retry
                if 400 <= e.code < 500 and e.code != 429:
                    is_transient = False

            if not is_transient or attempt == max_retries:
                raise e

            backoff = initial_backoff * (2 ** (attempt - 1))
            print(
                f"⚠️ JSONBin request failed: {e}. Retrying attempt {attempt}/{max_retries} in {backoff}s...",
                file=sys.stderr,
            )
            time.sleep(backoff)


# Suppress stdout/stderr to prevent yfinance/pandas output from corrupting stdout JSON
@contextmanager
def suppress_output():
    with open(os.devnull, "w") as devnull:
        old_out = sys.stdout
        old_err = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_out
            sys.stderr = old_err


def main():
    parser = argparse.ArgumentParser(
        description="Automate EOD Breadth and Nifty calculation and sync to JSONBin."
    )
    parser.add_argument(
        "--date", type=str, default="today", help="Date in YYYY-MM-DD format or 'today'"
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push data directly to JSONBin.io (requires env variables)",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "ind_nifty500list.csv")

    if not os.path.exists(csv_path):
        print(json.dumps({"error": f"Ticker list CSV not found at {csv_path}"}), file=sys.stderr)
        sys.exit(1)

    # 1. Load tickers
    try:
        df_tickers = pd.read_csv(csv_path)
        raw_symbols = df_tickers["Symbol"].dropna().tolist()
        symbols = [s.strip() for s in raw_symbols if s.strip() and not s.startswith("DUMMY")]
        yf_tickers = [s + ".NS" for s in symbols]
    except Exception as e:
        print(json.dumps({"error": f"Failed to load ticker list: {str(e)}"}), file=sys.stderr)
        sys.exit(1)

    # 2. Determine target date
    # Download a small slice of ^NSEI to find the latest trading day
    today_dt = datetime.now()
    start_search = today_dt - timedelta(days=10)

    with suppress_output():
        nifty_meta = yf.download(
            "^NSEI", start=start_search, end=today_dt + timedelta(days=2), progress=False
        )

    if nifty_meta.empty:
        print(
            json.dumps({"error": "Failed to download Nifty 50 metadata from Yahoo Finance"}),
            file=sys.stderr,
        )
        sys.exit(1)

    if isinstance(nifty_meta.columns, pd.MultiIndex):
        nifty_meta.columns = nifty_meta.columns.get_level_values(0)
    # Convert Nifty index to date index
    nifty_meta.index = pd.to_datetime(nifty_meta.index).date

    if args.date == "today":
        target_date = nifty_meta.index[-1]
    else:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(
                json.dumps({"error": f"Invalid date format: {args.date}. Must be YYYY-MM-DD"}),
                file=sys.stderr,
            )
            sys.exit(1)

    # Check if target date exists in Nifty trading days
    if target_date not in nifty_meta.index:
        # Find the closest preceding trading day
        preceding_days = [d for d in nifty_meta.index if d <= target_date]
        if not preceding_days:
            print(
                json.dumps({"error": f"No trading days found on or before {target_date}"}),
                file=sys.stderr,
            )
            sys.exit(1)
        target_date = preceding_days[-1]

    # 3. Calculate data windows
    # Needs 400 days to calculate 200 SMA and 252-day high/low safely
    start_date = target_date - timedelta(days=400)
    end_date = target_date + timedelta(days=2)

    # 4. Fetch Nifty 50 and Nifty 500 components in parallel
    with suppress_output():
        # Fetch Nifty 50
        nifty_history = yf.download("^NSEI", start=start_date, end=end_date, progress=False)
        nifty_history.index = pd.to_datetime(nifty_history.index).date
        if isinstance(nifty_history.columns, pd.MultiIndex):
            nifty_history.columns = nifty_history.columns.get_level_values(0)

        # Fetch Nifty 500
        stocks_data = yf.download(
            yf_tickers,
            start=start_date,
            end=end_date,
            group_by="ticker",
            threads=True,
            progress=False,
        )

    # 5. Process Nifty 50 metrics
    if target_date not in nifty_history.index:
        print(
            json.dumps({"error": f"Target date {target_date} missing in Nifty 50 history"}),
            file=sys.stderr,
        )
        sys.exit(1)

    nifty_row = nifty_history.loc[target_date]
    nifty_close = round(float(nifty_row["Close"]), 2)
    nifty_low = round(float(nifty_row["Low"]), 2)

    # Calculate Nifty 50 volume by summing constituent volumes
    nifty50_symbols = []
    try:
        nifty50_url = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
        req = urllib.request.Request(
            nifty50_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req) as response:
            content = response.read().decode("utf-8")
            df_nifty50 = pd.read_csv(io.StringIO(content))
            nifty50_symbols = [s.strip() for s in df_nifty50["Symbol"].dropna().tolist()]
    except Exception:
        # Fallback list if the download fails
        nifty50_symbols = [
            "ADANIENT",
            "ADANIPORTS",
            "APOLLOHOSP",
            "ASIANPAINT",
            "AXISBANK",
            "BAJAJ-AUTO",
            "BAJFINANCE",
            "BAJAJFINSV",
            "BEL",
            "BPCL",
            "BHARTIARTL",
            "BRITANNIA",
            "CIPLA",
            "COALINDIA",
            "DIVISLAB",
            "DRREDDY",
            "EICHERMOT",
            "GRASIM",
            "HCLTECH",
            "HDFCBANK",
            "HDFCLIFE",
            "HEROMOTOCO",
            "HINDALCO",
            "HINDUNILVR",
            "ICICIBANK",
            "ITC",
            "INDUSINDBK",
            "INFY",
            "JSWSTEEL",
            "KOTAKBANK",
            "LTIM",
            "LT",
            "M&M",
            "MARUTI",
            "NTPC",
            "NESTLEIND",
            "ONGC",
            "POWERGRID",
            "RELIANCE",
            "SBILIFE",
            "SHRIRAMFIN",
            "SBIN",
            "SUNPHARMA",
            "TCS",
            "TATACONSUM",
            "TATAMOTORS",
            "TATASTEEL",
            "TECHM",
            "TITAN",
            "ULTRACEMCO",
            "WIPRO",
        ]

    nifty_vol_raw = 0.0
    for s in nifty50_symbols:
        ticker = s + ".NS"
        if ticker in stocks_data.columns.levels[0]:
            df_stock = stocks_data[ticker].dropna(subset=["Volume"])
            if not df_stock.empty:
                df_stock.index = pd.to_datetime(df_stock.index).date
                if target_date in df_stock.index:
                    vol_val = df_stock.loc[target_date, "Volume"]
                    if isinstance(vol_val, pd.Series):
                        vol_val = vol_val.iloc[0]
                    nifty_vol_raw += float(vol_val)

    nifty_vol = round(nifty_vol_raw / 1e7, 2) if nifty_vol_raw > 0 else 0.0

    # 6. Process Nifty 500 stocks
    advances = 0
    declines = 0
    unchanged = 0
    highs_52w = 0
    lows_52w = 0
    above_sma20 = 0
    above_sma50 = 0
    above_sma200 = 0
    total_valid_stocks = 0

    for sym in symbols:
        ticker = sym + ".NS"
        if ticker not in stocks_data.columns.levels[0]:
            continue

        df = stocks_data[ticker].dropna(subset=["Close"])
        if df.empty:
            continue

        df.index = pd.to_datetime(df.index).date
        if target_date not in df.index:
            continue

        # Get location index of target date
        idx = df.index.get_loc(target_date)
        if idx < 1:  # Need at least one preceding row for previous close
            continue

        total_valid_stocks += 1
        close = float(df["Close"].iloc[idx])
        prev_close = float(df["Close"].iloc[idx - 1])
        high = float(df["High"].iloc[idx])
        low = float(df["Low"].iloc[idx])

        # Advances / Declines
        if close > prev_close:
            advances += 1
        elif close < prev_close:
            declines += 1
        else:
            unchanged += 1

        # 52W High / Low
        # Look back 252 trading days including target date
        window_start = max(0, idx - 251)
        window = df.iloc[window_start : idx + 1]

        hist_high = float(window["High"].max())
        hist_low = float(window["Low"].min())

        if high >= hist_high:
            highs_52w += 1
        if low <= hist_low:
            lows_52w += 1

        # Indicators
        # Calculated on the full history to keep SMA continuous and stable
        sma20_series = df["Close"].rolling(window=20).mean()
        sma50_series = df["Close"].rolling(window=50).mean()
        sma200_series = df["Close"].rolling(window=200).mean()

        if pd.notna(sma20_series.iloc[idx]) and close > sma20_series.iloc[idx]:
            above_sma20 += 1
        if pd.notna(sma50_series.iloc[idx]) and close > sma50_series.iloc[idx]:
            above_sma50 += 1
        if pd.notna(sma200_series.iloc[idx]) and close > sma200_series.iloc[idx]:
            above_sma200 += 1

    if total_valid_stocks == 0:
        print(json.dumps({"error": "No valid stocks processed"}), file=sys.stderr)
        sys.exit(1)

    # MA Breadth percentages (round to 1 decimal place)
    e20 = round((above_sma20 / total_valid_stocks) * 100, 1)
    s50 = round((above_sma50 / total_valid_stocks) * 100, 1)
    s200 = round((above_sma200 / total_valid_stocks) * 100, 1)

    # 7. Calculate Composite Score and Zone
    # Exact replica of calcScore(r) and getZone(s) from index.html
    adv_pct = (advances / (advances + declines) * 100) if (advances + declines) > 0 else 0.0
    hl_pct = (highs_52w / (highs_52w + lows_52w) * 100) if (highs_52w + lows_52w) > 0 else 50.0
    sma_pct = (e20 + s50 + s200) / 3.0
    score = min(100, max(0, int(round(adv_pct * 0.35 + hl_pct * 0.15 + sma_pct * 0.50))))

    # Get Zone
    if score >= 55:
        zone = "HEALTHY"
        r_val = "2–3R"
    elif score >= 45:
        zone = "EXPANDING"
        r_val = "1–2R"
    elif score >= 35:
        zone = "CAUTION"
        r_val = "0.5–1R"
    elif score >= 20:
        zone = "DEFENSIVE"
        r_val = "0.25R pilot"
    else:
        zone = "CORRECTION"
        r_val = "0R — stand aside"

    # Assemble today's record
    target_date_str = target_date.strftime("%Y-%m-%d")
    record = {
        "date": target_date_str,
        "adv": advances,
        "dec": declines,
        "unc": unchanged,
        "hi": highs_52w,
        "lo": lows_52w,
        "e20": e20,
        "s50": s50,
        "s200": s200,
        "nifty": nifty_close,
        "niftyLow": nifty_low,
        "vol": nifty_vol,
        "notes": "",
        "_updatedAt": int(datetime.now().timestamp() * 1000),
        "score": score,
        "zone": zone,
        "r": r_val,
    }

    # Output JSON directly to stdout
    if not args.push:
        print(json.dumps(record, indent=2))
        return

    # 8. Push to JSONBin.io (Option A)
    bin_id = os.environ.get("JSONBIN_BIN") or os.environ.get("JSONBIN_ID")
    master_key = os.environ.get("JSONBIN_KEY") or os.environ.get("JSONBIN_MASTER_KEY")

    if bin_id:
        bin_id = bin_id.strip()
    if master_key:
        master_key = master_key.strip()

    if not bin_id or not master_key:
        print(
            json.dumps(
                {
                    "error": "JSONBIN_BIN (or JSONBIN_ID) and JSONBIN_KEY (or JSONBIN_MASTER_KEY) environment variables must be set for --push"
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Fetching current bin data from JSONBin (Bin: {bin_id})...")
    url = f"https://api.jsonbin.io/v3/b/{bin_id}/latest"
    req = urllib.request.Request(
        url,
        headers={
            "X-Master-Key": master_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    )

    try:
        response_bytes = execute_request_with_retry(req)
        payload = json.loads(response_bytes.decode("utf-8"))["record"]
    except Exception as e:
        print(
            json.dumps({"warning": f"Skipping JSONBin sync. Failed to fetch data: {str(e)}"}),
            file=sys.stderr,
        )
        # Exit with 0 to allow the rest of the daily scanner workflow (VCP scanner and Git commit) to succeed
        sys.exit(0)

    # Ensure records exists
    if "records" not in payload:
        payload["records"] = []
    if "mpm" not in payload:
        payload["mpm"] = []

    # Update records array
    existing_records = payload["records"]
    # Filter out target date
    filtered_records = [r for r in existing_records if r.get("date") != target_date_str]
    filtered_records.append(record)
    # Sort newest first and limit to latest 30 rows as per saveToday()
    filtered_records.sort(key=lambda x: x.get("date", ""), reverse=True)
    payload["records"] = filtered_records[:30]

    # Auto-update MPM array
    nifty_close = float(record["nifty"])
    nifty_vol = float(record["vol"])

    # Get previous record (where nifty and vol are present)
    prev_record = None
    for r in filtered_records:
        if r.get("date") != target_date_str and r.get("nifty") and r.get("vol"):
            prev_record = r
            break

    if prev_record:
        prev_close = float(prev_record["nifty"])
        prev_vol = float(prev_record["vol"])

        dtype = (
            "acc"
            if (nifty_close > prev_close and nifty_vol > prev_vol)
            else "dist"
            if (nifty_close < prev_close and nifty_vol > prev_vol)
            else "neutral"
        )

        # Filter existing mpm entries for target date
        mpm_list = [m for m in payload["mpm"] if m.get("date") != target_date_str]

        # Add new auto MPM entry
        mpm_list.insert(
            0,
            {
                "id": f"eod_{target_date_str}",
                "date": target_date_str,
                "close": nifty_close,
                "pclose": prev_close,
                "vol": nifty_vol,
                "pvol": prev_vol,
                "dtype": dtype,
                "auto": True,
                "_updatedAt": int(datetime.now().timestamp() * 1000),
            },
        )

        # Sort and limit to 150 items as per mpmSave()
        mpm_list.sort(key=lambda x: x.get("date", ""), reverse=True)
        payload["mpm"] = mpm_list[:150]

    # Update timestamp
    payload["_pushedAt"] = int(datetime.now().timestamp() * 1000)

    # Push updated record back
    print("Pushing updated payload to JSONBin...")
    update_url = f"https://api.jsonbin.io/v3/b/{bin_id}"
    update_req = urllib.request.Request(
        update_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Master-Key": master_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
        method="PUT",
    )

    try:
        response_bytes = execute_request_with_retry(update_req)
        json.loads(response_bytes.decode("utf-8"))
        print(f"✅ Success! JSONBin updated. Record for {target_date_str} synced.")
    except Exception as e:
        print(
            json.dumps({"warning": f"Skipping JSONBin sync. Failed to push data: {str(e)}"}),
            file=sys.stderr,
        )
        # Exit with 0 so the daily scanner workflow continues
        sys.exit(0)


if __name__ == "__main__":
    main()
