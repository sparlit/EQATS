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


#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
NSE QUANTITATIVE STOCK SCANNER
==============================

Purpose
-------
Uses ~3 years of NSE daily history to evaluate each stock in two separate ways:

1) NEXT-DAY / INTRADAY WATCHLIST
   - Current technical setup
   - Historical behaviour of similar setups
   - Liquidity / volatility / volume
   - Optional local 5/15-minute confirmation

2) SWING WATCHLIST
   - Current trend quality
   - Historical 5/10/15-session behaviour of similar setups
   - Momentum, volume, volatility and structure

IMPORTANT
---------
This is a research/ranking system, not a guaranteed prediction system.
5x leverage increases both gains and losses.

DATA
----
NSE official daily archive files are used where available.
The program keeps valid files in data/daily and never treats HTML/blocked
responses as market data.

Optional intraday file:
data/intraday/SYMBOL.csv

Columns:
datetime,open,high,low,close,volume

Outputs:
output/all_scores.csv
output/next_day_candidates.csv
output/swing_candidates.csv
output/historical_setup_stats.csv
output/scanner_report.xlsx

Run:
    python stock_scanner.py
    python stock_scanner.py --refresh
    python stock_scanner.py --days 1100
"""


import argparse
import io
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# CONFIGURATION
# ============================================================

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DAILY = DATA / "daily"
INTRADAY = DATA / "intraday"
CACHE = DATA / "cache"
OUTPUT = BASE / "output"

for p in (DAILY, INTRADAY, CACHE, OUTPUT):
    p.mkdir(parents=True, exist_ok=True)

NSE_HOME = "https://www.nseindia.com/"
UDIFF_START = date(2024, 7, 8)

WORKERS = 2
TIMEOUT = 35
MAX_RETRIES = 3

MIN_HISTORY = 220
MIN_PRICE = 10.0
MIN_AVG_VALUE = 5_000_000  # Rs 50 lakh
STALE_WARNING_DAYS = 7

# Candidate selection is intentionally less restrictive than the old
# "must have 5/10 aligned factors" approach. The ranking score decides.
NEXT_DAY_COUNT = 30
SWING_COUNT = 30

# Historical matching parameters.
MIN_SIMILAR_SETUPS = 8
HISTORY_LOOKBACK = 760  # approximately 3 years of sessions
FORWARD_HORIZONS = (1, 3, 5, 10, 15)


# ============================================================
# HTTP
# ============================================================


def make_session():
    s = requests.Session()

    retry = Retry(
        total=MAX_RETRIES,
        connect=MAX_RETRIES,
        read=MAX_RETRIES,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=WORKERS,
        pool_maxsize=WORKERS,
    )

    s.mount("https://", adapter)

    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
        }
    )
    return s


SESSION = make_session()


def warm_nse_session():
    try:
        r = SESSION.get(NSE_HOME, timeout=TIMEOUT)
        print(f"NSE homepage: HTTP {r.status_code}")
        return r.status_code == 200
    except Exception as exc:
        print(f"NSE homepage error: {exc}")
        return False


# ============================================================
# GENERAL HELPERS
# ============================================================


def clean_col(x):
    x = str(x).strip().upper()
    x = re.sub(r"[^A-Z0-9]+", "_", x)
    return x.strip("_")


def norm_cols(df):
    df = df.copy()
    df.columns = [clean_col(c) for c in df.columns]
    return df


def col(df, *names):
    lookup = set(df.columns)
    for n in names:
        n = clean_col(n)
        if n in lookup:
            return n
    return None


def num(s):
    return pd.to_numeric(s, errors="coerce")


def safe_float(x, default=np.nan):
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def pct(x, decimals=2):
    if pd.isna(x):
        return np.nan
    return round(float(x), decimals)


# ============================================================
# NSE ARCHIVE URLS
# ============================================================


def old_bhav_url(d: date):
    return (
        "https://nsearchives.nseindia.com/content/historical/"
        f"EQUITIES/{d.year}/{d.strftime('%b').upper()}/"
        f"cm{d.strftime('%d%b%Y').upper()}bhav.csv.zip"
    )


def udiff_url(d: date):
    return f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"


def full_bhav_url(d: date):
    return f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def candidate_urls(d: date):
    if d < UDIFF_START:
        return [
            ("legacy", old_bhav_url(d)),
            ("full", full_bhav_url(d)),
        ]
    return [
        ("udiff", udiff_url(d)),
        ("full", full_bhav_url(d)),
    ]


# ============================================================
# DOWNLOAD / VALIDATION
# ============================================================


def extract_csv_from_zip(content):
    if not content or len(content) < 1000:
        return None

    head = content[:100].lower()
    if b"<html" in head or b"<!doctype" in head:
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                return None
            with z.open(names[0]) as f:
                raw = f.read()

        return raw if len(raw) >= 1000 else None
    except Exception:
        return None


def validate_raw_csv(raw):
    try:
        sample = pd.read_csv(
            io.BytesIO(raw),
            nrows=5,
            low_memory=False,
        )
        sample = norm_cols(sample)

        symbol = col(sample, "SYMBOL", "TCKSYM")
        close = col(sample, "CLOSE", "CLOSE_PRICE")
        high = col(sample, "HIGH", "HIGH_PRICE")
        low = col(sample, "LOW", "LOW_PRICE")

        return bool(symbol and close and high and low)
    except Exception:
        return False


def download_day(d: date, refresh=False):
    filename = DAILY / f"nse_{d:%Y%m%d}.csv"

    if filename.exists() and not refresh:
        try:
            raw = filename.read_bytes()
            if validate_raw_csv(raw):
                return d, True, "cache"
        except Exception:
            pass
        filename.unlink(missing_ok=True)

    for kind, url in candidate_urls(d):
        try:
            r = SESSION.get(
                url,
                timeout=TIMEOUT,
                headers={
                    "Referer": "https://www.nseindia.com/all-reports",
                    "Accept": ("text/csv,application/zip,application/octet-stream,*/*"),
                },
            )

            if r.status_code != 200:
                continue

            raw = r.content if kind == "full" else extract_csv_from_zip(r.content)

            if raw is None or not validate_raw_csv(raw):
                continue

            filename.write_bytes(raw)
            return d, True, kind

        except Exception:
            continue

    return d, False, "not_available"


def trading_weekdays(start, end):
    return [x.date() for x in pd.date_range(start=start, end=end, freq="B")]


def download_history(days, refresh=False):
    end = date.today()
    start = end - timedelta(days=days)
    dates = trading_weekdays(start, end)

    print()
    print("=" * 72)
    print("NSE DAILY HISTORY")
    print("=" * 72)
    print(f"Requested period : {start:%d-%b-%Y} -> {end:%d-%b-%Y}")
    print(f"Weekdays to check: {len(dates):,}")
    print(f"Workers          : {WORKERS}")

    if refresh:
        # Refresh only recent data; do NOT destroy the 3-year cache.
        refresh_from = end - timedelta(days=15)
        requested = [d for d in dates if d >= refresh_from]
        print(f"Refresh period   : {refresh_from:%d-%b-%Y} -> {end:%d-%b-%Y}")
    else:
        requested = dates

    success = downloaded = cached = failed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = [pool.submit(download_day, d, False) for d in requested]

        for i, fut in enumerate(as_completed(jobs), 1):
            _d, ok, mode = fut.result()

            if ok:
                success += 1
                if mode == "cache":
                    cached += 1
                else:
                    downloaded += 1
            else:
                failed += 1

            if i == 1 or i % 25 == 0 or i == len(jobs):
                print(
                    f"Progress: {i:,}/{len(jobs):,} | "
                    f"success={success:,} "
                    f"downloaded={downloaded:,} "
                    f"cached={cached:,} "
                    f"failed={failed:,}",
                    flush=True,
                )

    print()
    print(f"Dates processed : {len(requested):,}")
    print(f"Valid files     : {success:,}")
    print(f"Downloaded      : {downloaded:,}")
    print(f"Cached          : {cached:,}")
    print(f"Unavailable     : {failed:,}")

    if not list(DAILY.glob("nse_*.csv")):
        msg = (
            "\nNSE DOWNLOAD ERROR\n"
            "No valid NSE daily files exist in data/daily.\n"
            "NSE may be temporarily blocking archive requests.\n"
        )
        raise RuntimeError(msg)


# ============================================================
# DAILY NORMALISATION
# ============================================================


def normalize_daily(raw, forced_date):
    if raw.empty:
        return pd.DataFrame()

    raw = norm_cols(raw)

    symbol_c = col(raw, "SYMBOL", "TCKSYM")
    series_c = col(raw, "SERIES", "SERIES_CODE")
    open_c = col(raw, "OPEN", "OPEN_PRICE")
    high_c = col(raw, "HIGH", "HIGH_PRICE")
    low_c = col(raw, "LOW", "LOW_PRICE")
    close_c = col(raw, "CLOSE", "CLOSE_PRICE", "LAST_PRICE")

    volume_c = col(
        raw,
        "TOTTRDQTY",
        "TOTAL_TRADED_QUANTITY",
        "TTL_TRD_QNTY",
        "VOLUME",
    )

    turnover_c = col(
        raw,
        "TOTTRDVAL",
        "TOTAL_TRADED_VALUE",
        "TURNOVER_LACS",
        "TURNOVER",
    )

    delivery_qty_c = col(
        raw,
        "DELIV_QTY",
        "DELIVERY_QTY",
        "DELIVERABLE_QTY",
    )

    delivery_pct_c = col(
        raw,
        "DELIV_PER",
        "DELIVERY_PCT",
        "DELIVERY_PERCENT",
    )

    if not symbol_c or not close_c:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "DATE": pd.Timestamp(forced_date),
            "SYMBOL": (raw[symbol_c].astype(str).str.strip().str.upper()),
            "OPEN": num(raw[open_c]) if open_c else np.nan,
            "HIGH": num(raw[high_c]) if high_c else np.nan,
            "LOW": num(raw[low_c]) if low_c else np.nan,
            "CLOSE": num(raw[close_c]),
            "VOLUME": num(raw[volume_c]) if volume_c else np.nan,
            "TURNOVER": (num(raw[turnover_c]) if turnover_c else np.nan),
            "DELIVERY_QTY": (num(raw[delivery_qty_c]) if delivery_qty_c else np.nan),
            "DELIVERY_PCT": (num(raw[delivery_pct_c]) if delivery_pct_c else np.nan),
        }
    )

    if series_c:
        out["SERIES"] = raw[series_c].astype(str).str.upper().str.strip()
        normal = out[out["SERIES"].isin(["EQ", "BE", "SM"])]
        if not normal.empty:
            out = normal
    else:
        out["SERIES"] = ""

    out = out[out["SYMBOL"].notna() & (out["SYMBOL"] != "") & (out["SYMBOL"] != "NAN") & out["CLOSE"].notna()]

    return out.drop_duplicates(["DATE", "SYMBOL"], keep="last")


def load_all_daily():
    files = sorted(DAILY.glob("nse_*.csv"))

    print()
    print(f"Loading {len(files):,} daily files...")

    frames = []

    for f in files:
        m = re.fullmatch(r"nse_(\d{8})\.csv", f.name)
        if not m:
            continue

        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()

            raw = pd.read_csv(f, low_memory=False)
            df = normalize_daily(raw, d)

            if not df.empty:
                frames.append(df)
        except Exception:
            continue

    if not frames:
        msg = "No valid daily data files could be loaded."
        raise RuntimeError(msg)

    data = pd.concat(frames, ignore_index=True)

    data["DATE"] = pd.to_datetime(data["DATE"])

    data = data.drop_duplicates(["DATE", "SYMBOL"], keep="last").sort_values(["SYMBOL", "DATE"]).reset_index(drop=True)

    latest = data["DATE"].max()
    age = (pd.Timestamp.today().normalize() - latest).days

    print(f"Loaded {len(data):,} observations.")
    print(f"Date range: {data['DATE'].min():%d-%b-%Y} -> {latest:%d-%b-%Y}")

    if age > STALE_WARNING_DAYS:
        print(f"WARNING: latest available NSE session is {age} calendar days old.")
        print("The scanner will analyse the latest AVAILABLE session and will not invent a current/future date.")

    return data


# ============================================================
# INDICATORS
# ============================================================


def EMA(s, n):
    return s.ewm(
        span=n,
        adjust=False,
        min_periods=n,
    ).mean()


def RSI(s, n=14):
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    ag = gain.ewm(
        alpha=1 / n,
        adjust=False,
        min_periods=n,
    ).mean()

    al = loss.ewm(
        alpha=1 / n,
        adjust=False,
        min_periods=n,
    ).mean()

    rs = ag / al.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))

    return out.where(
        ~((al == 0) & (ag > 0)),
        100,
    )


def ATR(df, n=14):
    pc = df["CLOSE"].shift(1)

    tr = pd.concat(
        [
            df["HIGH"] - df["LOW"],
            (df["HIGH"] - pc).abs(),
            (df["LOW"] - pc).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / n,
        adjust=False,
        min_periods=n,
    ).mean()


def MACD(s):
    fast = EMA(s, 12)
    slow = EMA(s, 26)
    line = fast - slow
    signal = EMA(line, 9)
    hist = line - signal
    return line, signal, hist


def add_indicators(df):
    df = df.sort_values("DATE").copy()

    c = df["CLOSE"]
    v = df["VOLUME"].fillna(0)

    df["EMA20"] = EMA(c, 20)
    df["EMA50"] = EMA(c, 50)
    df["EMA200"] = EMA(c, 200)

    df["RSI14"] = RSI(c, 14)

    _, _, mh = MACD(c)
    df["MACD_HIST"] = mh
    df["MACD_DELTA"] = mh.diff()

    df["ATR14"] = ATR(df, 14)
    df["ATR_PCT"] = df["ATR14"] / c.replace(0, np.nan) * 100

    df["VOL20"] = v.rolling(20).mean()
    df["VOL50"] = v.rolling(50).mean()
    df["VOL_RATIO20"] = v / df["VOL20"].replace(0, np.nan)

    df["VWAP20"] = (c * v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)

    df["VWAP_DIST_PCT"] = (c - df["VWAP20"]) / df["VWAP20"].replace(0, np.nan) * 100

    df["PREV_HIGH"] = df["HIGH"].shift(1)
    df["PREV_LOW"] = df["LOW"].shift(1)
    df["PREV_CLOSE"] = c.shift(1)

    df["WEEK_HIGH"] = df["HIGH"].shift(1).rolling(5).max()
    df["WEEK_LOW"] = df["LOW"].shift(1).rolling(5).min()

    df["GAP_PCT"] = (df["OPEN"] - df["PREV_CLOSE"]) / df["PREV_CLOSE"].replace(0, np.nan) * 100

    df["RET1"] = c.pct_change() * 100

    hi20 = df["HIGH"].rolling(20).max()
    lo20 = df["LOW"].rolling(20).min()

    df["RANGE20_POS"] = (c - lo20) / (hi20 - lo20).replace(0, np.nan)

    # Daily range as percentage.
    df["DAY_RANGE_PCT"] = (df["HIGH"] - df["LOW"]) / df["PREV_CLOSE"].replace(0, np.nan) * 100

    # Consecutive streak.
    direction = np.sign(df["RET1"].fillna(0))
    groups = (direction != direction.shift()).cumsum()
    streak = direction.groupby(groups).cumcount() + 1
    df["UP_STREAK"] = np.where(direction > 0, streak, 0)
    df["DOWN_STREAK"] = np.where(direction < 0, streak, 0)

    # Historical 20-day return.
    df["RET5"] = c.pct_change(5) * 100
    df["RET10"] = c.pct_change(10) * 100
    df["RET20"] = c.pct_change(20) * 100

    # Simple rolling realised volatility.
    df["HV20"] = df["RET1"].rolling(20).std() * np.sqrt(252)

    # Relative ATR percentile.
    df["ATR_PCTL"] = df["ATR_PCT"].rolling(120, min_periods=40).rank(pct=True) * 100

    # Relative volume percentile.
    df["VOL_PCTL"] = df["VOL_RATIO20"].rolling(120, min_periods=40).rank(pct=True) * 100

    return df


# ============================================================
# HISTORICAL GAP / BEHAVIOUR STATISTICS
# ============================================================


def historical_stats(df):
    x = df.dropna(subset=["RET1"]).copy()

    if x.empty:
        return {
            "UP_DAY_PCT_3Y": np.nan,
            "DOWN_DAY_PCT_3Y": np.nan,
            "AVG_UP_RETURN_3Y": np.nan,
            "AVG_DOWN_RETURN_3Y": np.nan,
            "AVG_GAP_PCT_3Y": np.nan,
            "UP_GAP_FREQ_3Y": np.nan,
            "DOWN_GAP_FREQ_3Y": np.nan,
            "AVG_UP_GAP_3Y": np.nan,
            "AVG_DOWN_GAP_3Y": np.nan,
            "AVG_GAP_FILL_PCT_3Y": np.nan,
            "MAX_UP_STREAK_3Y": np.nan,
            "MAX_DOWN_STREAK_3Y": np.nan,
        }

    up = x[x["RET1"] > 0]
    down = x[x["RET1"] < 0]

    gaps = x.dropna(subset=["GAP_PCT", "OPEN", "PREV_CLOSE"])

    up_gap = gaps[gaps["GAP_PCT"] >= 1]
    down_gap = gaps[gaps["GAP_PCT"] <= -1]

    # Approximate same-day gap-fill:
    # positive gap: how much of gap back toward previous close was filled.
    # negative gap: same concept in reverse.
    fill_values = []

    for _, r in gaps.iterrows():
        g = float(r["GAP_PCT"])
        if abs(g) < 1:
            continue

        prev_close = safe_float(r["PREV_CLOSE"])
        low = safe_float(r["LOW"])
        high = safe_float(r["HIGH"])

        if pd.isna(prev_close):
            continue

        if g > 0:
            gap_abs = float(r["OPEN"] - prev_close)
            if gap_abs > 0:
                fill = (r["OPEN"] - low) / gap_abs * 100
                fill_values.append(min(max(fill, 0), 100))
        else:
            gap_abs = float(prev_close - r["OPEN"])
            if gap_abs > 0:
                fill = (high - r["OPEN"]) / gap_abs * 100
                fill_values.append(min(max(fill, 0), 100))

    # Streaks.
    direction = np.sign(x["RET1"].fillna(0))
    groups = (direction != direction.shift()).cumsum()
    streak = direction.groupby(groups).cumcount() + 1

    up_streak = streak[direction > 0]
    down_streak = streak[direction < 0]

    return {
        "UP_DAY_PCT_3Y": pct((len(up) / len(x)) * 100),
        "DOWN_DAY_PCT_3Y": pct((len(down) / len(x)) * 100),
        "AVG_UP_RETURN_3Y": pct(up["RET1"].mean()),
        "AVG_DOWN_RETURN_3Y": pct(down["RET1"].mean()),
        "AVG_GAP_PCT_3Y": pct(gaps["GAP_PCT"].mean()),
        "UP_GAP_FREQ_3Y": pct((len(up_gap) / len(gaps)) * 100) if len(gaps) else np.nan,
        "DOWN_GAP_FREQ_3Y": pct((len(down_gap) / len(gaps)) * 100) if len(gaps) else np.nan,
        "AVG_UP_GAP_3Y": pct(up_gap["GAP_PCT"].mean()) if len(up_gap) else np.nan,
        "AVG_DOWN_GAP_3Y": pct(down_gap["GAP_PCT"].mean()) if len(down_gap) else np.nan,
        "AVG_GAP_FILL_PCT_3Y": pct(np.mean(fill_values)) if fill_values else np.nan,
        "MAX_UP_STREAK_3Y": int(up_streak.max()) if len(up_streak) else 0,
        "MAX_DOWN_STREAK_3Y": int(down_streak.max()) if len(down_streak) else 0,
    }


# ============================================================
# HISTORICAL SIMILAR-SETUP ENGINE
# ============================================================


def setup_state(row):
    """
    Compact representation of today's regime.

    We deliberately use broad buckets so historical matching does not
    become over-fitted to one exact RSI or volume value.
    """
    trend = (
        1
        if row["CLOSE"] > row["EMA20"] > row["EMA50"] > row["EMA200"]
        else -1
        if row["CLOSE"] < row["EMA20"] < row["EMA50"] < row["EMA200"]
        else 0
    )

    rsi = safe_float(row["RSI14"])
    if pd.isna(rsi):
        rsi_bucket = "NA"
    elif rsi < 40:
        rsi_bucket = "LOW"
    elif rsi < 52:
        rsi_bucket = "WEAK"
    elif rsi < 62:
        rsi_bucket = "MID"
    elif rsi < 72:
        rsi_bucket = "STRONG"
    else:
        rsi_bucket = "HOT"

    vr = safe_float(row["VOL_RATIO20"])
    if pd.isna(vr):
        vol_bucket = "NA"
    elif vr < 0.8:
        vol_bucket = "LOW"
    elif vr < 1.2:
        vol_bucket = "NORMAL"
    elif vr < 1.8:
        vol_bucket = "HIGH"
    else:
        vol_bucket = "SURGE"

    macd = safe_float(row["MACD_HIST"])
    macd_delta = safe_float(row["MACD_DELTA"])
    if pd.isna(macd) or pd.isna(macd_delta):
        macd_state = "NA"
    elif macd > 0 and macd_delta > 0:
        macd_state = "UP"
    elif macd < 0 and macd_delta < 0:
        macd_state = "DOWN"
    else:
        macd_state = "MIXED"

    vwap = safe_float(row["VWAP_DIST_PCT"])
    if pd.isna(vwap):
        vwap_state = "NA"
    elif vwap > 1:
        vwap_state = "ABOVE"
    elif vwap < -1:
        vwap_state = "BELOW"
    else:
        vwap_state = "NEAR"

    rp = safe_float(row["RANGE20_POS"])
    if pd.isna(rp):
        range_state = "NA"
    elif rp >= 0.75:
        range_state = "HIGH"
    elif rp <= 0.25:
        range_state = "LOW"
    else:
        range_state = "MID"

    return (
        trend,
        rsi_bucket,
        vol_bucket,
        macd_state,
        vwap_state,
        range_state,
    )


def historical_similar_setups(df):
    """
    Look through the previous ~3 years for days whose regime resembles
    today's regime.

    Forward returns are calculated only from information that would have
    been available AFTER that historical setup day. The current day itself
    is excluded from the historical sample.
    """
    if len(df) < MIN_HISTORY:
        return {
            "SIMILAR_SETUPS": 0,
            "HIST_NEXTDAY_WIN_PCT": np.nan,
            "HIST_NEXTDAY_AVG_PCT": np.nan,
            "HIST_3D_WIN_PCT": np.nan,
            "HIST_3D_AVG_PCT": np.nan,
            "HIST_5D_WIN_PCT": np.nan,
            "HIST_5D_AVG_PCT": np.nan,
            "HIST_10D_WIN_PCT": np.nan,
            "HIST_10D_AVG_PCT": np.nan,
            "HIST_15D_WIN_PCT": np.nan,
            "HIST_15D_AVG_PCT": np.nan,
            "HIST_SETUP_QUALITY": "INSUFFICIENT",
        }

    d = df.copy().reset_index(drop=True)

    states = [setup_state(row) for _, row in d.iterrows()]
    state_cols = [
        "STATE_TREND",
        "STATE_RSI",
        "STATE_VOL",
        "STATE_MACD",
        "STATE_VWAP",
        "STATE_RANGE",
    ]

    state_df = pd.DataFrame(states, columns=state_cols)
    d = pd.concat([d, state_df], axis=1)

    # Forward returns from close-to-close.
    for h in FORWARD_HORIZONS:
        d[f"FWD_{h}D"] = d["CLOSE"].shift(-h) / d["CLOSE"] * 100 - 100

    current_state = tuple(states[-1])

    # Last HISTORY_LOOKBACK rows, excluding current day and rows without
    # enough future data.
    end_idx = max(0, len(d) - 1)
    start_idx = max(0, end_idx - HISTORY_LOOKBACK)

    hist = d.iloc[start_idx:end_idx].copy()

    for h in FORWARD_HORIZONS:
        hist = hist[hist[f"FWD_{h}D"].notna()]

    if hist.empty:
        return {
            "SIMILAR_SETUPS": 0,
            "HIST_NEXTDAY_WIN_PCT": np.nan,
            "HIST_NEXTDAY_AVG_PCT": np.nan,
            "HIST_3D_WIN_PCT": np.nan,
            "HIST_3D_AVG_PCT": np.nan,
            "HIST_5D_WIN_PCT": np.nan,
            "HIST_5D_AVG_PCT": np.nan,
            "HIST_10D_WIN_PCT": np.nan,
            "HIST_10D_AVG_PCT": np.nan,
            "HIST_15D_WIN_PCT": np.nan,
            "HIST_15D_AVG_PCT": np.nan,
            "HIST_SETUP_QUALITY": "INSUFFICIENT",
        }

    # Exact broad-state match first.
    mask = (
        (hist["STATE_TREND"] == current_state[0])
        & (hist["STATE_RSI"] == current_state[1])
        & (hist["STATE_VOL"] == current_state[2])
        & (hist["STATE_MACD"] == current_state[3])
        & (hist["STATE_VWAP"] == current_state[4])
        & (hist["STATE_RANGE"] == current_state[5])
    )

    matches = hist[mask].copy()

    # If exact regime is too rare, use a similarity score. This prevents
    # a good stock from being rejected simply because one bucket differs.
    if len(matches) < MIN_SIMILAR_SETUPS:
        weights = {
            "STATE_TREND": 3,
            "STATE_RSI": 2,
            "STATE_VOL": 2,
            "STATE_MACD": 2,
            "STATE_VWAP": 1,
            "STATE_RANGE": 1,
        }

        score = np.zeros(len(hist), dtype=float)

        for c, w in weights.items():
            score += (hist[c].to_numpy() == current_state[state_cols.index(c)]) * w

        hist = hist.copy()
        hist["_SIM_SCORE"] = score

        # At least 6/11 similarity when possible.
        matches = hist[hist["_SIM_SCORE"] >= 6].copy()

        if len(matches) > 100:
            matches = matches.nlargest(100, "_SIM_SCORE")

    n = len(matches)

    out = {"SIMILAR_SETUPS": int(n)}

    for h in FORWARD_HORIZONS:
        s = matches[f"FWD_{h}D"]

        out[f"HIST_{h}D_WIN_PCT"] = pct((s > 0).mean() * 100) if n else np.nan

        out[f"HIST_{h}D_AVG_PCT"] = pct(s.mean()) if n else np.nan

    if n < MIN_SIMILAR_SETUPS:
        quality = "INSUFFICIENT"
    else:
        win5 = safe_float(out["HIST_5D_WIN_PCT"])
        avg5 = safe_float(out["HIST_5D_AVG_PCT"])

        if not pd.isna(win5) and not pd.isna(avg5):
            if win5 >= 65 and avg5 > 0:
                quality = "STRONG"
            elif win5 >= 55 and avg5 > 0:
                quality = "POSITIVE"
            elif win5 < 45 and avg5 < 0:
                quality = "NEGATIVE"
            else:
                quality = "MIXED"
        else:
            quality = "MIXED"

    out["HIST_SETUP_QUALITY"] = quality
    return out


# ============================================================
# CURRENT TECHNICAL SCORE
# ============================================================


def current_factors(df):
    x = df.iloc[-1]
    p = df.iloc[-2]

    factors = {}

    # Trend
    trend = 0
    trend += 1 if x["CLOSE"] > x["EMA20"] else -1
    trend += 1 if x["CLOSE"] > x["EMA50"] else -1
    trend += 1 if x["CLOSE"] > x["EMA200"] else -1
    trend += 1 if x["EMA20"] > p["EMA20"] else -1
    factors["Trend"] = int(np.sign(trend))

    # Momentum
    momentum = 0
    if 52 <= x["RSI14"] <= 72:
        momentum += 1
    elif x["RSI14"] < 45:
        momentum -= 1

    momentum += 1 if x["MACD_HIST"] > 0 else -1
    momentum += 1 if x["MACD_DELTA"] > 0 else -1
    factors["Momentum"] = int(np.sign(momentum))

    # Volume
    volume = 0
    if x["VOL_RATIO20"] >= 1.5:
        volume += 1
    if x["RET1"] > 0 and x["VOL_RATIO20"] >= 1.15:
        volume += 1
    if x["RET1"] < 0 and x["VOL_RATIO20"] >= 1.15:
        volume -= 1
    factors["Volume"] = int(np.sign(volume))

    # Structure
    structure = 0
    if x["CLOSE"] > x["PREV_HIGH"]:
        structure += 1
    if x["CLOSE"] < x["PREV_LOW"]:
        structure -= 1

    if x["RANGE20_POS"] >= 0.8:
        structure += 1
    elif x["RANGE20_POS"] <= 0.2:
        structure -= 1

    factors["Structure"] = int(np.sign(structure))

    # VWAP
    factors["VWAP"] = 1 if x["VWAP_DIST_PCT"] > 0.5 else -1 if x["VWAP_DIST_PCT"] < -0.5 else 0

    # RSI
    factors["RSI"] = 1 if 52 <= x["RSI14"] <= 70 else -1 if 30 <= x["RSI14"] < 45 else 0

    # MACD
    factors["MACD"] = (
        1 if x["MACD_HIST"] > 0 and x["MACD_DELTA"] > 0 else -1 if x["MACD_HIST"] < 0 and x["MACD_DELTA"] < 0 else 0
    )

    # Gap
    factors["Gap"] = 1 if x["GAP_PCT"] >= 1 else -1 if x["GAP_PCT"] <= -1 else 0

    # Delivery
    if pd.notna(x["DELIVERY_PCT"]):
        factors["Delivery"] = (
            1 if x["RET1"] > 0 and x["DELIVERY_PCT"] >= 50 else -1 if x["RET1"] < 0 and x["DELIVERY_PCT"] >= 50 else 0
        )
    else:
        factors["Delivery"] = 0

    # Liquidity
    avg_value = (df["CLOSE"] * df["VOLUME"].fillna(0)).rolling(20).mean().iloc[-1]

    factors["Liquidity"] = 1 if avg_value >= 100_000_000 else 0 if avg_value >= MIN_AVG_VALUE else -1

    return factors, avg_value


def technical_score(df):
    factors, avg_value = current_factors(df)

    score = int(sum(factors.values()))
    bullish = sum(v == 1 for v in factors.values())
    bearish = sum(v == -1 for v in factors.values())

    if score >= 4:
        bias = "Bullish"
        aligned = bullish
    elif score <= -4:
        bias = "Bearish"
        aligned = bearish
    else:
        bias = "Neutral-Range"
        aligned = max(bullish, bearish)

    positives = [k for k, v in factors.items() if v == 1]
    negatives = [k for k, v in factors.items() if v == -1]

    return {
        "TECH_SCORE": score,
        "BIAS": bias,
        "ALIGNED": aligned,
        "BULLISH_FACTORS": bullish,
        "BEARISH_FACTORS": bearish,
        "PRIMARY_DRIVER": " + ".join(positives[:4]) or "No strong driver",
        "CONFLICTING_SIGNAL": ", ".join(negatives[:3]) or "None material",
        "AVG_VALUE20": safe_float(avg_value),
    }


# ============================================================
# RISK / EXPECTED RANGE
# ============================================================


def risk_fields(df, bias):
    x = df.iloc[-1]

    atr_pct = safe_float(x["ATR_PCT"])
    price = safe_float(x["CLOSE"])

    if pd.isna(atr_pct):
        atr_pct = np.nan

    if bias == "Bullish":
        low_pct = max(0.10, atr_pct * 0.35) if not pd.isna(atr_pct) else np.nan
        high_pct = atr_pct * 1.50 if not pd.isna(atr_pct) else np.nan
        invalidation = np.nanmin(
            [
                safe_float(x["PREV_LOW"]),
                safe_float(x["VWAP20"]),
            ]
        )
    elif bias == "Bearish":
        low_pct = -atr_pct * 1.50 if not pd.isna(atr_pct) else np.nan
        high_pct = -max(0.10, atr_pct * 0.35) if not pd.isna(atr_pct) else np.nan
        invalidation = np.nanmax(
            [
                safe_float(x["PREV_HIGH"]),
                safe_float(x["VWAP20"]),
            ]
        )
    else:
        low_pct = -atr_pct if not pd.isna(atr_pct) else np.nan
        high_pct = atr_pct if not pd.isna(atr_pct) else np.nan
        invalidation = safe_float(x["PREV_CLOSE"])

    if pd.isna(atr_pct):
        leverage_risk = "UNKNOWN"
    elif atr_pct >= 5:
        leverage_risk = "VERY_HIGH"
    elif atr_pct >= 3:
        leverage_risk = "HIGH"
    elif atr_pct >= 2:
        leverage_risk = "MODERATE"
    else:
        leverage_risk = "LOW"

    return {
        "EXPECTED_LOW_PCT": pct(low_pct),
        "EXPECTED_HIGH_PCT": pct(high_pct),
        "EXPECTED_LOW_PRICE": pct(price * (1 + low_pct / 100))
        if not pd.isna(price) and not pd.isna(low_pct)
        else np.nan,
        "EXPECTED_HIGH_PRICE": pct(price * (1 + high_pct / 100))
        if not pd.isna(price) and not pd.isna(high_pct)
        else np.nan,
        "INVALIDATION": pct(invalidation),
        "LEVERAGE_RISK": leverage_risk,
    }


# ============================================================
# HISTORICAL SCORE
# ============================================================


def historical_score(hist):
    """
    Converts historical matching-setups into a 0-100 directional quality
    score.

    This is deliberately separate from the technical score.
    """
    n = hist.get("SIMILAR_SETUPS", 0)

    if n < MIN_SIMILAR_SETUPS:
        return 50.0, "INSUFFICIENT"

    w1 = safe_float(hist.get("HIST_NEXTDAY_WIN_PCT"))
    w5 = safe_float(hist.get("HIST_5D_WIN_PCT"))
    w10 = safe_float(hist.get("HIST_10D_WIN_PCT"))

    a1 = safe_float(hist.get("HIST_NEXTDAY_AVG_PCT"))
    a5 = safe_float(hist.get("HIST_5D_AVG_PCT"))
    a10 = safe_float(hist.get("HIST_10D_AVG_PCT"))

    values = [x for x in [w1, w5, w10] if not pd.isna(x)]

    if not values:
        return 50.0, "INSUFFICIENT"

    win_component = np.mean(values)

    avg_values = [x for x in [a1, a5, a10] if not pd.isna(x)]

    # Cap average-return influence so extreme outliers do not dominate.
    avg_component = 0
    if avg_values:
        avg_component = np.clip(
            np.mean(avg_values) * 8,
            -20,
            20,
        )

    score = float(
        np.clip(
            50 + (win_component - 50) * 0.7 + avg_component,
            0,
            100,
        )
    )

    quality = "STRONG" if score >= 70 else "POSITIVE" if score >= 57 else "NEGATIVE" if score <= 43 else "MIXED"

    return round(score, 2), quality


# ============================================================
# OPTIONAL LOCAL INTRADAY CONFIRMATION
# ============================================================


def intraday_score(symbol):
    path = INTRADAY / f"{symbol}.csv"

    if not path.exists():
        return {
            "INTRADAY_STATUS": "NOT_AVAILABLE",
            "INTRADAY_BIAS": "NOT_AVAILABLE",
            "INTRADAY_SCORE": np.nan,
        }

    try:
        df = pd.read_csv(path)
        df = norm_cols(df)

        dt = col(
            df,
            "DATETIME",
            "DATE_TIME",
            "TIMESTAMP",
            "DATE",
        )

        if not dt:
            return {
                "INTRADAY_STATUS": "INVALID_FILE",
                "INTRADAY_BIAS": "NOT_AVAILABLE",
                "INTRADAY_SCORE": np.nan,
            }

        required = {}
        for target in ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]:
            c = col(df, target)
            if not c:
                return {
                    "INTRADAY_STATUS": "MISSING_COLUMN",
                    "INTRADAY_BIAS": "NOT_AVAILABLE",
                    "INTRADAY_SCORE": np.nan,
                }
            required[target] = c

        x = (
            pd.DataFrame(
                {
                    "DT": pd.to_datetime(df[dt], errors="coerce"),
                    "OPEN": num(df[required["OPEN"]]),
                    "HIGH": num(df[required["HIGH"]]),
                    "LOW": num(df[required["LOW"]]),
                    "CLOSE": num(df[required["CLOSE"]]),
                    "VOLUME": num(df[required["VOLUME"]]),
                }
            )
            .dropna()
            .sort_values("DT")
        )

        if len(x) < 50:
            return {
                "INTRADAY_STATUS": "INSUFFICIENT_DATA",
                "INTRADAY_BIAS": "NOT_AVAILABLE",
                "INTRADAY_SCORE": np.nan,
            }

        vwap = (x["CLOSE"] * x["VOLUME"]).rolling(20).sum() / x["VOLUME"].rolling(20).sum().replace(0, np.nan)

        last = x.iloc[-1]
        s = 0

        s += 1 if last["CLOSE"] > vwap.iloc[-1] else -1
        s += 1 if last["CLOSE"] > x["CLOSE"].iloc[-20] else -1
        s += 1 if last["CLOSE"] > last["OPEN"] else -1

        bias = "Bullish" if s >= 2 else "Bearish" if s <= -2 else "Neutral-Range"

        return {
            "INTRADAY_STATUS": "AVAILABLE",
            "INTRADAY_BIAS": bias,
            "INTRADAY_SCORE": s,
        }

    except Exception as exc:
        return {
            "INTRADAY_STATUS": f"ERROR:{type(exc).__name__}",
            "INTRADAY_BIAS": "NOT_AVAILABLE",
            "INTRADAY_SCORE": np.nan,
        }


# ============================================================
# ONE STOCK
# ============================================================


def analyse_symbol(symbol, raw_df):
    if len(raw_df) < MIN_HISTORY:
        return None

    df = raw_df.copy()
    df = add_indicators(df)

    # Use last available session for that symbol.
    x = df.iloc[-1]

    if pd.isna(x["CLOSE"]) or x["CLOSE"] < MIN_PRICE:
        return None

    # Basic liquidity filter.
    avg_value = (df["CLOSE"] * df["VOLUME"].fillna(0)).rolling(20).mean().iloc[-1]

    if pd.isna(avg_value) or avg_value < MIN_AVG_VALUE:
        return None

    required = [
        "EMA20",
        "EMA50",
        "EMA200",
        "RSI14",
        "MACD_HIST",
        "ATR14",
        "VOL_RATIO20",
        "VWAP20",
        "PREV_CLOSE",
    ]

    if any(pd.isna(x[k]) for k in required):
        return None

    tech = technical_score(df)

    hist_basic = historical_stats(df.tail(HISTORY_LOOKBACK))

    hist_setup = historical_similar_setups(df.tail(HISTORY_LOOKBACK))

    hscore, hquality = historical_score(hist_setup)

    # Directional historical score:
    # 50 = neutral, >50 positive historical outcome, <50 negative.
    # Technical score is mapped to 0-100.
    tech_score_100 = np.clip(
        50 + tech["TECH_SCORE"] * 5,
        0,
        100,
    )

    # Next-day score emphasises current setup + historical next-day behaviour.
    hist_next = safe_float(hist_setup.get("HIST_NEXTDAY_WIN_PCT"))
    hist_next_component = hist_next if not pd.isna(hist_next) else 50

    next_day_score = 0.45 * tech_score_100 + 0.35 * hscore + 0.20 * hist_next_component

    # Swing score emphasises 5/10/15-day historical behaviour.
    h5 = safe_float(hist_setup.get("HIST_5D_WIN_PCT"))
    h10 = safe_float(hist_setup.get("HIST_10D_WIN_PCT"))
    h15 = safe_float(hist_setup.get("HIST_15D_WIN_PCT"))

    swing_win_values = [v for v in [h5, h10, h15] if not pd.isna(v)]

    swing_hist_win = float(np.mean(swing_win_values)) if swing_win_values else 50.0

    trend_quality = (
        100
        if x["CLOSE"] > x["EMA20"] > x["EMA50"] > x["EMA200"]
        else 0
        if x["CLOSE"] < x["EMA20"] < x["EMA50"] < x["EMA200"]
        else 50
    )

    swing_score = 0.35 * tech_score_100 + 0.40 * swing_hist_win + 0.15 * hscore + 0.10 * trend_quality

    # High volatility is not automatically bad, but it increases risk.
    atr_pct = safe_float(x["ATR_PCT"])
    if not pd.isna(atr_pct):
        if atr_pct >= 6:
            swing_score -= 8
        elif atr_pct >= 4:
            swing_score -= 4
        elif atr_pct >= 3:
            swing_score -= 2

    swing_score = float(np.clip(swing_score, 0, 100))

    # Historical direction should not override current direction silently.
    # For the final ranking, preserve current technical bias.
    bias = tech["BIAS"]

    risk = risk_fields(df, bias)
    intra = intraday_score(str(symbol))

    # Confidence is based on current factors + historical sample quality.
    aligned = tech["ALIGNED"]

    if aligned >= 7 and hist_setup["SIMILAR_SETUPS"] >= 20:
        confidence = "High"
    elif aligned >= 5 and hist_setup["SIMILAR_SETUPS"] >= MIN_SIMILAR_SETUPS:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "SYMBOL": str(symbol),
        "DATA_DATE": x["DATE"].date(),
        "CMP": pct(x["CLOSE"]),
        # Main decisions.
        "BIAS": bias,
        "NEXT_DAY_SCORE": round(next_day_score, 2),
        "SWING_SCORE": round(swing_score, 2),
        "TECH_SCORE": tech["TECH_SCORE"],
        "TECH_SCORE_100": round(tech_score_100, 2),
        "ALIGNED": f"{aligned}/10",
        "CONFIDENCE": confidence,
        # Current technicals.
        "RSI14": pct(x["RSI14"]),
        "ATR14": pct(x["ATR14"]),
        "ATR_PCT": pct(x["ATR_PCT"]),
        "ATR_PERCENTILE": pct(x["ATR_PCTL"]),
        "EMA20": pct(x["EMA20"]),
        "EMA50": pct(x["EMA50"]),
        "EMA200": pct(x["EMA200"]),
        "MACD_HIST": pct(x["MACD_HIST"], 4),
        "MACD_DELTA": pct(x["MACD_DELTA"], 4),
        "VOL_RATIO20": pct(x["VOL_RATIO20"]),
        "VOL_PERCENTILE": pct(x["VOL_PCTL"]),
        "VWAP20": pct(x["VWAP20"]),
        "VWAP_DIST_PCT": pct(x["VWAP_DIST_PCT"]),
        "DAY_RANGE_PCT": pct(x["DAY_RANGE_PCT"]),
        "RANGE20_POS": pct(x["RANGE20_POS"], 3),
        "RET1": pct(x["RET1"]),
        "RET5": pct(x["RET5"]),
        "RET10": pct(x["RET10"]),
        "RET20": pct(x["RET20"]),
        "GAP_PCT": pct(x["GAP_PCT"]),
        "DELIVERY_PCT": pct(x["DELIVERY_PCT"]),
        "PREV_HIGH": pct(x["PREV_HIGH"]),
        "PREV_LOW": pct(x["PREV_LOW"]),
        "PREV_CLOSE": pct(x["PREV_CLOSE"]),
        "WEEK_HIGH": pct(x["WEEK_HIGH"]),
        "WEEK_LOW": pct(x["WEEK_LOW"]),
        # 3-year behavioural statistics.
        **hist_basic,
        # Similar historical setups.
        **hist_setup,
        "HISTORICAL_SCORE": round(hscore, 2),
        "HISTORICAL_QUALITY": hquality,
        # Explanation.
        "PRIMARY_DRIVER": tech["PRIMARY_DRIVER"],
        "CONFLICTING_SIGNAL": tech["CONFLICTING_SIGNAL"],
        # Range / risk.
        **risk,
        # Liquidity.
        "AVG_VALUE20": round(avg_value, 0),
        # Optional intraday.
        **intra,
    }


# ============================================================
# SCAN ALL STOCKS
# ============================================================


def scan(data):
    latest_date = data["DATE"].max()
    age = (pd.Timestamp.today().normalize() - latest_date).days

    print()
    print("=" * 72)
    print("SCANNING NSE EQUITIES")
    print("=" * 72)
    print(f"Latest available session: {latest_date:%d-%b-%Y} ({age} calendar days old)")

    symbols = data.loc[data["DATE"] == latest_date, "SYMBOL"].dropna().unique()

    print(f"Symbols on latest session: {len(symbols):,}")

    results = []

    for i, symbol in enumerate(symbols, 1):
        if i == 1 or i % 100 == 0:
            print(
                f"Processed {i:,}/{len(symbols):,}",
                flush=True,
            )

        df = data[data["SYMBOL"] == symbol].copy()

        try:
            result = analyse_symbol(symbol, df)
            if result is not None:
                results.append(result)
        except Exception as exc:
            # One bad stock must never stop the complete scan.
            print(f"Warning: {symbol} skipped ({type(exc).__name__}: {exc})")

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results)


# ============================================================
# CANDIDATE SELECTION
# ============================================================


def select_candidates(results):
    if results.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Never allow Neutral-Range stocks to masquerade as directional
    # candidates.
    directional = results[results["BIAS"].isin(["Bullish", "Bearish"])].copy()

    # Next-day:
    # rank bullish high-to-low and bearish low-to-high separately,
    # preserving both long and short opportunities.
    bull = directional[directional["BIAS"] == "Bullish"].sort_values(
        ["NEXT_DAY_SCORE", "HISTORICAL_SCORE"],
        ascending=False,
    )

    bear = directional[directional["BIAS"] == "Bearish"].sort_values(
        ["NEXT_DAY_SCORE", "HISTORICAL_SCORE"],
        ascending=True,
    )

    next_day = pd.concat(
        [
            bull.head(NEXT_DAY_COUNT // 2),
            bear.head(NEXT_DAY_COUNT // 2),
        ],
        ignore_index=True,
    )

    # Swing: direction-independent ranking by swing quality.
    swing = (
        directional.sort_values(
            ["SWING_SCORE", "HISTORICAL_SCORE"],
            ascending=False,
        )
        .head(SWING_COUNT)
        .copy()
    )

    return next_day, swing


# ============================================================
# POSITION SELECTION ENGINE
# ============================================================


def position_selection(all_results, next_day, swing):
    """
    Combine the scanner's existing next-day, swing and historical outputs
    into one practical research ranking.

    This does NOT create a new prediction model. It combines the scores
    already produced by the scanner and adds explicit agreement/risk flags.
    """
    if all_results.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = all_results.copy()

    next_symbols = set(next_day.get("SYMBOL", pd.Series(dtype=str)).astype(str))
    swing_symbols = set(swing.get("SYMBOL", pd.Series(dtype=str)).astype(str))

    df["IN_NEXT_DAY"] = df["SYMBOL"].astype(str).isin(next_symbols)
    df["IN_SWING"] = df["SYMBOL"].astype(str).isin(swing_symbols)
    df["OVERLAP"] = df["IN_NEXT_DAY"] & df["IN_SWING"]

    # Existing scanner scores are already 0-100.
    # Historical score is deliberately included because the scanner's
    # three-year setup engine is one of the user's core requirements.
    next_s = pd.to_numeric(df["NEXT_DAY_SCORE"], errors="coerce").fillna(50)
    swing_s = pd.to_numeric(df["SWING_SCORE"], errors="coerce").fillna(50)
    hist_s = pd.to_numeric(df["HISTORICAL_SCORE"], errors="coerce").fillna(50)

    # Optional local intraday confirmation: neutral if unavailable.
    if "INTRADAY_SCORE" in df.columns:
        intra = pd.to_numeric(df["INTRADAY_SCORE"], errors="coerce")
    else:
        intra = pd.Series(np.nan, index=df.index, dtype=float)
    intra_component = 50 + intra.fillna(0) * 8
    intra_component = intra_component.clip(0, 100)

    risk_penalty = (
        df.get("LEVERAGE_RISK", pd.Series("UNKNOWN", index=df.index))
        .astype(str)
        .map(
            {
                "LOW": 0,
                "MODERATE": 2,
                "HIGH": 5,
                "VERY_HIGH": 10,
                "UNKNOWN": 0,
            }
        )
        .fillna(0)
    )

    # Overall research score. This is a ranking aid, not a price forecast.
    df["POSITION_SCORE"] = (
        (0.30 * next_s + 0.30 * swing_s + 0.25 * hist_s + 0.15 * intra_component - risk_penalty).clip(0, 100).round(2)
    )

    # Explicit agreement classification.
    def mode(row):
        nd = bool(row["IN_NEXT_DAY"])
        sw = bool(row["IN_SWING"])
        if nd and sw:
            return "BOTH"
        if nd:
            return "INTRADAY"
        if sw:
            return "SWING"
        return "WATCH"

    df["TRADE_MODE"] = df.apply(mode, axis=1)

    def action(row):
        bias = str(row.get("BIAS", "Neutral-Range"))
        mode_ = row["TRADE_MODE"]
        conf = str(row.get("CONFIDENCE", "Low"))
        score = safe_float(row.get("POSITION_SCORE"))
        if mode_ == "WATCH" or bias == "Neutral-Range":
            return "WATCH"
        if conf == "Low" or pd.isna(score) or score < 55:
            return "WATCH"
        if bias == "Bullish":
            return "LONG BIAS"
        if bias == "Bearish":
            return "SHORT BIAS"
        return "WATCH"

    df["POSITION_ACTION"] = df.apply(action, axis=1)

    # Priority: overlap first, then confidence, then combined score.
    conf_rank = df["CONFIDENCE"].map({"High": 3, "Medium": 2, "Low": 1}).fillna(0)
    df["_CONF_RANK"] = conf_rank
    df = df.sort_values(
        ["OVERLAP", "_CONF_RANK", "POSITION_SCORE", "HISTORICAL_SCORE"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    df.insert(0, "POSITION_RANK", np.arange(1, len(df) + 1))
    df = df.drop(columns=["_CONF_RANK"])

    overlap = df[df["OVERLAP"]].copy()
    return df, overlap


# ============================================================
# SAVE REPORTS
# ============================================================


def save_results(all_results):
    if all_results.empty:
        print("No eligible stocks.")
        return

    next_day, swing = select_candidates(all_results)
    position_df, overlap_df = position_selection(all_results, next_day, swing)

    # All stocks ranked by next-day score, then swing score.
    all_ranked = all_results.sort_values(
        ["NEXT_DAY_SCORE", "SWING_SCORE"],
        ascending=False,
    ).reset_index(drop=True)

    all_ranked.insert(
        0,
        "OVERALL_RANK",
        np.arange(1, len(all_ranked) + 1),
    )

    # Separate ranks.
    all_ranked["NEXT_DAY_RANK"] = all_ranked["NEXT_DAY_SCORE"].rank(method="min", ascending=False).astype(int)

    all_ranked["SWING_RANK"] = all_ranked["SWING_SCORE"].rank(method="min", ascending=False).astype(int)

    next_day = next_day.copy()
    swing = swing.copy()

    next_day = next_day.sort_values(
        ["BIAS", "NEXT_DAY_SCORE"],
        ascending=[True, False],
    )

    swing = swing.sort_values(
        "SWING_SCORE",
        ascending=False,
    )

    all_ranked.to_csv(
        OUTPUT / "all_scores.csv",
        index=False,
    )

    next_day.to_csv(
        OUTPUT / "next_day_candidates.csv",
        index=False,
    )

    swing.to_csv(
        OUTPUT / "swing_candidates.csv",
        index=False,
    )

    # Historical setup summary.
    hist_cols = [
        "SYMBOL",
        "DATA_DATE",
        "BIAS",
        "HISTORICAL_SCORE",
        "HISTORICAL_QUALITY",
        "SIMILAR_SETUPS",
        "HIST_NEXTDAY_WIN_PCT",
        "HIST_NEXTDAY_AVG_PCT",
        "HIST_3D_WIN_PCT",
        "HIST_3D_AVG_PCT",
        "HIST_5D_WIN_PCT",
        "HIST_5D_AVG_PCT",
        "HIST_10D_WIN_PCT",
        "HIST_10D_AVG_PCT",
        "HIST_15D_WIN_PCT",
        "HIST_15D_AVG_PCT",
    ]

    hist_cols = [c for c in hist_cols if c in all_ranked.columns]

    all_ranked[hist_cols].to_csv(
        OUTPUT / "historical_setup_stats.csv",
        index=False,
    )

    # Position-selection reports. These are derived from the existing
    # scanner outputs; raw scanner columns remain untouched.
    position_df.to_csv(
        OUTPUT / "position_selection.csv",
        index=False,
    )
    overlap_df.to_csv(
        OUTPUT / "high_priority_overlap.csv",
        index=False,
    )

    # Excel workbook.
    try:
        with pd.ExcelWriter(
            OUTPUT / "scanner_report.xlsx",
            engine="openpyxl",
        ) as writer:
            next_day.to_excel(
                writer,
                sheet_name="Next_Day",
                index=False,
            )
            swing.to_excel(
                writer,
                sheet_name="Swing",
                index=False,
            )
            all_ranked.to_excel(
                writer,
                sheet_name="All_Scores",
                index=False,
            )
            all_ranked[hist_cols].to_excel(
                writer,
                sheet_name="Historical_Setups",
                index=False,
            )
            position_df.to_excel(
                writer,
                sheet_name="Position_Selection",
                index=False,
            )
            overlap_df.to_excel(
                writer,
                sheet_name="High_Priority_Overlap",
                index=False,
            )

    except Exception as exc:
        print(f"Excel warning: {exc}")

    # Console summary.
    print()
    print("=" * 100)
    print("NEXT-DAY / INTRADAY WATCHLIST")
    print("=" * 100)

    if next_day.empty:
        print("No directional candidates.")
    else:
        cols = [
            "SYMBOL",
            "BIAS",
            "NEXT_DAY_SCORE",
            "SWING_SCORE",
            "HISTORICAL_SCORE",
            "SIMILAR_SETUPS",
            "HIST_NEXTDAY_WIN_PCT",
            "HIST_5D_WIN_PCT",
            "CONFIDENCE",
            "CMP",
            "ATR_PCT",
            "VOL_RATIO20",
            "LEVERAGE_RISK",
        ]
        cols = [c for c in cols if c in next_day.columns]
        print(next_day[cols].to_string(index=False))

    print()
    print("=" * 100)
    print("SWING WATCHLIST")
    print("=" * 100)

    if swing.empty:
        print("No swing candidates.")
    else:
        cols = [
            "SYMBOL",
            "BIAS",
            "SWING_SCORE",
            "HISTORICAL_SCORE",
            "SIMILAR_SETUPS",
            "HIST_5D_WIN_PCT",
            "HIST_10D_WIN_PCT",
            "HIST_15D_WIN_PCT",
            "CONFIDENCE",
            "CMP",
            "RSI14",
            "ATR_PCT",
            "VOL_RATIO20",
            "LEVERAGE_RISK",
        ]
        cols = [c for c in cols if c in swing.columns]
        print(swing[cols].to_string(index=False))

    print()
    print("=" * 100)
    print("POSITION SELECTION")
    print("=" * 100)
    if position_df.empty:
        print("No position-selection rows.")
    else:
        pos_cols = [
            "POSITION_RANK",
            "SYMBOL",
            "TRADE_MODE",
            "POSITION_ACTION",
            "BIAS",
            "POSITION_SCORE",
            "NEXT_DAY_SCORE",
            "SWING_SCORE",
            "HISTORICAL_SCORE",
            "HISTORICAL_QUALITY",
            "SIMILAR_SETUPS",
            "CONFIDENCE",
            "LEVERAGE_RISK",
            "PRIMARY_DRIVER",
            "CONFLICTING_SIGNAL",
        ]
        pos_cols = [c for c in pos_cols if c in position_df.columns]
        print(position_df[pos_cols].head(30).to_string(index=False))

    print()
    print("=" * 100)
    print("HIGH-PRIORITY OVERLAP")
    print("=" * 100)
    if overlap_df.empty:
        print("No stocks are simultaneously in the next-day and swing top lists.")
    else:
        overlap_cols = [
            "POSITION_RANK",
            "SYMBOL",
            "BIAS",
            "POSITION_SCORE",
            "NEXT_DAY_SCORE",
            "SWING_SCORE",
            "HISTORICAL_SCORE",
            "HISTORICAL_QUALITY",
            "CONFIDENCE",
            "LEVERAGE_RISK",
        ]
        overlap_cols = [c for c in overlap_cols if c in overlap_df.columns]
        print(overlap_df[overlap_cols].head(30).to_string(index=False))

    print()
    print("=" * 100)
    print("FILES CREATED")
    print("=" * 100)
    print(OUTPUT / "all_scores.csv")
    print(OUTPUT / "next_day_candidates.csv")
    print(OUTPUT / "swing_candidates.csv")
    print(OUTPUT / "historical_setup_stats.csv")
    print(OUTPUT / "position_selection.csv")
    print(OUTPUT / "high_priority_overlap.csv")
    print(OUTPUT / "scanner_report.xlsx")


# ============================================================
# LEAKAGE-SAFE ML RANKING
# ============================================================
ML_ENABLED = True
ML_MIN_ROWS = 1000
ML_VALIDATION_DAYS = 63
ML_TOP_N = 30
ML_RANDOM_STATE = 42
ML_FEATURES = [
    "RSI14",
    "MACD_HIST",
    "MACD_DELTA",
    "ATR_PCT",
    "VOL_RATIO20",
    "VOL_PERCENTILE",
    "VWAP_DIST_PCT",
    "GAP_PCT",
    "DAY_RANGE_PCT",
    "RANGE20_POS",
    "RET1",
    "RET5",
    "RET10",
    "RET20",
    "EMA20",
    "EMA50",
    "EMA200",
    "DELIVERY_PCT",
    "UP_STREAK",
    "DOWN_STREAK",
    "WEEK_HIGH",
    "WEEK_LOW",
    "PREV_HIGH",
    "PREV_LOW",
]


def build_ml_panel(data):
    rows = []
    for _symbol, g in data.groupby("SYMBOL", sort=False):
        g = add_indicators(g.sort_values("DATE").copy())
        if len(g) < 272:
            continue
        g["FWD_1D"] = g["CLOSE"].shift(-1) / g["CLOSE"] - 1
        g["FWD_5D"] = g["CLOSE"].shift(-5) / g["CLOSE"] - 1
        cols = ["DATE", "SYMBOL", "FWD_1D", "FWD_5D"] + [c for c in ML_FEATURES if c in g.columns]
        rows.append(g[cols])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def train_ml(panel):
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
    except Exception as exc:
        return None, None, {"ML_STATUS": "SKLEARN_NOT_INSTALLED", "ML_ERROR": str(exc)}
    if panel.empty:
        return None, None, {"ML_STATUS": "NO_TRAINING_PANEL"}
    features = [c for c in ML_FEATURES if c in panel.columns]
    dates = sorted(panel.DATE.dropna().unique())
    if len(dates) < 315:
        return None, None, {"ML_STATUS": "INSUFFICIENT_TIME_HISTORY"}
    vd = dates[-ML_VALIDATION_DAYS:]
    td = dates[:-ML_VALIDATION_DAYS]
    tr = panel[panel.DATE.isin(td)]
    va = panel[panel.DATE.isin(vd)]

    def fit(target):
        a = tr.dropna(subset=[target])
        if len(a) < ML_MIN_ROWS:
            return None, np.nan, np.nan, np.nan
        m = make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0, random_state=ML_RANDOM_STATE
            ),
        )
        m.fit(a[features], a[target])
        b = va.dropna(subset=[target])
        if b.empty:
            return m, np.nan, np.nan, np.nan
        p = m.predict(b[features])
        n = min(ML_TOP_N, len(b))
        idx = np.argsort(p)[-n:]
        ic = float(pd.Series(b[target]).rank().corr(pd.Series(p).rank()))
        precision = float(np.mean(b[target].to_numpy()[idx] > 0))
        topret = float(np.mean(b[target].to_numpy()[idx]))
        return m, ic, precision, topret

    mn, icn, pn, rn = fit("FWD_1D")
    ms, ics, ps, rs = fit("FWD_5D")
    return (
        mn,
        ms,
        {
            "ML_STATUS": "WALK_FORWARD_VALIDATED",
            "ML_TRAIN_FROM": str(pd.Timestamp(min(td)).date()),
            "ML_TRAIN_TO": str(pd.Timestamp(max(td)).date()),
            "ML_VALID_FROM": str(pd.Timestamp(min(vd)).date()),
            "ML_VALID_TO": str(pd.Timestamp(max(vd)).date()),
            "ML_NEXT_RANK_IC": icn,
            "ML_NEXT_PRECISION_AT_30": pn,
            "ML_NEXT_TOP30_AVG_RETURN": rn,
            "ML_SWING_RANK_IC": ics,
            "ML_SWING_PRECISION_AT_30": ps,
            "ML_SWING_TOP30_AVG_RETURN": rs,
            "ML_FEATURE_COUNT": len(features),
        },
    )


def apply_ml(data, results):
    if results.empty or not ML_ENABLED:
        return results, {"ML_STATUS": "DISABLED"}
    try:
        panel = build_ml_panel(data)
        mn, ms, metrics = train_ml(panel)
        if mn is None and ms is None:
            return results, metrics
        rows = []
        for symbol, g in data.groupby("SYMBOL", sort=False):
            if len(g) < MIN_HISTORY:
                continue
            x = add_indicators(g.sort_values("DATE")).iloc[-1]
            row = {"SYMBOL": symbol}
            row.update({f: safe_float(x.get(f)) for f in ML_FEATURES})
            rows.append(row)
        latest = pd.DataFrame(rows)
        if latest.empty:
            return results, metrics
        feats = [c for c in ML_FEATURES if c in latest.columns]
        latest["ML_NEXTDAY_RAW"] = mn.predict(latest[feats]) if mn is not None else np.nan
        latest["ML_SWING_RAW"] = ms.predict(latest[feats]) if ms is not None else np.nan
        latest["ML_NEXTDAY_SCORE"] = latest["ML_NEXTDAY_RAW"].rank(pct=True) * 100
        latest["ML_SWING_SCORE"] = latest["ML_SWING_RAW"].rank(pct=True) * 100
        latest["ML_NEXTDAY_RANK"] = latest["ML_NEXTDAY_SCORE"].rank(ascending=False, method="min")
        latest["ML_SWING_RANK"] = latest["ML_SWING_SCORE"].rank(ascending=False, method="min")
        out = results.merge(
            latest[["SYMBOL", "ML_NEXTDAY_SCORE", "ML_SWING_SCORE", "ML_NEXTDAY_RANK", "ML_SWING_RANK"]],
            on="SYMBOL",
            how="left",
        )
        out["NEXT_DAY_ML_BLEND"] = (
            pd.to_numeric(out["NEXT_DAY_SCORE"], errors="coerce")
            .fillna(50)
            .where(
                out["ML_NEXTDAY_SCORE"].isna(),
                0.70 * pd.to_numeric(out["NEXT_DAY_SCORE"], errors="coerce").fillna(50)
                + 0.30 * out["ML_NEXTDAY_SCORE"],
            )
        )
        out["SWING_ML_BLEND"] = (
            pd.to_numeric(out["SWING_SCORE"], errors="coerce")
            .fillna(50)
            .where(
                out["ML_SWING_SCORE"].isna(),
                0.70 * pd.to_numeric(out["SWING_SCORE"], errors="coerce").fillna(50) + 0.30 * out["ML_SWING_SCORE"],
            )
        )
        out["ML_DIRECTION"] = np.where(
            out["ML_NEXTDAY_SCORE"] >= 55,
            "Bullish",
            np.where(out["ML_NEXTDAY_SCORE"] <= 45, "Bearish", "Neutral-Range"),
        )
        out["ML_AGREES_WITH_BIAS"] = out["ML_DIRECTION"].eq(out["BIAS"])
        # Keep validation values visible in every exported row.
        for k, v in metrics.items():
            out[k] = v
        return out, metrics
    except Exception as exc:
        print(f"ML layer warning: {type(exc).__name__}: {exc}")
        return results, {"ML_STATUS": f"ERROR_{type(exc).__name__}", "ML_ERROR": str(exc)}


# ============================================================
# MAIN
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="NSE 3-year historical behaviour stock scanner")

    parser.add_argument(
        "--days",
        type=int,
        default=1100,
        help="Calendar days of daily history (default: 1100).",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh recent NSE daily files while retaining history.",
    )

    args = parser.parse_args()

    print("=" * 72)
    print("NSE HISTORICAL-BEHAVIOUR + NEXT-DAY + SWING SCANNER")
    print("=" * 72)
    print(f"System date: {datetime.now():%d-%b-%Y %H:%M:%S}")
    print("3-year history is used for historical setup matching and forward-return statistics.")

    if not warm_nse_session():
        print("Could not establish NSE homepage session.")
        return 1

    download_history(
        days=args.days,
        refresh=args.refresh,
    )

    data = load_all_daily()

    results = scan(data)

    if results.empty:
        print("\nNo eligible stocks passed the minimum history/price/liquidity requirements.")
        return 0

    # ML is trained only on historical rows and validated chronologically.
    # It supplements the transparent scanner score; it does not replace it.
    results, ml_metrics = apply_ml(data, results)
    print("\nML VALIDATION")
    for k, v in ml_metrics.items():
        print(f"  {k}: {v}")

    save_results(results)

    print()
    print("=" * 72)
    print("SCAN COMPLETE")
    print("=" * 72)
    print("Historical statistics describe what happened after similar historical setups; they are not guarantees.")
    print("5x leverage magnifies losses as well as gains. LEVERAGE_RISK is a warning, not a recommendation.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
