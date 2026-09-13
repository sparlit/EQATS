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
Core screening logic for the NSE 52-Week Pullback Screener.

Filters (over the trailing 52 weeks, per stock):
  1. The 52-week high must be OLD  -> it was set more than `min_days` ago
     (i.e. price has NOT crossed/reclaimed that high in the last 3 months).
  2. The current close is a shallow PULLBACK -> it sits `band_low`..`band_high`
     percent BELOW the 52-week high (default 1%..10%).

Data source: Yahoo Finance via yfinance (works globally, incl. from cloud hosts).
The NSE symbol universe is loaded from a bundled CSV so the app never has to
call NSE directly (NSE blocks most cloud IPs).
"""


import gc
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import frontier  # high-water frontier for multi-year / all-time high windows
import pandas as pd

try:  # yfinance is only needed at run time, not for importing helpers
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

# ----------------------------------------------------------------------------
# Config defaults (all overridable from the UI)
# ----------------------------------------------------------------------------
LOOKBACK_WINDOW_DAYS = 365  # "52 weeks" for the high computation
FETCH_DAYS = 420  # calendar days of history to pull (buffer > 365)
MIN_TRADING_DAYS = 200  # skip stocks with too little history for a 52wk high
BATCH_SIZE = 50  # tickers per yfinance download call (smaller = lower peak RAM)
DOWNLOAD_THREADS = 6  # bounded yfinance workers (free host has a low thread ceiling)
AVG_VOL_DAYS = 20  # window for the average-volume column
SPLIT_JUMP_PCT = 35.0  # flag a likely split/bonus if a 1-day move exceeds this

DEFAULT_MIN_DAYS = 90  # "3 months"
DEFAULT_BAND_LOW = 1.0  # % below high (min pullback)
DEFAULT_BAND_HIGH = 10.0  # % below high (max pullback)
DEFAULT_MIN_AVG_VOL = 30000  # avg 20-day volume threshold for the Qty+Circuit filter
CIRCUIT_BAND_PCT = 20  # the "upper circuit = 20%" filter target
DEFAULT_LISTING_MIN_MONTHS = 3  # listing-window filter: youngest age (months since listing)
DEFAULT_LISTING_MAX_MONTHS = 12  # listing-window filter: oldest age

FO_PATH = "data/fo_stocks.csv"  # bundled F&O underlyings list
BANDS_PATH = "data/price_bands.csv"  # nightly per-symbol price bands (broker feed)
SNAPSHOT_PATH = "data/screener_snapshot.csv"  # nightly precomputed base metrics
FRONTIER_STORE_PATH = "data/frontier_store.csv"  # maintained high-water frontier store

DEFAULT_MIN_HISTORY_DAYS = 200  # skip stocks with too little history for a high

# Snapshot the app reads: all-time-high + the encoded frontier (for any N-year
# window) + the reference/liquidity fields.
SNAPSHOT_COLUMNS = [
    "Symbol",
    "Company",
    "LastClose",
    "AvgVol20d",
    "is_fno",
    "Band",
    "ListingDate",
    "LastDate",
    "HighATH",
    "HighATHDate",
    "Frontier",
]

RESULT_COLUMNS = [
    "Symbol",
    "Company",
    "LastClose",
    "52wHigh",
    "ATHHigh",
    "HighDate",
    "DaysSinceHigh",
    "PctFromHigh",
    "PctFromATH",
    "AvgVol20d",
    "F&O",
    "Band%",
    "ListingDate",
    "Basis",
]


@dataclass
class ScreenStats:
    universe: int = 0
    fetched: int = 0
    skipped_no_data: list[str] = field(default_factory=list)
    skipped_short_history: list[str] = field(default_factory=list)
    split_warnings: list[str] = field(default_factory=list)
    as_of: str | None = None  # latest trading date seen in the data


# ----------------------------------------------------------------------------
# Universe
# ----------------------------------------------------------------------------
def load_universe(
    path: str = "data/nse_equity_list.csv",
    fo_path: str = FO_PATH,
    bands_path: str = BANDS_PATH,
) -> pd.DataFrame:
    """
    Return the bundled universe with columns:
      Symbol, Company, Ticker, is_fno (bool), Band (float %, NaN if unknown).

    F&O flag comes from the bundled F&O list; Band comes from the nightly broker
    feed. Both are optional — if a file is missing the column defaults sensibly.
    Reads `df.attrs["band_as_of"]` / `df.attrs["has_band_data"]` for feed status.
    """
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"NAME OF COMPANY": "Company", "SYMBOL": "Symbol"})
    df["Symbol"] = df["Symbol"].astype(str).str.strip()
    df["Company"] = df["Company"].astype(str).str.strip()
    df = df[df["Symbol"] != ""].drop_duplicates(subset="Symbol").reset_index(drop=True)
    df["Ticker"] = df["Symbol"] + ".NS"

    # Listing date (powers the listing-window filter; format like 08-JUL-1999)
    if "DATE OF LISTING" in df.columns:
        df["ListingDate"] = pd.to_datetime(
            df["DATE OF LISTING"].astype(str).str.strip(),
            format="%d-%b-%Y",
            errors="coerce",
        )
    else:
        df["ListingDate"] = pd.NaT

    # F&O flag
    fno_set = _load_fno_set(fo_path)
    df["is_fno"] = df["Symbol"].isin(fno_set)

    # Price bands (nightly broker feed)
    band_map, band_as_of = _load_bands(bands_path)
    df["Band"] = df["Symbol"].map(band_map).astype("float")

    df.attrs["band_as_of"] = band_as_of
    df.attrs["has_band_data"] = bool(band_map)
    return df[["Symbol", "Company", "Ticker", "is_fno", "Band", "ListingDate"]]


def _load_fno_set(fo_path: str) -> set[str]:
    try:
        fo = pd.read_csv(fo_path)
        col = "Symbol" if "Symbol" in fo.columns else fo.columns[0]
        return set(fo[col].astype(str).str.strip())
    except Exception:
        return set()


def _load_bands(bands_path: str) -> tuple[dict, str | None]:
    """Return ({Symbol: band%}, as_of_date_or_None). Empty if the feed is absent."""
    try:
        b = pd.read_csv(bands_path)
        b.columns = [c.strip() for c in b.columns]
        sym = "Symbol" if "Symbol" in b.columns else b.columns[0]
        band_col = "Band" if "Band" in b.columns else b.columns[1]
        b[sym] = b[sym].astype(str).str.strip()
        band_map = dict(zip(b[sym], pd.to_numeric(b[band_col], errors="coerce"), strict=False))
        as_of = None
        if "AsOf" in b.columns and not b["AsOf"].dropna().empty:
            as_of = str(b["AsOf"].dropna().iloc[0])
        return band_map, as_of
    except Exception:
        return {}, None


def band_feed_status(bands_path: str = BANDS_PATH) -> tuple[bool, str | None]:
    """(has_data, as_of) — lets the UI enable/disable the 20% band filter."""
    band_map, as_of = _load_bands(bands_path)
    return bool(band_map), as_of


# ----------------------------------------------------------------------------
# Download helpers
# ----------------------------------------------------------------------------
def _band_num(v) -> int | None:
    """Coerce a band value to an int %, or None if missing/NaN/no-band."""
    try:
        if v is None or v != v:  # None or NaN
            return None
        n = round(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _download_batch(tickers: list[str], start, retries: int = 2) -> pd.DataFrame | None:
    """Download one batch; retry a couple of times on transient failures/empties."""
    if yf is None:
        msg = "yfinance is not installed"
        raise RuntimeError(msg)
    last_err = None
    for attempt in range(retries + 1):
        try:
            data = yf.download(
                tickers,
                start=start,
                interval="1d",
                auto_adjust=False,  # match NSE's displayed (unadjusted) 52wk high
                group_by="ticker",
                threads=DOWNLOAD_THREADS,  # bounded — avoid exhausting the host thread limit
                progress=False,
            )
            if data is not None and not data.empty:
                return data
        except Exception as e:  # network / rate-limit hiccup
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    if last_err is not None:
        # swallow: caller records these tickers as no-data
        pass
    return None


def _extract_one(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Pull a single ticker's OHLCV frame out of a multi-ticker download."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if ticker not in data.columns.get_level_values(0):
                return None
            sub = data[ticker].copy()
        else:
            sub = data.copy()  # single-ticker fallback
    except Exception:
        return None
    sub = sub.dropna(how="all")
    if sub.empty or "Close" not in sub.columns:
        return None
    # keep only what we use and downcast to float32 to trim memory
    keep = [c for c in ("High", "Close", "Volume") if c in sub.columns]
    sub = sub[keep].copy()
    for c in keep:
        sub[c] = pd.to_numeric(sub[c], downcast="float")
    return sub


# ----------------------------------------------------------------------------
# Per-stock computation
# ----------------------------------------------------------------------------
def _evaluate_both(sub: pd.DataFrame) -> dict | None:
    """
    Compute 52-week metrics for BOTH bases (intraday High and daily Close) for one
    stock. Returns a snapshot dict, {"_short_history": True}, or None if unusable.
    """
    sub = sub.sort_index()
    close = sub["Close"].dropna()
    if close.empty:
        return None

    last_date = close.index[-1]
    cutoff = last_date - timedelta(days=LOOKBACK_WINDOW_DAYS)
    window = sub.loc[sub.index >= cutoff]
    if len(window) < MIN_TRADING_DAYS:
        return {"_short_history": True}

    last_close = float(window["Close"].dropna().iloc[-1])

    def _high(series):
        s = series.dropna()
        if s.empty:
            return None, None
        hi = float(s.max())
        if hi <= 0:
            return None, None
        hd = s[s == hi].index.max()  # most-recent touch of the high
        return round(hi, 2), hd.date().isoformat()

    high_h, date_h = _high(window["High"])
    high_c, date_c = _high(window["Close"])
    if high_h is None and high_c is None:
        return None

    vol = window["Volume"].dropna()
    avg_vol = int(vol.tail(AVG_VOL_DAYS).mean()) if not vol.empty else 0

    daily_ret = window["Close"].pct_change().abs()
    split_flag = bool((daily_ret > SPLIT_JUMP_PCT / 100.0).any())

    return {
        "LastClose": round(last_close, 2),
        "HighH": high_h,
        "HighHDate": date_h,
        "HighC": high_c,
        "HighCDate": date_c,
        "AvgVol20d": avg_vol,
        "_last_date": last_date,
        "_split_flag": split_flag,
    }


def compute_snapshot(universe: pd.DataFrame, progress_cb=None):
    """
    HEAVY step — run in the scheduled snapshot job, NOT the web app.

    Downloads prices for the whole universe and computes per-stock base metrics
    for BOTH bases (intraday High and daily Close) plus F&O / band / listing. No
    filtering. Returns (snapshot_df, stats) with columns == SNAPSHOT_COLUMNS.
    """
    stats = ScreenStats(universe=len(universe))
    start = (datetime.now() - timedelta(days=FETCH_DAYS)).date()

    sym_by_ticker = dict(zip(universe["Ticker"], universe["Symbol"], strict=False))
    name_by_ticker = dict(zip(universe["Ticker"], universe["Company"], strict=False))
    fno_by_sym = dict(zip(universe["Symbol"], universe.get("is_fno", False), strict=False))
    band_by_sym = dict(zip(universe["Symbol"], universe.get("Band", float("nan")), strict=False))
    listing_by_sym = dict(zip(universe["Symbol"], universe.get("ListingDate", pd.NaT), strict=False))
    tickers = list(universe["Ticker"])

    rows: list[dict] = []
    latest_seen = None
    total = len(tickers)
    done = 0

    for batch in _chunks(tickers, BATCH_SIZE):
        data = _download_batch(batch, start)
        if data is None:
            stats.skipped_no_data.extend(sym_by_ticker[t] for t in batch)
        else:
            for t in batch:
                sub = _extract_one(data, t)
                sym = sym_by_ticker[t]
                if sub is None:
                    stats.skipped_no_data.append(sym)
                    continue
                m = _evaluate_both(sub)
                if m is None:
                    stats.skipped_no_data.append(sym)
                    continue
                if m.get("_short_history"):
                    stats.skipped_short_history.append(sym)
                    continue
                stats.fetched += 1
                if m["_split_flag"]:
                    stats.split_warnings.append(sym)
                ld = m["_last_date"]
                if latest_seen is None or ld > latest_seen:
                    latest_seen = ld
                listing = listing_by_sym.get(sym)
                rows.append(
                    {
                        "Symbol": sym,
                        "Company": name_by_ticker[t],
                        "LastClose": m["LastClose"],
                        "HighH": m["HighH"],
                        "HighHDate": m["HighHDate"],
                        "HighC": m["HighC"],
                        "HighCDate": m["HighCDate"],
                        "AvgVol20d": m["AvgVol20d"],
                        "is_fno": bool(fno_by_sym.get(sym, False)),
                        "Band": band_by_sym.get(sym),
                        "ListingDate": (
                            listing.date().isoformat() if listing is not None and not pd.isna(listing) else ""
                        ),
                        "LastDate": ld.date().isoformat(),
                    }
                )
        del data
        gc.collect()
        done += len(batch)
        if progress_cb:
            progress_cb(min(done, total), total)

    if latest_seen is not None:
        stats.as_of = latest_seen.date().isoformat()
    snap = pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)
    return snap, stats


def load_snapshot(path: str = SNAPSHOT_PATH) -> pd.DataFrame:
    """Load the precomputed snapshot (empty df if missing). `df.attrs['as_of']` set."""
    try:
        snap = pd.read_csv(path)
    except Exception:
        empty = pd.DataFrame(columns=SNAPSHOT_COLUMNS)
        empty.attrs["as_of"] = None
        return empty
    if "is_fno" in snap.columns:
        snap["is_fno"] = snap["is_fno"].map(lambda x: str(x).strip().lower() in ("true", "1"))
    as_of = None
    if "LastDate" in snap.columns and not snap["LastDate"].dropna().empty:
        as_of = str(snap["LastDate"].dropna().max())
    snap.attrs["as_of"] = as_of
    return snap


def merge_reference(price_df: pd.DataFrame) -> pd.DataFrame:
    """Add F&O / band / listing reference fields to a price-derived frame and
    emit exactly SNAPSHOT_COLUMNS.

    `price_df` carries the per-stock price fields (Symbol, Company, LastClose,
    AvgVol20d, LastDate, HighATH, HighATHDate, Frontier). This merges the
    reference data so the snapshot doubles as the frontier store (one file).
    """
    df = price_df.copy()
    df["Symbol"] = df["Symbol"].astype(str).str.strip()

    uni = load_universe()
    is_fno = dict(zip(uni["Symbol"], uni["is_fno"], strict=False))
    band = dict(zip(uni["Symbol"], uni["Band"], strict=False))
    listing = dict(zip(uni["Symbol"], uni["ListingDate"], strict=False))

    df["is_fno"] = df["Symbol"].map(is_fno).fillna(False)
    df["Band"] = df["Symbol"].map(band)
    ld = pd.to_datetime(df["Symbol"].map(listing), errors="coerce")
    df["ListingDate"] = ld.dt.date.astype("string").fillna("")
    for col in SNAPSHOT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[SNAPSHOT_COLUMNS]


def _window_years(window) -> float | None:
    """Resolve a window selector to a number of trailing years.

    None => all-time high; 1.0 => 52-week high; any other number => that many
    years. Accepts "ath"/"all-time", "52w"/"52-week", or a numeric year count.
    """
    if window is None:
        return None
    w = str(window).strip().lower()
    if w in ("ath", "all", "alltime", "all-time"):
        return None
    if w in ("52w", "52wk", "52week", "52-week"):
        return 1.0
    try:
        return float(window)
    except (TypeError, ValueError):
        return None


def _window_label(window) -> str:
    """Human label for the chosen high window."""
    years = _window_years(window)
    if years is None:
        return "All-time"
    if str(window).strip().lower().startswith("52"):
        return "52-week"
    return f"{years:g}-year"


def _window_high(df: pd.DataFrame, window, as_of) -> tuple[pd.Series, pd.Series]:
    """Return (high, high_date) Series for the chosen window.

    window = "ath" (all-time high, direct columns), "52w" (52-week high), or a
    number of years (derived per-row from the encoded Frontier). Falls back to
    legacy HighH columns if the snapshot predates the frontier format.
    """
    years = _window_years(window)
    if years is None and "HighATH" in df.columns:
        return pd.to_numeric(df["HighATH"], errors="coerce"), pd.to_datetime(df["HighATHDate"], errors="coerce")
    if years is not None and "Frontier" in df.columns:
        cutoff = frontier.years_cutoff(years, as_of.date() if pd.notna(as_of) else None)
        highs, dates = [], []
        for s in df["Frontier"]:
            p, d = frontier.nyear_high(frontier.decode_frontier(s), cutoff)
            highs.append(p)
            dates.append(d)
        return pd.to_numeric(pd.Series(highs, index=df.index), errors="coerce"), pd.to_datetime(
            pd.Series(dates, index=df.index), errors="coerce"
        )
    # legacy fallback (old snapshot format)
    return pd.to_numeric(df.get("HighH"), errors="coerce"), pd.to_datetime(df.get("HighHDate"), errors="coerce")


def screen_snapshot(
    snap: pd.DataFrame,
    window="ath",
    min_days: int = DEFAULT_MIN_DAYS,
    band_low: float = DEFAULT_BAND_LOW,
    band_high: float = DEFAULT_BAND_HIGH,
    fno_only: bool = False,
    qty_circuit_only: bool = False,
    qty_threshold: float = DEFAULT_MIN_AVG_VOL,
    qty_keep: str = "above",
    listing_only: bool = False,
    listing_min_months: int = DEFAULT_LISTING_MIN_MONTHS,
    listing_max_months: int = DEFAULT_LISTING_MAX_MONTHS,
) -> pd.DataFrame:
    """
    LIGHT step — the web app runs this. Applies the base screen + optional filters
    to the precomputed snapshot in memory (no network, no heavy compute).

    `window` selects the high: "ath" (all-time, default) or a number of years
    (any N; derived from the per-stock frontier). Base (always): the window high
    is older than `min_days` AND close is `band_low`..`band_high`% below it.
    Optional (AND when enabled): F&O; Qty+Circuit (avg vol vs threshold by
    direction AND band==20%); Listing window (min..max months).
    """
    if snap is None or snap.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    df = snap.copy()
    if "is_fno" in df.columns and df["is_fno"].dtype == object:
        df["is_fno"] = df["is_fno"].map(lambda x: str(x).strip().lower() in ("true", "1"))
    as_of = pd.to_datetime(df["LastDate"], errors="coerce").max()

    df["_high"], df["_hdate"] = _window_high(df, window, as_of)
    df["_close"] = pd.to_numeric(df["LastClose"], errors="coerce")
    df = df[df["_high"].notna() & (df["_high"] > 0) & df["_hdate"].notna() & df["_close"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    df["_days"] = (as_of - df["_hdate"]).dt.days
    df["_pct"] = (df["_high"] - df["_close"]) / df["_high"] * 100.0

    # BASE screen (always)
    df = df[(df["_days"] > min_days) & (df["_pct"] >= band_low) & (df["_pct"] <= band_high)].copy()

    df["_band"] = df["Band"].map(_band_num)
    df["_vol"] = pd.to_numeric(df["AvgVol20d"], errors="coerce").fillna(0)

    # OPTIONAL filters (AND)
    if fno_only:
        df = df[df["is_fno"]]
    if qty_circuit_only:
        qmask = (df["_vol"] <= qty_threshold) if qty_keep == "below" else (df["_vol"] >= qty_threshold)
        df = df[qmask & (df["_band"] == CIRCUIT_BAND_PCT)]
    if listing_only:
        _today = pd.Timestamp.now().normalize()
        newest = _today - pd.DateOffset(months=int(listing_min_months))
        oldest = _today - pd.DateOffset(months=int(listing_max_months))
        ld = pd.to_datetime(df["ListingDate"], errors="coerce")
        df = df[(ld >= oldest) & (ld <= newest)]

    if df.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    def _band_disp(row):
        bn = row["_band"]
        return int(bn) if bn is not None and not pd.isna(bn) else ("NB" if row["is_fno"] else "—")

    def _ld_disp(v):
        return v if isinstance(v, str) and v else "—"

    win_label = _window_label(window)
    ath = pd.to_numeric(df.get("HighATH"), errors="coerce")
    pct_ath = ((ath - df["_close"]) / ath * 100.0).round(2)
    out = pd.DataFrame(
        {
            "Symbol": df["Symbol"],
            "Company": df["Company"],
            "LastClose": df["_close"].round(2),
            "52wHigh": df["_high"].round(2),  # holds the selected-window high
            "ATHHigh": ath.round(2),  # all-time high (shown alongside N-year)
            "HighDate": df["_hdate"].dt.date.astype(str),
            "DaysSinceHigh": df["_days"].astype(int),
            "PctFromHigh": df["_pct"].round(2),
            "PctFromATH": pct_ath,
            "AvgVol20d": df["_vol"].astype(int),
            "F&O": df["is_fno"].map(lambda x: "Yes" if x else "No"),
            "Band%": df.apply(_band_disp, axis=1),
            "ListingDate": df["ListingDate"].map(_ld_disp),
            "Basis": win_label,
        },
        columns=RESULT_COLUMNS,
    )
    return out.sort_values("PctFromHigh").reset_index(drop=True)
