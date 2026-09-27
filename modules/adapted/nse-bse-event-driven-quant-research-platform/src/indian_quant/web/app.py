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


"""FastAPI web dashboard for the NSE-BSE quant platform."""


import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from indian_quant.config import load_settings
from indian_quant.web import data_loader as dl
from indian_quant.web import suggestion_loader as sl
from indian_quant.web.auth import (
    get_current_user_id,
    get_current_username,
    hash_password,
    require_login,
    verify_password,
)
from indian_quant.web.fast_loader import get_latest_signals_cached
from indian_quant.web.scheduler import get_scheduler_status, start_scheduler, stop_scheduler
from indian_quant.web.watchlist_store import WatchlistStore
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="NSE-BSE Quant Platform", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key="nse-bse-quant-9f8e7d6c5b4a3210-prod", max_age=86400 * 7)

# hypothesis name -> id (matches hypotheses table seed; used by positions filter)
_HYPOTHESES_BY_NAME = {
    "delivery_momentum": 1,
    "circuit_breakout": 2,
    "surveillance_recovery": 3,
    "announcement_alpha": 4,
}

# Capital allocated per hypothesis (₹10L each; total = 10L × active hypotheses)
HYPO_CAPITAL = 1_000_000


@app.on_event("startup")
def _start_scheduler():
    import contextlib
    import threading

    def _delayed_start():
        import time

        time.sleep(5)
        with contextlib.suppress(Exception):
            start_scheduler()

    threading.Thread(target=_delayed_start, daemon=True).start()
    # Ensure default user exists for watchlist FK constraint
    try:
        ws = _ws()
        if not ws.get_user_by_username("admin"):
            ws.create_user("admin", "admin@local.dev", "dev-only-hash")
        ws.close()
    except Exception:
        pass


@app.on_event("shutdown")
def _stop_scheduler():
    stop_scheduler()


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _ws() -> WatchlistStore:
    settings = load_settings()
    db = Path(settings.storage.metadata_dsn.removeprefix("sqlite:///"))
    return WatchlistStore(db)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    papers = dl.get_paper_summary()
    gate = dl.get_gate_progress()
    signals = get_latest_signals_cached()
    sugg = sl.get_suggestion_summary()
    uid = get_current_user_id(request)
    watchlist_count = 0
    if uid:
        ws = _ws()
        watchlist_count = ws.symbol_count(uid)
        ws.close()
    # Per-horizon breakdown
    load_settings()
    import os
    import subprocess

    import sqlalchemy as sa
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    sugg_by_hz = md.suggestions_by_horizon()
    engine = get_pg_engine()
    dashboard_extra = {}
    with engine.connect() as conn:
        # System health
        web_ok = True
        mcp_ok = bool(subprocess.run(["pgrep", "-f", "nse-bse-mcp"], capture_output=True).returncode == 0)
        scheduler_ok = bool(subprocess.run(["pgrep", "-f", "platform_scheduler"], capture_output=True).returncode == 0)
        dashboard_extra["system"] = {"web": web_ok, "mcp": mcp_ok, "scheduler": scheduler_ok}
        # Surveillance summary
        surv = conn.execute(
            sa.text("""
            SELECT framework, COUNT(*) FROM surveillance_stocks WHERE status='ACTIVE' GROUP BY framework
        """)
        ).fetchall()
        surv_signals = conn.execute(sa.text("SELECT COUNT(*) FROM surveillance_signals")).scalar()
        surv_positions = conn.execute(
            sa.text("SELECT COUNT(*) FROM paper_signals WHERE status='OPEN' AND note LIKE '%surveillance%'")
        ).scalar()
        dashboard_extra["surveillance"] = {
            "by_framework": dict(surv),
            "total_stocks": sum(r[1] for r in surv),
            "signals": surv_signals,
            "positions": surv_positions,
        }
        # Hypotheses performance
        hyps = conn.execute(
            sa.text("""
            SELECT h.name,
                   COUNT(t.id) as trades,
                   SUM(CASE WHEN t.realized_net_bps > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(t.realized_net_bps) as avg_pnl
            FROM hypotheses h
            LEFT JOIN paper_signals t ON t.hypothesis_id = h.id
            WHERE h.is_active
            GROUP BY h.id, h.name
        """)
        ).fetchall()
        dashboard_extra["hypotheses"] = [
            {
                "name": r[0],
                "trades": r[1] or 0,
                "wins": r[2] or 0,
                "win_rate": round((r[2] or 0) / r[1] * 100, 1) if r[1] else 0,
                "avg_pnl": round(r[3] or 0, 1),
            }
            for r in hyps
        ]
        # Recent trades (last 7 settled)
        recent = (
            conn.execute(
                sa.text("""
            SELECT symbol, exit_date, exit_reason, realized_net_bps, return_pct,
                   horizon_label, note, close_at_signal, exit_close
            FROM paper_signals
            WHERE status='SETTLED'
            ORDER BY exit_date DESC, exit_close DESC
            LIMIT 7
        """)
            )
            .mappings()
            .fetchall()
        )
        dashboard_extra["recent_trades"] = [dict(r) for r in recent]
        # Portfolio risk
        try:
            risk = (
                conn.execute(
                    sa.text(
                        "SELECT total_value, var_95, var_99, sharpe_ratio, max_drawdown, n_positions "
                        "FROM portfolio_risk ORDER BY snapshot_date DESC LIMIT 1"
                    )
                )
                .mappings()
                .fetchone()
            )
            dashboard_extra["risk"] = dict(risk) if risk else None
        except Exception:
            dashboard_extra["risk"] = None
        # Data freshness
        last_signal = conn.execute(sa.text("SELECT MAX(signal_date) FROM surveillance_signals")).scalar()
        last_sugg = conn.execute(sa.text("SELECT MAX(suggestion_date) FROM daily_suggestions")).scalar()
        dashboard_extra["freshness"] = {
            "surveillance": str(last_signal)[:10] if last_signal else "—",
            "suggestions": str(last_sugg)[:10] if last_sugg else "—",
        }
    md.close()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "papers": papers,
            "gate": gate,
            "signals": signals,
            "sugg": sugg,
            "sugg_by_hz": sugg_by_hz,
            "username": get_current_username(request),
            "watchlist_count": watchlist_count,
            "extra": dashboard_extra,
        },
    )


@app.get("/signals", response_class=HTMLResponse)
async def signals_page(request: Request):
    signals = get_latest_signals_cached()
    all_sigs = signals.get("all", [])
    # Pre-count market cap classes and segments for initial render
    from collections import Counter

    cap_counts = Counter(s.get("market_cap_class", "Other") for s in all_sigs)
    seg_counts = Counter(s.get("segment", "EQ") for s in all_sigs)
    return templates.TemplateResponse(
        request,
        "signals.html",
        {
            "request": request,
            "signals": {"date": signals.get("date", ""), "total": len(all_sigs)},
            "cap_counts": cap_counts,
            "seg_counts": seg_counts,
            "username": get_current_username(request),
        },
    )


@app.get("/api/signals")
async def api_signals(
    cap: str = "All",
    sort: str = "score",
    order: str = "desc",
    signal_type: str = "All",
    segment: str = "All",
    page: int = 1,
    per_page: int = 50,
):
    from indian_quant.web.fast_loader import get_signals_for_api

    return get_signals_for_api(
        cap=cap,
        sort=sort,
        order=order,
        signal_type=signal_type,
        segment=segment,
        page=page,
        per_page=per_page,
    )


@app.get("/api/portfolio")
async def api_portfolio(
    horizon: str = "",
    status: str = "",
    limit: int = 200,
):
    dl._settings()
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    pf = md.portfolio_summary()
    by_hz = md.paper_trades_by_horizon()
    trades = md.trade_log(
        horizon=horizon or None,
        status=status or None,
        limit=limit,
    )
    md.close()
    return {"portfolio": pf, "by_horizon": by_hz, "trades": trades}


@app.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    import json as _json
    from pathlib import Path

    bt_path = Path("docs/research/generated/cluster_backtest.json")
    data = None
    paper = {}
    if bt_path.exists():
        raw = _json.loads(bt_path.read_text())
        eq = raw.get("equity_curve", [])
        data = {
            "summary": raw.get("summary", {}),
            "config": raw.get("summary", {}),
            "trades": raw.get("trades", []),
            "equity_dates": [row[0][:10] for row in eq],
            "equity_values": [row[1] for row in eq],
            "by_signal": raw.get("by_signal", {}),
        }
    # Paper trading stats for comparison
    ps = dl.get_paper_summary()
    paper = {
        "settled": ps.get("settled", 0),
        "avg_net_bps": ps.get("avg_net_bps"),
        "hit_rate": ps.get("hit_rate"),
        "win_rate": round(ps["hit_rate"] * 100, 1) if ps.get("hit_rate") else None,
    }
    # Per-hypothesis live paper performance (syncs backtest page with live trading)
    hypo_perf: list = []
    try:
        import sqlalchemy as sa
        from indian_quant.config.connections import get_engine

        _eng = get_engine()
        with _eng.connect() as _conn:
            _rows = (
                _conn.execute(
                    sa.text("""
                SELECT h.id, h.name,
                       COUNT(*) FILTER (WHERE ps.status = 'OPEN') AS open_n,
                       COUNT(*) FILTER (WHERE ps.status <> 'OPEN') AS settled_n,
                       AVG(ps.conviction_score) FILTER (WHERE ps.status = 'OPEN') AS avg_conv,
                       SUM(ps.position_value) FILTER (WHERE ps.status = 'OPEN') AS open_value
                FROM hypotheses h
                LEFT JOIN paper_signals ps ON ps.hypothesis_id = h.id
                GROUP BY h.id, h.name ORDER BY h.id
            """)
                )
                .mappings()
                .fetchall()
            )
            hypo_perf = [dict(r) for r in _rows]
    except Exception:
        hypo_perf = []
    return templates.TemplateResponse(
        request,
        "backtest.html",
        {
            "request": request,
            "data": data,
            "paper": paper,
            "hypo_perf": hypo_perf,
            "username": get_current_username(request),
        },
    )


@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request):
    horizon = request.query_params.get("horizon", "")
    filter_type = request.query_params.get("type", "")  # legacy: surveillance/delivery
    hypo = request.query_params.get("hypo", "")  # hypothesis name filter
    dl._settings()
    import sqlalchemy as sa
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    pf = md.portfolio_summary()
    by_hz = md.paper_trades_by_horizon()
    engine = get_pg_engine()
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sa.text("""
            SELECT * FROM paper_signals
            WHERE status = 'OPEN'
               OR (status = 'SETTLED' AND exit_date::date >= CURRENT_DATE - INTERVAL '1 day')
            ORDER BY (status = 'OPEN') DESC, created_at DESC
            LIMIT 100
        """)
            )
            .mappings()
            .fetchall()
        )
        trades = [dict(r) for r in rows]
        # Per-hypothesis metrics + capital allocation (₹10L each)
        hyp_rows = conn.execute(
            sa.text("""
            SELECT h.name,
                   COUNT(t.id) as trades,
                   SUM(CASE WHEN t.realized_net_bps > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(t.realized_net_bps) as avg_net,
               SUM(CASE WHEN t.exit_reason = 'STOP' THEN 1 ELSE 0 END) as stops,
               SUM(CASE WHEN t.exit_reason = 'HORIZON' THEN 1 ELSE 0 END) as horizon_exits,
               AVG(t.days_held) as avg_days,
               SUM(t.position_value) as total_value,
               SUM(CASE WHEN t.status = 'OPEN' THEN t.position_value ELSE 0 END) as deployed,
               COUNT(CASE WHEN t.status = 'OPEN' THEN 1 END) as open_count,
               SUM(CASE WHEN t.status = 'SETTLED'
                        THEN t.position_value * t.realized_net_bps / 10000.0 ELSE 0 END) as realized_pnl
            FROM hypotheses h
            LEFT JOIN paper_signals t ON t.hypothesis_id = h.id
            WHERE h.is_active
            GROUP BY h.id, h.name
            ORDER BY h.name
        """)
        ).fetchall()
        by_hyp = {}
        for r in hyp_rows:
            n = r[1] or 0
            w = r[2] or 0
            deployed = round(r[8] or 0)
            realized = round(r[10] or 0, 2)
            by_hyp[r[0]] = {
                "trades": n,
                "wins": w,
                "win_rate": round(w / n * 100, 1) if n else 0,
                "avg_net": round(r[3], 1) if r[3] else None,
                "stops": r[4] or 0,
                "horizon_exits": r[5] or 0,
                "avg_days": round(r[6], 1) if r[6] else None,
                "total_value": r[7] or 0,
                "allocated": HYPO_CAPITAL,
                "deployed": deployed,
                "open_count": r[9] or 0,
                "realized_pnl": realized,
                "available": HYPO_CAPITAL - deployed,
                "equity": HYPO_CAPITAL + realized,
            }
        cap_total = {
            "allocated": HYPO_CAPITAL * len(by_hyp),
            "deployed": sum(h["deployed"] for h in by_hyp.values()),
            "open_count": sum(h["open_count"] for h in by_hyp.values()),
            "realized_pnl": round(sum(h["realized_pnl"] for h in by_hyp.values()), 2),
            "available": sum(h["available"] for h in by_hyp.values()),
            "equity": round(sum(h["equity"] for h in by_hyp.values()), 2),
        }
        # --- live sync audit (guarantees /positions ↔ /journal stay reconciled) ---
        with engine.connect() as _c:
            _paper = dict(_c.execute(sa.text("SELECT status, COUNT(*) FROM paper_signals GROUP BY 1")).fetchall())
            _journal = dict(
                _c.execute(
                    sa.text(
                        "SELECT CASE WHEN exit_date IS NULL THEN 'OPEN' ELSE 'SETTLED' END, COUNT(*) FROM trade_journal GROUP BY 1"
                    )
                ).fetchall()
            )
            issues = []
            if _paper != _journal:
                issues.append("counts")
            r = (
                _c.execute(
                    sa.text("""
                SELECT
                    COUNT(*) FILTER (WHERE j.paper_trade_id IS NULL) as missing_entries,
                    COUNT(*) FILTER (WHERE p.status='SETTLED' AND j.exit_date IS NULL) as missing_exits,
                    COUNT(*) FILTER (WHERE p.id NOT IN (SELECT paper_trade_id FROM trade_journal)) as orphans,
                    COUNT(*) FILTER (WHERE p.status='SETTLED' AND ABS(p.realized_net_bps - COALESCE(j.net_bps,0)) > 0.01) as bps_mismatch
                FROM paper_signals p
                LEFT JOIN trade_journal j ON j.paper_trade_id = p.id
            """)
                )
                .mappings()
                .fetchone()
            )
            d = dict(r) if r else {}
            if d.get("missing_entries", 0) > 0:
                issues.append("missing_entries")
            if d.get("missing_exits", 0) > 0:
                issues.append("missing_exits")
            if d.get("orphans", 0) > 0:
                issues.append("orphans")
            if d.get("bps_mismatch", 0) > 0:
                issues.append("bps_mismatch")
            cap_total["_sync"] = "OK" if not issues else ",".join(issues)
    # Filter by horizon
    if horizon:
        trades = [t for t in trades if t.get("horizon_label") == horizon]
    # Filter by hypothesis (primary filter — hypothesis_id is authoritative)
    if hypo:
        trades = [t for t in trades if t.get("hypothesis_id") == _HYPOTHESES_BY_NAME.get(hypo)]
    # Legacy type filter (surveillance/delivery) based on note field
    elif filter_type == "surveillance":
        trades = [t for t in trades if t.get("note") and "surveillance" in t["note"]]
    elif filter_type == "delivery":
        trades = [t for t in trades if not t.get("note") or "surveillance" not in t["note"]]
    # Fetch live prices for open positions
    live_prices = {}
    open_symbols = [t["symbol"] for t in trades if t.get("status") == "OPEN" and t.get("symbol")]
    if open_symbols:
        try:
            from indian_quant.web.live_prices import LivePriceService

            lps = LivePriceService()
            raw = lps.get_live_prices(open_symbols)
            for sym, data in raw.items():
                live_prices[sym] = data
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("Live prices fetch failed: %s", e)
    md.close()
    papers = dl.get_paper_summary()
    return templates.TemplateResponse(
        request,
        "positions.html",
        {
            "request": request,
            "papers": papers,
            "pf": pf,
            "by_hz": by_hz,
            "by_hyp": by_hyp,
            "cap_total": cap_total,
            "trades": trades,
            "live_prices": live_prices,
            "filter_horizon": horizon,
            "filter_type": filter_type,
            "filter_hypo": hypo,
            "username": get_current_username(request),
        },
    )


@app.post("/positions/exit/{trade_id}")
async def positions_manual_exit(request: Request, trade_id: int):
    """Manually exit an open paper trade at the live price (reason=MANUAL)."""
    require_login(request)
    from datetime import date as _date

    import sqlalchemy as sa
    from indian_quant.hypotheses.registry import HypothesisRegistry
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()
    with engine.connect() as conn:
        trade = (
            conn.execute(
                sa.text("SELECT id, symbol, status, close_at_signal FROM paper_signals WHERE id = :i"),
                {"i": trade_id},
            )
            .mappings()
            .fetchone()
        )
    if not trade:
        return JSONResponse({"error": f"trade {trade_id} not found"}, status_code=404)
    if trade["status"] != "OPEN":
        return JSONResponse({"error": f"trade {trade_id} is already {trade['status']}"}, status_code=400)
    # Exit at live price
    exit_price = None
    try:
        from indian_quant.web.live_prices import LivePriceService

        raw = LivePriceService().get_live_prices([trade["symbol"]])
        exit_price = (raw.get(trade["symbol"]) or {}).get("last_price")
    except Exception:
        exit_price = None
    if not exit_price:
        return JSONResponse({"error": f"no live price for {trade['symbol']} — cannot exit now"}, status_code=503)
    registry = HypothesisRegistry(engine)
    closed = registry.close_trade(
        trade_id=trade_id,
        exit_date=str(_date.today()),
        exit_price=float(exit_price),
        exit_reason="MANUAL",
        notes="Manual exit from positions page",
    )
    if not closed:
        return JSONResponse({"error": f"failed to close trade {trade_id}"}, status_code=500)
    return RedirectResponse("/positions", status_code=303)


@app.get("/research", response_class=HTMLResponse)
async def research_page(request: Request):
    research = dl.get_research_results()
    return templates.TemplateResponse(
        request,
        "research.html",
        {
            "request": request,
            "research": research,
            "username": get_current_username(request),
        },
    )


@app.get("/sectors", response_class=HTMLResponse)
async def sectors_page(request: Request):
    return templates.TemplateResponse(
        request,
        "sectors.html",
        {
            "request": request,
            "username": get_current_username(request),
        },
    )


@app.get("/risk", response_class=HTMLResponse)
async def risk_page(request: Request):
    return templates.TemplateResponse(
        request,
        "risk.html",
        {
            "request": request,
            "username": get_current_username(request),
        },
    )


@app.get("/suggestions", response_class=HTMLResponse)
async def suggestions_page(request: Request):
    dl._settings()
    import sqlalchemy as sa
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()
    md = PgMetadataStore(engine)
    summary = md.suggestions_summary()
    with engine.connect() as conn:
        recent = [
            dict(r)
            for r in conn.execute(
                sa.text("SELECT * FROM daily_suggestions ORDER BY suggestion_date DESC, symbol LIMIT 100")
            )
            .mappings()
            .fetchall()
        ]
        by_type = [
            dict(r)
            for r in conn.execute(
                sa.text("""
                SELECT signal_type, COUNT(*) n, AVG(actual_return_bps) avg_net,
                       SUM(hit)*1.0/COUNT(*)*100 accuracy
                FROM daily_suggestions WHERE status='REALIZED'
                GROUP BY signal_type ORDER BY avg_net DESC
            """)
            )
            .mappings()
            .fetchall()
        ]
    # Get cached signals for market cap breakdown
    cached_signals = get_latest_signals_cached()
    all_signals = cached_signals.get("all", [])
    return templates.TemplateResponse(
        request,
        "suggestions.html",
        {
            "request": request,
            "summary": summary,
            "recent": recent,
            "by_type": by_type,
            "signals": all_signals,
            "username": get_current_username(request),
        },
    )


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    from indian_quant.web.portfolio_analytics import compute_full_analytics

    analytics = compute_full_analytics()
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "request": request,
            "analytics": analytics,
            "username": get_current_username(request),
        },
    )


@app.get("/api/analytics")
async def api_analytics():
    from indian_quant.web.portfolio_analytics import compute_full_analytics

    return JSONResponse(compute_full_analytics())


@app.get("/api/data-freshness")
async def api_data_freshness():
    from indian_quant.config.connections import check_data_freshness, get_engine

    return JSONResponse(check_data_freshness(get_engine()))


@app.get("/api/signal-decay")
async def api_signal_decay():
    from indian_quant.config.connections import get_engine
    from scripts.signal_decay import signal_decay_analysis

    return JSONResponse(signal_decay_analysis(get_engine()))


@app.get("/journal/export/csv")
async def journal_export_csv():
    import csv
    import io

    from fastapi.responses import StreamingResponse
    from indian_quant.config.connections import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT * FROM v_all_trades ORDER BY entry_date DESC")).mappings().fetchall()
    if not rows:
        return JSONResponse({"error": "no data"}, status_code=404)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows([dict(r) for r in rows])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=journal_export.csv"},
    )


@app.get("/journal/export/json")
async def journal_export_json():
    from indian_quant.config.connections import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT * FROM v_all_trades ORDER BY entry_date DESC")).mappings().fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/surveillance")
async def surveillance_redirect():
    """Redirect /surveillance to the consolidated hypothesis page."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/hypothesis/3", status_code=301)


@app.get("/api/surveillance")
async def api_surveillance():
    import sqlalchemy as sa
    from indian_quant.config.connections import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        active = conn.execute(
            sa.text("""
            SELECT symbol, framework, stage, stage_raw, first_seen_date, has_ibc
            FROM surveillance_stocks WHERE status='ACTIVE'
        """)
        ).fetchall()
        signals = conn.execute(
            sa.text("""
            SELECT symbol, signal_type, strength, framework, stage, price, ret_1m, ret_3m, vol_20d, notes
            FROM surveillance_signals
            WHERE signal_date = (SELECT MAX(signal_date) FROM surveillance_signals)
            ORDER BY strength DESC
        """)
        ).fetchall()
    return JSONResponse(
        {
            "active": [dict(r._mapping) for r in active],
            "signals": [dict(r._mapping) for r in signals],
        }
    )


@app.get("/announcements/{symbol}", response_class=HTMLResponse)
async def announcements_page(request: Request, symbol: str):
    announcements = dl.get_announcements(symbol.upper())
    available = dl.get_available_announcement_symbols()
    return templates.TemplateResponse(
        request,
        "announcements.html",
        {
            "request": request,
            "symbol": symbol.upper(),
            "announcements": announcements,
            "available_symbols": available,
            "username": get_current_username(request),
        },
    )


# ── Auth Routes ──────────────────────────────────────────────────────


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if get_current_user_id(request):
        return RedirectResponse("/watchlist", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "error": error,
        },
    )


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    ws = _ws()
    user = ws.get_user_by_username(username.strip())
    ws.close()
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password",
            },
            status_code=401,
        )
    request.session["user_id"] = user["user_id"]
    request.session["username"] = user["username"]
    return RedirectResponse("/watchlist", status_code=303)


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    if get_current_user_id(request):
        return RedirectResponse("/watchlist", status_code=303)
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "request": request,
            "error": error,
        },
    )


@app.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    username = username.strip()
    email = email.strip()

    if not re.match(r"^[a-zA-Z0-9_]{3,30}$", username):
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "error": "Username: 3-30 chars, letters/numbers/underscore only",
            },
            status_code=400,
        )
    if "@" not in email or "." not in email:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "error": "Invalid email address",
            },
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "error": "Password must be at least 8 characters",
            },
            status_code=400,
        )
    if password != password2:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "error": "Passwords do not match",
            },
            status_code=400,
        )

    ws = _ws()
    if ws.username_exists(username):
        ws.close()
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "error": "Username already taken",
            },
            status_code=400,
        )
    if ws.email_exists(email):
        ws.close()
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "error": "Email already registered",
            },
            status_code=400,
        )

    ws.create_user(username, email, hash_password(password))
    ws.close()
    return RedirectResponse("/login?registered=1", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ── Watchlist Routes ────────────────────────────────────────────────


@app.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request):
    uid = require_login(request)
    ws = _ws()
    stocks = ws.list_stocks(uid)
    signals = ws.get_all_signals_for_user(uid)
    signal_map = {s["symbol"]: s for s in signals}
    ws.close()
    # Refresh signal_map from PG cached_signals for freshness
    if stocks:
        try:
            import sqlalchemy as sa
            from indian_quant.web.prod_config import get_pg_engine

            pg = get_pg_engine()
            syms = [s["symbol"] for s in stocks]
            with pg.connect() as conn:
                rows = (
                    conn.execute(
                        sa.text(
                            "SELECT symbol, signal_type, close, deliv_pct, deliv_z, rsi, sma_20, "
                            "segment, updated_at FROM cached_signals WHERE symbol = ANY(:syms)"
                        ),
                        {"syms": syms},
                    )
                    .mappings()
                    .fetchall()
                )
                for r in rows:
                    sym = r["symbol"]
                    if sym in signal_map:
                        signal_map[sym].update({k: v for k, v in r.items() if v is not None})
                    else:
                        signal_map[sym] = dict(r)
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "watchlist.html",
        {
            "request": request,
            "username": get_current_username(request),
            "stocks": stocks,
            "signal_map": signal_map,
        },
    )


@app.get("/stock/{symbol}", response_class=HTMLResponse)
async def stock_detail_page(request: Request, symbol: str):
    uid = get_current_user_id(request)
    from indian_quant.web.stock_analysis import get_stock_analysis

    analysis = get_stock_analysis(symbol.upper(), uid)

    # Fallback: build analysis from cached_signals + investorfeed when no parquet data
    if analysis is None:
        analysis = _fallback_stock_analysis(symbol.upper(), uid)
        if analysis is None:
            return templates.TemplateResponse(
                request,
                "stock_detail.html",
                {
                    "request": request,
                    "symbol": symbol.upper(),
                    "analysis": None,
                    "username": get_current_username(request),
                },
            )

    return templates.TemplateResponse(
        request,
        "stock_detail.html",
        {
            "request": request,
            "symbol": symbol.upper(),
            "analysis": analysis,
            "username": get_current_username(request),
        },
    )


def _fallback_stock_analysis(symbol: str, uid: int | None) -> dict | None:
    """Build stock analysis from cached_signals + investorfeed when parquet is missing."""
    import sqlalchemy as sa
    from indian_quant.config.connections import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        r = conn.execute(
            sa.text("SELECT * FROM cached_signals WHERE symbol = :sym LIMIT 1"),
            {"sym": symbol},
        )
        row = r.mappings().first()
        if not row:
            return None
        row = dict(row)

    # Get investorfeed data (P/E, P/B, ROE, sector)
    ifd = {}
    try:
        from indian_quant.ingestion.web.investorfeed_client import InvestorFeedClient

        client = InvestorFeedClient(use_cache=True)
        profile = client.get_single_profile(symbol)
        if profile:
            ifd = profile
    except Exception:
        pass

    close = row.get("close") or 0
    return {
        "symbol": symbol,
        "exchange": row.get("exchange", "NSE"),
        "segment": row.get("segment", "EQ"),
        "latest_date": row.get("signal_date", ""),
        "latest_close": close,
        "prev_close": close,
        "ret_1d_pct": row.get("ret_1d_pct"),
        "signal_type": row.get("signal_type"),
        "deliv_pct": row.get("deliv_pct"),
        "deliv_z": row.get("deliv_z"),
        "vol_z": row.get("vol_z"),
        "hi_streak": row.get("hi_streak"),
        "rsi": row.get("rsi"),
        "macd": row.get("macd"),
        "macd_signal": row.get("macd_signal"),
        "macd_hist": None,
        "sma_20": row.get("sma_20"),
        "sma_50": row.get("sma_50"),
        "atr_14": row.get("atr_14"),
        "entry_zone_low": row.get("entry_zone_low"),
        "entry_zone_high": row.get("entry_zone_high"),
        "stop_loss": row.get("stop_loss"),
        "target_price": row.get("target_price"),
        "price_dates": "[]",
        "price_closes": "[]",
        "price_volumes": "[]",
        "sma_20_series": "[]",
        "sma_50_series": "[]",
        "deliv_z_dates": "[]",
        "deliv_z_series": "[]",
        "deliv_pct_series": "[]",
        "recent_suggestions": [],
        "is_watched": False,
        "watchlist_notes": "",
        "market_cap_cr": row.get("market_cap_cr") or ifd.get("mcap_cr"),
        "market_cap_class": row.get("market_cap_class"),
        "sector": row.get("sector") or ifd.get("sector"),
        "pe_trailing": row.get("pe_trailing") or ifd.get("pe_ratio"),
        "price_to_book": row.get("price_to_book") or ifd.get("pb"),
        "roe": row.get("roe") or ifd.get("roe"),
        "professional_score": row.get("professional_score"),
        "conviction_score": row.get("professional_score"),
        "from_cache": True,
    }


# ── Watchlist API ───────────────────────────────────────────────────


@app.post("/api/watchlist/add")
async def api_watchlist_add(request: Request):
    uid = require_login(request)
    body = await request.json()
    symbol = body.get("symbol", "").strip().upper()
    notes = body.get("notes", "")
    if not symbol:
        return JSONResponse({"error": "symbol required"}, status_code=400)
    # Allow any valid NSE symbol (letters, numbers, ampersand, hyphen)
    if not all(c.isalnum() or c in ("&", "-", "_") for c in symbol):
        return JSONResponse({"error": "Invalid symbol format"}, status_code=400)
    ws = _ws()
    try:
        wl_id = ws.add_stock(uid, symbol, notes)
        ws.close()
        return JSONResponse({"ok": True, "watchlist_id": wl_id})
    except Exception as e:
        ws.close()
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/watchlist/remove")
async def api_watchlist_remove(request: Request):
    uid = require_login(request)
    body = await request.json()
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        return JSONResponse({"error": "symbol required"}, status_code=400)
    ws = _ws()
    ws.remove_stock(uid, symbol)
    ws.close()
    return JSONResponse({"ok": True})


@app.get("/api/watchlist")
async def api_watchlist_list(request: Request):
    uid = require_login(request)
    ws = _ws()
    stocks = ws.list_stocks(uid)
    signals = ws.get_all_signals_for_user(uid)
    ws.close()
    return JSONResponse({"stocks": stocks, "signals": signals})


@app.get("/api/search")
async def api_search_stocks(q: str = "", limit: int = 20):
    q = q.strip().upper()
    if len(q) < 1:
        return JSONResponse([])
    settings = load_settings()
    seen = set()
    matches = []

    nse_dl_dir = settings.normalized_dir / "delivery" / "NSE"
    bse_dl_dir = settings.normalized_dir / "delivery" / "BSE"

    def has_delivery_data(sym: str) -> bool:
        return ((nse_dl_dir / f"{sym}.parquet").exists() if nse_dl_dir.exists() else False) or (
            (bse_dl_dir / f"{sym}.parquet").exists() if bse_dl_dir.exists() else False
        )

    # 1) NSE delivery parquet files
    if nse_dl_dir.exists():
        for p in sorted(nse_dl_dir.glob("*.parquet")):
            sym = p.stem
            if q in sym and sym not in seen:
                matches.append({"symbol": sym, "exchange": "NSE", "segment": "EQ", "has_data": True})
                seen.add(sym)
            if len(matches) >= limit:
                break

    # 2) BSE delivery parquet files
    if bse_dl_dir.exists() and len(matches) < limit:
        for p in sorted(bse_dl_dir.glob("*.parquet")):
            sym = p.stem
            if q in sym and sym not in seen:
                matches.append({"symbol": sym, "exchange": "BSE", "segment": "EQ", "has_data": True})
                seen.add(sym)
            if len(matches) >= limit:
                break

    # 3) Universe registry (broader set, may not have data yet)
    reg_path = settings.data_root / "universe" / "registry.json"
    if reg_path.exists() and len(matches) < limit:
        try:
            import json as _json

            reg = _json.loads(reg_path.read_text())
            for sym, info in reg.get("symbols", {}).items():
                if q in sym and sym not in seen:
                    matches.append(
                        {
                            "symbol": sym,
                            "exchange": info.get("exchange", "NSE"),
                            "segment": info.get("segment", "EQ"),
                            "has_data": has_delivery_data(sym),
                        }
                    )
                    seen.add(sym)
                if len(matches) >= limit:
                    break
        except Exception:
            pass

    # 4) Instruments table (database)
    if len(matches) < limit:
        try:
            import sqlite3 as _sq

            db = Path(settings.storage.metadata_dsn.removeprefix("sqlite:///"))
            if db.exists():
                con = _sq.connect(str(db))
                rows = con.execute(
                    "SELECT DISTINCT symbol, exchange, segment FROM instruments WHERE symbol LIKE ? LIMIT ?",
                    (f"%{q}%", limit),
                ).fetchall()
                # conn auto-closed by 'with' block above
                for sym, exch, seg in rows:
                    if sym not in seen:
                        matches.append(
                            {
                                "symbol": sym,
                                "exchange": exch,
                                "segment": seg,
                                "has_data": has_delivery_data(sym),
                            }
                        )
                        seen.add(sym)
        except Exception:
            pass

    return JSONResponse(matches[:limit])


# ── Professional Quant Layer API Endpoints ──

import math
from datetime import date, datetime


def _clean_nan(obj):
    """Convert NaN/Inf floats and datetime to JSON-safe values."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


@app.get("/api/fundamentals/{symbol}")
async def api_fundamentals(symbol: str):
    """Get fundamental data for a stock."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()
    symbol = symbol.upper()

    with engine.connect() as conn:
        # Key ratios
        kr = conn.execute(sa.text("SELECT * FROM key_ratios WHERE symbol = :s"), {"s": symbol}).mappings().fetchone()

        # Company profile
        cp = (
            conn.execute(sa.text("SELECT * FROM company_profile WHERE symbol = :s"), {"s": symbol})
            .mappings()
            .fetchone()
        )

        # Quarterly financials
        qf = (
            conn.execute(
                sa.text("SELECT * FROM quarterly_financials WHERE symbol = :s ORDER BY period DESC LIMIT 8"),
                {"s": symbol},
            )
            .mappings()
            .fetchall()
        )

    result = {
        "symbol": symbol,
        "key_ratios": dict(kr) if kr else None,
        "company_profile": dict(cp) if cp else None,
        "quarterly_financials": [dict(q) for q in qf],
    }
    return JSONResponse(_clean_nan(result))


@app.get("/api/institutional/{symbol}")
async def api_institutional(symbol: str):
    """Get institutional flow data for a stock."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()
    symbol = symbol.upper()

    with engine.connect() as conn:
        # Shareholding history
        sh = (
            conn.execute(
                sa.text("SELECT * FROM shareholding_history WHERE symbol = :s ORDER BY quarter DESC LIMIT 4"),
                {"s": symbol},
            )
            .mappings()
            .fetchall()
        )

        # Insider trades
        it = (
            conn.execute(
                sa.text("SELECT * FROM insider_trades WHERE symbol = :s ORDER BY trade_date DESC LIMIT 20"),
                {"s": symbol},
            )
            .mappings()
            .fetchall()
        )

        # Promoter pledge
        pp = (
            conn.execute(sa.text("SELECT * FROM promoter_pledge WHERE symbol = :s"), {"s": symbol})
            .mappings()
            .fetchone()
        )

        # Bulk deals
        bd = (
            conn.execute(
                sa.text("SELECT * FROM bulk_deals WHERE symbol = :s ORDER BY deal_date DESC LIMIT 10"), {"s": symbol}
            )
            .mappings()
            .fetchall()
        )

    result = {
        "symbol": symbol,
        "shareholding": [dict(s) for s in sh],
        "insider_trades": [dict(i) for i in it],
        "promoter_pledge": dict(pp) if pp else None,
        "bulk_deals": [dict(b) for b in bd],
    }
    return JSONResponse(_clean_nan(result))


@app.get("/api/fii-dii")
async def api_fii_dii():
    """Get FII/DII daily flow data."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()

    with engine.connect() as conn:
        rows = (
            conn.execute(sa.text("SELECT * FROM fii_dii_daily ORDER BY trade_date DESC LIMIT 30")).mappings().fetchall()
        )

    return JSONResponse(_clean_nan({"data": [dict(r) for r in rows]}))


@app.get("/api/sectors")
async def api_sectors():
    """Get sector performance data."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()

    with engine.connect() as conn:
        # Sector map with stock counts
        sectors = (
            conn.execute(
                sa.text("""
                SELECT s.sector, COUNT(*) as stock_count,
                       AVG(k.pe_trailing) as avg_pe,
                       AVG(k.roe) as avg_roe,
                       AVG(k.debt_to_equity) as avg_de
                FROM sector_map s
                LEFT JOIN key_ratios k ON s.symbol = k.symbol
                WHERE s.sector IS NOT NULL
                GROUP BY s.sector
                ORDER BY stock_count DESC
            """)
            )
            .mappings()
            .fetchall()
        )

        # Latest sector daily
        daily = (
            conn.execute(
                sa.text("""
                SELECT sector, trade_date, avg_return, avg_deliv_z, stock_count
                FROM sector_daily
                WHERE trade_date = (SELECT MAX(trade_date) FROM sector_daily)
                ORDER BY avg_return DESC
            """)
            )
            .mappings()
            .fetchall()
        )

    return JSONResponse(
        _clean_nan(
            {
                "sectors": [dict(s) for s in sectors],
                "daily": [dict(d) for d in daily],
            }
        )
    )


@app.get("/api/portfolio/risk")
async def api_portfolio_risk():
    """Get portfolio risk metrics."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()

    with engine.connect() as conn:
        risk = (
            conn.execute(sa.text("SELECT * FROM portfolio_risk ORDER BY snapshot_date DESC LIMIT 1"))
            .mappings()
            .fetchone()
        )

    return JSONResponse(_clean_nan({"risk": dict(risk) if risk else None}))


@app.get("/api/stock/{symbol}/risk")
async def api_stock_risk(symbol: str):
    """Get risk metrics for a stock."""
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    engine = get_pg_engine()
    symbol = symbol.upper()

    with engine.connect() as conn:
        risk = conn.execute(sa.text("SELECT * FROM stock_risk WHERE symbol = :s"), {"s": symbol}).mappings().fetchone()

    return JSONResponse(_clean_nan({"symbol": symbol, "risk": dict(risk) if risk else None}))


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/admin/scheduler")
async def admin_scheduler_status():
    return get_scheduler_status()


@app.post("/api/admin/refresh-cache")
async def admin_refresh_cache():
    import threading

    from indian_quant.web.scheduler import _full_cache_rebuild

    t = threading.Thread(target=_full_cache_rebuild, daemon=True)
    t.start()
    return {"status": "started", "message": "Cache rebuild running in background"}


# ══════════════════════════════════════════════════════════════════════
# HYPOTHESIS FRAMEWORK — public routes, no auth required
# ══════════════════════════════════════════════════════════════════════


def _hreg():
    from indian_quant.hypotheses.registry import HypothesisRegistry
    from indian_quant.web.prod_config import get_pg_engine

    return HypothesisRegistry(get_pg_engine())


@app.get("/hypotheses", response_class=HTMLResponse)
async def hypotheses_page(request: Request):
    """Public overview of all hypotheses with summary metrics."""
    reg = _hreg()
    hypotheses = reg.list_all()
    summaries = {}
    for h in hypotheses:
        hid = h["id"]
        summaries[hid] = {
            "trade_summary": reg.trade_summary(hid),
            "stock_count": reg.stock_count(hid),
            "latest_signals": reg.latest_signals(hid, limit=7),
        }
    return templates.TemplateResponse(
        request,
        "hypotheses.html",
        {
            "request": request,
            "hypotheses": hypotheses,
            "summaries": summaries,
            "username": get_current_username(request),
        },
    )


@app.get("/hypothesis/{hypo_id}", response_class=HTMLResponse)
async def hypothesis_detail(request: Request, hypo_id: int):
    """Public detail page for a single hypothesis — signals, trades, analytics."""
    import sqlalchemy as sa

    reg = _hreg()
    hypo = reg.get_by_id(hypo_id)
    if not hypo:
        return HTMLResponse("Hypothesis not found", status_code=404)

    trade_summary = reg.trade_summary(hypo_id)
    open_trades = reg.open_trades(hypo_id)
    settled_trades = reg.settled_trades(hypo_id, limit=50)
    latest_signals = reg.latest_signals(hypo_id, limit=20)
    stocks = reg.list_stocks(hypo_id, active_only=True)

    # Build equity curve from settled trades
    equity_dates = []
    equity_values = []
    cumulative_pnl = 0.0
    for t in reversed(settled_trades):
        ret = t.get("return_pct") or 0
        pos_val = t.get("position_value") or 0
        pnl = pos_val * ret / 100 if pos_val else 0
        cumulative_pnl += pnl
        equity_dates.append(str(t.get("exit_date", "")))
        equity_values.append(round(cumulative_pnl, 2))

    # Hypothesis-specific extra data
    extra = {}
    hypo_name = hypo.get("name", "")

    if hypo_name == "surveillance_recovery":
        from indian_quant.config.connections import get_engine as _get_engine

        _eng = _get_engine()
        with _eng.connect() as conn:
            # Framework stats (for top cards)
            fw_stats = conn.execute(
                sa.text("""
                SELECT framework, COUNT(*) as cnt
                FROM surveillance_stocks WHERE status='ACTIVE'
                GROUP BY framework ORDER BY cnt DESC
            """)
            ).fetchall()
            extra["surv_stats"] = [(r[0], r[1]) for r in fw_stats]

            # Total surveillance stocks
            extra["total_surveillance_stocks"] = conn.execute(
                sa.text("SELECT COUNT(*) FROM surveillance_stocks WHERE status='ACTIVE'")
            ).scalar()

            # Full active surveillance stocks (for stocks table)
            active_stocks = (
                conn.execute(
                    sa.text("""
                SELECT symbol, framework, stage, stage_raw, first_seen_date, has_ibc
                FROM surveillance_stocks WHERE status = 'ACTIVE'
                ORDER BY framework, symbol
            """)
                )
                .mappings()
                .fetchall()
            )
            extra["surv_active_stocks"] = [dict(r) for r in active_stocks]

            # Full surveillance signals with all columns (for signals table)
            full_signals = (
                conn.execute(
                    sa.text("""
                SELECT symbol, signal_type, strength, framework, stage,
                       price, ret_1m, ret_3m, vol_20d, notes, signal_date
                FROM surveillance_signals
                WHERE signal_date = (SELECT MAX(signal_date) FROM surveillance_signals)
                ORDER BY strength DESC
            """)
                )
                .mappings()
                .fetchall()
            )
            extra["surv_full_signals"] = [dict(r) for r in full_signals]

            # Surveillance paper positions (open)
            surv_positions = (
                conn.execute(
                    sa.text("""
                SELECT symbol, close_at_signal, entry_date, horizon_days,
                       stop_pct, note, position_value
                FROM paper_signals
                WHERE exit_date IS NULL AND note LIKE '%surveillance%'
                ORDER BY symbol
            """)
                )
                .mappings()
                .fetchall()
            )
            extra["surv_positions"] = [dict(r) for r in surv_positions]

    elif hypo_name == "circuit_breakout":
        from indian_quant.config.connections import get_engine as _get_engine

        _eng = _get_engine()
        with _eng.connect() as conn:
            # Circuit limits stats
            circuit_count = conn.execute(sa.text("SELECT COUNT(*) FROM stock_circuit_limits")).scalar()
            extra["circuit_count"] = circuit_count

            circuit_symbols = conn.execute(sa.text("SELECT COUNT(DISTINCT symbol) FROM stock_circuit_limits")).scalar()
            extra["circuit_symbols"] = circuit_symbols

            # Upper/lower hit counts (last 30 days)
            upper_hits = conn.execute(
                sa.text("""
                SELECT COUNT(DISTINCT symbol) FROM hypothesis_signals
                WHERE hypothesis_id = 2 AND signal_type = 'circuit_upper_breakout'
                AND signal_date >= CURRENT_DATE - INTERVAL '30 days'
            """)
            ).scalar()
            extra["circuit_upper_hits"] = upper_hits

            lower_hits = conn.execute(
                sa.text("""
                SELECT COUNT(DISTINCT symbol) FROM hypothesis_signals
                WHERE hypothesis_id = 2 AND signal_type = 'circuit_lower_reversal'
                AND signal_date >= CURRENT_DATE - INTERVAL '30 days'
            """)
            ).scalar()
            extra["circuit_lower_hits"] = lower_hits

            # Data sources
            sources = conn.execute(
                sa.text("""
                SELECT source, COUNT(*) as cnt FROM stock_circuit_limits
                GROUP BY source ORDER BY cnt DESC
            """)
            ).fetchall()
            extra["circuit_sources"] = " / ".join(f"{r[0]}({r[1]})" for r in sources)

            # Recent circuit limits (last 200)
            limits = (
                conn.execute(
                    sa.text("""
                SELECT symbol, trade_date, prev_close, upper_circuit, lower_circuit, filter_pct, source
                FROM stock_circuit_limits
                ORDER BY trade_date DESC, symbol
                LIMIT 200
            """)
                )
                .mappings()
                .fetchall()
            )
            import math

            extra["circuit_limits"] = []
            for r in limits:
                row = dict(r)
                for k, v in row.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        row[k] = 0
                extra["circuit_limits"].append(row)

            # Pattern analysis stats (clean NaN/Inf values)
            import json as _json
            import math as _math
            from pathlib import Path as _Path

            stats_path = _Path("data/cache/circuit_pattern_stats.json")
            if stats_path.exists():
                try:
                    raw_stats = _json.loads(stats_path.read_text())
                    clean_stats = {}
                    for k, v in raw_stats.items():
                        clean_v = {}
                        for sk, sv in v.items():
                            if isinstance(sv, float) and (_math.isnan(sv) or _math.isinf(sv)):
                                clean_v[sk] = 0
                            else:
                                clean_v[sk] = sv
                        clean_stats[k] = clean_v
                    extra["circuit_pattern_stats"] = clean_stats
                except Exception:
                    extra["circuit_pattern_stats"] = {}
            else:
                extra["circuit_pattern_stats"] = {}

    return templates.TemplateResponse(
        request,
        "hypothesis_detail.html",
        {
            "request": request,
            "hypo": hypo,
            "trade_summary": trade_summary,
            "open_trades": open_trades,
            "settled_trades": settled_trades,
            "latest_signals": latest_signals,
            "stocks": stocks,
            "equity_dates": equity_dates,
            "equity_values": equity_values,
            "extra": extra,
            "username": get_current_username(request),
        },
    )


@app.get("/api/hypothesis/{hypo_id}/signals")
async def api_hypothesis_signals(hypo_id: int, date: str = "", limit: int = 50):
    reg = _hreg()
    return reg.get_signals(hypo_id, signal_date=date or None, limit=limit)


@app.get("/api/hypothesis/{hypo_id}/trades")
async def api_hypothesis_trades(hypo_id: int, status: str = ""):
    reg = _hreg()
    if status == "OPEN":
        return reg.open_trades(hypo_id)
    if status == "SETTLED":
        return reg.settled_trades(hypo_id)
    return {"open": reg.open_trades(hypo_id), "settled": reg.settled_trades(hypo_id)}


@app.get("/api/hypothesis/{hypo_id}/summary")
async def api_hypothesis_summary(hypo_id: int):
    reg = _hreg()
    return reg.trade_summary(hypo_id)


@app.post("/api/hypothesis/{hypo_id}/add-stock")
async def api_hypothesis_add_stock(hypo_id: int, symbol: str = Form(...), exchange: str = Form("NSE")):
    reg = _hreg()
    rid = reg.add_stock(hypo_id, symbol, exchange, added_by="manual")
    return {"status": "ok", "added": bool(rid), "symbol": symbol.upper()}


@app.post("/api/hypothesis/{hypo_id}/remove-stock")
async def api_hypothesis_remove_stock(hypo_id: int, symbol: str = Form(...), reason: str = Form("manual")):
    reg = _hreg()
    ok = reg.remove_stock(hypo_id, symbol, reason)
    return {"status": "ok", "removed": ok, "symbol": symbol.upper()}


@app.post("/api/hypothesis/{hypo_id}/trade/open")
async def api_hypothesis_trade_open(
    hypo_id: int,
    symbol: str = Form(...),
    entry_price: float = Form(...),
    qty: int = Form(...),
    stop_pct: float = Form(0.07),
    horizon_days: int = Form(10),
    notes: str = Form(""),
):
    reg = _hreg()
    from datetime import date

    trade_id = reg.open_trade(
        hypothesis_id=hypo_id,
        symbol=symbol,
        entry_date=str(date.today()),
        entry_price=entry_price,
        qty=qty,
        stop_pct=stop_pct,
        horizon_days=horizon_days,
        notes=notes or "manual entry",
    )
    return {"status": "ok", "trade_id": trade_id, "symbol": symbol.upper()}


@app.post("/api/hypothesis/{hypo_id}/trade/close")
async def api_hypothesis_trade_close(
    hypo_id: int,
    trade_id: int = Form(...),
    exit_price: float = Form(...),
    exit_reason: str = Form("MANUAL"),
    notes: str = Form(""),
):
    reg = _hreg()
    from datetime import date

    result = reg.close_trade(trade_id, str(date.today()), exit_price, exit_reason, notes)
    return {"status": "ok", "result": result}


# ══════════════════════════════════════════════════════════════════════
# TRADE JOURNAL — public routes
# ══════════════════════════════════════════════════════════════════════


@app.get("/journal", response_class=HTMLResponse)
async def journal_page(request: Request, setup: str = "", reviewed: str = "all"):
    """Trade journal listing with filters."""
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    rev = None
    if reviewed == "yes":
        rev = True
    elif reviewed == "no":
        rev = False
    entries = md.journal_list(setup_type=setup, reviewed=rev, limit=50)
    stats = md.journal_stats()
    # Hypothesis-wise journal + capital details (same ₹10L basis as /positions)
    import sqlalchemy as sa
    from indian_quant.web.prod_config import get_pg_engine

    _eng = get_pg_engine()
    with _eng.connect() as conn:
        cap_rows = (
            conn.execute(
                sa.text("""
            SELECT h.name,
                   SUM(CASE WHEN t.status = 'OPEN' THEN t.position_value ELSE 0 END) as deployed,
                   COUNT(CASE WHEN t.status = 'OPEN' THEN 1 END) as open_count,
                   SUM(CASE WHEN t.status = 'SETTLED'
                            THEN t.position_value * t.realized_net_bps / 10000.0 ELSE 0 END) as realized_pnl
            FROM hypotheses h
            LEFT JOIN paper_signals t ON t.hypothesis_id = h.id
            WHERE h.is_active
            GROUP BY h.id, h.name
        """)
            )
            .mappings()
            .fetchall()
        )
        j_rows = (
            conn.execute(
                sa.text("""
            SELECT setup_type, COUNT(*) as entries,
                   SUM(CASE WHEN net_bps > 0 THEN 1 ELSE 0 END) as winners,
                   AVG(net_bps) as avg_net,
                   SUM(CASE WHEN review_date IS NOT NULL THEN 1 ELSE 0 END) as reviewed,
                   SUM(CASE WHEN exit_date IS NULL THEN 1 ELSE 0 END) as open_j
            FROM trade_journal
            GROUP BY setup_type
        """)
            )
            .mappings()
            .fetchall()
        )
    _jmap = {r["setup_type"]: dict(r) for r in j_rows}
    by_hyp = {}
    for r in cap_rows:
        name = r["name"]
        j = _jmap.get(name, {})
        n = j.get("entries") or 0
        w = j.get("winners") or 0
        deployed = round(r["deployed"] or 0)
        realized = round(r["realized_pnl"] or 0, 2)
        by_hyp[name] = {
            "allocated": HYPO_CAPITAL,
            "deployed": deployed,
            "open_count": r["open_count"] or 0,
            "realized_pnl": realized,
            "available": HYPO_CAPITAL - deployed,
            "equity": round(HYPO_CAPITAL + realized, 2),
            "entries": n,
            "winners": w,
            "win_rate": round(w / n * 100, 1) if n else 0,
            "avg_net": round(j.get("avg_net"), 1) if j.get("avg_net") is not None else None,
            "reviewed": j.get("reviewed") or 0,
            "open_j": j.get("open_j") or 0,
        }
    md.close()
    return templates.TemplateResponse(
        request,
        "journal.html",
        {
            "request": request,
            "entries": entries,
            "stats": stats,
            "by_hyp": by_hyp,
            "setup_filter": setup,
            "reviewed_filter": reviewed,
            "username": get_current_username(request),
        },
    )


@app.get("/journal/{trade_id}", response_class=HTMLResponse)
async def journal_detail(request: Request, trade_id: int):
    """Single trade journal entry detail by journal ID."""
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    # Lookup by journal id (not paper_trade_id)
    import sqlalchemy as sa

    with md._engine.connect() as conn:
        r = conn.execute(
            sa.text("SELECT paper_trade_id FROM trade_journal WHERE id = :jid"), {"jid": trade_id}
        ).fetchone()
    if not r:
        md.close()
        return HTMLResponse("Journal entry not found", status_code=404)
    paper_trade_id = r[0]
    entry = md.journal_entry(paper_trade_id)
    md.close()
    if not entry:
        return HTMLResponse("Journal entry not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "journal_detail.html",
        {
            "request": request,
            "entry": entry,
            "username": get_current_username(request),
        },
    )


@app.post("/api/journal/{trade_id}/review")
async def api_journal_add_review(
    trade_id: int,
    review_rating: int = Form(3),
    what_went_right: str = Form(""),
    what_went_wrong: str = Form(""),
    lessons_learned: str = Form(""),
    would_repeat: bool = Form(True),
    setup_quality: str = Form(""),
    execution_grade: str = Form(""),
    notes: str = Form(""),
):
    """Add post-trade review via API."""
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    ok = md.journal_add_review(
        trade_id,
        review_rating=review_rating,
        what_went_right=what_went_right,
        what_went_wrong=what_went_wrong,
        lessons_learned=lessons_learned,
        would_repeat=would_repeat,
        setup_quality=setup_quality,
        execution_grade=execution_grade,
        notes=notes,
    )
    md.close()
    return {"status": "ok" if ok else "not_found"}


@app.get("/api/journal/stats")
async def api_journal_stats():
    """Journal aggregate stats as JSON."""
    from indian_quant.storage.pg_metadata import PgMetadataStore
    from indian_quant.web.prod_config import get_pg_engine

    md = PgMetadataStore(get_pg_engine())
    stats = md.journal_stats()
    md.close()
    return stats
