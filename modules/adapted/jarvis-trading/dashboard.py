from __future__ import annotations

import datetime as dt
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from dotenv import load_dotenv

load_dotenv()

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ai.brain import (
    generate_market_briefing,
    generate_screener_commentary,
    generate_stock_analysis,
    generate_task_list,
    generate_trade_journal_summary,
)
from analytics.footprint import APPROXIMATION_NOTE, build_footprint, fetch_intraday
from backtest.backtest import BacktestConfig, backtest_symbol
from data.econ_calendar import fetch_calendar
from data.fetcher import fetch_symbol_history, load_universe
from data.fii_dii import fetch_fii_dii
from data.live_market import fetch_gainers_losers, fetch_indices
from data.market_context import build_briefing_context
from data.news_feed import fetch_market_news
from loguru import logger
from plotly.subplots import make_subplots
from reports.pdf_generator import generate_screener_pdf, generate_text_report, generate_trade_journal_pdf
from reports.trade_log import append_trade_log, load_trade_journal
from reports.weekly_review import generate_weekly_review
from risk.risk import calculate_position
from screener.regime_classifier import RegimeResult, classify_regime
from screener.screener import run_screener
from storage.db import (
    add_task,
    add_to_watchlist,
    get_risk_history,
    get_tasks,
    get_watchlist,
    init_db,
    remove_from_watchlist,
    save_risk_calc,
    save_watchlist_from_screener,
)
from utils.timez import now_ist

DATA_DIR = Path("data")
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def is_ist_market_session_active(dt: dt.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else dt.datetime.now(ist)
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
AXIOM NSE Trading Intelligence — Stark Industries Edition v5.0
Neura Capital | Powered by Groq · Built by the best.
"Sometimes you gotta run before you can walk." — T. Stark
"""

# ─────────────────────────────────────────────────────────────────
# AXIOM CSS — STARK INDUSTRIES EDITION
# ─────────────────────────────────────────────────────────────────

AXIOM_CSS = """
<style>
/* ═══════════════════════════════════════════════════════════════
   AXIOM OS v5.0 — 
"""