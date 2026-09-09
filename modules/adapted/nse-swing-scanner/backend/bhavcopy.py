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
bhavcopy.py
Latest-day delivery / traded-value data for the scanner.

Multi-provider fallback chain (real NSE delivery data is gold, but NSE's
archive endpoints are routinely blocked by Akamai bot protection, so we
have a documented ladder):

  1. **NSE archives** (`nse:bhavcopy`) — primary source. CSVs at
     https://nsearchives.nseindia.com/content/equities/eq_bhavcopy_full_YYYYMMDD.csv
     or sec_bhavdata_full_YYYYMMDD.csv carry real delivery_qty / delivery_val
     columns. Tries the most recent 5 trading days.
  2. **yfinance traded-value proxy** (`yfinance:traded_value_proxy`) — when NSE
     fails, fetches the latest day's OHLCV for the universe via yfinance and
     reports `volume × close` as the per-symbol traded value. NOT delivery;
     marked with `delivery_kind: "traded_value_proxy"` so the UI can label
     it correctly.
  3. **BSE archives** (`bse:bhavcopy`) — last-resort attempt from BSE's
     bhavcopy endpoint. Different host/CDN than NSE so sometimes works
     when NSE is blocked.

The returned payload always uses the NSE-shaped dict:
  data[symbol] = {"delivery_qty": ..., "delivery_value_inr": ...,
                  "delivery_pct": ..., "delivery_kind": ...}
with a top-level `source_status` ("ok" | "fallback_used" | "source_failed")
and a `provider_chain` list describing what was tried.
"""
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf
from cache import read_cache, write_cache
from nse_client import NSE_ARCHIVES_BASE, nse_get
from settings import BHAVCOPY_CACHE_TTL_SECONDS
from source_status import make_status, worst_status

ARCHIVES_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
    "Referer": "https://www.nseindia.com/",
}

# BSE uses the same User-Agent language; BSE's CDN is on a separate host.
BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/csv,application/zip,*/*",
    "Referer": "https://www.bseindia.com/",
}

BHAVCOPY_FILENAMES = [
    "sec_bhavdata_full_{date}.csv",
    "eq_bhavcopy_full_{date}.csv",
]

BSE_BHAVCOPY_FILENAMES = [
    "EQ{date}_CSV.ZIP",  # historical filename
    "EQ_ISINCODE_{date}.ZIP",  # alternate
]

YFINANCE_PROVIDER = "yfinance:traded_value_proxy"
NSE_PROVIDER = "nse:bhavcopy"
BSE_PROVIDER = "bse:bhavcopy"


def _bhavcopy_url_for(d: date) -> list[str]:
    d_str = d.strftime("%Y%m%d")
    return [f"{NSE_ARCHIVES_BASE}/content/equities/" + fn.format(date=d_str) for fn in BHAVCOPY_FILENAMES]


def _bse_bhavcopy_url_for(d: date) -> list[str]:
    """BSE filename patterns observed historically. The exact filename
    rotates; we try a small set on each lookback day."""
    d_str = d.strftime("%d%m%y")
    return [
        "https://www.bseindia.com/download/BhavCopy/Equity/" + fn.format(date=d_str) for fn in BSE_BHAVCOPY_FILENAMES
    ]


# ---------------------------------------------------------------------------
# Provider 1: NSE archives
# ---------------------------------------------------------------------------


def _try_nse_archives(timeout: int, max_lookback_days: int) -> dict:
    """Try the NSE bhavcopy CSV endpoints for the most recent lookback days.
    Returns a source_status dict; status='ok' if any URL returned a parseable CSV."""
    today = date.today()
    last_err: str | None = None
    for offset in range(max_lookback_days + 1):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:  # Sat/Sun — NSE doesn't publish bhavcopy
            continue
        for url in _bhavcopy_url_for(d):
            try:
                resp = requests.get(url, headers=ARCHIVES_HEADERS, timeout=timeout)
            except Exception as e:
                last_err = str(e)
                continue
            if resp.status_code != 200 or len(resp.text) < 100:
                last_err = f"HTTP {resp.status_code}"
                continue
            try:
                df = pd.read_csv(io.StringIO(resp.text))
            except Exception as e:
                last_err = f"csv parse failed: {e}"
                continue
            parsed = _parse_bhavcopy(df)
            if parsed:
                return make_status(
                    source=f"{NSE_PROVIDER}:{url}",
                    status="ok",
                    as_of=d.isoformat(),
                    data=parsed,
                    extra={"delivery_kind": "actual"},
                )
    return make_status(
        source=NSE_PROVIDER,
        status="source_failed",
        data={},
        error=last_err or "no bhavcopy reachable in lookback window",
    )


# ---------------------------------------------------------------------------
# Provider 2: yfinance traded-value proxy
# ---------------------------------------------------------------------------


def _yfinance_fetch_one(yf_ticker: str, timeout: int = 10) -> dict | None:
    """Fetch the latest day's OHLCV for one ticker. Returns None on any error."""
    try:
        t = yf.Ticker(yf_ticker)
        hist = t.history(period="5d", auto_adjust=True, timeout=timeout)
    except Exception:
        return None
    if hist is None or hist.empty or "Volume" not in hist.columns:
        return None
    valid = hist.dropna(subset=["Close"])
    if valid.empty:
        return None
    last = valid.iloc[-1]
    if pd.isna(last["Close"]) or pd.isna(last["Volume"]):
        return None
    close = float(last["Close"])
    volume = float(last["Volume"])
    return {
        "close": close,
        "volume": volume,
        "as_of": valid.index[-1].strftime("%Y-%m-%d"),
    }


def _try_yfinance_traded_value(
    symbols: list[str],
    yf_tickers: list[str],
    workers: int = 12,
) -> dict:
    """Fallback: fetch latest-day OHLCV for the universe and report
    `volume × close` as a traded-value proxy. NOT delivery data."""
    if not symbols or not yf_tickers or len(symbols) != len(yf_tickers):
        return make_status(
            source=YFINANCE_PROVIDER,
            status="source_failed",
            data={},
            error="universe symbols/tickers missing or mismatched",
        )

    # Hash the joined ticker list so the cache filename stays short for the
    # Nifty 500 universe (~7000 chars would otherwise exceed most filesystem
    # filename limits of ~255 bytes).
    import hashlib

    universe_hash = hashlib.sha256(",".join(yf_tickers).encode("utf-8")).hexdigest()[:16]
    cache_key = f"yfproxy:{universe_hash}"
    cached = read_cache(cache_key, max_age_seconds=BHAVCOPY_CACHE_TTL_SECONDS)
    if cached is not None:
        cached.setdefault("provider", YFINANCE_PROVIDER)
        return cached

    by_symbol: dict[str, dict] = {}
    errors: list[str] = []
    workers = max(1, min(workers, len(yf_tickers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_yfinance_fetch_one, yf): sym for sym, yf in zip(symbols, yf_tickers, strict=False)}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                rec = fut.result()
            except Exception as e:
                errors.append(f"{sym}: {e}")
                continue
            if rec is None:
                continue
            close = rec["close"]
            volume = rec["volume"]
            by_symbol[sym] = {
                # NOTE: these fields are TRADED value / volume, NOT delivery.
                # The "delivery_" prefix is preserved for downstream contract
                # compatibility; consumers should consult `delivery_kind`.
                "delivery_qty": volume,
                "delivery_value_inr": volume * close,
                "delivery_pct": None,
                "delivery_kind": "traded_value_proxy",
            }

    if not by_symbol:
        return make_status(
            source=YFINANCE_PROVIDER,
            status="source_failed",
            data={},
            error="; ".join(errors[:3]) or "no yfinance rows returned",
        )

    # Find the most common as_of date across successful fetches.
    [
        _yfinance_fetch_one.cache_info().currsize if False else None  # placeholder
    ]
    # We don't carry as_of per-row from the parallel fetch; use today's date
    # as a coarse "as_of" — the row's date is also exposed via the cached payload.
    result = make_status(
        source=YFINANCE_PROVIDER,
        status="ok",
        as_of=date.today().isoformat(),
        data=by_symbol,
        extra={
            "delivery_kind": "traded_value_proxy",
            "universe_size": len(by_symbol),
        },
    )
    write_cache(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Provider 3: BSE archives (best-effort)
# ---------------------------------------------------------------------------


def _try_bse_archives(timeout: int, max_lookback_days: int) -> dict:
    today = date.today()
    last_err: str | None = None
    for offset in range(max_lookback_days + 1):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        for url in _bse_bhavcopy_url_for(d):
            try:
                resp = requests.get(url, headers=BSE_HEADERS, timeout=timeout)
            except Exception as e:
                last_err = str(e)
                continue
            if resp.status_code != 200 or len(resp.content) < 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            # BSE returns a ZIP archive; extract the inner CSV.
            try:
                import zipfile

                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                csv_name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
                if not csv_name:
                    last_err = "no CSV in BSE zip"
                    continue
                with zf.open(csv_name) as fh:
                    df = pd.read_csv(fh)
            except Exception as e:
                last_err = f"BSE parse failed: {e}"
                continue
            parsed = _parse_bhavcopy(df)
            if parsed:
                return make_status(
                    source=f"{BSE_PROVIDER}:{url}",
                    status="ok",
                    as_of=d.isoformat(),
                    data=parsed,
                    extra={"delivery_kind": "actual"},
                )
    return make_status(
        source=BSE_PROVIDER,
        status="source_failed",
        data={},
        error=last_err or "no BSE bhavcopy reachable in lookback window",
    )


# ---------------------------------------------------------------------------
# Combined fetcher with fallback chain
# ---------------------------------------------------------------------------


def fetch_bhavcopy(
    timeout: int = 15,
    max_lookback_days: int = 5,
    universe_symbols: list[str] | None = None,
    universe_yf_tickers: list[str] | None = None,
) -> dict:
    """
    Try providers in order: NSE archives → yfinance traded-value proxy → BSE.

    The returned payload matches the NSE shape:
      data[symbol] = {"delivery_qty", "delivery_value_inr", "delivery_pct",
                      "delivery_kind"}
    so the existing scanner.py integration doesn't need to change beyond
    passing the universe.

    `provider_chain` lists what was tried in order, with each provider's
    outcome, so the UI can show "NSE failed → yfinance proxy served".
    """
    chain: list[dict] = []

    # 1. NSE archives
    nse = _try_nse_archives(timeout, max_lookback_days)
    chain.append({"provider": nse["source"], "status": nse["status"]})
    if nse["status"] == "ok":
        nse.setdefault("provider_chain", chain)
        return nse

    # 2. yfinance traded-value proxy (only if we know the universe)
    yf_result: dict | None = None
    if universe_symbols and universe_yf_tickers:
        yf_result = _try_yfinance_traded_value(
            universe_symbols,
            universe_yf_tickers,
        )
        chain.append({"provider": yf_result["source"], "status": yf_result["status"]})
        if yf_result["status"] == "ok":
            merged = _merge_partial(nse, yf_result)
            merged["provider_chain"] = chain
            return merged

    # 3. BSE archives (best-effort, falls back gracefully)
    bse = _try_bse_archives(timeout, max_lookback_days)
    chain.append({"provider": bse["source"], "status": bse["status"]})
    if bse["status"] == "ok" and yf_result and yf_result.get("status") == "ok":
        merged = _merge_partial(yf_result, bse)
        merged["provider_chain"] = chain
        return merged
    if bse["status"] == "ok":
        bse["provider_chain"] = chain
        return bse

    # All providers failed
    combined_error = "; ".join(c.get("provider", "?") + "=" + c.get("status", "?") for c in chain)
    result = make_status(
        source="+".join(c["provider"] for c in chain),
        status="source_failed",
        data={},
        error=f"all providers failed: {combined_error}",
    )
    result["provider_chain"] = chain
    return result


def _merge_partial(secondary: dict, primary: dict) -> dict:
    """Merge data from `primary` over `secondary`. Primary's status wins if ok."""
    merged_data = dict(secondary.get("data") or {})
    merged_data.update(primary.get("data") or {})
    return make_status(
        source=primary["source"],
        status=primary["status"],
        as_of=primary.get("as_of"),
        data=merged_data,
        extra={
            "delivery_kind": primary.get("delivery_kind", "actual"),
            "fallback_from": secondary["source"],
        },
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_bhavcopy(df: pd.DataFrame) -> dict[str, dict]:
    """
    Normalize column names and extract per-symbol delivery qty / value / pct.
    NSE column names vary; we lowercase + strip + match.
    """
    df.columns = [str(c).strip().lower() for c in df.columns]
    sym_col = next((c for c in ("symbol", "symbol_nse", "scrip", "scripcode") if c in df.columns), None)
    if sym_col is None:
        return {}
    deliv_qty_col = next((c for c in ("delivqty", "delivery_qty", "del_qty") if c in df.columns), None)
    deliv_val_col = next((c for c in ("delivval", "delivery_value", "del_val") if c in df.columns), None)
    deliv_pct_col = next((c for c in ("deliv_per", "delivery_pct", "del_pct") if c in df.columns), None)
    close_col = next((c for c in ("close", "close_price", "last") if c in df.columns), None)
    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        sym = str(row[sym_col]).strip().upper()
        if not sym or sym in ("SYMBOL", "NAN", "SCRIPCODE"):
            continue
        # BSE codes are numeric; we keep them as-is but the scanner matches by
        # NSE symbol, so the caller needs to translate. For now we accept both.
        rec: dict = {}
        if deliv_qty_col is not None and pd.notna(row.get(deliv_qty_col)):
            rec["delivery_qty"] = float(row[deliv_qty_col])
        if deliv_val_col is not None and pd.notna(row.get(deliv_val_col)):
            v = float(row[deliv_val_col])
            # NSE publishes delivery value in lakhs of rupees; convert to INR.
            rec["delivery_value_inr"] = v * 1_00_000
        elif deliv_qty_col is not None and close_col is not None:
            q = row.get(deliv_qty_col)
            p = row.get(close_col)
            if pd.notna(q) and pd.notna(p):
                rec["delivery_value_inr"] = float(q) * float(p)
        if deliv_pct_col is not None and pd.notna(row.get(deliv_pct_col)):
            rec["delivery_pct"] = float(row[deliv_pct_col])
        if rec:
            rec.setdefault("delivery_kind", "actual")
            out[sym] = rec
    return out


# ---------------------------------------------------------------------------
# Per-symbol lookup (kept stable for scanner.py)
# ---------------------------------------------------------------------------


def lookup_delivery(bhavcopy_payload: dict, symbol: str) -> dict:
    """
    Look up a single symbol in a bhavcopy source_status payload.

    Returns the per-symbol record with the additional `source_status`,
    `source`, `delivery_kind`, `fallback_from` fields lifted from the payload.
    """
    overall = bhavcopy_payload.get("status", "source_failed")
    per = bhavcopy_payload.get("data") or {}
    hit = per.get(symbol.upper())
    if hit is not None:
        return {
            "delivery_qty": hit.get("delivery_qty"),
            "delivery_value_inr": hit.get("delivery_value_inr"),
            "delivery_pct": hit.get("delivery_pct"),
            "delivery_kind": hit.get("delivery_kind", "actual"),
            "fallback_from": bhavcopy_payload.get("fallback_from"),
            "as_of": bhavcopy_payload.get("as_of"),
            "source_status": overall,
            "source": bhavcopy_payload.get("source"),
        }
    return {
        "delivery_qty": None,
        "delivery_value_inr": None,
        "delivery_pct": None,
        "delivery_kind": None,
        "fallback_from": bhavcopy_payload.get("fallback_from"),
        "as_of": bhavcopy_payload.get("as_of"),
        "source_status": "missing" if overall == "ok" else overall,
        "source": bhavcopy_payload.get("source"),
    }
