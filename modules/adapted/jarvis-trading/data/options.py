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
Index option-chain analytics — sourced from Moneycontrol (NSE blocks datacenter IPs).

Moneycontrol serves the chain as an HTML table at
  https://www.moneycontrol.com/indices/fno/view-option-chain/<SYMBOL>/<YYYY-MM-DD>
We parse it for per-strike Call/Put OI, then compute PCR, max-pain,
support/resistance. Underlying spot comes from yfinance. A GitHub-Actions
snapshot (data/options_cache.json) is the fallback if Moneycontrol throttles.
"""

import io
import json
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from loguru import logger

from config import DATA_DIR

CACHE_FILE = DATA_DIR / "options_cache.json"
GITHUB_RAW = "https://raw.githubusercontent.com/agrawalarnav129-ui/jarvis-trading/main/data/options_cache.json"
MC_URL = "https://www.moneycontrol.com/indices/fno/view-option-chain/{sym}/{exp}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
SYMBOLS = ["NIFTY", "BANKNIFTY"]
_SPOT_TICKER = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}


def _num(x) -> float:
    s = str(x).replace(",", "").strip()
    if s in ("-", "", "nan", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _expiry_candidates() -> list[str]:
    """Upcoming Tue/Thu (NSE weekly/monthly expiry days), nearest first."""
    today = date.today()
    out = [today + timedelta(days=i) for i in range(45)]
    return [d.strftime("%Y-%m-%d") for d in out if d.weekday() in (1, 3)][:10]


def _spot(symbol: str) -> float:
    try:
        import yfinance as yf

        df = yf.Ticker(_SPOT_TICKER.get(symbol, "^NSEI")).history(period="2d")
        return round(float(df["Close"].dropna().iloc[-1]), 2) if not df.empty else 0.0
    except Exception:
        return 0.0


def _parse_table(html: str) -> list[dict]:
    """Parse the Moneycontrol option-chain table → [{strike, ceOI, peOI, ceLTP, peLTP}]."""
    tables = pd.read_html(io.StringIO(html))
    tbl = next((t for t in tables if t.shape[1] >= 11 and t.shape[0] >= 5), None)
    if tbl is None:
        return []
    rows = []
    for _, r in tbl.iterrows():
        v = r.tolist()
        strike = _num(v[5])
        if strike <= 0:
            continue
        ce_oi, pe_oi = _num(v[0]), _num(v[10])
        rows.append(
            {"strike": strike, "ceOI": int(ce_oi), "peOI": int(pe_oi), "ceLTP": _num(v[4]), "peLTP": _num(v[6])}
        )
    return [r for r in rows if r["ceOI"] or r["peOI"]]


def _analyse(rows: list[dict], symbol: str, spot: float, expiry: str) -> dict:
    sl = sorted(rows, key=lambda x: x["strike"])
    ce_oi = sum(r["ceOI"] for r in sl)
    pe_oi = sum(r["peOI"] for r in sl)

    def pain(at: float) -> float:
        return sum(r["ceOI"] * max(0, at - r["strike"]) + r["peOI"] * max(0, r["strike"] - at) for r in sl)

    max_pain = min((r["strike"] for r in sl), key=pain) if sl else None

    resistance = max(sl, key=lambda x: x["ceOI"])["strike"] if sl else None
    support = max(sl, key=lambda x: x["peOI"])["strike"] if sl else None
    if spot <= 0 and sl:
        spot = max_pain or sl[len(sl) // 2]["strike"]
    atm = min(sl, key=lambda x: abs(x["strike"] - spot)) if sl else None
    step = (sl[1]["strike"] - sl[0]["strike"]) if len(sl) > 1 else 50
    chain = [r for r in sl if atm and abs(r["strike"] - atm["strike"]) <= 15 * step]

    return {
        "symbol": symbol,
        "available": True,
        "spot": round(spot, 2),
        "expiry": expiry,
        "pcr": round(pe_oi / ce_oi, 2) if ce_oi else 0,
        "total_ce_oi": int(ce_oi),
        "total_pe_oi": int(pe_oi),
        "max_pain": max_pain,
        "support": support,
        "resistance": resistance,
        "atm_iv": None,
        "chain": [{"strike": r["strike"], "ceOI": r["ceOI"], "peOI": r["peOI"]} for r in chain],
    }


def fetch_option_chain(symbol: str = "NIFTY") -> dict:
    symbol = symbol.upper()
    spot = _spot(symbol)
    s = requests.Session()
    s.headers.update(_HEADERS)
    for exp in _expiry_candidates():
        try:
            r = s.get(MC_URL.format(sym=symbol, exp=exp), timeout=15)
            if r.status_code != 200:
                continue
            rows = _parse_table(r.text)
            if len(rows) >= 5:
                out = _analyse(rows, symbol, spot, exp)
                out["source"] = "Moneycontrol"
                return out
        except Exception as exc:
            logger.debug("MC option-chain {} {} failed: {}", symbol, exp, exc)
    logger.warning("Moneycontrol option-chain failed for {}; trying cache", symbol)
    cached = _read_cache().get(symbol)
    if cached and cached.get("available"):
        return {**cached, "source": "Moneycontrol (cached)"}
    return {"symbol": symbol, "available": False, "note": "Option chain temporarily unavailable"}


def write_cache() -> None:
    out: dict = {}
    for sym in SYMBOLS:
        try:
            out[sym] = fetch_option_chain(sym)
        except Exception as exc:
            logger.warning("Options cache {} failed: {}", sym, exc)
    out["updated"] = datetime.utcnow().isoformat() + "Z"
    CACHE_FILE.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    logger.info("Options cache written: {}", CACHE_FILE)


def _read_cache() -> dict:
    # Prefer GitHub raw (reflects fresh commits without a redeploy), then the
    # build-time local copy.
    try:
        r = requests.get(GITHUB_RAW, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}
