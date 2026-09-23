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
Fundamentals cache — company info / shareholding / quarterly results for the
whole universe, built nightly by GitHub Actions (yfinance works there; Yahoo's
quoteSummary API intermittently blocks Render's datacenter IP).

The Company Terminal tries a live fetch first (freshest when Yahoo allows) and
falls back to this cache, so it always works on the cloud.
"""

import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from loguru import logger

from config import DATA_DIR

CACHE_FILE = DATA_DIR / "fundamentals_cache.json.gz"
GITHUB_RAW = "https://raw.githubusercontent.com/agrawalarnav129-ui/jarvis-trading/main/data/fundamentals_cache.json.gz"

_RAW: dict | None = None


def _load() -> dict:
    global _RAW
    if _RAW is not None:
        return _RAW
    try:
        if CACHE_FILE.exists():
            with gzip.open(CACHE_FILE, "rt", encoding="utf-8") as f:
                _RAW = json.load(f).get("data", {})
            logger.info("Fundamentals cache loaded: {} symbols", len(_RAW))
            return _RAW
    except Exception as exc:
        logger.warning("Fundamentals cache load failed: {}", exc)
    try:
        r = requests.get(GITHUB_RAW, timeout=15)
        if r.status_code == 200:
            _RAW = json.loads(gzip.decompress(r.content).decode("utf-8")).get("data", {})
            logger.info("Fundamentals cache loaded from GitHub raw: {} symbols", len(_RAW))
            return _RAW
    except Exception as exc:
        logger.warning("Fundamentals raw fetch failed: {}", exc)
    _RAW = {}
    return _RAW


def get_cached_fundamentals(symbol: str) -> dict | None:
    sym = symbol.upper().replace(".NS", "")
    return _load().get(sym)


# ── builder (GitHub Actions / residential) ──────────────────────────────────
def build_fundamentals_cache(max_symbols: int = 520, workers: int = 6) -> dict:
    import warnings

    warnings.simplefilter("ignore")

    from data.company import fetch_company
    from data.fetcher import load_universe

    symbols = [s.replace(".NS", "") for s in load_universe()["symbol"].dropna().astype(str).tolist()[:max_symbols]]
    symbols = list(dict.fromkeys(symbols))
    logger.info("Building fundamentals cache for {} symbols…", len(symbols))

    def _one(sym: str):
        try:
            c = fetch_company(sym, use_cache=False)
            if not c.get("available"):
                return None
            c.pop("tech", None)  # technicals are computed fresh at read time
            if c.get("summary"):
                c["summary"] = str(c["summary"])[:400]
            # earnings dates (past + scheduled) → powers the earnings playbook
            try:
                import yfinance as yf

                ed = yf.Ticker(f"{sym}.NS").earnings_dates
                if ed is not None and len(ed):
                    c["earnings_dates"] = sorted({d.strftime("%Y-%m-%d") for d in ed.index})
            except Exception:
                pass
            return (sym, c)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = [r for r in ex.map(_one, symbols) if r]

    out = dict(results)
    payload = {"updated": datetime.utcnow().isoformat() + "Z", "count": len(out), "data": out}
    with gzip.open(CACHE_FILE, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), default=str)
    logger.info(
        "Fundamentals cache written: {} symbols → {} ({:.2f} MB)", len(out), CACHE_FILE, CACHE_FILE.stat().st_size / 1e6
    )
    return payload
