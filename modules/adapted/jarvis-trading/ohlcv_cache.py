"""
OHLCV cache — 2 years of daily bars for the scan universe, so the condition
Builder scan + backtest read from memory instead of fetching yfinance live
(turns the cold-start wait into instant). Built daily by GitHub Actions
(yfinance works there), committed as a small gzipped JSON; the backend loads it
once per process and serves per-symbol frames on demand.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime

from loguru import logger

from config import DATA_DIR

CACHE_FILE = DATA_DIR / "ohlcv_cache.json.gz"
MAX_SYMBOLS = 520          # full universe — screener + Builder both read from cache
BENCH = "^NSEI"

_RAW: dict | None = None   # in-memory {sym: {t,o,h,l,c,v}}, loaded once


def _load() -> dict:
    global _RAW
    if _RAW is not None:
        return _RAW
    try:
        if CACHE_FILE.exists():
            with gzip.open(CACHE_FILE, "rt", encoding="utf-8") as f:
                _RAW = json.load(f).get("data", {})
            logger.info("OHLCV cache loaded: {} symbols", len(_RAW))
        else:
            _RAW = {}
    except Exception as exc:
        logger.warning("OHLCV cache load failed: {}", exc)
        _RAW = {}
    return _RAW


def get_cached_ohlcv(sym: str):
    """Return a normalized OHLCV DataFrame for a cached symbol, else None."""
    raw = _load().get(sym)
    if not raw or not raw.get("t"):
        return None
    import pandas as pd
    idx = pd.to_datetime(raw["t"], unit="s")
    return pd.DataFrame({"open": raw["o"], "high": raw["h"], "low": raw["l"],
                         "close": raw["c"], "volume": raw["v"]}, index=idx)


def cache_status() -> dict:
    return {"available": CACHE_FILE.exists(), "symbols": len(_load())}


# ── builder (GitHub Actions) ────────────────────────────────────────────────
def build_cache(period: str = "2y") -> dict:
    import warnings
    warnings.simplefilter("ignore")
    import pandas as pd
    import yfinance as yf

    from data.fetcher import load_universe

    symbols = load_universe()["symbol"].dropna().astype(str).tolist()[:MAX_SYMBOLS]
    if BENCH not in symbols:
        symbols.append(BENCH)
    logger.info("Building OHLCV cache for {} symbols…", len(symbols))

    out: dict[str, dict] = {}
    for i in range(0, len(symbols), 80):
        chunk = symbols[i:i + 80]
        try:
            df = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                             progress=False, threads=True, auto_adjust=True)
        except Exception as exc:
            logger.warning("chunk fetch failed: {}", exc)
            continue
        for sym in chunk:
            try:
                sub = df[sym][["Open", "High", "Low", "Close", "Volume"]].dropna()
                sub = sub[sub["Close"] > 0]
                if len(sub) < 30:
                    continue
                out[sym] = {
                    "t": [int(ts.timestamp()) for ts in sub.index],
                    "o": [round(float(x), 2) for x in sub["Open"]],
                    "h": [round(float(x), 2) for x in sub["High"]],
                    "l": [round(float(x), 2) for x in sub["Low"]],
                    "c": [round(float(x), 2) for x in sub["Close"]],
                    "v": [int(x) for x in sub["Volume"].fillna(0)],
                }
            except Exception:
                continue

    payload = {"updated": datetime.utcnow().isoformat() + "Z", "count": len(out), "data": out}
    with gzip.open(CACHE_FILE, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    logger.info("OHLCV cache written: {} symbols → {} ({:.1f} MB)",
                len(out), CACHE_FILE, CACHE_FILE.stat().st_size / 1e6)
    return payload
