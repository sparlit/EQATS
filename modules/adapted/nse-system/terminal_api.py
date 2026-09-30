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
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, status
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


app = FastAPI(title="NSE Intelligence Terminal", version="24.1", lifespan=lifespan)
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


@app.get("/api/sources")
def source_health(user: str = Depends(verify_user)):
    from data_sources import get_registry

    return {"sources": get_registry().health(), "time": dt.datetime.now().isoformat()}


@app.get("/api/deployment-check")
def deployment_check(user: str = Depends(verify_user)):
    conn = get_conn()
    out = {"checks": [], "fails": 0}
    today = dt.date.today()

    def add(ok, label, detail=""):
        out["checks"].append({"ok": ok, "label": label, "detail": detail})
        if not ok:
            out["fails"] += 1

    def _clean(val):
        s = str(val)
        if ":" in s and s.split(":", 1)[0] in ("tv", "csv", "calc"):
            return s.split(":", 1)[1]
        return s

    for table, col, max_days in [
        ("prices_daily", "date", 5),
        ("technicals_daily", "date", 5),
        ("universe_broad", "updated_at", 30),
        ("fundamentals", "uploaded_at", 30),
        ("swing_signals", "signal_date", 14),
        ("trend_candidates", "date", 5),
        ("value_radar", "date", 30),
        ("positional_picks", "date", 30),
        ("pwin_daily", "date", 14),
    ]:
        try:
            r = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
            latest = r[0] if r else None
            if not latest:
                add(False, table, "empty")
                continue
            cleaned = _clean(latest)
            d = dt.date.fromisoformat(str(cleaned)[:10])
            age = (today - d).days
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            add(age <= max_days, table, f"latest {str(cleaned)[:10]} ({age}d), {n} rows")
        except Exception as e:
            add(False, table, f"err: {e}")

    try:
        n = conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0]
        add(n > 0, "strategy_runs", f"{n} runs")
    except Exception as e:
        add(False, "strategy_runs", str(e))

    try:
        n = conn.execute("SELECT COUNT(*) FROM setup_pool").fetchone()[0]
        add(n > 0, "setup_pool", f"{n} setups")
    except Exception as e:
        add(False, "setup_pool", str(e))

    try:
        iso = today.isoformat()
        n = conn.execute("SELECT COUNT(*) FROM swing_signals WHERE signal_date=?", (iso,)).fetchone()[0]
        add(True, "swing signals today", f"{n} signals")
        n2 = conn.execute("SELECT COUNT(*) FROM trend_candidates WHERE date=?", (iso,)).fetchone()[0]
        add(True, "trend candidates today", f"{n2} stocks")
    except Exception as e:
        add(False, "today's activity", str(e))

    conn.close()

    try:
        from alerts import _creds

        tok, chat = _creds()
        add(bool(tok and chat), "telegram creds", "secret file" if tok else "MISSING")
    except Exception as e:
        add(False, "telegram creds", str(e))

    out["summary"] = "ALL CHECKS PASSED" if out["fails"] == 0 else f"{out['fails']} checks failed"
    out["time"] = dt.datetime.now().isoformat(timespec="seconds")
    return out


@app.get("/api/regime")
def regime(user: str = Depends(verify_user)):
    try:
        from regime import MarketRegime

        rg = MarketRegime.compute()
        return {
            "ok": True,
            "is_bullish": rg.is_bullish,
            "level": rg.level,
            "size_mult": rg.size_mult,
            "allows_swing": rg.allows_swing,
            "allows_aw": rg.allows_aw,
            "stance": rg.level,
            "symbol": rg.symbol,
            "index_close": rg.index_close,
            "ema10": rg.ema10,
            "ema20": rg.ema20,
            "ema10_slope_pct": rg.ema10_slope_pct,
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


# ============================================================
# Traders (Phase 3.5 — framework for famous-trader methods)
# ============================================================
@app.get("/api/traders")
def list_traders_api(user: str = Depends(verify_user)):
    import traders

    try:
        return {"traders": traders.list_traders()}
    except Exception as e:
        return {"traders": [], "error": str(e)}


@app.get("/api/traders/{slug}")
def get_trader_api(slug: str, user: str = Depends(verify_user)):
    import traders

    t = traders.get_trader(slug)
    if not t:
        raise HTTPException(status_code=404, detail="trader not found")
    return {"slug": t.SLUG, "name": t.NAME, "pillar": t.PILLAR, "source": t.SOURCE, "methods": t.METHODS}


@app.get("/api/traders/{slug}/scan")
def scan_trader_api(slug: str, limit: int = 800, user: str = Depends(verify_user)):
    import traders

    t = traders.get_trader(slug)
    if not t:
        raise HTTPException(status_code=404, detail="trader not found")
    try:
        sigs = t.scan(limit=limit)
        return {"slug": slug, "name": t.NAME, "n_signals": len(sigs), "signals": sigs}
    except Exception as e:
        return {"slug": slug, "error": str(e), "signals": []}


# ============================================================
# Trader League (#087) — Rs 10 lakh paper league + pre-deployment
# backtest of our system. Engine: trader_league.py. The heavy replay
# runs as a low-priority background process; the rest are DB reads.
# ============================================================
def _league_mode(mode, ex):
    return (mode if mode in ("backtest", "live") else "backtest", ex if ex in ("book", "common") else "book")


@app.get("/api/league/overview")
def league_overview(mode: str = "backtest", ex: str = Query("book", alias="exit"), user: str = Depends(verify_user)):
    import trader_league as TL

    mode, ex = _league_mode(mode, ex)
    try:
        return TL.overview(mode, ex)
    except Exception as e:
        return {"mode": mode, "exit": ex, "rows": [], "error": str(e)}


@app.get("/api/league/player/{slug}")
def league_player(
    slug: str, mode: str = "backtest", ex: str = Query("book", alias="exit"), user: str = Depends(verify_user)
):
    import trader_league as TL

    mode, ex = _league_mode(mode, ex)
    try:
        return TL.player_detail(slug, mode, ex)
    except Exception as e:
        return {"slug": slug, "playing": False, "error": str(e)}


@app.get("/api/league/status")
def league_status(user: str = Depends(verify_user)):
    import trader_league as TL

    try:
        return TL.status()
    except Exception as e:
        return {"players": [], "error": str(e)}


@app.post("/api/league/simulate")
def league_simulate(mode: str = "backtest", user: str = Depends(verify_user)):
    import trader_league as TL

    mode, _ = _league_mode(mode, "book")
    return TL.start_simulation(mode)


@app.post("/api/league/replay")
def league_replay(years: float = 3, symbols: int = 300, workers: int = 1, user: str = Depends(verify_user)):
    import trader_league as TL

    years = min(max(float(years), 0.5), 10.0)
    symbols = min(max(int(symbols), 20), 1500)
    workers = min(max(int(workers), 1), 8)
    try:
        return TL.start_replay_process(years, symbols, workers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Strategies
# ============================================================
@app.get("/api/strategies")
def list_strategies(user: str = Depends(verify_user)):
    import rule_engine

    return {"strategies": rule_engine.load_strategies()}


@app.post("/api/strategies/seed")
def seed_strategies(force: bool = False, user: str = Depends(verify_user)):
    import rule_engine

    n = rule_engine.seed_if_empty(force=force)
    return {"seeded": n}


@app.post("/api/strategies/run-all")
def run_all_strategies(user: str = Depends(verify_user)):
    import rule_engine

    try:
        return {"results": rule_engine.run_all()}
    except Exception as e:
        return {"error": str(e), "results": {}}


@app.post("/api/strategies/backtest-cache/clear")
def clear_backtest_cache(name: str | None = None, user: str = Depends(verify_user)):
    import strategy_backtest

    try:
        strategy_backtest.clear_cache(name)
        return {"cleared": True, "name": name}
    except Exception as e:
        return {"cleared": False, "error": str(e)}


@app.get("/api/strategies/{name}")
def get_strategy(name: str, user: str = Depends(verify_user)):
    import rule_engine

    s = rule_engine.get_strategy(name)
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    return s


@app.post("/api/strategies/{name}")
def save_strategy(name: str, payload: dict, user: str = Depends(verify_user)):
    import rule_engine

    rule_engine.save_strategy(name, payload)
    return {"saved": True, "name": name}


@app.delete("/api/strategies/{name}")
def delete_strategy(name: str, user: str = Depends(verify_user)):
    import rule_engine

    rule_engine.delete_strategy(name)
    return {"deleted": True, "name": name}


@app.get("/api/strategies/{name}/run")
def run_strategy_api(name: str, limit: int = 30, user: str = Depends(verify_user)):
    import rule_engine

    try:
        return rule_engine.run_strategy(name, limit=limit)
    except Exception as e:
        return {"error": str(e), "picks": []}


@app.get("/api/strategies/{name}/backtest")
def backtest_strategy_api(
    name: str,
    years: int = 2,
    step: int = 5,
    universe_limit: int = 150,
    stop_pct: float = 0.05,
    target_r: float = 3.0,
    hold_bars: int = 30,
    refresh: bool = False,
    user: str = Depends(verify_user),
):
    import strategy_backtest

    try:
        return strategy_backtest.backtest_strategy(
            name,
            years=years,
            step=step,
            universe_limit=universe_limit,
            stop_pct=stop_pct,
            target_r=target_r,
            hold_bars=hold_bars,
            use_cache=not refresh,
        )
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Research
# ============================================================
@app.get("/api/research/{symbol}")
def research_api(symbol: str, user: str = Depends(verify_user)):
    import research_cockpit

    try:
        return research_cockpit.analyze_symbol(symbol.upper())
    except Exception as e:
        return {"symbol": symbol.upper(), "error": str(e)}


@app.get("/api/research-universe")
def research_universe_api(compute_missing: bool = False, user: str = Depends(verify_user)):
    import research_cockpit

    try:
        return research_cockpit.analyze_universe(compute_missing=compute_missing)
    except Exception as e:
        return {"error": str(e), "rows": [], "n_setups": 0}


@app.get("/api/research-sector")
def research_sector_api(user: str = Depends(verify_user)):
    import research_cockpit

    try:
        return research_cockpit.sector_aggregate()
    except Exception as e:
        return {"error": str(e), "sectors": [], "n_sectors": 0}


@app.post("/api/research-cache/clear")
def research_cache_clear(symbol: str | None = None, user: str = Depends(verify_user)):
    import research_cockpit

    try:
        research_cockpit.clear_cache(symbol.upper() if symbol else None)
        return {"cleared": True, "symbol": symbol}
    except Exception as e:
        return {"cleared": False, "error": str(e)}


# ============================================================
# Compare
# ============================================================
@app.get("/api/compare")
def compare_api(symbols: str, user: str = Depends(verify_user)):
    import compare_tool

    try:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not syms:
            return {"error": "no symbols", "rows": []}
        return compare_tool.compare(syms, max_n=4)
    except Exception as e:
        return {"error": str(e), "rows": []}


# ============================================================
# Patterns
# ============================================================
@app.get("/api/patterns/latest")
def patterns_latest(limit: int = 100, user: str = Depends(verify_user)):
    import patterns

    return {"patterns": patterns.latest(limit=limit)}


@app.get("/api/patterns/stats")
def patterns_stats(user: str = Depends(verify_user)):
    import pattern_grader

    try:
        return {"stats": pattern_grader.stats()}
    except Exception as e:
        return {"stats": {}, "error": str(e)}


@app.get("/api/patterns/history/{symbol}")
def patterns_history(symbol: str, limit: int = 500, user: str = Depends(verify_user)):
    import patterns

    try:
        return {"symbol": symbol.upper(), "signals": patterns.history_for_symbol(symbol.upper(), limit=limit)}
    except Exception as e:
        return {"symbol": symbol.upper(), "signals": [], "error": str(e)}


@app.post("/api/patterns/scan")
def patterns_scan(bg: BackgroundTasks, user: str = Depends(verify_user)):
    import patterns

    bg.add_task(patterns.run)
    return {"started": True}


@app.get("/api/patterns/{symbol}")
def patterns_for_symbol(symbol: str, limit: int = 50, user: str = Depends(verify_user)):
    import patterns

    return {
        "symbol": symbol.upper(),
        "patterns": patterns.for_symbol(symbol.upper(), limit=limit),
        "live_detect": patterns.detect_symbol(symbol.upper()),
    }


# ============================================================
# Existing endpoints
# ============================================================
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
        "risk_pct, pullback, impulse, ema_zone, outcome, mode "
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
            "mode": r[10] or "SWING",
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


@app.get("/api/trend")
def trend_api(n: int = 50, user: str = Depends(verify_user)):
    import trend_scanner

    try:
        return {"candidates": trend_scanner.top(n)}
    except Exception as e:
        return {"candidates": [], "error": str(e)}


@app.post("/api/trend/scan")
def trend_scan(bg: BackgroundTasks, user: str = Depends(verify_user)):
    import trend_scanner

    bg.add_task(trend_scanner.compute)
    return {"started": True}


@app.get("/api/templates/latest")
def templates_latest(limit: int = 30, user: str = Depends(verify_user)):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT date, symbol, template, similarity "
            "FROM template_scores "
            "WHERE date=(SELECT MAX(date) FROM template_scores) "
            "ORDER BY similarity DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    return {"matches": [{"date": r[0], "symbol": r[1], "template": r[2], "similarity": r[3]} for r in rows]}


@app.get("/api/delivery/top")
def delivery_top(n: int = 30, user: str = Depends(verify_user)):
    import delivery

    return {"rows": delivery.top(n)}


@app.get("/api/delivery/accum")
def delivery_accum(n: int = 30, user: str = Depends(verify_user)):
    import delivery

    return {"candidates": delivery.accumulation(n)}


@app.get("/api/delivery/{symbol}")
def delivery_symbol(symbol: str, limit: int = 20, user: str = Depends(verify_user)):
    import delivery

    return {
        "symbol": symbol.upper(),
        "history": delivery.for_symbol(symbol.upper(), limit),
        "score": delivery.delivery_score(symbol.upper()),
    }


@app.get("/api/value-radar")
def value_radar_api(n: int = 25, tier: str | None = None, user: str = Depends(verify_user)):
    import value_radar

    try:
        return {"picks": value_radar.top(n, tier=tier)}
    except Exception as e:
        return {"picks": [], "error": str(e)}


@app.get("/api/positional")
def positional_api(n: int = 25, tier: str | None = None, user: str = Depends(verify_user)):
    import positional_scanner

    try:
        return {"picks": positional_scanner.top(n, tier=tier)}
    except Exception as e:
        return {"picks": [], "error": str(e)}


@app.get("/api/strategy-runs")
def strategy_runs_api(n: int = 20, user: str = Depends(verify_user)):
    import strategy_runs

    try:
        return {"runs": strategy_runs.history(n)}
    except Exception as e:
        return {"runs": [], "error": str(e)}


@app.get("/api/strategy-summary")
def strategy_summary_api(user: str = Depends(verify_user)):
    import strategy_runs

    try:
        return {"summary": strategy_runs.summary_by_target()}
    except Exception as e:
        return {"summary": [], "error": str(e)}


@app.post("/api/webhook/ingest")
def webhook_ingest(payload: dict, x_webhook_token: str = Header(default="")):
    token = os.getenv("WEBHOOK_TOKEN")
    if not token:
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key='webhook_token'").fetchone()
        conn.close()
        token = row[0] if row else None
    if not token:
        raise HTTPException(status_code=503, detail="webhook not configured")
    got_hdr = x_webhook_token or ""
    got_body = str(payload.get("token", ""))
    ok = secrets.compare_digest(got_hdr, token) or secrets.compare_digest(got_body, token)
    if not ok:
        raise HTTPException(status_code=401, detail="bad webhook token")
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS webhook_events(
        created_at TEXT, source TEXT, symbol TEXT, kind TEXT,
        price REAL, payload TEXT)""")
    conn.execute(
        "INSERT INTO webhook_events VALUES (?,?,?,?,?,?)",
        (
            dt.datetime.now().isoformat(timespec="seconds"),
            str(payload.get("source", "unknown"))[:40],
            str(payload.get("symbol", "")).upper()[:20],
            str(payload.get("kind", "alert"))[:40],
            safe_float(payload.get("price")),
            json.dumps(payload, default=str)[:2000],
        ),
    )
    conn.commit()
    conn.close()
    try:
        from alerts import send

        send(
            f"📡 WEBHOOK {payload.get('source')} "
            f"{str(payload.get('symbol', '')).upper()} "
            f"{payload.get('kind')} @ {payload.get('price')}"
        )
    except Exception:
        pass
    return {"stored": True}


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

        raw = df.rename(columns={"close": "Close", "high": "High", "low": "Low", "volume": "Volume"})
        raw = raw.set_index("date")
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
def sizing(
    symbol: str,
    trigger: float | None = None,
    stop: float | None = None,
    shape: float | None = None,
    user: str = Depends(verify_user),
):
    import sizing as sz

    try:
        return sz.suggest(symbol.upper(), trigger=trigger, stop=stop, shape_score=shape)
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
        n = min(max(limit, 10), 100)
        hits = screener_engine.screen_universe(limit=n, show=False)
        return {"scanned": n, "hits": hits}
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
