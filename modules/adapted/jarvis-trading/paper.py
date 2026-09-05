"""
Paper-Trading Autopilot — a forward-testing strategy incubator.

Any 🔔-enabled Builder scan gets a virtual portfolio that automatically "takes"
its signals under the AXIOM rulebook and tracks the result forward, in real
time. Unlike a backtest (which replays history and is easy to curve-fit), this
accumulates a genuine forward track record: "Momentum breakout: +6.2R live".

Rulebook per position
  entry   : next session's OPEN after the signal (no look-ahead)
  stop    : entry − 1.5 × ATR(14)
  target  : entry + 2R  (R = entry − stop)
  exits   : stop / target intrabar, else time-stop after MAX_BARS
  sizing  : 2% of virtual equity risked per trade
  cap     : MAX_OPEN concurrent positions per strategy

State lives in data/state/paper_portfolios.json (committed by the Actions job),
so the record survives across serverless runs.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
from loguru import logger

STATE = Path("data/state/paper_portfolios.json")
START_EQUITY = 1_000_000.0
RISK_PCT = 0.02          # 2% of equity per trade
ATR_MULT = 1.5           # stop distance
TARGET_R = 2.0           # reward:risk
MAX_OPEN = 5             # concurrent positions per strategy
MAX_BARS = 15            # time stop (trading days)


# ── state ───────────────────────────────────────────────────────────────────
def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"portfolios": {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, separators=(",", ":"), default=str), encoding="utf-8")


def _new_portfolio(name: str) -> dict:
    return {"name": name, "started": date.today().isoformat(), "equity": START_EQUITY,
            "open": [], "closed": [], "curve": [{"date": date.today().isoformat(), "equity": START_EQUITY}]}


# ── price helpers (OHLCV cache) ─────────────────────────────────────────────
def _bars(symbol: str):
    from data.ohlcv_cache import get_cached_ohlcv
    df = get_cached_ohlcv(f"{symbol}.NS" if not symbol.endswith(".NS") else symbol)
    if df is None or df.empty:
        return None
    return ([d.strftime("%Y-%m-%d") for d in df.index], df)


def _atr(df, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    return float(tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().iloc[-1])


# ── the engine ──────────────────────────────────────────────────────────────
def process_signals(name: str, signal_symbols: list[str], state: dict) -> dict:
    """Advance one strategy's portfolio: mark open positions to market (checking
    stops/targets), then open new positions from today's signals."""
    pf = state["portfolios"].setdefault(name, _new_portfolio(name))
    today = date.today().isoformat()

    # 1) manage open positions
    still_open = []
    for pos in pf["open"]:
        got = _bars(pos["symbol"])
        if not got:
            still_open.append(pos)
            continue
        dates, df = got
        try:
            i0 = dates.index(pos["entry_date"])
        except ValueError:
            i0 = int(np.searchsorted(np.array(dates), pos["entry_date"]))
        exit_px = exit_date = reason = None
        bars_held = 0
        for i in range(i0 + 1, len(dates)):
            bars_held = i - i0
            lo, hi = float(df["low"].iloc[i]), float(df["high"].iloc[i])
            if lo <= pos["stop"]:
                exit_px, exit_date, reason = pos["stop"], dates[i], "stop"
                break
            if hi >= pos["target"]:
                exit_px, exit_date, reason = pos["target"], dates[i], "target"
                break
            if bars_held >= MAX_BARS:
                exit_px, exit_date, reason = float(df["close"].iloc[i]), dates[i], "time"
                break
        if exit_px is None:
            pos["last_price"] = float(df["close"].iloc[-1])
            pos["open_r"] = round((pos["last_price"] - pos["entry"]) / pos["risk_per_share"], 2)
            still_open.append(pos)
            continue
        pnl = (exit_px - pos["entry"]) * pos["qty"]
        r_mult = (exit_px - pos["entry"]) / pos["risk_per_share"]
        pf["equity"] = round(pf["equity"] + pnl, 2)
        pf["closed"].append({**{k: pos[k] for k in ("symbol", "entry_date", "entry", "stop", "target", "qty")},
                             "exit": round(exit_px, 2), "exit_date": exit_date, "reason": reason,
                             "pnl": round(pnl, 2), "r": round(r_mult, 2), "bars": bars_held})
        pf["curve"].append({"date": exit_date, "equity": pf["equity"]})
    pf["open"] = still_open

    # 2) open new positions from signals (respect the concurrency cap)
    held = {p["symbol"] for p in pf["open"]}
    for sym in signal_symbols:
        if len(pf["open"]) >= MAX_OPEN:
            break
        if sym in held:
            continue
        got = _bars(sym)
        if not got:
            continue
        dates, df = got
        if len(df) < 20:
            continue
        # entry = latest available open (the signal fired on the prior close)
        entry = float(df["open"].iloc[-1])
        atr = _atr(df)
        if entry <= 0 or not np.isfinite(atr) or atr <= 0:
            continue
        risk_ps = ATR_MULT * atr
        stop = entry - risk_ps
        qty = int((pf["equity"] * RISK_PCT) / risk_ps)
        if qty <= 0:
            continue
        pf["open"].append({
            "symbol": sym, "entry_date": dates[-1], "entry": round(entry, 2),
            "stop": round(stop, 2), "target": round(entry + TARGET_R * risk_ps, 2),
            "risk_per_share": round(risk_ps, 4), "qty": qty,
            "last_price": round(float(df["close"].iloc[-1]), 2), "open_r": 0.0,
        })
        held.add(sym)
    return state


def portfolio_stats(pf: dict) -> dict:
    closed = pf.get("closed", [])
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    open_r = sum(p.get("open_r", 0) or 0 for p in pf.get("open", []))
    eq = [c["equity"] for c in pf.get("curve", [])] or [START_EQUITY]
    peak, dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        dd = min(dd, (v - peak) / peak * 100)
    return {
        "name": pf.get("name"), "started": pf.get("started"),
        "equity": round(pf.get("equity", START_EQUITY), 2),
        "return_pct": round((pf.get("equity", START_EQUITY) / START_EQUITY - 1) * 100, 2),
        "trades": len(closed), "open_positions": len(pf.get("open", [])),
        "win_rate": round(len(wins) / len(rs) * 100, 1) if rs else 0.0,
        "total_r": round(sum(rs), 2), "open_r": round(open_r, 2),
        "avg_r": round(float(np.mean(rs)), 2) if rs else 0.0,
        "expectancy": round(float(np.mean(rs)), 2) if rs else 0.0,
        "max_drawdown": round(dd, 2),
    }


def all_portfolios() -> dict:
    state = load_state()
    pfs = state.get("portfolios", {})
    if not pfs:
        return {"available": False, "note": "No paper portfolios yet — enable 🔔 on a Builder scan."}
    out = []
    for name, pf in pfs.items():
        out.append({**portfolio_stats(pf),
                    "open": pf.get("open", []),
                    "closed": sorted(pf.get("closed", []), key=lambda t: t.get("exit_date") or "", reverse=True)[:40],
                    "curve": pf.get("curve", [])[-120:]})
    out.sort(key=lambda p: p["total_r"], reverse=True)
    return {"available": True, "portfolios": out}
