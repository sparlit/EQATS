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
AXIOM API — FastAPI backend that exposes the existing Python trading engine
to the React frontend. Reuses data/, screener/, storage/ modules directly.

Run locally:  uvicorn backend.main:app --reload --port 8000
"""

import sys
from pathlib import Path

# Ensure project root on path when run as `uvicorn backend.main:app`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from cachetools import TTLCache
from data.econ_calendar import fetch_calendar
from data.fii_dii import fetch_fii_dii
from data.live_market import fetch_gainers_losers, fetch_indices
from data.news_feed import fetch_market_news
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

IST = ZoneInfo("Asia/Kolkata")

app = FastAPI(title="AXIOM API", version="1.0", description="Advanced eXpert Intelligence for Operations in Market")

# CORS — allow the Vercel frontend + local dev. Tighten ALLOWED_ORIGINS in prod via env.
import os

_origins = os.getenv("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins == "*" else [o.strip() for o in _origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-process TTL caches to avoid hammering upstream sources
_cache: dict[str, TTLCache] = {
    "indices": TTLCache(maxsize=2, ttl=180),
    "movers": TTLCache(maxsize=2, ttl=180),
    "news": TTLCache(maxsize=2, ttl=600),
    "calendar": TTLCache(maxsize=2, ttl=1800),
    "fii": TTLCache(maxsize=2, ttl=900),
    "regime": TTLCache(maxsize=2, ttl=900),
}


def _cached(bucket: str, fn):
    c = _cache[bucket]
    if "v" in c:
        return c["v"]
    val = fn()
    c["v"] = val
    return val


# Per-key caches (symbol-scoped) — Render has no parquet engine, so without
# these every chart/quote call re-hits yfinance. These make repeats instant.
_hist_cache: TTLCache = TTLCache(maxsize=128, ttl=120)
_quote_cache: TTLCache = TTLCache(maxsize=64, ttl=60)


def _keyed(cache: TTLCache, key: str, fn):
    if key in cache:
        return cache[key]
    val = fn()
    cache[key] = val
    return val


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AXIOM API", "time_ist": datetime.now(IST).isoformat()}


@app.get("/api/clock")
def clock():
    """Authoritative IST time for the frontend clock."""
    now = datetime.now(IST)
    is_open = now.weekday() < 5 and (now.hour, now.minute) >= (9, 15) and (now.hour, now.minute) <= (15, 30)
    return {
        "iso": now.isoformat(),
        "ist": now.strftime("%H:%M:%S"),
        "date": now.strftime("%a, %d %b %Y"),
        "market_open": is_open,
    }


@app.get("/api/market/indices")
def indices():
    return {"indices": _cached("indices", fetch_indices)}


@app.get("/api/market/movers")
def movers():
    return _cached("movers", lambda: fetch_gainers_losers("NIFTY", 6))


@app.get("/api/news")
def news():
    items = _cached("news", lambda: fetch_market_news(20))
    # datetime objects aren't JSON-serialisable — drop the raw field
    return {"news": [{k: v for k, v in n.items() if k != "published"} for n in items]}


@app.get("/api/calendar")
def calendar():
    cal = _cached("calendar", lambda: fetch_calendar(14))
    corp = [{**e, "date": e["date"].isoformat() if e.get("date") else None} for e in cal.get("corporate", [])]
    macro = [{**e, "date": e["date"].isoformat() if e.get("date") else None} for e in cal.get("macro", [])]
    return {"corporate": corp, "macro": macro}


@app.get("/api/fii-dii")
def fii_dii():
    return _cached("fii", fetch_fii_dii)


@app.get("/api/regime")
def regime():
    def _run():
        from screener.regime_classifier import classify_regime

        r = classify_regime()
        return {
            "regime": r.regime,
            "nifty_close": r.nifty_close,
            "ema50": r.ema50,
            "ema200": r.ema200,
            "adx": r.adx_value,
            "max_positions": r.max_positions,
            "min_rr": r.min_rr,
            "reason": r.reason,
        }

    try:
        return _cached("regime", _run)
    except Exception as exc:
        logger.warning("Regime failed: {}", exc)
        raise HTTPException(status_code=503, detail="Regime classification unavailable")


@app.get("/api/watchlist")
def watchlist():
    try:
        import pandas as pd

        from config import WATCHLIST_CSV

        if WATCHLIST_CSV.exists():
            df = pd.read_csv(WATCHLIST_CSV)
            return {"watchlist": df.to_dict("records")}
    except Exception as exc:
        logger.warning("Watchlist read failed: {}", exc)
    return {"watchlist": []}


# The full screener is heavy (fetches the universe). Run once, cache 10 min, and
# let the screener / RS-ranking / custom-scan endpoints all read these records.
_screener_cache: TTLCache = TTLCache(maxsize=1, ttl=600)
_SCAN_COLS = [
    "symbol",
    "grade",
    "score",
    "close",
    "rsi",
    "adx",
    "rs_20d",
    "rs_60d",
    "volume_ratio",
    "ema9",
    "ema21",
    "ema50",
    "ema200",
    "mtf",
    "mtf_of",
    "notes",
]


def _full_screener() -> list[dict]:
    if "v" in _screener_cache:
        return _screener_cache["v"]
    from screener.screener import run_screener

    df = run_screener(None)
    rows = [] if df.empty else df[[c for c in _SCAN_COLS if c in df.columns]].to_dict("records")
    _screener_cache["v"] = rows
    return rows


@app.on_event("startup")
def _warm_screener() -> None:
    """Pre-compute the screener in the background at boot (reads the OHLCV
    cache, ~7s) so the first user request never waits or times out."""
    import threading

    def _warm():
        try:
            rows = _full_screener()
            logger.info("Screener cache warmed: {} rows", len(rows))
        except Exception as exc:
            logger.warning("Screener warm failed: {}", exc)

    threading.Thread(target=_warm, daemon=True).start()


@app.get("/api/screener")
def screener(limit: int = 30):
    """Top candidates by composite score (cached 10 min)."""
    try:
        return {"results": _full_screener()[:limit]}
    except Exception as exc:
        logger.exception("Screener failed: {}", exc)
        raise HTTPException(status_code=503, detail="Screener unavailable")


@app.get("/api/rs-ranking")
def rs_ranking(by: str = "rs_20d", limit: int = 40):
    """Relative-strength leaderboard vs Nifty (sorted by 20D or 60D RS)."""
    try:
        key = "rs_60d" if by == "rs_60d" else "rs_20d"
        rows = sorted(_full_screener(), key=lambda r: r.get(key) or -999, reverse=True)
        return {"by": key, "results": rows[:limit]}
    except Exception as exc:
        logger.exception("RS ranking failed: {}", exc)
        raise HTTPException(status_code=503, detail="RS ranking unavailable")


@app.get("/api/scan/custom")
def scan_custom(
    rsi_min: float = 0,
    rsi_max: float = 100,
    adx_min: float = 0,
    vol_min: float = 0,
    score_min: float = 0,
    rs20_min: float = -999,
    grade: str = "",
    above_ema200: bool = False,
    ema_aligned: bool = False,
    sort_by: str = "score",
    limit: int = 60,
):
    """User-defined scanner over the universe (filters the cached screener results)."""
    try:

        def ok(r: dict) -> bool:
            rsi = r.get("rsi")
            adx = r.get("adx")
            if rsi is not None and not (rsi_min <= rsi <= rsi_max):
                return False
            if adx is not None and adx < adx_min:
                return False
            if (r.get("volume_ratio") or 0) < vol_min:
                return False
            if (r.get("score") or 0) < score_min:
                return False
            if (r.get("rs_20d") if r.get("rs_20d") is not None else -999) < rs20_min:
                return False
            if grade and r.get("grade") != grade.upper():
                return False
            if above_ema200 and not (r.get("close") and r.get("ema200") and r["close"] > r["ema200"]):
                return False
            if ema_aligned and not (
                r.get("ema9") and r.get("ema21") and r.get("ema50") and r["ema9"] > r["ema21"] > r["ema50"]
            ):
                return False
            return True

        skey = sort_by if sort_by in ("score", "rs_20d", "rs_60d", "rsi", "adx", "volume_ratio") else "score"
        rows = sorted([r for r in _full_screener() if ok(r)], key=lambda r: r.get(skey) or -999, reverse=True)
        return {"count": len(rows), "results": rows[:limit]}
    except Exception as exc:
        logger.exception("Custom scan failed: {}", exc)
        raise HTTPException(status_code=503, detail="Custom scan unavailable")


_symbols_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


@app.get("/api/symbols")
def symbols():
    """Universe symbols + company names for fast client-side search."""
    if "v" in _symbols_cache:
        return _symbols_cache["v"]
    try:
        from data.fetcher import load_universe

        df = load_universe()
        out = [
            {
                "symbol": str(r.get("symbol") or r.get("yfinance_ticker")),
                "name": str(r.get("company_name") or ""),
                "sector": str(r.get("industry") or ""),
            }
            for r in df.to_dict("records")
            if r.get("symbol") or r.get("yfinance_ticker")
        ]
        payload = {"count": len(out), "symbols": out}
        _symbols_cache["v"] = payload
        return payload
    except Exception as exc:
        logger.exception("Symbols list failed: {}", exc)
        raise HTTPException(status_code=503, detail="Symbols unavailable")


# ── Sketch Pattern Finder ─────────────────────────────────────────────
# Match a user-drawn price shape against the whole universe's recent closes.
_closes_cache: TTLCache = TTLCache(maxsize=1, ttl=900)


def _closes_data() -> dict:
    if "v" not in _closes_cache:
        from data.closes import read_closes

        _closes_cache["v"] = read_closes()
    return _closes_cache["v"]


def _norm(arr):
    import numpy as np

    a = np.asarray(arr, dtype=float)
    lo, hi = a.min(), a.max()
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


class PatternReq(BaseModel):
    shape: list[float]  # drawn curve, sampled top→bottom-agnostic
    window: int = 60  # trailing bars to match against
    top: int = 24
    min_price: float = 0.0


@app.post("/api/pattern-match")
def pattern_match(req: PatternReq):
    """Rank universe symbols whose recent price action best matches a drawn shape."""
    import numpy as np

    shape = [float(x) for x in (req.shape or []) if x == x]
    if len(shape) < 4:
        raise HTTPException(status_code=400, detail="Shape too short")
    target = _norm(shape)
    n = len(target)
    xi = np.linspace(0, 1, n)
    win = max(20, min(int(req.window), 250))

    payload = _closes_data()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    results = []
    for sym, closes in data.items():
        if not closes or len(closes) < max(30, win // 2):
            continue
        seg = np.asarray(closes[-win:], dtype=float)
        if req.min_price and seg[-1] < req.min_price:
            continue
        # resample segment to the sketch's resolution, then min-max normalize
        rs = np.interp(xi, np.linspace(0, 1, len(seg)), seg)
        cand = _norm(rs)
        dist = float(np.mean(np.abs(cand - target)))  # shape distance 0..1
        corr = float(np.corrcoef(cand, target)[0, 1]) if np.std(cand) > 0 else 0.0
        if np.isnan(corr):
            corr = 0.0
        score = max(0.0, (1 - dist) * 0.6 + (corr + 1) / 2 * 0.4) * 100
        results.append(
            {
                "symbol": sym,
                "score": round(score, 1),
                "last": round(float(seg[-1]), 2),
                "pct": round(float((seg[-1] - seg[0]) / seg[0] * 100), 1) if seg[0] else 0.0,
                "spark": [round(float(v), 2) for v in seg[-min(len(seg), 80) :]],
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return {
        "count": len(results),
        "window": win,
        "updated": payload.get("updated"),
        "results": results[: max(1, min(int(req.top), 60))],
    }


# ── Quant Lab ──────────────────────────────────────────────────────────────
_quant_cache: TTLCache = TTLCache(maxsize=64, ttl=300)


@app.get("/api/quant/gex")
def quant_gex(symbol: str = "NIFTY"):
    """Dealer gamma-exposure (GEX) profile from the option chain."""
    try:
        from analytics.quant import gamma_exposure

        return _keyed(_quant_cache, f"gex:{symbol.upper()}", lambda: gamma_exposure(symbol))
    except Exception as exc:
        logger.exception("GEX failed: {}", exc)
        raise HTTPException(status_code=503, detail="GEX unavailable")


@app.get("/api/quant/vol-cone")
def quant_vol_cone(symbol: str):
    """Realized-volatility cone / term structure with historical percentile bands."""
    try:
        from analytics.quant import vol_cone

        return _keyed(_quant_cache, f"cone:{symbol.upper()}", lambda: vol_cone(symbol))
    except Exception as exc:
        logger.exception("Vol cone failed: {}", exc)
        raise HTTPException(status_code=503, detail="Vol cone unavailable")


@app.get("/api/quant/expectancy")
def quant_expectancy(symbol: str):
    """Expectancy (R) surface over a stop(ATR) × target(R:R) grid."""
    try:
        from analytics.quant import expectancy_surface

        return _keyed(_quant_cache, f"exp:{symbol.upper()}", lambda: expectancy_surface(symbol))
    except Exception as exc:
        logger.exception("Expectancy surface failed: {}", exc)
        raise HTTPException(status_code=503, detail="Expectancy surface unavailable")


class CorrReq(BaseModel):
    symbols: list[str] = []


@app.post("/api/quant/correlation")
def quant_correlation(req: CorrReq):
    """Return-correlation matrix across symbols (defaults to the watchlist)."""
    try:
        from analytics.quant import correlation

        syms = [s.strip() for s in req.symbols if s.strip()]
        if not syms:
            import csv

            from config import DATA_DIR

            wl = DATA_DIR / "watchlist.csv"
            if wl.exists():
                with wl.open() as f:
                    syms = [r["symbol"] for r in csv.DictReader(f) if r.get("symbol")][:12]
        syms = [s if s.endswith(".NS") else f"{s}.NS" for s in syms][:15]
        return correlation(syms)
    except Exception as exc:
        logger.exception("Correlation failed: {}", exc)
        raise HTTPException(status_code=503, detail="Correlation unavailable")


_macro_cache: TTLCache = TTLCache(maxsize=1, ttl=300)


@app.get("/api/global-macro")
def global_macro():
    """World indices, commodities, crypto, FX + risk-on/off composite."""
    try:
        from data.global_macro import fetch_global_macro

        return _keyed(_macro_cache, "v", fetch_global_macro)
    except Exception as exc:
        logger.exception("Global macro failed: {}", exc)
        raise HTTPException(status_code=503, detail="Global macro unavailable")


_wnews_cache: TTLCache = TTLCache(maxsize=1, ttl=600)


@app.get("/api/world-news")
def world_news():
    """Geocoded news markers (RSS headlines matched to a gazetteer) for the map."""
    try:
        from data.world_news import geocode_news

        return _keyed(_wnews_cache, "v", geocode_news)
    except Exception as exc:
        logger.exception("World news failed: {}", exc)
        return {"available": False, "points": []}


_livech_cache: TTLCache = TTLCache(maxsize=1, ttl=1800)  # 30 min — conserves YouTube API quota


@app.get("/api/live-channels")
def live_channels_ep():
    """Which business-TV channels are currently live (for the Live-TV card)."""
    try:
        from data.live_channels import live_channels

        return _keyed(_livech_cache, "v", live_channels)
    except Exception as exc:
        logger.exception("Live channels failed: {}", exc)
        return {"channels": [], "first_live": None}


_company_cache: TTLCache = TTLCache(maxsize=64, ttl=3600)


def _company_get(symbol: str) -> dict:
    """fetch_company with caching — but never cache failures, so a transient
    Yahoo block doesn't pin 'no data' for an hour."""
    from data.company import fetch_company

    key = symbol.upper()
    if key in _company_cache:
        return _company_cache[key]
    result = fetch_company(symbol)
    if result.get("available"):
        _company_cache[key] = result
    return result


@app.get("/api/company")
def company(symbol: str):
    """Company terminal: fundamentals + shareholding + quarterly financials + technicals."""
    try:
        return _company_get(symbol)
    except Exception as exc:
        logger.exception("Company data failed: {}", exc)
        raise HTTPException(status_code=503, detail="Company data unavailable")


_peers_cache: TTLCache = TTLCache(maxsize=32, ttl=3600)


@app.get("/api/company/peers")
def company_peers(symbol: str):
    """Peer comparison — same-industry names side by side (COMP panel)."""

    def _run():
        import pandas as pd
        from data.company import fetch_company

        from config import DATA_DIR

        sym = symbol.upper().replace(".NS", "")
        uni = pd.read_csv(DATA_DIR / "universe.csv")
        row = uni[uni["Symbol"].str.upper() == sym]
        if row.empty:
            return {"symbol": sym, "available": False, "note": "Symbol not in universe."}
        industry = row.iloc[0]["Industry"]
        peers_syms = uni[uni["Industry"] == industry]["Symbol"].str.upper().tolist()
        # self first, then up to 5 peers (universe order ≈ liquidity)
        ordered = [sym, *[s for s in peers_syms if s != sym][:5]]
        rows = []
        for s in ordered:
            try:
                c = _company_get(s)
                if not c.get("available"):
                    continue
                rows.append(
                    {
                        "symbol": c["symbol"],
                        "name": (c.get("name") or c["symbol"])[:28],
                        "market_cap": c.get("market_cap"),
                        "pe": c.get("pe"),
                        "pb": c.get("pb"),
                        "roe": c.get("roe"),
                        "rev_growth": c.get("rev_growth"),
                        "profit_margin": c.get("profit_margin"),
                        "div_yield": c.get("div_yield"),
                        "rs_nifty": (c.get("tech") or {}).get("rs_nifty"),
                        "pct_chg20": (c.get("tech") or {}).get("pct_chg20"),
                        "self": c["symbol"] == sym,
                    }
                )
            except Exception as exc:
                logger.debug("peer {} failed: {}", s, exc)
        return {"symbol": sym, "available": bool(rows), "industry": industry, "peers": rows}

    try:
        key = symbol.upper()
        if key in _peers_cache:
            return _peers_cache[key]
        result = _run()
        if result.get("available"):
            _peers_cache[key] = result
        return result
    except Exception as exc:
        logger.exception("Peers failed: {}", exc)
        raise HTTPException(status_code=503, detail="Peers unavailable")


_airead_cache: TTLCache = TTLCache(maxsize=32, ttl=3600)


@app.get("/api/company/ai")
def company_ai(symbol: str):
    """One-click AI read of the company: valuation vs quality, red flags, verdict."""

    def _run():
        import json as _json

        from ai.brain import _call_groq

        c = _company_get(symbol)
        if not c.get("available"):
            return {"available": False, "note": "No company data."}
        slim = {k: v for k, v in c.items() if k != "summary" and v is not None}
        sys_p = (
            "You are AXIOM's equity analyst for an NSE swing trader. Given fundamentals, "
            "shareholding, quarterly results and technicals, give a direct read. Cite the "
            "numbers. No disclaimers, no fluff."
        )
        user = (
            "Analyze this company. Output ONLY JSON: "
            '{"verdict": "QUALITY"|"FAIR"|"EXPENSIVE"|"AVOID", '
            '"bull": "<2 sentences with numbers>", "bear": "<2 sentences with numbers>", '
            '"technical": "<1 sentence on current technical posture>", '
            '"flags": ["<red flag>", ...max 3]}\n\nDATA: ' + _json.dumps(slim, default=str)[:5000]
        )
        raw = _call_groq(sys_p, user, max_tokens=900)
        import re

        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        try:
            out = _json.loads(m.group(0)) if m else {}
        except Exception:
            out = {}
        if not out.get("verdict"):
            return {"available": False, "note": "AI read unavailable — try again."}
        return {
            "available": True,
            "symbol": c["symbol"],
            **{k: out.get(k) for k in ("verdict", "bull", "bear", "technical", "flags")},
        }

    try:
        key = symbol.upper()
        if key in _airead_cache:
            return _airead_cache[key]
        result = _run()
        if result.get("available"):
            _airead_cache[key] = result
        return result
    except Exception as exc:
        logger.exception("AI read failed: {}", exc)
        raise HTTPException(status_code=503, detail="AI read unavailable")


# heatmap sector name → universe Industry values
_SECTOR_INDUSTRIES = {
    "IT": ["IT"],
    "Banking": ["Financial Services"],
    "Auto": ["Automobile"],
    "Pharma": ["Pharma", "Healthcare"],
    "FMCG": ["FMCG"],
    "Metal": ["Metals & Mining"],
    "Energy": ["Oil Gas & Fuels", "Power"],
    "Infra": ["Construction", "Capital Goods"],
    "Realty": ["Realty"],
    "PSU Bank": ["Financial Services"],
}


@app.get("/api/sector/constituents")
def sector_constituents(sector: str):
    """Ranked constituents of a heatmap sector (score/RS/MTF from the screener cache)."""
    try:
        import pandas as pd

        from config import DATA_DIR

        industries = _SECTOR_INDUSTRIES.get(sector)
        uni = pd.read_csv(DATA_DIR / "universe.csv")
        if industries:
            members = uni[uni["Industry"].isin(industries)]
        else:  # allow direct Industry names too (e.g. "Chemicals")
            members = uni[uni["Industry"] == sector]
        if members.empty:
            return {"sector": sector, "available": False, "note": "Unknown sector."}
        tickers = {str(t).upper() for t in members["yfinance_Ticker"].dropna()}
        names = {str(r["yfinance_Ticker"]).upper(): str(r["Company_Name"]) for _, r in members.iterrows()}
        rows = [
            dict(r, name=names.get(str(r.get("symbol", "")).upper(), ""))
            for r in _full_screener()
            if str(r.get("symbol", "")).upper() in tickers
        ]
        rows.sort(key=lambda r: r.get("score") or 0, reverse=True)
        return {
            "sector": sector,
            "available": bool(rows),
            "industries": industries or [sector],
            "count": len(rows),
            "results": rows,
        }
    except Exception as exc:
        logger.exception("Sector constituents failed: {}", exc)
        raise HTTPException(status_code=503, detail="Sector data unavailable")


# Heatmap sector label → matching universe Industry values (substring match)
_SECTOR_INDUSTRY = {
    "IT": ["Information Technology", "IT", "Telecom"],
    "Banking": ["Financial Services", "Bank"],
    "PSU Bank": ["Financial Services", "Bank"],
    "Auto": ["Automobile"],
    "Pharma": ["Pharma", "Healthcare"],
    "FMCG": ["FMCG", "Consumer"],
    "Metal": ["Metals & Mining"],
    "Energy": ["Oil Gas & Fuels", "Power", "Energy"],
    "Infra": ["Construction", "Capital Goods", "Services"],
    "Realty": ["Realty", "Construction"],
}
_secdd_cache: TTLCache = TTLCache(maxsize=16, ttl=600)


@app.get("/api/sector/constituents")
def sector_constituents(sector: str, limit: int = 25):
    """Drill-down: screener-scored constituents of a heatmap sector, ranked."""

    def _run():
        import pandas as pd

        from config import DATA_DIR

        uni = pd.read_csv(DATA_DIR / "universe.csv")
        pats = _SECTOR_INDUSTRY.get(sector, [sector])
        mask = uni["Industry"].fillna("").str.contains("|".join(pats), case=False, regex=True)
        syms = {s.upper() for s in uni[mask]["Symbol"].dropna().astype(str)}
        rows = [r for r in _full_screener() if str(r.get("symbol", "")).replace(".NS", "").upper() in syms]
        rows.sort(key=lambda r: r.get("score") or 0, reverse=True)
        return {"available": bool(rows), "sector": sector, "count": len(rows), "constituents": rows[:limit]}

    try:
        return _keyed(_secdd_cache, f"{sector}|{limit}", _run)
    except Exception as exc:
        logger.exception("Sector drill-down failed: {}", exc)
        return {"available": False, "sector": sector, "constituents": [], "note": "Unavailable."}


@app.get("/api/paper")
def paper_portfolios():
    """Paper-Trading Autopilot: forward track record per alert-enabled scan."""
    try:
        from analytics.paper import all_portfolios

        return all_portfolios()
    except Exception as exc:
        logger.exception("Paper portfolios failed: {}", exc)
        return {"available": False, "note": "Paper portfolios unavailable."}


_earn_cache: TTLCache = TTLCache(maxsize=64, ttl=3600)


@app.get("/api/earnings-playbook")
def earnings_playbook(symbol: str):
    """Historical post-earnings behavior for a symbol (results-day move, drift)."""
    try:
        from analytics.earnings import earnings_stats

        st = _keyed(_earn_cache, symbol.upper(), lambda: earnings_stats(symbol))
        if not st:
            return {"available": False, "note": "No earnings history for this symbol."}
        return {"available": True, "symbol": symbol.upper().replace(".NS", ""), **st}
    except Exception as exc:
        logger.exception("Earnings playbook failed: {}", exc)
        return {"available": False, "note": "Earnings playbook unavailable."}


_honesty_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


@app.get("/api/signal-honesty")
def signal_honesty_ep():
    """Forward-test of AXIOM's own picks: grade vs 5/10/20-day forward returns."""
    try:
        from analytics.honesty import signal_honesty

        return _keyed(_honesty_cache, "v", signal_honesty)
    except Exception as exc:
        logger.exception("Signal honesty failed: {}", exc)
        return {"available": False, "note": "Signal honesty unavailable."}


_sitrep_cache: TTLCache = TTLCache(maxsize=1, ttl=900)


@app.get("/api/global-sitrep")
def global_sitrep():
    """AI Global Situation Report — per-region market stance + India impact."""
    try:
        from ai.sitrep import build_sitrep

        return _keyed(_sitrep_cache, "v", build_sitrep)
    except Exception as exc:
        logger.exception("SITREP failed: {}", exc)
        return {"available": False, "note": "SITREP unavailable."}


_sentiment_cache: TTLCache = TTLCache(maxsize=1, ttl=600)


@app.get("/api/news-sentiment")
def news_sentiment():
    """AI sentiment over the live headline feed → market meter + per-stock tags."""
    try:
        from ai.sentiment import analyze_news_sentiment

        return _keyed(_sentiment_cache, "v", analyze_news_sentiment)
    except Exception as exc:
        logger.exception("News sentiment failed: {}", exc)
        return {
            "available": False,
            "headlines": [],
            "by_symbol": {},
            "market": {"score": 0, "label": "Unavailable", "bull": 0, "bear": 0, "neutral": 0},
        }


@app.get("/api/breadth")
def breadth():
    """Market internals from the universe closes cache (% above DMAs, A/D, 52w highs)."""
    try:
        from analytics.quant import market_breadth

        return _keyed(_quant_cache, "breadth", market_breadth)
    except Exception as exc:
        logger.exception("Breadth failed: {}", exc)
        raise HTTPException(status_code=503, detail="Breadth unavailable")


@app.get("/api/quant/rrg")
def quant_rrg(symbols: str = "", tail: int = 8):
    """Relative Rotation Graph (RS-Ratio vs RS-Momentum vs NIFTY)."""
    try:
        from analytics.rrg import compute_rrg

        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        if not syms:
            import csv

            from config import DATA_DIR

            wl = DATA_DIR / "watchlist.csv"
            if wl.exists():
                with wl.open() as f:
                    syms = [r["symbol"] for r in csv.DictReader(f) if r.get("symbol")][:15]
        key = f"rrg:{','.join(sorted(syms))}:{tail}"
        return _keyed(_quant_cache, key, lambda: compute_rrg(syms, tail=max(2, min(int(tail), 16))))
    except Exception as exc:
        logger.exception("RRG failed: {}", exc)
        raise HTTPException(status_code=503, detail="RRG unavailable")


class Position(BaseModel):
    symbol: str
    risk_pct: float = 2.0


class HeatReq(BaseModel):
    positions: list[Position] = []
    candidate: Position | None = None


@app.post("/api/portfolio-heat")
def portfolio_heat(req: HeatReq):
    """Pre-trade portfolio heat: correlation to the open book + aggregate risk vs caps."""
    try:
        from analytics.quant import correlation

        from config import MAX_DAILY_RISK_PCT, MAX_POSITION_RISK_PCT

        book = list(req.positions)
        allpos = book + ([req.candidate] if req.candidate else [])
        syms = [(p.symbol if p.symbol.endswith(".NS") else f"{p.symbol}.NS") for p in allpos]
        total_risk = sum(p.risk_pct for p in allpos)
        cap = MAX_DAILY_RISK_PCT * 100
        warnings = []
        if total_risk > cap:
            warnings.append(f"Total open risk {total_risk:.1f}% exceeds the {cap:.0f}% daily cap.")
        if req.candidate and req.candidate.risk_pct > MAX_POSITION_RISK_PCT * 100:
            warnings.append(
                f"Candidate risk {req.candidate.risk_pct:.1f}% exceeds the {MAX_POSITION_RISK_PCT * 100:.0f}% per-trade cap."
            )
        if len(allpos) > 2:
            warnings.append(f"{len(allpos)} positions — house rule is max 2 concurrent.")

        corr = correlation(syms) if len(syms) >= 2 else {"available": False}
        # highest correlation of candidate vs each existing position
        cand_pairs = []
        if req.candidate and corr.get("available"):
            labels = corr["symbols"]
            ci = len(labels) - 1  # candidate appended last (if all resolved)
            cand_label = req.candidate.symbol.replace(".NS", "")
            if cand_label in labels:
                ci = labels.index(cand_label)
                for j, lab in enumerate(labels):
                    if j != ci:
                        cand_pairs.append({"symbol": lab, "corr": corr["matrix"][ci][j]})
                cand_pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
                for p in cand_pairs:
                    if p["corr"] >= 0.7:
                        warnings.append(
                            f"Candidate is {p['corr']:.2f} correlated with {p['symbol']} — effectively one bet."
                        )
                        break
        return {
            "total_risk": round(total_risk, 1),
            "cap": cap,
            "positions": len(allpos),
            "correlation": corr,
            "candidate_pairs": cand_pairs[:5],
            "warnings": warnings,
            "ok": not warnings,
        }
    except Exception as exc:
        logger.exception("Portfolio heat failed: {}", exc)
        raise HTTPException(status_code=503, detail="Portfolio heat unavailable")


@app.get("/api/events/watch")
def events_watch(symbols: str = "", days: int = 10):
    """Flag upcoming corporate (results/board) + high-impact macro events for given
    symbols, enriched with each stock's historical post-earnings behavior."""
    try:
        from analytics.earnings import earnings_stats
        from data.econ_calendar import fetch_corporate_events, macro_events

        want = {s.strip().replace(".NS", "").upper() for s in symbols.split(",") if s.strip()}
        corp = fetch_corporate_events(days_ahead=days, limit=60)
        hits = [dict(e) for e in corp if e.get("symbol", "").replace(".NS", "").upper() in want] if want else []
        seen = {h.get("symbol", "").replace(".NS", "").upper() for h in hits}
        # merge scheduled earnings from the fundamentals cache (covers gaps in
        # the NSE calendar) + attach the playbook stats
        for sym in want:
            try:
                st = earnings_stats(sym)
            except Exception:
                st = None
            if not st:
                continue
            if sym not in seen and st.get("days_to") is not None and 0 <= st["days_to"] <= days:
                hits.append({"symbol": sym, "purpose": "Results", "date_str": st.get("next_date", ""), "date": None})
                seen.add(sym)
            for h in hits:
                if h.get("symbol", "").replace(".NS", "").upper() == sym:
                    h["earnings"] = st
        macro = [e for e in macro_events(days_ahead=days) if (e.get("impact") or "").upper() == "HIGH"]
        return {"days": days, "flagged": hits, "macro": macro, "count": len(hits), "any": bool(hits or macro)}
    except Exception as exc:
        logger.exception("Events watch failed: {}", exc)
        return {"days": days, "flagged": [], "macro": [], "count": 0, "any": False}


class NLScanReq(BaseModel):
    query: str


@app.post("/api/scan/nl")
def scan_nl(req: NLScanReq):
    """Natural-language screener — Groq parses the query into scan filters, then runs them."""
    try:
        import json as _json

        from ai.brain import _call_groq

        sys_p = (
            "You convert a trader's request into JSON scan filters for an NSE screener. "
            "Output ONLY a JSON object (no prose) with any of these keys: "
            "rsi_min,rsi_max,adx_min,vol_min (volume x avg),score_min,rs20_min (relative strength %),"
            "grade (A|B|C),above_ema200 (bool),ema_aligned (bool),sort_by (score|rs_20d|rs_60d|rsi|adx|volume_ratio). "
            'Only include keys the user implies. Example: {"adx_min":25,"vol_min":1.5,"ema_aligned":true,"sort_by":"rs_20d"}'
        )
        raw = _call_groq(sys_p, req.query, max_tokens=200).strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
        start, end = raw.find("{"), raw.rfind("}")
        params = _json.loads(raw[start : end + 1]) if start >= 0 else {}

        # sanitize → only known keys
        allowed = {
            "rsi_min",
            "rsi_max",
            "adx_min",
            "vol_min",
            "score_min",
            "rs20_min",
            "grade",
            "above_ema200",
            "ema_aligned",
            "sort_by",
        }
        clean = {k: v for k, v in params.items() if k in allowed}

        def ok(r: dict) -> bool:
            rsi, adx = r.get("rsi"), r.get("adx")
            if "rsi_min" in clean and rsi is not None and rsi < clean["rsi_min"]:
                return False
            if "rsi_max" in clean and rsi is not None and rsi > clean["rsi_max"]:
                return False
            if "adx_min" in clean and adx is not None and adx < clean["adx_min"]:
                return False
            if "vol_min" in clean and (r.get("volume_ratio") or 0) < clean["vol_min"]:
                return False
            if "score_min" in clean and (r.get("score") or 0) < clean["score_min"]:
                return False
            if "rs20_min" in clean and (r.get("rs_20d") if r.get("rs_20d") is not None else -999) < clean["rs20_min"]:
                return False
            if clean.get("grade") and r.get("grade") != str(clean["grade"]).upper():
                return False
            if clean.get("above_ema200") and not (r.get("close") and r.get("ema200") and r["close"] > r["ema200"]):
                return False
            if clean.get("ema_aligned") and not (
                r.get("ema9") and r.get("ema21") and r.get("ema50") and r["ema9"] > r["ema21"] > r["ema50"]
            ):
                return False
            return True

        skey = (
            clean.get("sort_by")
            if clean.get("sort_by") in ("score", "rs_20d", "rs_60d", "rsi", "adx", "volume_ratio")
            else "score"
        )
        rows = sorted([r for r in _full_screener() if ok(r)], key=lambda r: r.get(skey) or -999, reverse=True)
        return {"query": req.query, "filters": clean, "count": len(rows), "results": rows[:50]}
    except Exception as exc:
        logger.exception("NL scan failed: {}", exc)
        raise HTTPException(status_code=503, detail="NL scan unavailable")


class TradeReview(BaseModel):
    symbol: str
    entry: float
    stop: float
    target: float
    capital: float = 1_000_000
    risk_pct: float = 2.0
    side: str = "long"
    note: str = ""


@app.post("/api/trade-review")
def trade_review(t: TradeReview):
    """Rules-grounded 'second opinion': deterministic checks vs the rulebook + AI verdict."""
    try:
        risk_per_share = abs(t.entry - t.stop)
        reward = abs(t.target - t.entry)
        rr = round(reward / risk_per_share, 2) if risk_per_share else 0.0
        stop_pct = round(risk_per_share / t.entry * 100, 2) if t.entry else 0.0
        # regime
        regime_name = "UNKNOWN"
        try:
            from screener.regime_classifier import classify_regime

            regime_name = classify_regime().regime
        except Exception:
            pass
        checks = []

        def chk(name, passed, detail):
            checks.append({"rule": name, "pass": bool(passed), "detail": detail})

        chk("R:R ≥ 2:1", rr >= 2, f"R:R is {rr}:1")
        chk("Stop ≤ 2% of entry", stop_pct <= 2.0, f"Stop is {stop_pct}% from entry")
        chk("Risk ≤ 2% of capital", t.risk_pct <= 2.0, f"Risking {t.risk_pct}%")
        chk("Regime allows longs", not (t.side == "long" and regime_name == "BEARISH"), f"Regime: {regime_name}")
        passed = sum(c["pass"] for c in checks)
        verdict = "TAKE" if passed == len(checks) else "CAUTION" if passed >= len(checks) - 1 else "SKIP"

        ai_text = ""
        try:
            from ai.brain import _call_groq

            facts = (
                f"Symbol {t.symbol} ({t.side}). Entry {t.entry}, Stop {t.stop}, Target {t.target}. "
                f"R:R {rr}:1, stop {stop_pct}% of entry, risking {t.risk_pct}% of capital. Regime {regime_name}. "
                f"Rule checks: "
                + "; ".join(f"{c['rule']}={'OK' if c['pass'] else 'FAIL'}" for c in checks)
                + f". Trader note: {t.note or 'none'}."
            )
            sys_p = (
                "You are AXIOM, a hedge-fund risk manager reviewing a trader's PLANNED trade against "
                "their rulebook (R:R≥2, stop≤2% of capital, max 2 positions, no longs in BEARISH regime, "
                "no FOMO/chasing). Give a crisp verdict in 3-4 sentences: confirm the deterministic verdict "
                "or push back, name the single biggest risk, and one concrete adjustment. No fluff."
            )
            ai_text = _call_groq(sys_p, facts, max_tokens=260)
        except Exception:
            pass
        return {
            "symbol": t.symbol,
            "rr": rr,
            "stop_pct": stop_pct,
            "regime": regime_name,
            "checks": checks,
            "verdict": verdict,
            "passed": passed,
            "total": len(checks),
            "ai": ai_text or "AI review unavailable — deterministic checks above stand.",
        }
    except Exception as exc:
        logger.exception("Trade review failed: {}", exc)
        raise HTTPException(status_code=503, detail="Trade review unavailable")


# ── Condition-builder scanner (QuantEdge engine) ────────────────────────────
_builder_cache: TTLCache = TTLCache(maxsize=24, ttl=300)
_BUILDER_UNIVERSES = {"NIFTY 50": 50, "NIFTY 100": 100, "NIFTY 200": 200, "ALL (250)": 250}


def _builder_symbols(name: str) -> list[str]:
    from data.fetcher import load_universe

    syms = load_universe()["symbol"].dropna().astype(str).tolist()
    n = _BUILDER_UNIVERSES.get(name, 100)
    return syms[:n]


class BuilderReq(BaseModel):
    universe: str = "NIFTY 100"
    conditions: list[dict] = []


@app.post("/api/scan/builder")
def scan_builder(req: BuilderReq):
    """Chartink-style condition-builder scan over a universe (ported QuantEdge engine)."""
    try:
        import json as _json

        if not req.conditions:
            raise HTTPException(status_code=400, detail="Add at least one condition.")
        key = f"{req.universe}|{_json.dumps(req.conditions, sort_keys=True)}"

        def _run():
            import pandas as pd
            from data.fetcher import fetch_symbol_history
            from data.ohlcv_cache import get_cached_ohlcv
            from screener.ta_engine import run_builder

            def _fetch(sym, period="1y", interval="1d"):
                cached = get_cached_ohlcv(sym)
                if cached is not None and not cached.empty:
                    return cached
                try:
                    return fetch_symbol_history(sym, period=period, interval=interval)
                except Exception:
                    return pd.DataFrame()

            nifty = _fetch("^NSEI", "2y")
            syms = _builder_symbols(req.universe)
            rows = run_builder(syms, req.conditions, _fetch, nifty)
            rows.sort(key=lambda r: r.get("rs_nifty") or 0, reverse=True)
            return {"count": len(rows), "scanned": len(syms), "universe": req.universe, "results": rows}

        return _keyed(_builder_cache, key, _run)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Builder scan failed: {}", exc)
        raise HTTPException(status_code=503, detail="Builder scan unavailable")


class BuilderBTReq(BaseModel):
    universe: str = "NIFTY 50"
    conditions: list[dict] = []
    from_date: str = "2024-01-01"
    to_date: str = ""
    stop_loss: float = 3.0
    exit_days: int = 8
    exit_rule: str = "After N Days"
    min_rr: float = 2.0


@app.post("/api/scan/builder/backtest")
def scan_builder_backtest(req: BuilderBTReq):
    """Replay the builder conditions over history → trade log, equity curve, stats."""
    try:
        if not req.conditions:
            raise HTTPException(status_code=400, detail="Build a scan first.")
        import pandas as pd
        from data.fetcher import fetch_symbol_history
        from data.ohlcv_cache import get_cached_ohlcv
        from screener.ta_engine import run_backtest

        def _fetch(sym, period="2y", interval="1d"):
            cached = get_cached_ohlcv(sym)
            if cached is not None and not cached.empty:
                return cached
            try:
                return fetch_symbol_history(sym, period=period, interval=interval)
            except Exception:
                return pd.DataFrame()

        nifty = _fetch("^NSEI", "2y")
        syms = _builder_symbols(req.universe)
        trades, equity, stats = run_backtest(
            syms,
            req.conditions,
            _fetch,
            nifty,
            from_date=req.from_date,
            to_date=req.to_date or None,
            stop_pct=req.stop_loss,
            exit_days=req.exit_days,
            exit_rule=req.exit_rule,
            target_rr=req.min_rr,
            cap=40,
        )
        return {"trades": trades, "equity": equity, "stats": stats}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Builder backtest failed: {}", exc)
        raise HTTPException(status_code=503, detail="Builder backtest unavailable")


@app.get("/api/backtest")
def backtest(symbol: str, period: str = "2y", rr: float = 2.5, capital: float = 1_000_000):
    """Run the breakout backtest on one symbol. Returns metrics + recent trades."""
    try:
        from backtest.backtest import BacktestConfig, backtest_symbol
        from data.fetcher import fetch_symbol_history

        sym = symbol.strip().upper()
        if not sym.endswith(".NS"):
            sym += ".NS"
        df = fetch_symbol_history(sym, period=period, interval="1d")
        if df.empty or len(df) < 220:
            raise HTTPException(status_code=422, detail="Insufficient history (need ~220+ daily bars)")
        cfg = BacktestConfig(rr_target=rr, starting_capital=float(capital))
        res = backtest_symbol(df, symbol=sym, cfg=cfg)
        trades = res.trades.copy()
        if not trades.empty:
            for c in ("entry_date", "exit_date"):
                if c in trades.columns:
                    trades[c] = trades[c].astype(str)
        equity = [round(float(v), 2) for v in res.equity.values.tolist()]
        return {
            "symbol": sym,
            "metrics": res.metrics,
            "trades": trades.tail(40).to_dict("records") if not trades.empty else [],
            "equity": equity,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Backtest failed: {}", exc)
        raise HTTPException(status_code=503, detail=f"Backtest failed: {exc}")


class AssistantBody(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/assistant")
def assistant(body: AssistantBody):
    """AXIOM AI chat — powered by the Groq brain."""
    try:
        from ai.brain import _AXIOM_SYSTEM, _call_groq

        ctx = "\n".join(f"{m.get('role')}: {m.get('text')}" for m in body.history[-6:])
        user = (
            (f"Conversation so far:\n{ctx}\n\n" if ctx else "")
            + f"User: {body.message}\n\nRespond as AXIOM — institutional NSE trading assistant. Be direct, analytical, professional."
        )
        reply = _call_groq(_AXIOM_SYSTEM, user, max_tokens=900)
        if not reply:
            raise HTTPException(status_code=503, detail="AI unavailable — check GROQ_API_KEY")
        return {"reply": reply}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Assistant failed: {}", exc)
        raise HTTPException(status_code=503, detail="AI assistant unavailable")


@app.get("/api/footprint")
def footprint(symbol: str, days: int = 1, bins: int = 30):
    """Approximated order-flow footprint from 1-min bars."""
    try:
        from analytics.footprint import APPROXIMATION_NOTE, build_footprint, fetch_intraday

        sym = symbol.strip().upper()
        if not sym.endswith(".NS"):
            sym += ".NS"
        df = fetch_intraday(sym, days=days, interval="1m")
        if df.empty:
            raise HTTPException(status_code=422, detail="No intraday data (market closed or bad symbol)")
        fp = build_footprint(df, symbol=sym, bins=bins)
        return {
            "symbol": sym,
            "poc": fp.poc,
            "total_delta": fp.total_delta,
            "bars": fp.bars,
            "last": round(float(df["close"].iloc[-1]), 2),
            "profile": fp.profile.to_dict("records"),
            "note": APPROXIMATION_NOTE,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Footprint failed: {}", exc)
        raise HTTPException(status_code=503, detail="Footprint unavailable")


_scan_cache = TTLCache(maxsize=1, ttl=180)


@app.get("/api/scan")
def scan():
    """Scan the watchlist on 15-min data for live signals (BREAKOUT / BB_SQUEEZE / MOMENTUM)."""
    if "v" in _scan_cache:
        return _scan_cache["v"]
    try:
        from monitors.intraday_monitor import _compute_signals, _fetch_15m
        from storage.watchlist_csv import load_watchlist_symbols

        symbols = load_watchlist_symbols()[:18]
        results = []
        for sym in symbols:
            df = _fetch_15m(sym)
            if df.empty:
                continue
            data = _compute_signals(df)
            if not data:
                continue
            results.append(
                {
                    "symbol": sym.replace(".NS", ""),
                    "signals": data.get("signals", []),
                    "close": data.get("close"),
                    "rsi": data.get("rsi"),
                    "adx": data.get("adx"),
                    "vol_ratio": data.get("vol_ratio"),
                    "macd_hist": data.get("macd_hist"),
                }
            )
        # signals first, then by ADX
        results.sort(key=lambda r: (-len(r["signals"]), -(r.get("adx") or 0)))
        out = {"count": len(symbols), "results": results, "ist": datetime.now(IST).strftime("%H:%M:%S")}
        _scan_cache["v"] = out
        return out
    except Exception as exc:
        logger.exception("Scan failed: {}", exc)
        raise HTTPException(status_code=503, detail="Scanner unavailable")


@app.get("/api/tasks")
def tasks(session: str = "pre-market"):
    """AI-generated pre/post-market checklist."""
    try:
        from ai.brain import generate_task_list
        from data.fetcher import load_universe

        try:
            n = len(load_universe())
        except Exception:
            n = 0
        checklist = generate_task_list(
            {
                "session": session,
                "symbol_count": n,
                "market": "NSE",
                "time": datetime.now(IST).strftime("%H:%M IST"),
                "date": datetime.now(IST).strftime("%d %b %Y"),
            }
        )
        return {"session": session, "checklist": checklist or ""}
    except Exception as exc:
        logger.exception("Tasks failed: {}", exc)
        raise HTTPException(status_code=503, detail="Checklist generation unavailable")


_briefing_cache: TTLCache = TTLCache(maxsize=1, ttl=1800)


@app.get("/api/briefing")
def briefing():
    """Generate the institutional morning briefing text (cross-asset context + AI).
    Cached 30 min so the dashboard card doesn't re-pay context + AI per load."""

    def _run():
        from ai.brain import generate_market_briefing
        from data.market_context import build_briefing_context

        context = build_briefing_context()
        text = generate_market_briefing(context)
        if not text:
            msg = "AI unavailable"
            raise RuntimeError(msg)
        return {"briefing": text, "date": datetime.now(IST).strftime("%d %b %Y")}

    try:
        return _keyed(_briefing_cache, "v", _run)
    except Exception as exc:
        logger.exception("Briefing failed: {}", exc)
        raise HTTPException(status_code=503, detail="Briefing unavailable")


class BriefingSend(BaseModel):
    briefing: str


@app.post("/api/briefing/telegram")
def briefing_to_telegram(body: BriefingSend):
    """Render the briefing to a branded PDF and send it to Telegram."""
    try:
        from pathlib import Path

        from monitors.telegram_bot import send_document
        from reports.pdf_generator import generate_text_report

        out = ROOT / "data" / "reports"
        out.mkdir(parents=True, exist_ok=True)
        pdf = out / f"briefing_{datetime.now(IST).strftime('%Y%m%d_%H%M')}.pdf"
        generate_text_report("AXIOM Morning Briefing", body.briefing, pdf)
        ok, err = send_document(
            pdf, caption=f"📊 <b>AXIOM Morning Briefing — {datetime.now(IST).strftime('%d %b %Y')}</b>"
        )
        if not ok:
            raise HTTPException(status_code=503, detail=f"Telegram send failed: {err}")
        return {"sent": True, "file": pdf.name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Briefing->Telegram failed: {}", exc)
        raise HTTPException(status_code=503, detail="Send failed")


# yfinance intraday history limits → cap the requested period per interval.
_PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
_INTERVAL_MAXDAYS = {"5m": 60, "15m": 60, "30m": 60, "60m": 730, "1h": 730}


def _clamp_period(interval: str, period: str) -> str:
    cap = _INTERVAL_MAXDAYS.get(interval)
    if cap is None:
        return period  # daily/weekly — no clamp
    want = _PERIOD_DAYS.get(period, 180)
    return f"{min(want, cap)}d"


def _history(symbol: str, period: str, interval: str) -> dict:
    import pandas as pd
    from data.fetcher import fetch_symbol_history
    from utils.indicators import adx_full, atr, ema, rsi

    sym = symbol.strip().upper()
    if not sym.endswith(".NS"):
        sym += ".NS"
    yf_interval = "1h" if interval == "60m" else interval
    eff_period = _clamp_period(yf_interval, period)
    df = fetch_symbol_history(sym, period=eff_period, interval=yf_interval)
    if df.empty:
        raise HTTPException(status_code=422, detail="No data for symbol")

    # lightweight-charts requires ascending, de-duplicated timestamps
    df = df[~df.index.duplicated(keep="last")].sort_index()
    close = df["close"]
    ema20, ema50, ema200 = ema(close, 20), ema(close, 50), ema(close, 200)
    rsi_s = rsi(close, 14)
    adx_s = adx_full(df, 14)["adx"]
    last = df.iloc[-1]

    tail = df.tail(500)
    candles = [
        {
            "t": int(idx.timestamp()),
            "o": round(float(r.open), 2),
            "h": round(float(r.high), 2),
            "l": round(float(r.low), 2),
            "c": round(float(r.close), 2),
            "v": int(r.volume),
        }
        for idx, r in tail.iterrows()
    ]
    prev = float(close.iloc[-2]) if len(close) > 1 else float(last.close)
    return {
        "symbol": sym,
        "interval": interval,
        "last": round(float(last.close), 2),
        "change": round(float(last.close) - prev, 2),
        "pct": round((float(last.close) - prev) / prev * 100, 2) if prev else 0.0,
        "rsi": round(float(rsi_s.iloc[-1]), 1) if pd.notna(rsi_s.iloc[-1]) else None,
        "adx": round(float(adx_s.iloc[-1]), 1) if pd.notna(adx_s.iloc[-1]) else None,
        "ema20": round(float(ema20.iloc[-1]), 2),
        "ema50": round(float(ema50.iloc[-1]), 2),
        "ema200": round(float(ema200.iloc[-1]), 2) if pd.notna(ema200.iloc[-1]) else None,
        "atr": round(float(atr(df, 14).iloc[-1]), 2),
        "high_52w": round(float(close.tail(252).max()), 2),
        "low_52w": round(float(close.tail(252).min()), 2),
        "candles": candles,
    }


@app.get("/api/history")
def history(symbol: str, period: str = "6mo", interval: str = "1d"):
    """OHLCV + scalar indicators for one symbol/timeframe. Cached per symbol|interval|period."""
    try:
        key = f"{symbol.strip().upper()}|{interval}|{period}"
        return _keyed(_hist_cache, key, lambda: _history(symbol, period, interval))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("History failed: {}", exc)
        raise HTTPException(status_code=503, detail="History unavailable")


@app.get("/api/analysis")
def analysis(symbol: str):
    """AI 9-section technical analysis for one symbol."""
    try:
        from ai.brain import generate_stock_analysis

        h = history(symbol)  # reuse computed indicators
        data = {
            k: h[k] for k in ("last", "pct", "rsi", "adx", "ema20", "ema50", "ema200", "atr", "high_52w", "low_52w")
        }
        text = generate_stock_analysis(h["symbol"], data)
        return {"symbol": h["symbol"], "analysis": text}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analysis failed: {}", exc)
        raise HTTPException(status_code=503, detail="Analysis unavailable")


_sec_cache = TTLCache(maxsize=1, ttl=180)


@app.get("/api/sectors")
def sectors():
    """Sector performance (1-day %) for the heatmap — yfinance-based."""
    if "v" in _sec_cache:
        return _sec_cache["v"]
    from data.market_context import fetch_sector_performance

    perf = fetch_sector_performance()
    items = sorted([{"sector": k, "pct": v} for k, v in perf.items()], key=lambda x: x["pct"], reverse=True)
    out = {"sectors": items}
    _sec_cache["v"] = out
    return out


def _quote(symbols: str) -> dict:
    import yfinance as yf

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:40]
    tickers = [s if s.endswith(".NS") else s + ".NS" for s in syms]
    if not tickers:
        return {"quotes": []}
    data = yf.download(
        tickers, period="2d", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True
    )
    out = []
    for s, t in zip(syms, tickers, strict=False):
        try:
            df = data[t].dropna() if len(tickers) > 1 else data.dropna()
            if len(df) < 1:
                continue
            last = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else last
            out.append(
                {
                    "symbol": s.replace(".NS", ""),
                    "ltp": round(last, 2),
                    "change": round(last - prev, 2),
                    "pct": round((last - prev) / prev * 100, 2) if prev else 0.0,
                }
            )
        except Exception:
            continue
    return {"quotes": out}


@app.get("/api/quote")
def quote(symbols: str):
    """Batch last price + day % for a comma-separated symbol list (yfinance), cached 60s."""
    try:
        key = ",".join(sorted(s.strip().upper() for s in symbols.split(",") if s.strip()))
        return _keyed(_quote_cache, key, lambda: _quote(symbols))
    except Exception as exc:
        logger.warning("Quote failed: {}", exc)
        return {"quotes": []}


@app.post("/api/assistant/stream")
def assistant_stream(body: AssistantBody):
    """Streaming AXIOM chat — yields tokens as plain text as they arrive."""
    from ai.brain import _AXIOM_SYSTEM, call_groq_stream
    from fastapi.responses import StreamingResponse

    ctx = "\n".join(f"{m.get('role')}: {m.get('text')}" for m in body.history[-6:])
    user = (
        (f"Conversation so far:\n{ctx}\n\n" if ctx else "")
        + f"User: {body.message}\n\nRespond as AXIOM — institutional NSE trading assistant. Be direct, analytical, professional."
    )

    def gen():
        yield from call_groq_stream(_AXIOM_SYSTEM, user)

    return StreamingResponse(
        gen(), media_type="text/plain; charset=utf-8", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    )


_options_cache: TTLCache = TTLCache(maxsize=4, ttl=120)


@app.get("/api/options")
def options(symbol: str = "NIFTY"):
    """Index option-chain analytics: PCR, max-pain, support/resistance, ATM IV, OI chain."""
    try:
        sym = symbol.upper()
        from data.options import fetch_option_chain

        return _keyed(_options_cache, sym, lambda: fetch_option_chain(sym))
    except Exception as exc:
        logger.exception("Options failed: {}", exc)
        raise HTTPException(status_code=503, detail="Options unavailable")


@app.get("/")
def root():
    return {"service": "AXIOM API", "docs": "/docs", "health": "/api/health"}
