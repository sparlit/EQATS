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


import datetime as dt
import json
import os
import secrets
from contextlib import asynccontextmanager

import db
import pandas as pd
import scheduler_bg
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

load_dotenv()
APP_USER = os.getenv("ADMIN_USER", "ankit")
APP_PASS = os.getenv("ADMIN_PASS", "change_this_password")
API_HOST = os.getenv("API_HOST", "127.0.0.1")
security = HTTPBasic()


@asynccontextmanager
async def lifespan(app):
    scheduler_bg.start()
    yield
    scheduler_bg.stop()


app = FastAPI(title="NSE Intelligence Terminal", version="7.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="terminal/static"), name="static")


def verify_user(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username, APP_USER)
    pass_ok = secrets.compare_digest(credentials.password, APP_PASS)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login", headers={"WWW-Authenticate": "Basic"}
        )
    return credentials.username


def safe_float(v, nd=2):
    try:
        if v is None:
            return None
        return round(float(v), nd)
    except Exception:
        return None


def get_conn():
    return db.get_conn()


@app.get("/")
def root(user: str = Depends(verify_user)):
    return FileResponse("terminal/static/index.html")


@app.get("/api/health")
def health(user: str = Depends(verify_user)):
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
    except Exception:
        n = 0
    conn.close()
    return {"ok": True, "prices_rows": n, "time": dt.datetime.now().isoformat()}


@app.get("/api/regime")
def regime(user: str = Depends(verify_user)):
    try:
        from regime import MarketRegime

        rg = MarketRegime.compute()
        return {
            "ok": True,
            "is_bullish": rg.is_bullish,
            "stance": "BULLISH" if rg.is_bullish else "DEFENSIVE",
            "symbol": rg.symbol,
            "index_close": rg.index_close,
            "ema10": rg.ema10,
        }
    except Exception as e:
        return {"ok": False, "stance": "UNAVAILABLE", "error": str(e)}


@app.get("/api/macro")
def macro_flow(user: str = Depends(verify_user)):
    import macro

    try:
        data = macro.latest()
        if data:
            return data
    except Exception as e:
        print(f"[MACRO] api failed: {e}")
    return {"fii_net": None, "dii_net": None, "net_flow": None}


@app.get("/api/toppicks")
def toppicks(user: str = Depends(verify_user)):
    import top_picks

    try:
        top_picks.compute()
    except Exception as e:
        print(f"[TOPPICKS] compute failed: {e}")
    return {"picks": top_picks.top(15)}


@app.post("/api/pwin/refresh")
def pwin_refresh(bg: BackgroundTasks, user: str = Depends(verify_user)):
    import pwin_cache

    bg.add_task(pwin_cache.refresh_all)
    return {"started": True}


@app.get("/api/swing/signals")
def swing_signals(limit: int = 80, user: str = Depends(verify_user)):
    import pwin_cache
    import swing_live

    conn = get_conn()
    swing_live.ensure(conn)
    rows = conn.execute(
        "SELECT signal_date, symbol, entry_trigger, stop, target, "
        "risk_pct, pullback, impulse, ema_zone, outcome "
        "FROM swing_signals ORDER BY signal_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    signals = [
        {
            "date": r[0],
            "symbol": r[1],
            "trigger": safe_float(r[2]),
            "stop": safe_float(r[3]),
            "target": safe_float(r[4]),
            "risk_pct": safe_float(r[5]),
            "pullback": safe_float(r[6], 3),
            "impulse": safe_float(r[7], 3),
            "ema_zone": r[8],
            "outcome": r[9],
            "p_win": None,
        }
        for r in rows
    ]
    score = {
        r[0]: r[1] for r in conn.execute("SELECT outcome, COUNT(*) FROM swing_signals GROUP BY outcome").fetchall()
    }
    pw = pwin_cache.get_map(conn)
    conn.close()
    for s in signals:
        s["p_win"] = pw.get(s["symbol"])
    signals.sort(key=lambda x: -(x["p_win"] if x["p_win"] is not None else -1))
    wins = score.get("WIN", 0)
    graded = wins + score.get("LOSS", 0)
    return {"signals": signals, "scorecard": score, "win_rate": round(100 * wins / graded, 1) if graded else None}


@app.post("/api/swing/scan")
def run_swing_scan(bg: BackgroundTasks, user: str = Depends(verify_user)):
    import swing_live

    bg.add_task(swing_live.update_outcomes)
    bg.add_task(swing_live.scan)
    return {"started": True}


@app.get("/api/radar")
def radar(user: str = Depends(verify_user)):
    import pwin_cache

    conn = get_conn()
    rows = conn.execute(
        "SELECT symbol, perf1m, perf3m, relvol, mcap_cr FROM universe_broad ORDER BY mcap_cr DESC"
    ).fetchall()
    groups = {"Momentum": [], "Volume Spike": [], "Turnaround": []}
    for sym, p1, p3, rv, mc in rows:
        p1v, p3v, rvv = p1 or 0, p3 or 0, rv or 0
        item = {
            "symbol": sym,
            "perf1m": safe_float(p1v),
            "perf3m": safe_float(p3v),
            "relvol": safe_float(rvv),
            "mcap_cr": safe_float(mc),
            "p_win": None,
        }
        if rvv >= 2:
            groups["Volume Spike"].append(item)
        elif p1v >= 10 and p3v >= 8:
            groups["Momentum"].append(item)
        elif p1v >= 7 and p3v <= 0:
            groups["Turnaround"].append(item)
    for k in groups:
        groups[k] = groups[k][:40]
    events = []
    try:
        erows = conn.execute(
            "SELECT kind, symbol, text FROM events WHERE date=(SELECT MAX(date) FROM events) LIMIT 30"
        ).fetchall()
        for kind, sym, text in erows:
            events.append({"kind": kind, "symbol": sym, "text": text})
    except Exception:
        pass
    pw = pwin_cache.get_map(conn)
    conn.close()
    for k in groups:
        for item in groups[k]:
            item["p_win"] = pw.get(item["symbol"])
        groups[k].sort(key=lambda x: -(x["p_win"] if x["p_win"] is not None else -1))
    return {"groups": groups, "events": events, "total": len(rows)}


@app.get("/api/cockpit/{symbol}/chart")
def cockpit_chart(symbol: str, user: str = Depends(verify_user)):
    sym = symbol.upper()
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
    ).fetchall()
    conn.close()
    if not rows:
        return {"symbol": sym, "candles": [], "ema10": [], "ema20": [], "ema50": [], "ema200": [], "swing": None}
    df = pd.DataFrame(list(rows), columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).tail(420).copy()
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    candles = [
        {
            "time": r["date"].strftime("%Y-%m-%d"),
            "open": safe_float(r["open"]),
            "high": safe_float(r["high"]),
            "low": safe_float(r["low"]),
            "close": safe_float(r["close"]),
        }
        for _, r in df.iterrows()
    ]

    def line(col):
        return [
            {"time": r["date"].strftime("%Y-%m-%d"), "value": safe_float(r[col])}
            for _, r in df.iterrows()
            if safe_float(r[col]) is not None
        ]

    swing = None
    try:
        from setup import SetupDetector

        raw = df.rename(columns={"close": "Close", "high": "High", "low": "Low", "volume": "Volume"}).set_index("date")
        st = SetupDetector.detect(raw, sym)
        if st.triggered:
            swing = {
                "trigger": st.entry_price,
                "stop": st.stop_loss,
                "target": st.target_price,
                "pullback": st.pullback_depth,
                "impulse": st.impulse_pct,
                "zone": st.ema_proximity,
                "shape": st.shape_score,
            }
    except Exception:
        swing = None
    return {
        "symbol": sym,
        "candles": candles,
        "ema10": line("ema10"),
        "ema20": line("ema20"),
        "ema50": line("ema50"),
        "ema200": line("ema200"),
        "swing": swing,
    }


@app.get("/api/cockpit/{symbol}/summary")
def cockpit_summary(symbol: str, user: str = Depends(verify_user)):
    sym = symbol.upper()
    conn = get_conn()
    sector = mcap = fund_score = status = None
    r = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
    if r:
        sector = r[0]
    r = conn.execute("SELECT mcap_cr FROM universe_broad WHERE symbol=?", (sym,)).fetchone()
    if r:
        mcap = safe_float(r[0])
    r = conn.execute(
        "SELECT fundamental_score FROM scan_results WHERE symbol=? ORDER BY scan_date DESC LIMIT 1", (sym,)
    ).fetchone()
    if r:
        fund_score = safe_float(r[0])
    r = conn.execute("SELECT status FROM pipeline WHERE symbol=?", (sym,)).fetchone()
    if r:
        status = r[0]
    news = []
    try:
        nrows = conn.execute(
            "SELECT title, age_days, label FROM sentiment_headlines WHERE symbol=? ORDER BY age_days LIMIT 8", (sym,)
        ).fetchall()
        for title, age, label in nrows:
            news.append({"title": title, "age_days": age, "label": label})
    except Exception:
        pass
    conn.close()
    return {"symbol": sym, "sector": sector, "mcap_cr": mcap, "fund_score": fund_score, "status": status, "news": news}


@app.get("/api/meta/{symbol}")
def meta_score(symbol: str, user: str = Depends(verify_user)):
    import meta_model

    try:
        r = meta_model.score_symbol(symbol.upper())
        return r or {"symbol": symbol, "p_win": None, "why": []}
    except Exception as e:
        return {"symbol": symbol, "p_win": None, "why": [], "error": str(e)}


@app.get("/api/model/runs")
def model_runs(n: int = 10, user: str = Depends(verify_user)):
    import model_report

    return {"runs": model_report.history(n)}


@app.get("/api/ledger/stats")
def ledger_stats(user: str = Depends(verify_user)):
    import ledger

    return ledger.compute_stats() or {"total_trades": 0}


@app.get("/api/ledger/trades")
def ledger_trades(limit: int = 100, user: str = Depends(verify_user)):
    import ledger

    return {"trades": ledger.get_trades(limit)}


@app.get("/api/validate/latest")
def validate_latest(user: str = Depends(verify_user)):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT mode, run_date, payload FROM validation_log ORDER BY run_date DESC").fetchall()
    except Exception:
        rows = []
    conn.close()
    out = {}
    for mode, d, payload in rows:
        if mode not in out:
            try:
                out[mode] = dict(json.loads(payload), run_date=d)
            except Exception:
                out[mode] = {"run_date": d}
    return out


@app.get("/api/sizing/{symbol}")
def sizing(symbol: str, trigger: float | None = None, stop: float | None = None, user: str = Depends(verify_user)):
    import sizing as sz

    try:
        return sz.suggest(symbol.upper(), trigger=trigger, stop=stop)
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


@app.post("/api/sizing/capital")
def sizing_capital(payload: dict, user: str = Depends(verify_user)):
    import sizing as sz

    try:
        v = float(payload.get("capital", 0))
        if v <= 0:
            msg = "capital must be > 0"
            raise ValueError(msg)
        return {"capital": sz.set_capital(v)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/screener/scan")
def screener_scan(limit: int = 40, user: str = Depends(verify_user)):
    import screener_engine

    try:
        hits = screener_engine.screen_universe(limit=min(max(limit, 10), 100), show=False)
        return {"scanned": min(max(limit, 10), 100), "hits": hits}
    except Exception as e:
        return {"scanned": 0, "hits": [], "error": str(e)}


@app.get("/api/screener/{symbol}")
def screener_check(symbol: str, user: str = Depends(verify_user)):
    import screener_engine

    try:
        return screener_engine.evaluate_stock(symbol.upper())
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("terminal_api:app", host=API_HOST, port=8000, reload=True)
