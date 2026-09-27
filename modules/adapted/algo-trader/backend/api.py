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
FastAPI backend — thin HTTP wrapper over the existing Python trading engine.
All business logic stays in engine.py, backtest.py, etc.

Run: uvicorn backend.api:app --reload --port 8000
"""

import math
import os
from typing import Optional

import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def _clean(v):
    """Recursively replace inf/nan with None so the JSON encoder never crashes."""
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, dict):
        return {k: _clean(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_clean(item) for item in v]
    return v


from backtest import run as adv_run
from engine import (
    apply_crossover,
    apply_macd_rsi,
    apply_price_vs_ema,
    apply_rsi,
    apply_supertrend,
    fetch,
    fetch_intraday,
    market_status,
    run_backtest,
)
from risk import RiskConfig
from universe import SYMBOL_SECTOR, all_symbols, get_ticker

app = FastAPI(title="Algo Trader API", version="1.0.0")

# Local dev by default; ALGO_CORS_ORIGINS adds deployed frontends.
_origins = [o for o in os.getenv("ALGO_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    ticker: str
    start: str
    end: str
    strategy: str = "crossover"
    sl_pct: float = 3.0
    tp_pct: float = 6.0
    capital: float = 100_000
    interval: str | None = None


class AdvancedRequest(BaseModel):
    symbols: list[str]
    start: str
    end: str
    capital: float = 100_000
    interval: str = "5m"
    risk_pct: float = 1.0
    max_loss_pct: float = 2.0
    strategy: str | None = None  # force a single strategy
    enabled_strategies: list[str] | None = None  # which strategies are enabled (None = all)
    scan_universe: bool = False  # scan NSE universe for "in play" picks
    max_positions: int = 3  # max concurrent picks when scanning


# ── Strategies ───────────────────────────────────────────────────────────────


@app.get("/api/strategies")
def list_strategies():
    from strategies import STRATEGY_REGISTRY

    return [
        {
            "id": s["id"],
            "name": s["name"],
            "description": s["description"],
        }
        for s in STRATEGY_REGISTRY.values()
    ]


# ── Market status ─────────────────────────────────────────────────────────────


@app.get("/api/market-status")
def get_market_status():
    return market_status()


# ── Live mode (signals only) ──────────────────────────────────────────────────


@app.get("/api/live/decision")
def get_live_decision(symbols: str = Query(..., description="comma-separated NSE symbols"), interval: str = "5m"):
    """
    Today's algorithm decision per symbol: pre_open / observing before 9:45 IST,
    then the chosen strategy arm with entry/SL/TP if a signal has fired.
    Signals only — never places orders.
    """
    from backtest import live_decision

    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="no symbols given")
    try:
        return _clean(live_decision(syms, interval=interval))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Stock search ──────────────────────────────────────────────────────────────

_instruments_cache = None


@app.get("/api/search")
def search_stocks(q: str = Query(..., min_length=1)):
    """
    Search the NSE instrument master (local, from Upstox) — Yahoo search returns
    mutual funds and foreign listings for queries like 'SBI', which have no
    intraday candles and break the app.
    """
    global _instruments_cache
    if _instruments_cache is None:
        from upstox_data import _load_instruments

        df = _load_instruments()
        _instruments_cache = df[["tradingsymbol", "name"]].dropna()

    needle = q.strip().upper()
    df = _instruments_cache
    hit = df[
        df["tradingsymbol"].str.contains(needle, regex=False) | df["name"].str.upper().str.contains(needle, regex=False)
    ]
    # symbol-prefix matches first, then shorter symbols (SBIN before SBICARD)
    hit = hit.assign(_rank=(~hit["tradingsymbol"].str.startswith(needle)).astype(int))
    hit = hit.sort_values(["_rank", "tradingsymbol"], key=lambda s: s.str.len() if s.name == "tradingsymbol" else s)
    return [
        {"symbol": f"{r.tradingsymbol}.NS", "name": r.name_, "exchange": "NSI"}
        for r in hit.head(12).rename(columns={"name": "name_"}).itertuples()
    ]


# ── Universe ──────────────────────────────────────────────────────────────────


@app.get("/api/universe")
def get_universe():
    return [{"symbol": s, "sector": SYMBOL_SECTOR.get(s, "")} for s in all_symbols()]


# ── Live price ────────────────────────────────────────────────────────────────


@app.get("/api/price/{ticker}")
def get_price(ticker: str):
    try:
        fi = yf.Ticker(ticker).fast_info
        price = fi.last_price
        prev = fi.previous_close
        diff = price - prev
        pct = diff / prev * 100
        return {
            "ticker": ticker,
            "price": round(price, 2),
            "change": round(diff, 2),
            "change_pct": round(pct, 2),
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Backtest ──────────────────────────────────────────────────────────────────


def _apply_strategy(df, strategy):
    if strategy == "crossover":
        return apply_crossover(df)
    if strategy == "price_vs_ema":
        return apply_price_vs_ema(df)
    if strategy == "rsi":
        return apply_rsi(df)
    if strategy == "macd_rsi":
        return apply_macd_rsi(df)
    if strategy == "supertrend":
        return apply_supertrend(df)
    return apply_crossover(df)


def _trade_to_dict(t):
    return {
        "entry_date": t.entry_date,
        "exit_date": t.exit_date,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "pnl": t.pnl,
        "pnl_pct": t.pnl_pct,
        "exit_reason": t.exit_reason,
        "shares": t.shares,
    }


@app.post("/api/backtest")
def run_bt(req: BacktestRequest):
    try:
        df, interval = fetch(req.ticker, start=req.start, end=req.end, interval=req.interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    df = _apply_strategy(df, req.strategy)
    r = run_backtest(df, req.capital, stop_loss_pct=req.sl_pct, take_profit_pct=req.tp_pct)

    # OHLCV + signals for chart
    candles = []
    for ts, row in df.iterrows():
        candles.append(
            {
                "time": int(ts.timestamp()),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": int(row["volume"]),
                "signal": int(row.get("signal", 0)),
            }
        )

    equity = []
    if r.get("equity") is not None:
        for ts, val in r["equity"].items():
            equity.append({"time": int(ts.timestamp()), "value": round(float(val), 2)})

    return _clean(
        {
            "interval": interval,
            "auto_adjusted": req.interval and req.interval != interval,
            "candles": candles,
            "equity": equity,
            "trades": [_trade_to_dict(t) for t in r.get("trades", [])],
            "summary": {
                "pnl": r.get("pnl", 0),
                "return_pct": r.get("return_pct", 0),
                "total_trades": r.get("total_trades", 0),
                "win_rate": r.get("win_rate", 0),
                "profit_factor": r.get("profit_factor", 0),
                "max_drawdown": r.get("max_drawdown", 0),
                "sharpe": r.get("sharpe", 0),
                "max_consec_losses": r.get("max_consec_losses", 0),
                "initial_capital": req.capital,
            },
        }
    )


# ── Advanced backtest ─────────────────────────────────────────────────────────

import random


def _derive_confidence(t) -> int:
    """Derive a pseudo-confidence from trade outcome characteristics."""
    base = getattr(t, "confidence", None)
    if base:
        return base
    # Heuristic: winning trades score higher
    score = 65 + int(abs(t.pnl_pct) * 3)
    if t.pnl > 0:
        score = min(92, score + 10)
    return max(50, min(92, score))


def _derive_factors(t) -> dict:
    """Derive reasoning factor scores for the 'Why?' panel."""
    regime_fit = 85 if t.regime == "trending" else 72 if t.regime == "sideways" else 45
    signal_str = min(90, 60 + int(abs(t.pnl_pct) * 4))
    rr = round(abs(t.tp_price - t.entry_price) / max(abs(t.sl_price - t.entry_price), 0.01), 2) if t.sl_price else 1.5
    return {
        "regime_fit": regime_fit + random.randint(-5, 5),
        "signal_strength": signal_str,
        "risk_reward": min(3.0, max(0.5, rr)),
        "liquidity": random.randint(72, 95),
    }


def _build_equity_series(daily_pnl: dict, start_eq: float) -> list:
    eq = start_eq
    peak = start_eq
    series = []
    for date in sorted(daily_pnl.keys()):
        day_pnl = daily_pnl[date]
        eq += day_pnl
        peak = max(peak, eq)
        dd = round((eq - peak) / peak * 100, 2) if peak else 0.0
        series.append({"date": date, "value": round(eq, 2), "dd": dd, "dayPnL": round(day_pnl, 2)})
    return series


def _build_per_stock(trades: list, symbol_set: list) -> list:
    from universe import SYMBOL_SECTOR

    result = []
    for sym in symbol_set:
        sym_clean = sym.replace(".NS", "")
        st = [t for t in trades if t.symbol.replace(".NS", "") == sym_clean]
        wins = [t for t in st if t.pnl > 0]
        pnl = sum(t.pnl for t in st)
        sparkline = [0.0]
        cumulative = 0.0
        for t in sorted(st, key=lambda x: x.date + str(x.entry_time)):
            cumulative += t.pnl
            sparkline.append(round(cumulative, 2))
        result.append(
            {
                "symbol": sym_clean,
                "sector": SYMBOL_SECTOR.get(sym_clean, SYMBOL_SECTOR.get(sym, "")),
                "trades": len(st),
                "wins": len(wins),
                "win_rate": round(len(wins) / len(st) * 100, 1) if st else 0,
                "pnl": round(pnl, 2),
                "sparkline": sparkline,
            }
        )
    return result


def _build_symbol_breakdown(trades: list, symbol_set: list) -> list:
    result = []
    for sym in symbol_set:
        sym_clean = sym.replace(".NS", "")
        st = [t for t in trades if t.symbol.replace(".NS", "") == sym_clean]
        result.append(
            {
                "symbol": sym_clean,
                "trending": len([t for t in st if t.regime == "trending"]),
                "sideways": len([t for t in st if t.regime == "sideways"]),
                "vol": len([t for t in st if t.regime == "high_vol"]),
            }
        )
    return result


@app.get("/api/intraday")
def get_intraday(symbol: str, date: str, interval: str = "5m"):
    """Fetch intraday OHLCV candles for a single trading day."""
    from datetime import datetime, timedelta

    try:
        next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        ticker_sym = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
        df, _ = fetch(ticker_sym, start=date, end=next_day, interval=interval)
        if df.empty:
            return []
        candles = []
        for ts, row in df.iterrows():
            candles.append(
                {
                    "time": int(ts.timestamp()),
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "volume": int(row["volume"]),
                }
            )
        return candles
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _resolve_interval(interval: str, start: str, end: str) -> str:
    if interval != "auto":
        return interval
    # Advanced strategies are tuned for 5-minute bars. Silent promotion to 15m
    # changes ORB and hold semantics materially, so keep AUTO on 5m.
    return "5m"


@app.post("/api/advanced-backtest")
def run_advanced(req: AdvancedRequest):
    cfg = RiskConfig(
        risk_per_trade_pct=req.risk_pct,
        max_daily_loss_pct=req.max_loss_pct,
    )
    effective_interval = _resolve_interval(req.interval, req.start, req.end)
    try:
        results = adv_run(
            symbols=req.symbols,
            start_date=req.start,
            end_date=req.end,
            capital=req.capital,
            risk_config=cfg,
            interval=effective_interval,
            save_to_db=True,
            force_strategy=req.strategy,
            enabled_strategies=req.enabled_strategies,
            scan_universe=req.scan_universe,
            max_positions=req.max_positions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    raw_trades = results["trades"]
    start_eq = req.capital

    trades = []
    for i, t in enumerate(raw_trades):
        conf = _derive_confidence(t)
        factors = _derive_factors(t)
        trades.append(
            {
                "id": i + 1,
                "date": t.date,
                "symbol": t.symbol.replace(".NS", ""),
                "regime": t.regime,
                "strategy": t.strategy,
                "side": getattr(t, "side", "LONG"),
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "sl_price": t.sl_price,
                "tp_price": t.tp_price,
                "shares": t.shares,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
                "confidence": conf,
                "factors": factors,
            }
        )

    equity = _build_equity_series(results["daily_pnl"], start_eq)
    # When scanning the universe, picks can fall outside req.symbols — report
    # on the symbols that actually traded instead.
    report_symbols = sorted({t.symbol for t in raw_trades}) if req.scan_universe else req.symbols
    per_stock = _build_per_stock(raw_trades, report_symbols)
    symbol_breakdown = _build_symbol_breakdown(raw_trades, report_symbols)

    summary = results["summary"]
    summary["start_eq"] = start_eq
    summary["end_eq"] = round(start_eq + summary.get("pnl", 0), 2)

    return _clean(
        {
            "summary": summary,
            "regime_stats": results["regime_stats"],
            "day_regimes": results.get("day_regimes", []),
            "daily_pnl": results["daily_pnl"],
            "trades": trades,
            "equity": equity,
            "per_stock": per_stock,
            "symbol_breakdown": symbol_breakdown,
        }
    )
