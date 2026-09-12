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
nse_parser.py — NSE File Parser
==================================
Reads NSE daily CSV files and returns clean pandas DataFrames.
Called by nse_loader.py to process each day's downloaded files.

Functions:
    parse_bhavdata(file_path)   → EQ stocks: OHLCV + delivery
    parse_reg_ind(file_path)    → Blacklisted symbols set
    parse_cmvolt(file_path)     → Volatility per stock
    parse_52wk(file_path)       → 52-week high/low per stock
    parse_pe(file_path)         → P/E ratio per stock
    parse_mcap(file_path)       → Market cap per stock
    parse_ind_close(file_path)  → Index OHLCV (sector context)
    parse_all(day_folder, date) → Parse all files for one day

Usage:
    from nse_parser import parse_bhavdata, parse_all
    df = parse_bhavdata("nse_data/2026/03/05/sec_bhavdata_full_05032026.csv")
    print(df.head())
"""

import glob
import logging
import os
import sys
from datetime import date, datetime

import pandas as pd

# ── Logging Setup ─────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.FileHandler("logs/parser.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
# HELPER — File Finder
# ═════════════════════════════════════════════════════════════


def find_file(folder: str, pattern: str) -> str | None:
    """
    Find a file matching pattern inside folder.
    Returns full path or None if not found.

    Example:
        find_file("nse_data/2026/03/05", "sec_bhavdata_full_*.csv")
    """
    matches = glob.glob(os.path.join(folder, pattern))
    if matches:
        return matches[0]
    return None


# ═════════════════════════════════════════════════════════════
# 1. PARSE BHAVDATA — Core price + delivery file
# ═════════════════════════════════════════════════════════════


def parse_bhavdata(file_path: str, trade_date: date | None = None) -> pd.DataFrame | None:
    """
    Parse sec_bhavdata_full_{DDMMYYYY}.csv

    Returns DataFrame with columns:
        symbol, date, prev_close, open, high, low,
        close, avg_price, volume, turnover_lacs,
        trades, delivery_qty, delivery_pct

    Filters:
        - Only Series = EQ (mainboard equity)
        - Drops rows with missing close price
        - Strips whitespace from all string columns

    Args:
        file_path  : Full path to sec_bhavdata_full CSV
        trade_date : Date of trading (used if not in filename)

    Returns:
        DataFrame or None if file not found / parse error
    """
    if not os.path.exists(file_path):
        log.warning(f"Bhavdata file not found: {file_path}")
        return None

    try:
        # Read CSV
        df = pd.read_csv(file_path, skipinitialspace=True)

        # ── Clean column names ──
        df.columns = [c.strip().upper() for c in df.columns]

        # ── Check required columns exist ──
        required = ["SYMBOL", "SERIES", "CLOSE_PRICE"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            log.error(f"Missing columns in bhavdata: {missing} | File: {file_path}")
            return None

        # ── Strip whitespace from string columns ──
        str_cols = df.select_dtypes(include=["object"]).columns
        for col in str_cols:
            df[col] = df[col].str.strip()

        # ── Filter EQ series only ──
        df = df[df["SERIES"] == "EQ"].copy()

        if df.empty:
            log.warning(f"No EQ series rows found in: {file_path}")
            return None

        # ── Parse date ──
        if "DATE1" in df.columns:
            df["date"] = pd.to_datetime(df["DATE1"], format="%d-%b-%Y", errors="coerce")
        elif trade_date:
            df["date"] = pd.to_datetime(trade_date)
        else:
            # Extract date from filename: sec_bhavdata_full_05032026.csv
            fname = os.path.basename(file_path)
            date_str = fname.replace("sec_bhavdata_full_", "").replace(".csv", "")
            df["date"] = pd.to_datetime(date_str, format="%d%m%Y", errors="coerce")

        # ── Rename + select columns ──
        col_map = {
            "SYMBOL": "symbol",
            "PREV_CLOSE": "prev_close",
            "OPEN_PRICE": "open",
            "HIGH_PRICE": "high",
            "LOW_PRICE": "low",
            "LAST_PRICE": "last_price",
            "CLOSE_PRICE": "close",
            "AVG_PRICE": "avg_price",
            "TTL_TRD_QNTY": "volume",
            "TURNOVER_LACS": "turnover_lacs",
            "NO_OF_TRADES": "trades",
            "DELIV_QTY": "delivery_qty",
            "DELIV_PER": "delivery_pct",
        }

        # Only rename columns that actually exist
        existing_map = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing_map)

        # ── Select final columns (avoid duplicates) ──
        final_cols = ["symbol", "date"] + [
            v for v in col_map.values() if v in df.columns and v not in ["symbol", "date"]
        ]
        df = df[final_cols]

        # ── Convert numeric columns ──
        numeric_cols = [
            "prev_close",
            "open",
            "high",
            "low",
            "last_price",
            "close",
            "avg_price",
            "volume",
            "turnover_lacs",
            "trades",
            "delivery_qty",
            "delivery_pct",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # ── Drop rows with no close price ──
        before = len(df)
        df = df.dropna(subset=["close"])
        after = len(df)
        if before != after:
            log.info(f"Dropped {before - after} rows with missing close price")

        # ── Reset index ──
        df = df.reset_index(drop=True)

        log.info(f"Bhavdata parsed: {len(df)} EQ stocks | {file_path}")
        return df

    except Exception as e:
        log.exception(f"Error parsing bhavdata: {e} | File: {file_path}")
        return None


# ═════════════════════════════════════════════════════════════
# 2. PARSE REG_IND — Regulatory blacklist
# ═════════════════════════════════════════════════════════════


def parse_reg_ind(file_path: str) -> set | None:
    """
    Parse REG_IND{DDMMYYYY}.csv

    Returns a SET of blacklisted symbols.
    A stock is blacklisted if ANY of these flags = 1:
        GSM, Long_Term_ASM, Short_Term_ASM,
        IRP (Insolvency), Default, ESM

    Value of 1 = FLAGGED (dangerous)
    Value of 100 = Clean (safe)

    Args:
        file_path : Full path to REG_IND CSV

    Returns:
        Set of blacklisted symbol strings, or None on error
    """
    if not os.path.exists(file_path):
        log.warning(f"REG_IND file not found: {file_path}")
        return None

    try:
        df = pd.read_csv(file_path, skipinitialspace=True)
        df.columns = [c.strip() for c in df.columns]

        # ── Identify flag columns ──
        # These are the dangerous flags — value = 1 means flagged
        flag_cols = [
            "GSM",
            "Long_Term_Additional_Surveillance_Measure (Long Term ASM)",
            "Short_Term_Additional_Surveillance_Measure (Short Term ASM)",
            "Insolvency_Resolution_Process(IRP)",
            "Default",
            "ESM",
        ]

        # Only use columns that exist in this file
        existing_flags = [c for c in flag_cols if c in df.columns]

        if "Symbol" not in df.columns:
            log.error(f"No Symbol column in REG_IND: {file_path}")
            return None

        # ── Find blacklisted stocks ──
        # A stock is flagged if any flag column has value = 1
        if existing_flags:
            flagged_mask = df[existing_flags].apply(lambda row: any(str(v).strip() == "1" for v in row), axis=1)
            blacklisted = set(df.loc[flagged_mask, "Symbol"].str.strip().tolist())
        else:
            blacklisted = set()

        log.info(f"REG_IND parsed: {len(df)} stocks | {len(blacklisted)} blacklisted | {file_path}")
        return blacklisted

    except Exception as e:
        log.exception(f"Error parsing REG_IND: {e} | File: {file_path}")
        return None


# ═════════════════════════════════════════════════════════════
# 3. PARSE CMVOLT — Volatility per stock
# ═════════════════════════════════════════════════════════════


def parse_cmvolt(file_path: str) -> pd.DataFrame | None:
    """
    Parse CMVOLT_{DDMMYYYY}.CSV

    Returns DataFrame with columns:
        symbol, date, daily_vol, annual_vol

    annual_vol > 1.5 means annualised volatility > 150%
    These stocks are too erratic for 1-3 month holds.

    Args:
        file_path : Full path to CMVOLT CSV

    Returns:
        DataFrame or None on error
    """
    if not os.path.exists(file_path):
        log.warning(f"CMVOLT file not found: {file_path}")
        return None

    try:
        df = pd.read_csv(file_path, skipinitialspace=True)

        # CMVOLT columns (positional):
        # Date, Symbol, Close, PrevClose, LogReturn,
        # PrevDailyVol, CurrentDailyVol(E), AnnualisedVol(F)
        df.columns = [c.strip() for c in df.columns]

        # Rename to standard names
        # Column F = Annualised Volatility = last column
        col_map = {}
        cols = list(df.columns)

        if len(cols) >= 8:
            col_map = {
                cols[0]: "date",
                cols[1]: "symbol",
                cols[6]: "daily_vol",
                cols[7]: "annual_vol",
            }
        elif "Symbol" in cols:
            # Fallback if headers differ
            col_map = {"Symbol": "symbol"}
            if len(cols) >= 8:
                col_map[cols[7]] = "annual_vol"
                col_map[cols[6]] = "daily_vol"

        df = df.rename(columns=col_map)

        # Select only needed columns
        keep = [c for c in ["symbol", "date", "daily_vol", "annual_vol"] if c in df.columns]
        df = df[keep]

        # Clean
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str).str.strip()
        if "annual_vol" in df.columns:
            df["annual_vol"] = pd.to_numeric(df["annual_vol"], errors="coerce")
        if "daily_vol" in df.columns:
            df["daily_vol"] = pd.to_numeric(df["daily_vol"], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)

        df = df.dropna(subset=["symbol"])
        df = df.reset_index(drop=True)

        log.info(f"CMVOLT parsed: {len(df)} stocks | {file_path}")
        return df

    except Exception as e:
        log.exception(f"Error parsing CMVOLT: {e} | File: {file_path}")
        return None


# ═════════════════════════════════════════════════════════════
# 4. PARSE 52-WEEK HIGH/LOW
# ═════════════════════════════════════════════════════════════


def parse_52wk(file_path: str) -> pd.DataFrame | None:
    """
    Parse CM_52_wk_High_low_{DDMMYYYY}.csv

    Returns DataFrame with columns:
        symbol, week52_high, week52_low

    Values are ADJUSTED for corporate actions (bonus/split/rights).
    Use week52_high to detect breakout stocks.

    Args:
        file_path : Full path to 52W H/L CSV

    Returns:
        DataFrame or None on error
    """
    if not os.path.exists(file_path):
        log.warning(f"52W file not found: {file_path}")
        return None

    try:
        # First 2 rows are disclaimer text — skip them
        df = pd.read_csv(file_path, skiprows=2, skipinitialspace=True)
        df.columns = [c.strip().strip('"') for c in df.columns]

        col_map = {
            "SYMBOL": "symbol",
            "Adjusted_52_Week_High": "week52_high",
            "Adjusted_52_Week_Low": "week52_low",
        }

        existing = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing)

        keep = [c for c in ["symbol", "week52_high", "week52_low"] if c in df.columns]
        df = df[keep]

        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str).str.strip().str.strip('"')
        if "week52_high" in df.columns:
            df["week52_high"] = pd.to_numeric(df["week52_high"], errors="coerce")
        if "week52_low" in df.columns:
            df["week52_low"] = pd.to_numeric(df["week52_low"], errors="coerce")

        # Keep EQ series only if SERIES column exists
        if "SERIES" in df.columns:
            df = df[df["SERIES"].str.strip() == "EQ"]

        df = df.dropna(subset=["symbol"]).reset_index(drop=True)

        log.info(f"52W H/L parsed: {len(df)} stocks | {file_path}")
        return df

    except Exception as e:
        log.exception(f"Error parsing 52W file: {e} | File: {file_path}")
        return None


# ═════════════════════════════════════════════════════════════
# 5. PARSE PE RATIOS
# ═════════════════════════════════════════════════════════════


def parse_pe(file_path: str) -> pd.DataFrame | None:
    """
    Parse PE_{DDMMYY}.csv

    Returns DataFrame with columns:
        symbol, pe_ratio (adjusted P/E)

    pe_ratio > 80 = caution flag in scanner output.

    Args:
        file_path : Full path to PE CSV

    Returns:
        DataFrame or None on error
    """
    if not os.path.exists(file_path):
        log.warning(f"PE file not found: {file_path}")
        return None

    try:
        df = pd.read_csv(file_path, skipinitialspace=True)
        df.columns = [c.strip() for c in df.columns]

        col_map = {
            "SYMBOL": "symbol",
            "ADJUSTED P/E": "pe_ratio",
            "SYMBOL P/E": "pe_symbol",
        }

        existing = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing)

        # Use adjusted P/E if available, else symbol P/E
        if "pe_ratio" not in df.columns and "pe_symbol" in df.columns:
            df = df.rename(columns={"pe_symbol": "pe_ratio"})

        keep = [c for c in ["symbol", "pe_ratio"] if c in df.columns]
        df = df[keep]

        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str).str.strip()
        if "pe_ratio" in df.columns:
            df["pe_ratio"] = pd.to_numeric(df["pe_ratio"], errors="coerce")

        df = df.dropna(subset=["symbol"]).reset_index(drop=True)

        log.info(f"PE parsed: {len(df)} stocks | {file_path}")
        return df

    except Exception as e:
        log.exception(f"Error parsing PE: {e} | File: {file_path}")
        return None


# ═════════════════════════════════════════════════════════════
# 6. PARSE INDEX CLOSE — Sector context
# ═════════════════════════════════════════════════════════════


def parse_ind_close(file_path: str) -> pd.DataFrame | None:
    """
    Parse ind_close_all_{DDMMYYYY}.csv

    Returns DataFrame with columns:
        index_name, date, open, high, low, close,
        change_pct, volume, pe, pb, div_yield

    Use change_pct to identify which sectors are bullish today.

    Args:
        file_path : Full path to ind_close_all CSV

    Returns:
        DataFrame or None on error
    """
    if not os.path.exists(file_path):
        log.warning(f"ind_close file not found: {file_path}")
        return None

    try:
        df = pd.read_csv(file_path, skipinitialspace=True)
        df.columns = [c.strip() for c in df.columns]

        col_map = {
            "Index Name": "index_name",
            "Index Date": "date",
            "Open Index Value": "open",
            "High Index Value": "high",
            "Low Index Value": "low",
            "Closing Index Value": "close",
            "Change(%)": "change_pct",
            "Volume": "volume",
            "P/E": "pe",
            "P/B": "pb",
            "Div Yield": "div_yield",
        }

        existing = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing)

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)

        num_cols = ["open", "high", "low", "close", "change_pct", "pe", "pb", "div_yield"]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.reset_index(drop=True)

        log.info(f"Index close parsed: {len(df)} indices | {file_path}")
        return df

    except Exception as e:
        log.exception(f"Error parsing ind_close: {e} | File: {file_path}")
        return None


# ═════════════════════════════════════════════════════════════
# 7. PARSE ALL — Master function for one trading day
# ═════════════════════════════════════════════════════════════


def parse_all(day_folder: str, trade_date: date) -> dict:
    """
    Parse all available files for a single trading day.
    Automatically finds files by pattern in the day folder.

    Args:
        day_folder  : Path like "nse_data/2026/03/05"
        trade_date  : datetime.date object

    Returns:
        Dictionary with keys:
            "bhavdata"  → DataFrame (EQ stocks OHLCV + delivery)
            "blacklist" → Set of blacklisted symbols
            "volatility"→ DataFrame (annual vol per stock)
            "week52"    → DataFrame (52W H/L)
            "pe"        → DataFrame (P/E per stock)
            "ind_close" → DataFrame (index performance)

        Any key will be None if that file was not found.

    Example:
        from datetime import date
        result = parse_all("nse_data/2026/03/05", date(2026,3,5))
        df = result["bhavdata"]
        print(f"Stocks loaded: {len(df)}")
    """
    fmt_long = trade_date.strftime("%d%m%Y")  # 05032026
    fmt_short = trade_date.strftime("%d%m%y")  # 050326

    result = {
        "bhavdata": None,
        "blacklist": None,
        "volatility": None,
        "week52": None,
        "pe": None,
        "ind_close": None,
    }

    log.info(f"Parsing all files for: {trade_date} | Folder: {day_folder}")

    # ── 1. Bhavdata (MOST IMPORTANT) ──
    f = find_file(day_folder, f"sec_bhavdata_full_{fmt_long}.csv")
    if f:
        result["bhavdata"] = parse_bhavdata(f, trade_date)
    else:
        log.warning(f"sec_bhavdata_full not found for {trade_date}")

    # ── 2. Regulatory blacklist ──
    # REG_IND uses DDMMYY (short) format in filename
    f = find_file(day_folder, f"REG_IND{fmt_long}.csv")
    if not f:
        f = find_file(day_folder, f"REG_IND{fmt_short}.csv")
    if f:
        result["blacklist"] = parse_reg_ind(f)
    else:
        log.warning(f"REG_IND not found for {trade_date}")

    # ── 3. Volatility ──
    f = find_file(day_folder, f"CMVOLT_{fmt_long}.CSV")
    if not f:
        f = find_file(day_folder, f"CMVOLT_{fmt_long}.csv")
    if f:
        result["volatility"] = parse_cmvolt(f)
    else:
        log.warning(f"CMVOLT not found for {trade_date}")

    # ── 4. 52-week high/low ──
    f = find_file(day_folder, f"CM_52_wk_High_low_{fmt_long}.csv")
    if f:
        result["week52"] = parse_52wk(f)
    else:
        log.warning(f"CM_52_wk_High_low not found for {trade_date}")

    # ── 5. PE ratios ──
    f = find_file(day_folder, f"PE_{fmt_short}.csv")
    if f:
        result["pe"] = parse_pe(f)
    else:
        log.warning(f"PE file not found for {trade_date}")

    # ── 6. Index closes ──
    f = find_file(day_folder, f"ind_close_all_{fmt_long}.csv")
    if f:
        result["ind_close"] = parse_ind_close(f)
    else:
        log.warning(f"ind_close_all not found for {trade_date}")

    # ── Summary ──
    found = [k for k, v in result.items() if v is not None]
    missing = [k for k, v in result.items() if v is None]
    log.info(f"Parse complete | Found: {found} | Missing: {missing}")

    return result


# ═════════════════════════════════════════════════════════════
# QUICK TEST — Run this file directly to verify parser works
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from datetime import date

    print("=" * 60)
    print("  nse_parser.py -- Self Test")
    print("=" * 60)

    TEST_DATE = date(2026, 3, 5)
    TEST_FOLDER = os.path.join("nse_data", "2026", "03", "05")

    if not os.path.exists(TEST_FOLDER):
        print(f"\n  Test folder not found: {TEST_FOLDER}")
        print("  Run the downloader first:")
        print("  python nse_historical_downloader.py --date 05-03-2026")
        sys.exit(1)

    print(f"\n  Testing with: {TEST_DATE}")
    print(f"  Folder: {TEST_FOLDER}\n")

    results = parse_all(TEST_FOLDER, TEST_DATE)

    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)

    df = results["bhavdata"]
    if df is not None:
        print(f"\n  PASS  Bhavdata: {len(df)} EQ stocks")
        print(f"        Columns : {list(df.columns)}")
        print("        Sample  :")
        print(df[["symbol", "close", "volume", "delivery_pct"]].head(5).to_string(index=False))
    else:
        print("  FAIL  Bhavdata")

    bl = results["blacklist"]
    if bl is not None:
        print(f"\n  PASS  Blacklist: {len(bl)} flagged stocks")
        print(f"        Sample  : {list(bl)[:5]}")
    else:
        print("  FAIL  Blacklist (REG_IND not downloaded yet)")

    vdf = results["volatility"]
    if vdf is not None:
        print(f"\n  PASS  Volatility: {len(vdf)} stocks")
        if "annual_vol" in vdf.columns:
            high_vol = vdf[vdf["annual_vol"] > 1.5]
            print(f"        High vol stocks (>150%): {len(high_vol)}")
    else:
        print("  SKIP  Volatility (CMVOLT not downloaded -- needs bundle ZIP)")

    wdf = results["week52"]
    if wdf is not None:
        print(f"\n  PASS  52W H/L: {len(wdf)} stocks")
    else:
        print("  SKIP  52W H/L (needs bundle ZIP)")

    pdf = results["pe"]
    if pdf is not None:
        print(f"\n  PASS  PE: {len(pdf)} stocks")
    else:
        print("  SKIP  PE ratios (needs bundle ZIP)")

    idf = results["ind_close"]
    if idf is not None:
        print(f"\n  PASS  Index closes: {len(idf)} indices")
        if "change_pct" in idf.columns and "index_name" in idf.columns:
            top = idf.nlargest(3, "change_pct")[["index_name", "change_pct"]]
            print("        Top 3 gainers:")
            print(top.to_string(index=False))
    else:
        print("  FAIL  Index closes")

    print("\n" + "=" * 60)
    ok = sum(1 for v in results.values() if v is not None)
    total = len(results)
    core_ok = results["bhavdata"] is not None and results["ind_close"] is not None
    print(f"  {ok}/{total} files parsed")
    if core_ok:
        print("  PASS -- Core files ready. Loader can be built.")
        print("  NOTE -- CMVOLT/PE/52W need bundle ZIP from NSE website.")
    else:
        print("  FAIL -- Core files missing. Check downloader.")
    print("=" * 60)
