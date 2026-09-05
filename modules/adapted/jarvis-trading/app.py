from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any

import pandas as pd

from ai.brain import generate_market_briefing, generate_screener_commentary
from data.fetcher import load_universe
from reports.weekly_review import generate_weekly_review
from scheduler import start_scheduler
from screener.screener import run_screener
from storage.db import add_task, append_trade, get_tasks, get_trades, init_db


app = FastAPI(title="AXIOM NSE Trading Agent")
latest_screener_results: list[dict[str, Any]] = []


class ScreenerRequest(BaseModel):
    symbols: list[str] | None = None


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    start_scheduler()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "jarvis-nse-trading"}


@app.get("/universe")
def universe() -> dict[str, Any]:
    universe_df = load_universe()
    return {"count": len(universe_df), "symbols": universe_df["symbol"].tolist()}


@app.post("/screener")
def screen_symbols(request: ScreenerRequest) -> dict[str, Any]:
    symbols = request.symbols
    results = run_screener(symbols)
    global latest_screener_results
    latest_screener_results = results.to_dict(orient="records")
    commentary = generate_screener_commentary(latest_screener_results[:10])
    return {"count": len(latest_screener_results), "results": latest_screener_results, "commentary": commentary}


@app.get("/screener/latest")
def latest_screener() -> dict[str, Any]:
    if not latest_screener_results:
        raise HTTPException(status_code=404, detail="No screener results available")
    return {"count": len(latest_screener_results), "results": latest_screener_results}


@app.get("/briefing")
def briefing() -> dict[str, Any]:
    universe_df = load_universe()
    briefing_text = generate_market_briefing({
        "symbol_count": len(universe_df),
        "watchlist_count": min(10, len(universe_df)),
    })
    return {"briefing": briefing_text}


class TradeRequest(BaseModel):
    symbol: str
    entry_price: float
    exit_price: float | None = None
    quantity: int
    pnl: float
    setup_type: str | None = None
    notes: str | None = None
    holding_period: str | None = None


class TaskRequest(BaseModel):
    label: str
    context: str | None = None


@app.post("/trades")
def create_trade(request: TradeRequest) -> dict[str, Any]:
    append_trade(request.dict())
    return {"status": "created", "symbol": request.symbol}


@app.get("/trades")
def list_trades() -> dict[str, Any]:
    trades = get_trades()
    return {"count": len(trades), "trades": trades}


@app.get("/reports/weekly")
def weekly_report() -> dict[str, Any]:
    trades = get_trades()
    report = generate_weekly_review(pd.DataFrame(trades))
    return {"report": report}


@app.post("/tasks")
def create_task(request: TaskRequest) -> dict[str, Any]:
    add_task(request.label, request.context)
    return {"status": "created", "label": request.label}


@app.get("/tasks")
def list_tasks() -> dict[str, Any]:
    return {"tasks": get_tasks()}
