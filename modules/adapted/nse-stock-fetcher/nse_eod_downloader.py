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
"""
nse_eod_downloader.py
=====================

Bulk-download ~20 years of end-of-day OHLCV data for every listed NSE equity
using yfinance (Yahoo Finance).

Workflow
--------
1. Pull the official NSE equity master list (EQUITY_L.csv) from NSE archives.
2. Map each SYMBOL -> "SYMBOL.NS" (Yahoo's ticker convention for NSE).
3. Download daily bars in batches, with retries + backoff for throttling.
4. Write one file per symbol (CSV or Parquet), plus a failure log and manifest.

Resume-safe: re-running skips symbols already on disk. With --update it fetches
only the bars after the last stored date for each symbol.

Usage
-----
    pip install yfinance pandas requests pyarrow curl_cffi

    # specific companies: just list them, space separated
    python nse_eod_downloader.py RELIANCE TCS INFY HDFCBANK

    # ".NS" is optional, case doesn't matter, commas are tolerated
    python nse_eod_downloader.py reliance.ns TCS,INFY

    # tickers that already carry a suffix or caret pass through untouched
    python nse_eod_downloader.py RELIANCE INFY.BO ^NSEI

    # no symbols given -> the whole NSE universe (takes a few hours)
    python nse_eod_downloader.py --outdir ./nse_data --years 20

    # smoke test on 25 symbols of the full list
    python nse_eod_downloader.py --outdir ./nse_data --limit 25

    # later: top up with only the new bars
    python nse_eod_downloader.py --outdir ./nse_data --update

    # ignore what's on disk and re-download from scratch
    python nse_eod_downloader.py RELIANCE --force

    # retry only what failed last time
    python nse_eod_downloader.py --outdir ./nse_data --retry-failed
"""


import argparse
import contextlib
import io
import logging
import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

EQUITY_LIST_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]

log = logging.getLogger("nse")


# --------------------------------------------------------------------------- #
# Symbol universe
# --------------------------------------------------------------------------- #


def fetch_nse_symbols(series: set[str] | None = None) -> pd.DataFrame:
    """Download the NSE equity master list. Returns SYMBOL / NAME / SERIES / ISIN."""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    # NSE hands out cookies on the landing page; without them archives can 403.
    with contextlib.suppress(requests.RequestException):
        session.get("https://www.nseindia.com", timeout=15)

    last_error: Exception | None = None
    for url in EQUITY_LIST_URLS:
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip().upper() for c in df.columns]
            df = df.rename(columns={"NAME OF COMPANY": "NAME", "ISIN NUMBER": "ISIN"})
            for col in ("SYMBOL", "SERIES"):
                df[col] = df[col].astype(str).str.strip()
            if series:
                df = df[df["SERIES"].isin(series)]
            df = df.drop_duplicates("SYMBOL").reset_index(drop=True)
            log.info("Fetched %d symbols from %s", len(df), url)
            keep = [c for c in ("SYMBOL", "NAME", "SERIES", "ISIN") if c in df.columns]
            return df[keep]
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            last_error = exc
            log.warning("Could not fetch %s (%s)", url, exc)

    raise RuntimeError(
        "Failed to fetch the NSE equity list. Download EQUITY_L.csv manually from "
        "https://www.nseindia.com/market-data/securities-available-for-trading and "
        f"pass it with --symbols-file. Last error: {last_error}"
    )


def parse_symbol_args(raw: list[str]) -> list[str]:
    """Accept 'RELIANCE TCS', 'RELIANCE,TCS', 'reliance.ns' and mixtures of those."""
    out: list[str] = []
    for token in raw:
        for piece in token.replace(";", ",").split(","):
            piece = piece.strip()
            if piece:
                out.append(normalize_symbol(piece))
    seen: set[str] = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def normalize_symbol(symbol: str) -> str:
    """Store 'RELIANCE.NS' and 'reliance' alike as 'RELIANCE'; leave other suffixes."""
    s = symbol.strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def load_symbols(args) -> pd.DataFrame:
    series = (
        None
        if args.series.lower() == "all"
        else {s.strip().upper() for s in args.series.split(",")}
    )
    if args.symbols:
        picked = parse_symbol_args(args.symbols)
        log.info("Using %d symbol(s) from the command line: %s", len(picked), ", ".join(picked))
        return pd.DataFrame({"SYMBOL": picked})

    if args.symbols_file:
        df = pd.read_csv(args.symbols_file)
        df.columns = [c.strip().upper() for c in df.columns]
        df = df.rename(columns={"NAME OF COMPANY": "NAME", "ISIN NUMBER": "ISIN"})
        df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        if series and "SERIES" in df.columns:
            df = df[df["SERIES"].astype(str).str.strip().isin(series)]
        log.info("Loaded %d symbols from %s", len(df), args.symbols_file)
    else:
        df = fetch_nse_symbols(series)

    df = df.drop_duplicates("SYMBOL").reset_index(drop=True)
    if args.limit:
        df = df.head(args.limit)
    return df


def to_yahoo_ticker(symbol: str, suffix: str = ".NS") -> str:
    """Map an NSE symbol to its Yahoo ticker, e.g. RELIANCE -> RELIANCE.NS.

    Tickers that already carry a suffix or an index caret ('INFY.BO', '^NSEI')
    are passed through untouched, so you can mix them into the same run.
    A bare name always gets `suffix` appended -- use --suffix to change it.
    """
    s = symbol.strip().upper()
    if s.startswith("^") or "." in s:
        return s
    return f"{s}{suffix}"


# --------------------------------------------------------------------------- #
# Storage helpers
# --------------------------------------------------------------------------- #


def symbol_path(outdir: Path, symbol: str, fmt: str) -> Path:
    safe = symbol.replace("/", "_").replace("\\", "_")
    return outdir / "data" / f"{safe}.{'parquet' if fmt == 'parquet' else 'csv'}"


def read_existing(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, parse_dates=["Date"])
        if "Date" in df.columns:
            df = df.set_index("Date")
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as exc:  # noqa: BLE001 - a corrupt file shouldn't stop the run
        log.warning("Could not read %s (%s); it will be re-downloaded", path, exc)
        return None


def write_frame(df: pd.DataFrame, path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.index.name = "Date"
    if fmt == "parquet":
        out.to_parquet(path)
    else:
        out.to_csv(path, float_format="%.6f")


def merge_frames(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    combined = new if old is None or old.empty else pd.concat([old, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #


def make_session():
    """curl_cffi impersonation avoids most Yahoo rate-limit blocks. Optional."""
    try:
        from curl_cffi import requests as cffi_requests

        return cffi_requests.Session(impersonate="chrome")
    except Exception:  # noqa: BLE001 - plain yfinance still works, just slower
        return None


def download_batch(
    tickers: list[str],
    start: str,
    end: str | None,
    threads: bool | int,
    session,
) -> pd.DataFrame | None:
    kwargs = {
        "tickers": tickers,
        "start": start,
        "end": end,
        "interval": "1d",
        "auto_adjust": False,  # keep raw OHLC *and* Adj Close
        "actions": False,
        "group_by": "ticker",
        "progress": False,
        "threads": threads,
    }
    try:
        return yf.download(**kwargs, session=session) if session else yf.download(**kwargs)
    except TypeError:
        # older/newer yfinance versions differ on the `session` kwarg
        return yf.download(**kwargs)


def split_batch(raw: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Turn a (possibly MultiIndex) yfinance frame into {ticker: tidy frame}."""
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out

    for ticker in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0)
            if ticker in set(level0):
                sub = raw[ticker].copy()
            elif len(tickers) == 1:
                sub = raw.droplevel(0, axis=1).copy()
            else:
                continue
        else:
            sub = raw.copy()

        sub = sub.dropna(how="all")
        if sub.empty:
            continue
        for col in OHLCV_COLUMNS:
            if col not in sub.columns:
                sub[col] = pd.NA
        sub = sub[OHLCV_COLUMNS]
        sub.index = pd.to_datetime(sub.index).tz_localize(None)
        out[ticker] = sub.sort_index()
    return out


def fetch_with_retry(tickers, start, end, args, session) -> dict[str, pd.DataFrame]:
    delay = args.sleep
    for attempt in range(1, args.retries + 1):
        try:
            raw = download_batch(tickers, start, end, args.threads, session)
            frames = split_batch(raw, tickers)
            if frames or attempt == args.retries:
                return frames
            log.warning("Empty response for batch (attempt %d/%d)", attempt, args.retries)
        except Exception as exc:  # noqa: BLE001 - network/throttle errors are expected
            log.warning("Batch failed (attempt %d/%d): %s", attempt, args.retries, exc)
            if attempt == args.retries:
                return {}
        time.sleep(delay + random.uniform(0, 1.5))
        delay *= 2
    return {}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def run(args) -> int:
    outdir = Path(args.outdir).expanduser().resolve()
    (outdir / "data").mkdir(parents=True, exist_ok=True)

    default_start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=args.years)).strftime(
        "%Y-%m-%d"
    )
    end = args.end or (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    symbols_df = load_symbols(args)
    if not args.symbols:
        # don't let a 3-ticker run overwrite the cached full universe
        symbols_df.to_csv(outdir / "symbols.csv", index=False)
    symbols = symbols_df["SYMBOL"].tolist()

    if args.retry_failed:
        failed_path = outdir / "failures.csv"
        if not failed_path.exists():
            log.error("No failures.csv in %s", outdir)
            return 1
        wanted = set(pd.read_csv(failed_path)["SYMBOL"].astype(str))
        symbols = [s for s in symbols if s in wanted]
        log.info("Retrying %d previously failed symbols", len(symbols))

    # Decide a start date per symbol, then group so each batch shares one start.
    by_start: dict[str, list[str]] = defaultdict(list)
    skipped = 0
    for sym in symbols:
        path = symbol_path(outdir, sym, args.format)
        existing = None if args.force else (read_existing(path) if path.exists() else None)
        if existing is not None and not existing.empty:
            if not args.update:
                skipped += 1
                continue
            next_day = existing.index.max() + pd.Timedelta(days=1)
            if next_day >= pd.Timestamp(end):
                skipped += 1
                continue
            by_start[next_day.strftime("%Y-%m-%d")].append(sym)
        else:
            by_start[default_start].append(sym)

    pending = sum(len(v) for v in by_start.values())
    log.info(
        "%d symbols to fetch, %d already current, window %s -> %s",
        pending,
        skipped,
        default_start,
        end,
    )
    if pending == 0:
        return 0

    saved, empty, failed = 0, [], []
    done = 0
    t0 = time.time()
    session = make_session()

    for start, group in by_start.items():
        for batch in chunks(group, args.batch_size):
            tickers = [to_yahoo_ticker(s, args.suffix) for s in batch]
            frames = fetch_with_retry(tickers, start, end, args, session)

            for sym, ticker in zip(batch, tickers, strict=False):
                df = frames.get(ticker)
                path = symbol_path(outdir, sym, args.format)
                if df is None or df.empty:
                    if path.exists():
                        empty.append(sym)  # nothing new; not an error
                    else:
                        failed.append(sym)
                    continue
                merged = merge_frames(read_existing(path) if args.update else None, df)
                write_frame(merged, path, args.format)
                saved += 1

            done += len(batch)
            rate = done / max(time.time() - t0, 1e-9)
            eta = (pending - done) / rate if rate else 0
            log.info(
                "%d/%d done | saved=%d failed=%d | ETA %.1f min",
                done,
                pending,
                saved,
                len(failed),
                eta / 60,
            )
            time.sleep(args.sleep + random.uniform(0, 1.0))

    if failed:
        pd.DataFrame({"SYMBOL": failed}).to_csv(outdir / "failures.csv", index=False)
        log.warning("%d symbols returned no data; see failures.csv", len(failed))
    if empty:
        log.info("%d symbols had no new bars in the window", len(empty))

    pd.DataFrame(
        [
            {
                "run_at": datetime.now().isoformat(timespec="seconds"),
                "universe": len(symbols_df),
                "attempted": pending,
                "saved": saved,
                "failed": len(failed),
                "start": default_start,
                "end": end,
                "format": args.format,
            }
        ]
    ).to_csv(
        outdir / "manifest.csv",
        mode="a",
        index=False,
        header=not (outdir / "manifest.csv").exists(),
    )

    log.info("Finished in %.1f min. Files in %s", (time.time() - t0) / 60, outdir / "data")
    return 0


def build_combined(outdir: Path, fmt: str) -> None:
    """Optional: stack every per-symbol file into one long-format table."""
    files = sorted((outdir / "data").glob(f"*.{'parquet' if fmt == 'parquet' else 'csv'}"))
    frames = []
    for f in files:
        df = read_existing(f)
        if df is None or df.empty:
            continue
        df = df.reset_index()
        df.insert(0, "SYMBOL", f.stem)
        frames.append(df)
    if not frames:
        log.warning("Nothing to combine")
        return
    combined = pd.concat(frames, ignore_index=True)
    target = outdir / (f"nse_all_eod.{'parquet' if fmt == 'parquet' else 'csv'}")
    if fmt == "parquet":
        combined.to_parquet(target, index=False)
    else:
        combined.to_csv(target, index=False)
    log.info("Wrote %s (%d rows, %d symbols)", target, len(combined), combined["SYMBOL"].nunique())


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="NSE end-of-day downloader (yfinance)",
        epilog="Examples:\n"
        "  %(prog)s RELIANCE TCS INFY        download just these three\n"
        "  %(prog)s --years 20               download the entire NSE universe\n"
        "  %(prog)s RELIANCE --update        append only the newest bars",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "symbols",
        nargs="*",
        help="one or more NSE symbols, space separated (e.g. RELIANCE TCS "
        "INFY). The .NS suffix is optional. Omit entirely to download "
        "every listed NSE equity.",
    )
    p.add_argument("--outdir", default="./nse_data", help="output directory")
    p.add_argument("--years", type=int, default=20, help="history length in years")
    p.add_argument("--end", default=None, help="end date YYYY-MM-DD (default: tomorrow)")
    p.add_argument("--series", default="EQ,BE", help="NSE series filter, comma separated, or 'all'")
    p.add_argument(
        "--symbols-file", default=None, help="use a local EQUITY_L.csv instead of fetching it"
    )
    p.add_argument("--limit", type=int, default=0, help="only the first N symbols (testing)")
    p.add_argument(
        "--suffix",
        default=".NS",
        help="exchange suffix appended to bare symbols (default: .NS, use .BO for BSE)",
    )
    p.add_argument("--force", action="store_true", help="re-download even if a file already exists")
    p.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p.add_argument("--batch-size", type=int, default=25, help="tickers per yfinance call")
    p.add_argument("--sleep", type=float, default=1.5, help="base pause between batches (s)")
    p.add_argument("--retries", type=int, default=3, help="attempts per batch")
    p.add_argument("--threads", type=int, default=4, help="yfinance worker threads (0 = off)")
    p.add_argument(
        "--update", action="store_true", help="append only bars newer than what's already stored"
    )
    p.add_argument(
        "--retry-failed", action="store_true", help="only re-attempt symbols listed in failures.csv"
    )
    p.add_argument(
        "--combine",
        action="store_true",
        help="after downloading, also write one stacked long-format file",
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    args.threads = args.threads if args.threads and args.threads > 1 else False
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(outdir / "download.log", encoding="utf-8"),
        ],
    )
    code = run(args)
    if args.combine:
        build_combined(outdir, args.format)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
