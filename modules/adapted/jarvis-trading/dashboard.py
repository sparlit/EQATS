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
AXIOM NSE Trading Intelligence — Stark Industries Edition v5.0
Neura Capital | Powered by Groq · Built by the best.
"Sometimes you gotta run before you can walk." — T. Stark
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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

# ─────────────────────────────────────────────────────────────────
# AXIOM CSS — STARK INDUSTRIES EDITION
# ─────────────────────────────────────────────────────────────────

AXIOM_CSS = """
<style>
/* ═══════════════════════════════════════════════════════════════
   AXIOM OS v5.0 — STARK INDUSTRIES / NEURA CAPITAL
   Design System: Iron Man HUD · Arc Reactor Blue + Stark Gold
   "I am Iron Man." — T. Stark
═══════════════════════════════════════════════════════════════ */

/* ── FONTS ── */
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@500;700;900&family=Inter:wght@300;400;500;600;700&display=swap');

/* ── DESIGN TOKENS ── */
:root {
    /* Backgrounds — deep space */
    --bg-base:       #020912;
    --bg-surface:    #050e1c;
    --bg-elevated:   #081526;
    --bg-overlay:    #0b1d31;

    /* Arc Reactor Blue */
    --brand-primary:   #00c8ff;
    --brand-secondary: #007aaa;
    --brand-glow:      rgba(0, 200, 255, 0.18);

    /* Stark Gold */
    --color-gold:      #FFB300;
    --color-gold-dim:  rgba(255, 179, 0, 0.10);
    --color-gold-glow: rgba(255, 179, 0, 0.25);

    /* Iron Man Red */
    --color-iron-red:  #E63946;
    --color-red-dim:   rgba(230, 57, 70, 0.10);

    /* Semantic */
    --color-bull:    #00d68f;
    --color-bear:    #e63946;
    --color-neutral: #FFB300;
    --color-info:    #00c8ff;

    /* Text hierarchy */
    --text-primary:   #c8e8ff;
    --text-secondary: #5a94bc;
    --text-muted:     #234460;
    --text-accent:    #00c8ff;
    --text-gold:      #FFB300;

    /* Borders */
    --border-default: rgba(0, 200, 255, 0.09);
    --border-strong:  rgba(0, 200, 255, 0.28);
    --border-subtle:  rgba(0, 200, 255, 0.04);
    --border-gold:    rgba(255, 179, 0, 0.28);

    /* Glows */
    --glow-blue-sm:  0 0 12px rgba(0, 200, 255, 0.20);
    --glow-blue-md:  0 0 28px rgba(0, 200, 255, 0.25);
    --glow-gold:     0 0 16px rgba(255, 179, 0, 0.22);
    --shadow-card:   0 6px 32px rgba(0, 0, 0, 0.55);

    /* Shape */
    --radius-sm: 3px;
    --radius-md: 6px;
    --radius-lg: 10px;
}

/* ── BASE ── */
html, body, [data-testid="stApp"] {
    background-color: var(--bg-base) !important;
    color: var(--text-primary) !important;
    font-family: 'Inter', 'Share Tech Mono', monospace !important;
    font-size: 13px;
    line-height: 1.55;
}

/* ── HEX GRID BACKGROUND — Iron Man HUD aesthetic ── */
[data-testid="stApp"]::before {
    content: "";
    position: fixed;
    inset: 0;
    background:
        /* Arc reactor core glow from top */
        radial-gradient(ellipse 55% 32% at 50% -6%, rgba(0,200,255,0.11) 0%, transparent 65%),
        /* Right edge pulse */
        radial-gradient(ellipse 18% 60% at 104% 40%, rgba(0,200,255,0.04) 0%, transparent 70%),
        /* Left edge glow */
        radial-gradient(ellipse 12% 50% at -2% 60%, rgba(255,179,0,0.03) 0%, transparent 70%),
        /* Hex diamond grid — 60deg lines */
        repeating-linear-gradient(
            60deg,
            rgba(0,200,255,0.025) 0px, rgba(0,200,255,0.025) 1px,
            transparent 1px, transparent 36px
        ),
        /* Hex diamond grid — 120deg lines */
        repeating-linear-gradient(
            120deg,
            rgba(0,200,255,0.025) 0px, rgba(0,200,255,0.025) 1px,
            transparent 1px, transparent 36px
        ),
        /* Fine scan lines */
        repeating-linear-gradient(
            0deg,
            rgba(0,200,255,0.013) 0px, rgba(0,200,255,0.013) 1px,
            transparent 1px, transparent 4px
        );
    pointer-events: none;
    z-index: 0;
    animation: scanroll 22s linear infinite;
}
@keyframes scanroll {
    0%   { background-position: 0 0, 0 0, 0 0, 0 0, 0 0, 0 0; }
    100% { background-position: 0 0, 0 0, 0 0, 0 0, 0 0, 0 88px; }
}

/* ── MAIN CONTENT ── */
[data-testid="stAppViewContainer"] > .main > .block-container {
    padding-top: 0.5rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1480px;
}

/* ── SIDEBAR — Stark armor plating ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg,
        #010810 0%,
        #030c1a 40%,
        #020912 80%,
        #010810 100%
    ) !important;
    border-right: 1px solid var(--border-default) !important;
    box-shadow: 6px 0 48px rgba(0,0,0,0.7) !important;
}
/* Animated energy beam on sidebar edge */
[data-testid="stSidebar"]::after {
    content: "";
    position: absolute;
    top: 0; bottom: 0; right: -1px;
    width: 1px;
    background: linear-gradient(
        180deg,
        transparent 0%,
        rgba(0,200,255,0.0) 15%,
        rgba(0,200,255,0.8) 45%,
        rgba(255,179,0,0.6) 55%,
        rgba(0,200,255,0.0) 85%,
        transparent 100%
    );
    animation: energyBeam 6s ease-in-out infinite;
}
@keyframes energyBeam {
    0%, 100% { opacity: 0.1; transform: translateY(-40%); }
    50%       { opacity: 1.0; transform: translateY(40%); }
}

/* ── TYPOGRAPHY ── */
h1, h2, h3, h4 {
    font-family: 'Orbitron', sans-serif !important;
    color: var(--text-accent) !important;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    margin: 0 !important;
}
h1 {
    font-size: 1.35rem !important;
    font-weight: 900;
    text-shadow: 0 0 30px rgba(0,200,255,0.55), 0 0 70px rgba(0,200,255,0.2);
}
h2 { font-size: 0.9rem !important; font-weight: 700; }
h3 { font-size: 0.78rem !important; font-weight: 600; }

p, span, li, div, label {
    color: var(--text-primary) !important;
    font-family: 'Inter', sans-serif !important;
}

/* ── METRIC CARDS — HUD readout style ── */
[data-testid="metric-container"] {
    background: linear-gradient(135deg,
        rgba(8,21,38,0.97) 0%,
        rgba(5,14,28,0.99) 100%
    ) !important;
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-md) !important;
    padding: 14px 18px !important;
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(14px);
    box-shadow: var(--shadow-card) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
    clip-path: polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 8px 100%, 0 calc(100% - 8px));
}
/* Top gradient line */
[data-testid="metric-container"]::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--brand-primary) 50%, transparent);
    opacity: 0.55;
}
/* Corner bracket top-left */
[data-testid="metric-container"]::after {
    content: "";
    position: absolute;
    top: 0; left: 0;
    width: 11px; height: 11px;
    border-top: 2px solid rgba(0,200,255,0.65);
    border-left: 2px solid rgba(0,200,255,0.65);
}
[data-testid="metric-container"]:hover {
    border-color: rgba(0,200,255,0.25) !important;
    box-shadow: var(--shadow-card), var(--glow-blue-sm) !important;
}

[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.6rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
}
[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 1.5rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.03em !important;
}
[data-testid="stMetricDelta"] {
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.68rem !important;
}
[data-testid="stMetricDelta"] svg { display: none; }

/* ── BUTTONS — Angular Stark design ── */
[data-testid="stButton"] > button {
    background: rgba(0,200,255,0.04) !important;
    border: 1px solid var(--border-strong) !important;
    color: var(--brand-primary) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.69rem !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    border-radius: var(--radius-sm) !important;
    padding: 7px 16px !important;
    transition: all 0.15s ease !important;
    position: relative;
    overflow: hidden;
    clip-path: polygon(0 0, calc(100% - 7px) 0, 100% 7px, 100% 100%, 7px 100%, 0 calc(100% - 7px));
}
[data-testid="stButton"] > button::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, rgba(0,200,255,0.06), transparent 60%);
    opacity: 0;
    transition: opacity 0.15s;
}
[data-testid="stButton"] > button:hover {
    background: rgba(0,200,255,0.09) !important;
    border-color: var(--brand-primary) !important;
    box-shadow: 0 0 28px rgba(0,200,255,0.38), inset 0 0 14px rgba(0,200,255,0.07) !important;
    color: #ffffff !important;
    transform: translateY(-1px);
}
[data-testid="stButton"] > button:hover::before { opacity: 1; }
[data-testid="stButton"] > button:active {
    transform: translateY(0) !important;
    box-shadow: 0 0 10px rgba(0,200,255,0.2) !important;
}

/* ── FORM INPUTS ── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
    background: rgba(8,21,38,0.92) !important;
    border: 1px solid var(--border-default) !important;
    color: var(--text-primary) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.8rem !important;
    border-radius: var(--radius-sm) !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: var(--brand-primary) !important;
    box-shadow: 0 0 0 2px rgba(0,200,255,0.10), 0 0 18px rgba(0,200,255,0.13) !important;
    outline: none !important;
}

/* Select boxes */
[data-baseweb="select"] { background: rgba(8,21,38,0.92) !important; }
[data-baseweb="select"] > div {
    background: rgba(8,21,38,0.92) !important;
    border-color: var(--border-default) !important;
    color: var(--text-primary) !important;
    border-radius: var(--radius-sm) !important;
}
[data-baseweb="select"] > div:hover { border-color: var(--border-strong) !important; }

/* ── DATAFRAME / TABLES ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}
[data-testid="stDataFrame"] table {
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.74rem !important;
}
[data-testid="stDataFrame"] thead th {
    background: rgba(11,29,49,0.98) !important;
    color: var(--text-secondary) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.6rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid var(--border-default) !important;
    padding: 10px 12px !important;
}
[data-testid="stDataFrame"] tbody tr:nth-child(even) td {
    background: rgba(255,255,255,0.012) !important;
}
[data-testid="stDataFrame"] tbody tr:hover td {
    background: rgba(0,200,255,0.05) !important;
}

/* ── ALERTS ── */
[data-testid="stSuccess"] {
    background: rgba(0,214,143,0.07) !important;
    border: 1px solid rgba(0,214,143,0.22) !important;
    border-left: 3px solid var(--color-bull) !important;
    border-radius: var(--radius-sm) !important;
    color: #00d68f !important;
}
[data-testid="stError"] {
    background: rgba(230,57,70,0.07) !important;
    border: 1px solid rgba(230,57,70,0.22) !important;
    border-left: 3px solid var(--color-bear) !important;
    border-radius: var(--radius-sm) !important;
    color: #f87171 !important;
}
[data-testid="stWarning"] {
    background: rgba(255,179,0,0.07) !important;
    border: 1px solid rgba(255,179,0,0.22) !important;
    border-left: 3px solid var(--color-gold) !important;
    border-radius: var(--radius-sm) !important;
    color: #FFB300 !important;
}
[data-testid="stInfo"] {
    background: rgba(0,200,255,0.06) !important;
    border: 1px solid rgba(0,200,255,0.18) !important;
    border-left: 3px solid var(--color-info) !important;
    border-radius: var(--radius-sm) !important;
}

/* ── SIDEBAR RADIO NAV — Stark suit module selector ── */
.stRadio [data-testid="stWidgetLabel"] { display: none !important; }
.stRadio > div { gap: 1px !important; }
.stRadio label {
    display: block !important;
    padding: 9px 16px 9px 18px !important;
    border-radius: 0 !important;
    cursor: pointer;
    transition: all 0.12s ease !important;
    border: 1px solid transparent !important;
    border-left: 2px solid transparent !important;
    color: var(--text-muted) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.7rem !important;
    letter-spacing: 0.1em !important;
}
.stRadio label:hover {
    background: rgba(0,200,255,0.045) !important;
    color: var(--text-secondary) !important;
    border-left-color: rgba(0,200,255,0.3) !important;
}
.stRadio label[data-baseweb="radio"] {
    background: linear-gradient(90deg, rgba(0,200,255,0.08) 0%, transparent 100%) !important;
    color: var(--brand-primary) !important;
    border-left-color: var(--brand-primary) !important;
    text-shadow: 0 0 8px rgba(0,200,255,0.4);
}
.stRadio label > div:first-child { display: none !important; }
.stRadio label > div:last-child { margin: 0 !important; }

/* ── EXPANDER ── */
[data-testid="stExpander"] {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-md) !important;
}
[data-testid="stExpander"] summary {
    color: var(--text-secondary) !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em !important;
}

/* ── SPINNER ── */
[data-testid="stSpinner"] > div { border-top-color: var(--brand-primary) !important; }

/* ── SCROLLBAR ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg-base); }
::-webkit-scrollbar-thumb {
    background: rgba(0,200,255,0.18);
    border-radius: 2px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(0,200,255,0.35); }

/* ═══════════════════════════════════════════════════
   COMPONENT CLASSES — STARK DESIGN SYSTEM
═══════════════════════════════════════════════════ */

/* ── CARD — armor panel ── */
.nc-card {
    background: linear-gradient(135deg,
        rgba(8,21,38,0.97) 0%,
        rgba(5,14,28,0.99) 100%
    );
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    padding: 18px 22px;
    margin-bottom: 14px;
    position: relative;
    overflow: hidden;
    box-shadow: var(--shadow-card);
    transition: border-color 0.2s, box-shadow 0.2s;
}
.nc-card:hover {
    border-color: rgba(0,200,255,0.2);
    box-shadow: var(--shadow-card), var(--glow-blue-sm);
}
/* Top energy line — blue to gold */
.nc-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        var(--brand-primary) 35%,
        var(--color-gold) 65%,
        transparent 100%
    );
    opacity: 0.38;
}

/* CORNER BRACKETS — all four corners */
.nc-corner {
    position: absolute;
    width: 13px; height: 13px;
    pointer-events: none;
    z-index: 2;
}
.nc-tl { top: -1px;  left: -1px;  border-top: 2px solid rgba(0,200,255,0.72); border-left: 2px solid rgba(0,200,255,0.72); }
.nc-tr { top: -1px;  right: -1px; border-top: 2px solid rgba(255,179,0,0.55); border-right: 2px solid rgba(255,179,0,0.55); }
.nc-bl { bottom:-1px; left: -1px;  border-bottom: 2px solid rgba(255,179,0,0.55); border-left: 2px solid rgba(255,179,0,0.55); }
.nc-br { bottom:-1px; right: -1px; border-bottom: 2px solid rgba(0,200,255,0.72); border-right: 2px solid rgba(0,200,255,0.72); }

/* ── SECTION HEADER — HUD bracket style ── */
.nc-section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 22px 0 12px;
    padding-bottom: 9px;
    border-bottom: 1px solid var(--border-subtle);
}
.nc-sh-bracket {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78rem;
    color: var(--brand-primary);
    opacity: 0.55;
    flex-shrink: 0;
}
.nc-sh-dash {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.6rem;
    color: var(--text-muted);
    flex-shrink: 0;
}
.nc-sh-text {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.66rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.2em;
    flex: 1;
}
.nc-sh-ts {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.52rem;
    color: var(--text-muted);
    letter-spacing: 0.06em;
    opacity: 0.6;
}

/* ── LABEL ── */
.nc-label {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.58rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.16em;
    margin-bottom: 4px;
}

/* ── REGIME / STATUS BADGES — angled Stark style ── */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 12px;
    border-radius: 2px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    clip-path: polygon(6px 0, 100% 0, calc(100% - 6px) 100%, 0 100%);
}
.badge-bull    { background: rgba(0,214,143,0.12); color: #00d68f; border: 1px solid rgba(0,214,143,0.32); }
.badge-bear    { background: rgba(230,57,70,0.12);  color: #ff6b60; border: 1px solid rgba(230,57,70,0.32); }
.badge-neutral { background: rgba(255,179,0,0.12);  color: #FFB300; border: 1px solid rgba(255,179,0,0.32); }
.badge-a       { background: rgba(0,214,143,0.12); color: #00d68f; border: 1px solid rgba(0,214,143,0.32); }
.badge-b       { background: rgba(255,179,0,0.12);  color: #FFB300; border: 1px solid rgba(255,179,0,0.32); }
.badge-c       { background: rgba(230,57,70,0.12);  color: #ff6b60; border: 1px solid rgba(230,57,70,0.32); }

/* ── STAT ROW ── */
.stat-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 0;
    border-bottom: 1px solid var(--border-subtle);
}
.stat-row:last-child { border-bottom: none; }
.stat-key   { font-family: 'Share Tech Mono', monospace; font-size: 0.7rem; color: var(--text-secondary); letter-spacing: 0.06em; }
.stat-val   { font-family: 'Share Tech Mono', monospace; font-size: 0.78rem; color: var(--text-primary); }
.stat-green { color: #00d68f; }
.stat-red   { color: #e63946; }
.stat-gold  { color: #FFB300; }

/* ── HUD HEADER BAR ── */
.nc-hud-bar {
    background: rgba(5,14,28,0.97);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    margin-bottom: 16px;
    padding: 12px 20px;
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(10px);
    box-shadow: 0 4px 28px rgba(0,0,0,0.6), inset 0 1px 0 rgba(0,200,255,0.07);
}
/* Energy stripe — red · blue · gold (Iron Man suit colors) */
.nc-hud-bar::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(
        90deg,
        #E63946 0%,
        #E63946 8%,
        transparent 8%,
        transparent 10%,
        var(--brand-primary) 10%,
        var(--brand-primary) 55%,
        transparent 55%,
        transparent 57%,
        var(--color-gold) 57%,
        var(--color-gold) 100%
    );
    opacity: 0.65;
}
/* Bottom scanning line */
.nc-hud-bar::after {
    content: "";
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,200,255,0.2) 50%, transparent);
}

/* ── SYSTEM STATUS DOT ── */
.sys-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}
.sys-dot-green {
    background: #00d68f;
    box-shadow: 0 0 8px #00d68f;
    animation: arc-pulse 2.2s ease-in-out infinite;
}
.sys-dot-amber {
    background: #FFB300;
    box-shadow: 0 0 8px #FFB300;
    animation: arc-pulse 1.5s ease-in-out infinite;
}
.sys-dot-red {
    background: #e63946;
    box-shadow: 0 0 8px #e63946;
    animation: arc-pulse 0.7s ease-in-out infinite;
}

/* ── ARC REACTOR PULSE ── */
@keyframes arc-pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 8px currentColor; }
    50%       { opacity: 0.3; box-shadow: 0 0 2px currentColor; }
}

/* ── REACTOR SPIN (logo outer ring) ── */
@keyframes reactor-spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
}

/* ── TARGET LOCK (scan button ripple) ── */
@keyframes target-lock {
    0%   { box-shadow: 0 0 0 0 rgba(0,200,255,0.6); }
    70%  { box-shadow: 0 0 0 12px rgba(0,200,255,0); }
    100% { box-shadow: 0 0 0 0 rgba(0,200,255,0); }
}
.btn-target-lock {
    animation: target-lock 1.5s ease-out infinite !important;
}

/* ── PLOTLY CHARTS ── */
.js-plotly-plot .plotly .bg { fill: transparent !important; }

/* ── FOOTER ── */
.nc-footer {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.56rem;
    color: var(--text-muted);
    text-align: center;
    letter-spacing: 0.1em;
    padding-top: 8px;
    border-top: 1px solid var(--border-subtle);
    line-height: 2.2;
    opacity: 0.75;
}

/* Streamlit overrides */
.stMarkdown { margin-bottom: 0 !important; }
div[data-testid="column"] { padding: 0 5px !important; }

@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.25; } }
@keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0.25; } }

/* ── POWER METER BAR ── */
.power-meter {
    height: 2px;
    border-radius: 1px;
    background: linear-gradient(90deg, var(--brand-primary) var(--pct,80%), rgba(0,200,255,0.07) var(--pct,80%));
    margin-top: 3px;
}
</style>
"""


# ─────────────────────────────────────────────────────────────────
# ARC REACTOR LOGO SVG
# ─────────────────────────────────────────────────────────────────

_NC_LOGO_SVG = """
<svg width="44" height="44" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Outer ring -->
  <circle cx="22" cy="22" r="20" fill="none" stroke="rgba(0,200,255,0.28)" stroke-width="0.75"/>
  <!-- Cardinal tick marks -->
  <line x1="22" y1="2"  x2="22" y2="7"  stroke="#00c8ff" stroke-width="2"   stroke-linecap="round"/>
  <line x1="42" y1="22" x2="37" y2="22" stroke="#00c8ff" stroke-width="2"   stroke-linecap="round"/>
  <line x1="22" y1="42" x2="22" y2="37" stroke="#00c8ff" stroke-width="2"   stroke-linecap="round"/>
  <line x1="2"  y1="22" x2="7"  y2="22" stroke="#00c8ff" stroke-width="2"   stroke-linecap="round"/>
  <!-- Diagonal ticks -->
  <line x1="36.6" y1="7.4"  x2="33.4" y2="10.6" stroke="#FFB300" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="36.6" y1="36.6" x2="33.4" y2="33.4" stroke="#FFB300" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="7.4"  y1="36.6" x2="10.6" y2="33.4" stroke="#FFB300" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="7.4"  y1="7.4"  x2="10.6" y2="10.6" stroke="#FFB300" stroke-width="1.3" stroke-linecap="round"/>
  <!-- Middle dashed ring -->
  <circle cx="22" cy="22" r="14" fill="none" stroke="rgba(0,200,255,0.45)" stroke-width="1.2" stroke-dasharray="3.8 2.2"/>
  <!-- Arc reactor triangle — Iron Man Mark II core -->
  <polygon points="22,12 31,28 13,28" fill="rgba(0,200,255,0.07)" stroke="#00c8ff" stroke-width="1.6" stroke-linejoin="round"/>
  <!-- Inner ring -->
  <circle cx="22" cy="22" r="6" fill="rgba(0,200,255,0.1)" stroke="#00c8ff" stroke-width="1.5"/>
  <!-- Core -->
  <circle cx="22" cy="22" r="3.2" fill="#00c8ff"/>
  <!-- Pulsing ring -->
  <circle cx="22" cy="22" r="3.2" fill="none" stroke="rgba(0,200,255,0.7)" stroke-width="0.8">
    <animate attributeName="r" values="3.2;10;3.2" dur="3.8s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.7;0;0.7" dur="3.8s" repeatCount="indefinite"/>
  </circle>
</svg>"""


# ─────────────────────────────────────────────────────────────────
# HUD HEADER
# ─────────────────────────────────────────────────────────────────


def render_hud_header() -> None:
    now = now_ist()
    is_market = 9 <= now.hour < 16 and now.weekday() < 5
    mkt_color = "#00d68f" if is_market else "#234460"
    mkt_label = "MARKET OPEN" if is_market else "MARKET CLOSED"
    mkt_anim = "arc-pulse 2s ease-in-out infinite" if is_market else "none"
    threat_label = "LOW" if is_market else "STANDBY"
    threat_color = "#00d68f" if is_market else "#234460"
    uptime_str = f"{now.strftime('%H')}H {now.strftime('%M')}M"

    col_brand, col_vitals, col_right = st.columns([2, 3, 1])

    with col_brand:
        st.markdown(
            f'<div style="padding:10px 0 12px;border-bottom:1px solid rgba(0,200,255,0.07);">'
            f'<div style="display:flex;align-items:center;gap:14px;">'
            f"<div>{_NC_LOGO_SVG}</div>"
            f"<div>"
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.45rem;'
            f'color:rgba(255,179,0,0.55);letter-spacing:0.3em;text-transform:uppercase;">NEURA CAPITAL</div>'
            f'<div style="font-family:Orbitron,sans-serif;font-size:1.2rem;font-weight:900;'
            f"color:#00c8ff;letter-spacing:0.28em;"
            f'text-shadow:0 0 28px rgba(0,200,255,0.65),0 0 60px rgba(0,200,255,0.2);">A·X·I·O·M</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.47rem;'
            f'color:rgba(0,200,255,0.32);letter-spacing:0.14em;margin-top:1px;">ADVANCED EXPERT INTELLIGENCE FOR OPERATIONS IN MARKET</div>'
            f"</div></div></div>",
            unsafe_allow_html=True,
        )

    with col_vitals:
        st.markdown(
            f'<div style="padding:10px 16px 12px;border-bottom:1px solid rgba(0,200,255,0.07);'
            f'border-left:1px solid rgba(0,200,255,0.06);border-right:1px solid rgba(0,200,255,0.06);">'
            f'<div style="display:flex;gap:24px;align-items:center;justify-content:center;">'
            # ARC POWER
            f'<div style="text-align:center;">'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.5rem;color:#234460;letter-spacing:0.14em;text-transform:uppercase;">ARC POWER</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.95rem;color:#00c8ff;line-height:1.2;">94%</div>'
            f'<div style="height:2px;width:44px;background:linear-gradient(90deg,#00c8ff 94%,rgba(0,200,255,0.1) 94%);border-radius:1px;margin-top:3px;"></div>'
            f"</div>"
            # DIVIDER
            f'<div style="width:1px;height:28px;background:rgba(0,200,255,0.07);"></div>'
            # UPTIME
            f'<div style="text-align:center;">'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.5rem;color:#234460;letter-spacing:0.14em;text-transform:uppercase;">SESSION</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.95rem;color:#5a94bc;line-height:1.2;">{uptime_str}</div>'
            f'<div style="height:2px;width:44px;background:rgba(90,148,188,0.3);border-radius:1px;margin-top:3px;"></div>'
            f"</div>"
            # DIVIDER
            f'<div style="width:1px;height:28px;background:rgba(0,200,255,0.07);"></div>'
            # UNIVERSE
            f'<div style="text-align:center;">'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.5rem;color:#234460;letter-spacing:0.14em;text-transform:uppercase;">UNIVERSE</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.95rem;color:#5a94bc;line-height:1.2;">510 SYM</div>'
            f'<div style="height:2px;width:44px;background:rgba(90,148,188,0.3);border-radius:1px;margin-top:3px;"></div>'
            f"</div>"
            # DIVIDER
            f'<div style="width:1px;height:28px;background:rgba(0,200,255,0.07);"></div>'
            # THREAT
            f'<div style="text-align:center;">'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.5rem;color:#234460;letter-spacing:0.14em;text-transform:uppercase;">THREAT LVL</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.95rem;color:{threat_color};line-height:1.2;">{threat_label}</div>'
            f'<div style="height:2px;width:44px;background:{threat_color};opacity:0.4;border-radius:1px;margin-top:3px;"></div>'
            f"</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    with col_right:
        st.markdown(
            f'<div style="padding:10px 0 12px;border-bottom:1px solid rgba(0,200,255,0.07);text-align:right;">'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:1.5rem;color:#c8e8ff;line-height:1;letter-spacing:0.04em;">'
            f'{now.strftime("%H:%M")}<span style="color:#234460;font-size:0.95rem;">:{now.strftime("%S")}</span></div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.5rem;color:#234460;margin-top:2px;letter-spacing:0.1em;">'
            f"{now.strftime('%a %d %b %Y')} · IST</div>"
            f'<div style="display:inline-flex;align-items:center;gap:5px;margin-top:7px;'
            f"background:rgba(0,0,0,0.45);border:1px solid rgba({'0,214,143' if is_market else '35,68,96'},0.22);"
            f'border-radius:2px;padding:3px 10px;clip-path:polygon(4px 0,100% 0,calc(100% - 4px) 100%,0 100%);">'
            f'<span style="display:inline-block;width:5px;height:5px;border-radius:50%;'
            f"background:{mkt_color};box-shadow:0 0 6px {mkt_color};"
            f'animation:{mkt_anim};"></span>'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.58rem;'
            f'color:{mkt_color};letter-spacing:0.1em;">{mkt_label}</span>'
            f"</div></div>",
            unsafe_allow_html=True,
        )


def nc_card(content_html: str) -> None:
    st.markdown(
        f'<div class="nc-card">'
        f'<span class="nc-corner nc-tl"></span><span class="nc-corner nc-tr"></span>'
        f'<span class="nc-corner nc-bl"></span><span class="nc-corner nc-br"></span>'
        f"{content_html}</div>",
        unsafe_allow_html=True,
    )


def section_header(text: str, icon: str = "") -> None:
    ts = f"ID:{int(time.time()) % 100000:05d}"
    st.markdown(
        f'<div class="nc-section-header">'
        f'<span class="nc-sh-bracket">[</span>'
        f'<span class="nc-sh-dash">──</span>'
        f'<div class="nc-sh-text">{text}</div>'
        f'<span class="nc-sh-dash">──</span>'
        f'<span class="nc-sh-bracket">]</span>'
        f'<span class="nc-sh-ts">&nbsp;&nbsp;{ts}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────
# PLOTLY CHART THEME
# ─────────────────────────────────────────────────────────────────

_CHART_GRID = "rgba(0,200,255,0.06)"
_CHART_LINE = "rgba(0,200,255,0.14)"
_CHART_TICK = "#5a94bc"
_CHART_TEXT = "#c8e8ff"
_CHART_FONT = "Share Tech Mono"
_BULL_COLOR = "#00d68f"
_BEAR_COLOR = "#e63946"
_ACCENT_COLOR = "#00c8ff"
_GOLD_COLOR = "#FFB300"

PLOTLY_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(5,14,28,0.65)",
    "font": {"family": _CHART_FONT, "color": _CHART_TEXT, "size": 11},
    "xaxis": {
        "gridcolor": _CHART_GRID,
        "linecolor": _CHART_LINE,
        "tickfont": {"color": _CHART_TICK, "size": 10},
        "zerolinecolor": _CHART_GRID,
        "showgrid": True,
    },
    "yaxis": {
        "gridcolor": _CHART_GRID,
        "linecolor": _CHART_LINE,
        "tickfont": {"color": _CHART_TICK, "size": 10},
        "zerolinecolor": _CHART_GRID,
        "showgrid": True,
    },
    "margin": {"l": 48, "r": 16, "t": 44, "b": 36},
    "legend": {
        "bgcolor": "rgba(5,14,28,0.85)",
        "bordercolor": _CHART_LINE,
        "borderwidth": 1,
        "font": {"color": _CHART_TICK, "size": 10},
    },
}


def candlestick_chart(df: pd.DataFrame, symbol: str) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.72, 0.28],
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            increasing={"line": {"color": _BULL_COLOR, "width": 1}, "fillcolor": "rgba(0,214,143,0.18)"},
            decreasing={"line": {"color": _BEAR_COLOR, "width": 1}, "fillcolor": "rgba(230,57,70,0.18)"},
        ),
        row=1,
        col=1,
    )
    if "ema_9" in df.columns:
        for period, color in [(9, "#00c8ff"), (21, "#0ea5e9"), (50, "#FFB300"), (200, "#e63946")]:
            col = f"ema_{period}"
            if col in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=df[col],
                        name=f"EMA{period}",
                        line={"color": color, "width": 1},
                        opacity=0.85,
                    ),
                    row=1,
                    col=1,
                )
    vol_colors = [
        "rgba(0,214,143,0.42)" if c >= o else "rgba(230,57,70,0.42)"
        for c, o in zip(df["close"], df["open"], strict=False)
    ]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["volume"],
            name="Volume",
            marker={"color": vol_colors},
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    layout = PLOTLY_LAYOUT.copy()
    layout["title"] = {
        "text": f"<b>{symbol}</b>  ·  PRICE ACTION",
        "font": {"family": "Orbitron", "color": _ACCENT_COLOR, "size": 12},
        "x": 0.02,
    }
    layout["xaxis2"] = layout["xaxis"].copy()
    layout["yaxis2"] = layout["yaxis"].copy()
    fig.update_layout(**layout)
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def pnl_equity_curve(trades: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=trades.index,
            y=trades["cum_pnl"],
            fill="tozeroy",
            fillcolor="rgba(0,200,255,0.07)",
            line={"color": "#00c8ff", "width": 2},
            name="Equity Curve",
        )
    )
    fig.add_hline(y=0, line={"color": _CHART_LINE, "dash": "dot", "width": 1})
    layout = PLOTLY_LAYOUT.copy()
    layout["title"] = {
        "text": "CUMULATIVE P&L — EQUITY CURVE",
        "font": {"family": "Orbitron", "color": _ACCENT_COLOR, "size": 12},
        "x": 0.02,
    }
    fig.update_layout(**layout)
    return fig


def score_bar_chart(results: pd.DataFrame) -> go.Figure:
    top = results.sort_values("score", ascending=False).head(20)
    colors = [_BULL_COLOR if s >= 75 else _GOLD_COLOR if s >= 55 else _BEAR_COLOR for s in top["score"]]
    fig = go.Figure(
        go.Bar(
            x=top["symbol"],
            y=top["score"],
            marker={"color": colors, "opacity": 0.82, "line": {"color": "rgba(0,0,0,0)"}},
            text=top["score"].round(1),
            textposition="outside",
            textfont={"color": _CHART_TEXT, "size": 9},
        )
    )
    fig.add_hline(y=75, line={"color": _BULL_COLOR, "dash": "dash", "width": 1}, annotation_text="GRADE A")
    fig.add_hline(y=55, line={"color": _GOLD_COLOR, "dash": "dash", "width": 1}, annotation_text="GRADE B")
    layout = PLOTLY_LAYOUT.copy()
    layout["title"] = {
        "text": "TARGET SCORES  ·  TOP 20 CANDIDATES",
        "font": {"family": "Orbitron", "color": _ACCENT_COLOR, "size": 12},
        "x": 0.02,
    }
    layout["yaxis"] = dict(**layout["yaxis"], range=[0, 112])
    fig.update_layout(**layout)
    return fig


# ─────────────────────────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────────────────────────


def _regime_badge(regime: str) -> str:
    config = {
        "BULLISH": ("badge badge-bull", "BULLISH", "THREAT: LOW", "#00d68f"),
        "BEARISH": ("badge badge-bear", "BEARISH", "THREAT: CRITICAL", "#e63946"),
        "NEUTRAL": ("badge badge-neutral", "NEUTRAL", "THREAT: ELEVATED", "#FFB300"),
    }
    css, label, threat, t_col = config.get(regime, ("badge badge-neutral", regime, "THREAT: UNKNOWN", "#5a94bc"))
    return (
        f'<span class="{css}">{label}</span>'
        f"&nbsp;&nbsp;"
        f'<span style="font-family:Share Tech Mono,monospace;font-size:0.58rem;'
        f'color:{t_col};letter-spacing:0.14em;opacity:0.85;">{threat}</span>'
    )


# ── Cached data fetchers (TTL avoids re-fetching on every interaction) ──
@st.cache_data(ttl=120, show_spinner=False)
def _cx_indices():
    return fetch_indices()


@st.cache_data(ttl=120, show_spinner=False)
def _cx_gainers():
    return fetch_gainers_losers("NIFTY", 6)


@st.cache_data(ttl=300, show_spinner=False)
def _cx_news():
    return fetch_market_news(20)


@st.cache_data(ttl=900, show_spinner=False)
def _cx_calendar():
    return fetch_calendar(14)


@st.cache_data(ttl=600, show_spinner=False)
def _cx_fii():
    return fetch_fii_dii()


def _index_strip(indices: list[dict]) -> str:
    if not indices:
        return (
            '<div style="color:var(--text-muted);font-family:Share Tech Mono,monospace;'
            'font-size:0.7rem;padding:8px;">Index feed unavailable.</div>'
        )
    chips = []
    for i in indices:
        up = i["pct"] >= 0
        col = "#00d68f" if up else "#e63946"
        arrow = "▲" if up else "▼"
        chips.append(
            f'<div style="flex:1;min-width:150px;background:rgba(8,21,38,0.7);'
            f"border:1px solid rgba(0,200,255,0.10);border-left:2px solid {col};"
            f'border-radius:5px;padding:9px 13px;">'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.58rem;'
            f'color:var(--text-secondary);letter-spacing:0.12em;">{i["name"]}</div>'
            f'<div style="font-family:Orbitron,sans-serif;font-size:1.02rem;font-weight:700;'
            f'color:var(--text-primary);margin-top:3px;">{i["last"]:,.2f}</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.68rem;color:{col};'
            f'margin-top:2px;">{arrow} {i["change"]:+,.2f} ({i["pct"]:+.2f}%)</div>'
            f"</div>"
        )
    return f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">{"".join(chips)}</div>'


def _movers_table(rows: list[dict], up: bool) -> str:
    col = "#00d68f" if up else "#e63946"
    if not rows:
        return (
            '<div style="color:var(--text-muted);font-family:Share Tech Mono,monospace;'
            'font-size:0.66rem;padding:10px;">No data (market closed?).</div>'
        )
    out = []
    for r in rows:
        out.append(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:5px 8px;border-bottom:1px solid rgba(0,200,255,0.05);">'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.72rem;'
            f'color:var(--text-primary);">{r["symbol"]}</span>'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.68rem;'
            f'color:var(--text-secondary);">₹{r["ltp"]:,.1f}</span>'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.7rem;'
            f'color:{col};min-width:58px;text-align:right;">{r["pct"]:+.2f}%</span>'
            f"</div>"
        )
    return "".join(out)


def _news_panel(news: list[dict]) -> str:
    if not news:
        return (
            '<div style="color:var(--text-muted);font-family:Share Tech Mono,monospace;'
            'font-size:0.7rem;padding:10px;">News feed unavailable.</div>'
        )
    items = []
    for n in news:
        link = n.get("link") or "#"
        items.append(
            f'<a href="{link}" target="_blank" style="text-decoration:none;display:block;'
            f'padding:7px 4px;border-bottom:1px solid rgba(0,200,255,0.05);">'
            f'<div style="font-family:Inter,sans-serif;font-size:0.76rem;color:var(--text-primary);'
            f'line-height:1.35;">{n["title"]}</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.56rem;'
            f'color:var(--text-muted);margin-top:3px;letter-spacing:0.05em;">'
            f"{n['source']} · {n['published_str']}</div></a>"
        )
    return f'<div style="max-height:430px;overflow-y:auto;padding-right:4px;">{"".join(items)}</div>'


def _calendar_panel(cal: dict) -> str:
    out = ['<div style="max-height:430px;overflow-y:auto;padding-right:4px;">']
    macro = cal.get("macro", [])
    if macro:
        out.append('<div class="nc-label" style="margin:2px 0 6px;">MACRO &amp; MARKET</div>')
        for e in macro:
            ic = {"HIGH": "#e63946", "MED": "#FFB300"}.get(e.get("impact"), "#5a94bc")
            out.append(
                f'<div style="padding:5px 4px;border-bottom:1px solid rgba(0,200,255,0.05);">'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<span style="font-family:Inter,sans-serif;font-size:0.74rem;color:var(--text-primary);">{e["event"]}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:0.62rem;color:{ic};">{e["date_str"]}</span></div>'
                f'<div style="font-family:Share Tech Mono,monospace;font-size:0.55rem;color:var(--text-muted);margin-top:2px;">{e["note"]}</div>'
                f"</div>"
            )
    corp = cal.get("corporate", [])
    out.append('<div class="nc-label" style="margin:12px 0 6px;">RESULTS &amp; BOARD MEETINGS</div>')
    if corp:
        for e in corp:
            out.append(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:5px 4px;border-bottom:1px solid rgba(0,200,255,0.05);">'
                f'<div><span style="font-family:Share Tech Mono,monospace;font-size:0.72rem;color:var(--text-primary);">{e["symbol"]}</span>'
                f'<span style="font-family:Inter,sans-serif;font-size:0.6rem;color:var(--text-muted);margin-left:6px;">{e["purpose"]}</span></div>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:0.62rem;color:var(--text-gold);">{e["date_str"]}</span></div>'
            )
    else:
        out.append(
            '<div style="color:var(--text-muted);font-family:Share Tech Mono,monospace;font-size:0.64rem;padding:6px;">No upcoming events.</div>'
        )
    out.append("</div>")
    return "".join(out)


def show_overview() -> None:
    # ── LIVE INDEX STRIP ──
    section_header("Market Pulse — Live Indices")
    indices = _cx_indices()
    st.markdown(_index_strip(indices), unsafe_allow_html=True)

    # ── REGIME + FII/DII + BREADTH ──
    rc1, rc2, rc3 = st.columns([1.4, 1, 1])
    with rc1:
        regime: RegimeResult | None = st.session_state.get("regime")
        if st.button("◈ SCAN REGIME"):
            with st.spinner("Classifying Nifty regime..."):
                regime = classify_regime()
                st.session_state["regime"] = regime
        if regime:
            badge = _regime_badge(regime.regime)
            nc_card(
                f'<div class="nc-label">MARKET REGIME</div><div style="margin:8px 0;">{badge}</div>'
                f'<div style="font-family:Share Tech Mono,monospace;font-size:0.68rem;color:var(--text-secondary);">'
                f"ADX {regime.adx_value:.1f} · Max Pos {regime.max_positions} · Min R:R {regime.min_rr}:1</div>"
            )
        else:
            nc_card(
                '<div class="nc-label">MARKET REGIME</div>'
                '<div style="font-family:Share Tech Mono,monospace;font-size:0.7rem;color:var(--text-muted);margin-top:8px;">Click SCAN REGIME.</div>'
            )
    with rc2:
        fii = _cx_fii()
        if fii.get("available"):
            fnet = fii.get("fii", {}).get("net", 0)
            dnet = fii.get("dii", {}).get("net", 0)
            fc = "#00d68f" if fnet >= 0 else "#e63946"
            dc = "#00d68f" if dnet >= 0 else "#e63946"
            nc_card(
                f'<div class="nc-label">FII / DII FLOWS (₹ Cr) · {fii.get("date", "")}</div>'
                f'<div style="display:flex;gap:18px;margin-top:8px;">'
                f'<div><div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;color:var(--text-secondary);">FII</div>'
                f'<div style="font-family:Orbitron;font-size:0.92rem;color:{fc};">{fnet:+,.0f}</div></div>'
                f'<div><div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;color:var(--text-secondary);">DII</div>'
                f'<div style="font-family:Orbitron;font-size:0.92rem;color:{dc};">{dnet:+,.0f}</div></div></div>'
            )
        else:
            nc_card(
                '<div class="nc-label">FII / DII FLOWS</div><div style="font-family:Share Tech Mono,monospace;font-size:0.66rem;color:var(--text-muted);margin-top:8px;">Confirm manually.</div>'
            )
    with rc3:
        gl = _cx_gainers()
        if gl.get("available"):
            nc_card(
                f'<div class="nc-label">NIFTY BREADTH</div>'
                f'<div style="display:flex;gap:14px;margin-top:8px;">'
                f'<div><div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;color:var(--text-secondary);">Gainers</div>'
                f'<div style="font-family:Orbitron;font-size:0.92rem;color:#00d68f;">{len(gl.get("gainers", []))}+</div></div>'
                f'<div><div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;color:var(--text-secondary);">Losers</div>'
                f'<div style="font-family:Orbitron;font-size:0.92rem;color:#e63946;">{len(gl.get("losers", []))}+</div></div></div>'
            )
        else:
            nc_card(
                '<div class="nc-label">NIFTY BREADTH</div><div style="font-family:Share Tech Mono,monospace;font-size:0.66rem;color:var(--text-muted);margin-top:8px;">Market closed.</div>'
            )

    # ── MAIN GRID: NEWS | GAINERS/LOSERS | CALENDAR ──
    st.markdown("<br>", unsafe_allow_html=True)
    g_news, g_mid, g_cal = st.columns([1.25, 1.5, 1.25])

    with g_news:
        section_header("Market News")
        nc_card(_news_panel(_cx_news()))

    with g_mid:
        section_header("Top Gainers & Losers · NIFTY")
        gl = _cx_gainers()
        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown(
                '<div class="nc-label" style="color:#00d68f;margin-bottom:4px;">▲ GAINERS</div>', unsafe_allow_html=True
            )
            st.markdown(
                f'<div class="nc-card" style="padding:6px;">{_movers_table(gl.get("gainers", []), True)}</div>',
                unsafe_allow_html=True,
            )
        with mc2:
            st.markdown(
                '<div class="nc-label" style="color:#e63946;margin-bottom:4px;">▼ LOSERS</div>', unsafe_allow_html=True
            )
            st.markdown(
                f'<div class="nc-card" style="padding:6px;">{_movers_table(gl.get("losers", []), False)}</div>',
                unsafe_allow_html=True,
            )
        if st.button("↻ Refresh market data"):
            _cx_indices.clear()
            _cx_gainers.clear()
            _cx_fii.clear()
            st.rerun()

    with g_cal:
        section_header("Economic & Events Calendar")
        nc_card(_calendar_panel(_cx_calendar()))

    # ── PRICE CHART ──
    st.markdown("<br>", unsafe_allow_html=True)
    section_header("Price Action Terminal — OHLCV Analysis")
    universe = load_universe()
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        symbol = st.selectbox("SYMBOL", universe["symbol"].tolist(), index=0)
    with c2:
        period = st.selectbox("PERIOD", ["1mo", "3mo", "6mo", "1y"], index=2)
    with c3:
        interval = st.selectbox("INTERVAL", ["1d", "1wk"], index=0)

    if st.button("◈ LOAD CHART"):
        with st.spinner("Fetching OHLCV data..."):
            history = fetch_symbol_history(symbol, period=period, interval=interval)
            if not history.empty:
                st.plotly_chart(candlestick_chart(history, symbol), use_container_width=True)
            else:
                st.warning("No data returned for this symbol.")

    # ── AI BRIEFING ──
    st.markdown("<br>", unsafe_allow_html=True)
    section_header("AI Morning Briefing — AXIOM Intelligence")

    col_gen, col_full, col_email = st.columns(3)

    if col_gen.button("◈ QUICK BRIEFING"):
        with st.spinner("Fetching live market data..."):
            context = build_briefing_context()
            context["symbol_count"] = len(universe)
            context["watchlist_count"] = min(10, len(universe))
        with st.spinner("AXIOM writing briefing..."):
            briefing = generate_market_briefing(context)
        st.session_state["last_briefing"] = briefing
        st.session_state["last_briefing_context"] = context

    if col_full.button("◈ FULL PIPELINE"):
        with st.spinner("Step 1/4 — Classifying market regime..."):
            from screener.regime_classifier import classify_regime

            regime_obj = classify_regime()
        with st.spinner("Step 2/4 — Fetching market context..."):
            context = build_briefing_context()
            context["symbol_count"] = len(universe)
            context["regime"] = regime_obj.regime
            context["nifty_close"] = regime_obj.nifty_close
            context["adx"] = regime_obj.adx_value
            context["ema50"] = regime_obj.ema50
            context["ema200"] = regime_obj.ema200
        with st.spinner("Step 3/4 — Running screener for top picks..."):
            try:
                screener_df = run_screener(None)
                if not screener_df.empty:
                    top_picks = screener_df[screener_df["grade"].isin(["A", "B"])].head(5)
                    context["top_picks"] = top_picks[
                        [c for c in ["symbol", "score", "grade", "rs_20d", "rs_60d", "close"] if c in top_picks.columns]
                    ].to_dict("records")
                    st.session_state["screener_results"] = screener_df
            except Exception as exc:
                logger.warning("Screener skipped in pipeline: {}", exc)
                context["top_picks"] = []
        with st.spinner("Step 4/4 — AXIOM writing briefing..."):
            briefing = generate_market_briefing(context)
        st.session_state["last_briefing"] = briefing
        st.session_state["last_briefing_context"] = context
        pdf_path = REPORTS_DIR / f"briefing_{now_ist().strftime('%Y%m%d')}.pdf"
        generate_text_report("AXIOM Morning Briefing", briefing, pdf_path)
        st.success(f"Full pipeline complete. PDF saved: {pdf_path.name}")

    briefing = st.session_state.get("last_briefing", "")
    if briefing:
        st.text_area("", briefing, height=360, label_visibility="collapsed")

    if col_email.button("◈ SEND PDF TO TELEGRAM"):
        briefing = st.session_state.get("last_briefing")
        if not briefing:
            st.warning("Generate a briefing first.")
        else:
            from monitors.telegram_bot import send_document

            with st.spinner("Sending PDF to Telegram..."):
                pdf_path = REPORTS_DIR / f"briefing_{now_ist().strftime('%Y%m%d')}.pdf"
                generate_text_report("AXIOM Morning Briefing", briefing, pdf_path)
                ok, err = send_document(
                    pdf_path,
                    caption=f"📊 <b>AXIOM Morning Briefing — {now_ist().strftime('%d %b %Y')}</b>",
                )
            st.success("Briefing PDF sent to Telegram.") if ok else st.error(f"Telegram send failed: {err}")


def show_screener() -> None:
    section_header("Target Acquisition — NSE Universe Scanner")

    _col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("◈ ACQUIRE TARGETS"):
            with st.spinner("Scanning universe..."):
                results = run_screener(None)
                st.session_state["screener_results"] = results

    results: pd.DataFrame = st.session_state.get("screener_results", pd.DataFrame())

    if not results.empty:
        grade_a = results[results["grade"] == "A"] if "grade" in results.columns else results[results["score"] >= 75]
        grade_b = (
            results[results["grade"] == "B"]
            if "grade" in results.columns
            else results[(results["score"] >= 55) & (results["score"] < 75)]
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("TOTAL CANDIDATES", len(results))
        c2.metric("GRADE ALPHA", len(grade_a), delta=f"{len(grade_a) / len(results) * 100:.0f}%")
        c3.metric("GRADE BRAVO", len(grade_b))

        st.plotly_chart(score_bar_chart(results), use_container_width=True)

        section_header("Candidate Manifest")
        display_cols = [
            c
            for c in [
                "rank",
                "symbol",
                "grade",
                "score",
                "pa_score",
                "rs_score",
                "vol_score",
                "trend_score",
                "rs_20d",
                "rs_60d",
                "rsi",
                "adx",
                "volume_ratio",
                "close",
            ]
            if c in results.columns
        ]
        st.dataframe(results[display_cols], use_container_width=True, hide_index=True)

        section_header("Price Action Terminal")
        top_symbol = st.selectbox("SELECT TARGET", results["symbol"].tolist())
        if top_symbol:
            with st.spinner(f"Loading {top_symbol}..."):
                sym_history = fetch_symbol_history(top_symbol, period="3mo", interval="1d")
                if not sym_history.empty:
                    st.plotly_chart(candlestick_chart(sym_history, top_symbol), use_container_width=True)

        section_header("AXIOM Analyst Commentary")
        if st.button("◈ GENERATE COMMENTARY"):
            with st.spinner("AXIOM analysing candidates..."):
                commentary = generate_screener_commentary(results.head(10).to_dict(orient="records"))
            st.session_state["screener_commentary"] = commentary

        commentary = st.session_state.get("screener_commentary", "")
        if commentary:
            st.text_area("", commentary, height=280, label_visibility="collapsed")

        col_wl, col_pdf1 = st.columns(2)
        if col_wl.button("◈ SAVE ALPHA+BRAVO TO STRIKE LIST"):
            n = save_watchlist_from_screener(results)
            st.success(f"Saved {n} targets to strike list.")

        if col_pdf1.button("◈ EXPORT INTEL PDF"):
            regime_obj = st.session_state.get("regime")
            regime_str = regime_obj.regime if regime_obj else "UNKNOWN"
            with st.spinner("Generating PDF..."):
                pdf_path = REPORTS_DIR / f"screener_{now_ist().strftime('%Y%m%d_%H%M')}.pdf"
                generate_screener_pdf(results, commentary, pdf_path, regime=regime_str)
            st.success(f"Saved: {pdf_path.name}")

        section_header("Deep Target Analysis")
        analysis_symbol = st.selectbox("ANALYSE TARGET", results["symbol"].tolist(), key="analysis_sym")
        if st.button("◈ FULL ANALYSIS — 9 SECTIONS"):
            with st.spinner(f"Running analysis on {analysis_symbol}..."):
                hist = fetch_symbol_history(analysis_symbol, period="6mo", interval="1d")
                data = hist.tail(50).to_dict() if not hist.empty else {}
                analysis = generate_stock_analysis(analysis_symbol, data)
            st.text_area("", analysis, height=500, label_visibility="collapsed")

    else:
        st.markdown(
            '<div style="padding:32px;text-align:center;border:1px solid var(--border-default);'
            'border-radius:6px;background:rgba(8,21,38,0.6);">'
            '<div style="font-family:Share Tech Mono,monospace;font-size:0.9rem;'
            'color:var(--text-muted);letter-spacing:0.2em;">[ NO TARGETS ACQUIRED ]</div>'
            '<div style="font-family:Share Tech Mono,monospace;font-size:0.62rem;'
            'color:var(--text-muted);margin-top:8px;opacity:0.6;">Run scanner to acquire candidates.</div>'
            "</div>",
            unsafe_allow_html=True,
        )


def show_trade_journal() -> None:
    section_header("Mission Log — Trade Entry")

    prefill = st.session_state.pop("prefill_trade", {})
    regime_obj = st.session_state.get("regime")
    regime_default = regime_obj.regime if regime_obj else "BULLISH"

    with st.form("new_trade_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        symbol = c1.text_input("TARGET SYMBOL", value=prefill.get("symbol", ""))
        side = c2.selectbox("SIDE", ["LONG", "SHORT"])
        entry_price = c3.number_input("ENTRY PRICE", value=float(prefill.get("entry_price", 0.0)), format="%.2f")
        exit_price = c4.number_input("EXIT PRICE", value=0.0, format="%.2f")

        c5, c6, c7, c8 = st.columns(4)
        quantity = c5.number_input("QUANTITY", value=0, step=1)
        pnl = c6.number_input("P&L (₹)", value=0.0, format="%.2f")
        planned_sl = c7.number_input("PLANNED SL", value=float(prefill.get("stop", 0.0)), format="%.2f")
        planned_target = c8.number_input("PLANNED TARGET", value=float(prefill.get("target", 0.0)), format="%.2f")

        c9, c10, c11, c12 = st.columns(4)
        setup_type = c9.selectbox(
            "SETUP TYPE", ["Breakout", "Momentum Continuation", "BB Squeeze", "Reversal", "Other"]
        )
        session_type = c10.selectbox("SESSION", ["SWING", "INTRADAY"])
        regime_at_entry = c11.selectbox(
            "REGIME @ ENTRY",
            ["BULLISH", "NEUTRAL", "BEARISH"],
            index=["BULLISH", "NEUTRAL", "BEARISH"].index(regime_default)
            if regime_default in ["BULLISH", "NEUTRAL", "BEARISH"]
            else 0,
        )
        discipline_score = c12.slider("DISCIPLINE", 1, 10, 7)

        c13, c14 = st.columns(2)
        holding_period = c13.text_input("HOLDING PERIOD", value="1 day")
        notes = c14.text_area("MISSION NOTES", height=68)

        # Auto-compute actual R:R from entry/stop/exit
        actual_rr = 0.0
        if planned_sl and entry_price and entry_price != planned_sl:
            risk = abs(entry_price - planned_sl)
            if risk > 0 and exit_price:
                actual_rr = round(abs(exit_price - entry_price) / risk, 2)

        submitted = st.form_submit_button("◈ LOG MISSION")
        if submitted and symbol:
            append_trade_log(
                {
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "quantity": quantity,
                    "pnl": pnl,
                    "setup_type": setup_type,
                    "holding_period": holding_period,
                    "notes": notes,
                    "side": side,
                    "planned_sl": planned_sl,
                    "planned_target": planned_target,
                    "actual_rr": actual_rr,
                    "session_type": session_type,
                    "regime_at_entry": regime_at_entry,
                    "discipline_score": discipline_score,
                }
            )
            st.success(f"Mission logged: {symbol} | {side} | P&L ₹{pnl:,.2f} | R:R {actual_rr}")

    trades = load_trade_journal(200)

    if not trades.empty:
        trades["timestamp"] = pd.to_datetime(trades["created_at"])
        trades = trades.sort_values("timestamp").reset_index(drop=True)
        trades["cum_pnl"] = trades["pnl"].cumsum()

        metrics = generate_weekly_review(trades)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("TOTAL MISSIONS", metrics.get("total_trades", 0))
        c2.metric("WIN RATE", f"{metrics.get('win_rate', 0):.1f}%")
        c3.metric("TOTAL P&L", f"₹{metrics.get('total_pnl', 0):,.0f}")
        c4.metric("AVG P&L", f"₹{metrics.get('avg_pnl', 0):,.0f}")

        st.plotly_chart(pnl_equity_curve(trades.set_index("timestamp")), use_container_width=True)

        section_header("Mission History")
        display_cols = [
            c
            for c in [
                "symbol",
                "side",
                "setup_type",
                "entry_price",
                "exit_price",
                "quantity",
                "pnl",
                "actual_rr",
                "session_type",
                "regime_at_entry",
                "discipline_score",
                "holding_period",
                "created_at",
            ]
            if c in trades.columns
        ]
        st.dataframe(
            trades[display_cols].sort_values("created_at", ascending=False), use_container_width=True, hide_index=True
        )

        section_header("AXIOM Performance Review")
        col1, col2 = st.columns(2)
        if col1.button("◈ AI REVIEW"):
            with st.spinner("AXIOM reviewing missions..."):
                summary = generate_trade_journal_summary(trades.to_dict(orient="records"))
            st.text_area("", summary, height=260, label_visibility="collapsed")
        if col2.button("◈ EXPORT INTEL PDF"):
            path = generate_trade_journal_pdf(trades, REPORTS_DIR / "trade_journal.pdf")
            st.success(f"PDF exported: {path}")


def show_tasks() -> None:
    section_header("Briefing Dossier — Add Task")

    with st.form("task_form", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        task_label = c1.text_input("TASK")
        task_context = c2.text_area("CONTEXT", height=68)
        if st.form_submit_button("◈ ADD TO DOSSIER") and task_label:
            add_task(task_label, task_context)
            st.success("Task queued.")

    section_header("Active Task Queue")
    tasks = get_tasks()
    if tasks:
        task_df = pd.DataFrame(tasks)
        st.dataframe(task_df, use_container_width=True, hide_index=True)
    else:
        st.info("Dossier is empty.")

    section_header("AXIOM Checklist Generation")
    trades = load_trade_journal(50)
    if st.button("◈ GENERATE CHECKLIST"):
        with st.spinner("AXIOM building checklist..."):
            checklist = generate_task_list(
                {
                    "open_trades": len(trades),
                    "market": "NSE",
                    "time": now_ist().strftime("%H:%M IST"),
                    "date": now_ist().strftime("%d %b %Y"),
                }
            )
        st.text_area("", checklist, height=300, label_visibility="collapsed")


def show_watchlist() -> None:
    section_header("Strike List — Active Targets")
    entries = get_watchlist()

    if entries:
        df = pd.DataFrame(entries)
        c1, c2, c3 = st.columns(3)
        c1.metric("TOTAL TARGETS", len(df))
        c2.metric("ALPHA GRADE", len(df[df["grade"] == "A"]))
        c3.metric("BRAVO GRADE", len(df[df["grade"] == "B"]))

        display_cols = [
            c for c in ["symbol", "grade", "score", "rs_20d", "rs_60d", "close", "notes", "added_at"] if c in df.columns
        ]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        section_header("Manage Strike List")
        col_sym, col_btn = st.columns([2, 1])
        remove_sym = col_sym.selectbox("SELECT TARGET TO REMOVE", df["symbol"].tolist())
        if col_btn.button("◈ REMOVE"):
            remove_from_watchlist(remove_sym)
            st.success(f"Removed {remove_sym} from strike list.")
            st.rerun()

        section_header("Manual Entry")
        with st.form("manual_watchlist"):
            mc1, mc2, mc3, mc4 = st.columns(4)
            sym = mc1.text_input("SYMBOL")
            grade = mc2.selectbox("GRADE", ["A", "B"])
            score = mc3.number_input("SCORE", 0, 100, 65)
            close = mc4.number_input("PRICE", 0.0, format="%.2f")
            notes = st.text_input("NOTES")
            if st.form_submit_button("◈ ADD TO STRIKE LIST") and sym:
                add_to_watchlist(sym.upper(), grade, float(score), 0.0, 0.0, close, notes)
                st.success(f"Added {sym.upper()} to strike list.")
                st.rerun()
    else:
        st.markdown(
            '<div style="padding:32px;text-align:center;border:1px solid var(--border-default);'
            'border-radius:6px;background:rgba(8,21,38,0.6);">'
            '<div style="font-family:Share Tech Mono,monospace;font-size:0.9rem;'
            'color:var(--text-muted);letter-spacing:0.2em;">[ STRIKE LIST EMPTY ]</div>'
            '<div style="font-family:Share Tech Mono,monospace;font-size:0.62rem;'
            'color:var(--text-muted);margin-top:8px;opacity:0.6;">'
            "Run the scanner and save Grade A/B to populate targets.</div>"
            "</div>",
            unsafe_allow_html=True,
        )


def show_risk_calculator() -> None:
    section_header("Damage Assessment — Position Sizing")
    st.markdown(
        '<div style="font-family:Share Tech Mono,monospace;font-size:0.72rem;color:#5a94bc;'
        "margin-bottom:16px;padding:10px 14px;background:rgba(0,200,255,0.04);"
        'border:1px solid rgba(0,200,255,0.09);border-radius:4px;letter-spacing:0.06em;">'
        "FORMULA: Shares = (Capital × 2%) ÷ (Entry − Stop) &nbsp;·&nbsp; "
        "Max risk: 2% per trade &nbsp;·&nbsp; Min R:R: 2:1"
        "</div>",
        unsafe_allow_html=True,
    )

    regime_obj = st.session_state.get("regime")
    regime_str = regime_obj.regime if regime_obj else "BULLISH"

    with st.form("risk_form"):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("TARGET SYMBOL", value="")
        entry = c2.number_input("ENTRY PRICE (₹)", value=0.0, format="%.2f")
        stop = c3.number_input("STOP LOSS (₹)", value=0.0, format="%.2f")

        c4, c5, c6 = st.columns(3)
        target = c4.number_input("TARGET PRICE (₹)", value=0.0, format="%.2f")
        capital = c5.number_input("CAPITAL (₹)", value=100000.0, format="%.0f")
        regime_input = c6.selectbox(
            "REGIME", ["BULLISH", "NEUTRAL", "BEARISH"], index=["BULLISH", "NEUTRAL", "BEARISH"].index(regime_str)
        )

        submitted = st.form_submit_button("◈ CALCULATE")

    if submitted and entry > 0 and stop > 0:
        result = calculate_position(
            entry=entry,
            stop=stop,
            target=target,
            capital=capital,
            symbol=symbol.upper(),
            regime=regime_input,
        )

        verdict_color = "#00d68f" if result.passed else "#e63946"
        verdict_bg = "0,214,143" if result.passed else "230,57,70"
        st.markdown(
            f'<div style="background:rgba({verdict_bg},0.08);'
            f"border:1px solid {verdict_color};border-left:4px solid {verdict_color};"
            f"border-radius:4px;padding:12px 18px;margin:12px 0;"
            f'clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));">'
            f'<span style="font-family:Orbitron,sans-serif;font-size:1rem;'
            f'font-weight:700;color:{verdict_color};letter-spacing:0.15em;">'
            f"{result.verdict}</span></div>",
            unsafe_allow_html=True,
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("SHARES", f"{result.shares:,}")
        col2.metric("₹ AT RISK", f"₹{result.risk_amount:,.0f}", delta=f"{result.risk_pct:.2f}% of capital")
        col3.metric("R:R RATIO", f"{result.rr_ratio:.2f}:1")
        col4.metric("₹ REWARD", f"₹{result.reward:,.0f}")

        section_header("Trade Levels — Tactical Breakdown")
        kv_data = [
            ("Symbol", symbol.upper() or "—"),
            ("Entry", f"₹{result.entry:,.2f}"),
            (
                "Stop Loss",
                f"₹{result.stop:,.2f}  ({((result.entry - result.stop) / result.entry * 100):.2f}% below entry)",
            ),
            ("Target", f"₹{result.target:,.2f}" if result.target > 0 else "Not set"),
            ("Position Size", f"{result.shares:,} shares"),
            ("Capital at Risk", f"₹{result.risk_amount:,.2f}  ({result.risk_pct:.2f}%)"),
            ("Potential Reward", f"₹{result.reward:,.2f}" if result.reward > 0 else "—"),
            ("R:R Ratio", f"{result.rr_ratio:.2f}:1"),
            ("Regime", regime_input),
        ]
        st.markdown(
            '<div style="border:1px solid var(--border-default);border-radius:6px;overflow:hidden;margin-top:4px;">',
            unsafe_allow_html=True,
        )
        for i, (label, value) in enumerate(kv_data):
            bg = "rgba(255,255,255,0.012)" if i % 2 == 0 else "transparent"
            st.markdown(
                f'<div style="display:flex;align-items:center;padding:9px 16px;background:{bg};'
                f'border-bottom:1px solid var(--border-subtle);">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:0.68rem;'
                f"color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;"
                f'min-width:160px;">{label}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:0.8rem;'
                f'color:var(--text-primary);">{value}</span>'
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

        if result.rejection_reasons:
            section_header("Rejection Reasons")
            for r in result.rejection_reasons:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;padding:7px 12px;'
                    f"background:rgba(230,57,70,0.06);border:1px solid rgba(230,57,70,0.18);"
                    f'border-radius:4px;margin-bottom:4px;">'
                    f'<span style="color:#e63946;font-size:0.65rem;font-family:Share Tech Mono,monospace;">✕</span>'
                    f'<span style="font-family:Inter,sans-serif;font-size:0.76rem;color:#f87171;">{r}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

        if result.warnings:
            section_header("Warnings")
            for w in result.warnings:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;padding:7px 12px;'
                    f"background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.18);"
                    f'border-radius:4px;margin-bottom:4px;">'
                    f'<span style="color:#FFB300;font-size:0.65rem;font-family:Share Tech Mono,monospace;">⚠</span>'
                    f'<span style="font-family:Inter,sans-serif;font-size:0.76rem;color:#FFB300;">{w}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

        save_risk_calc(
            {
                "symbol": symbol.upper(),
                "entry": entry,
                "stop": stop,
                "target": target,
                "capital": capital,
                "shares": result.shares,
                "risk_amount": result.risk_amount,
                "risk_pct": result.risk_pct,
                "reward": result.reward,
                "rr_ratio": result.rr_ratio,
                "passed": result.passed,
            }
        )

        if result.passed:
            if st.button("◈ OPEN IN MISSION LOG"):
                st.session_state["prefill_trade"] = {
                    "symbol": symbol.upper(),
                    "entry_price": entry,
                    "quantity": result.shares,
                    "setup_type": "Breakout",
                }
                st.info("Trade pre-filled. Navigate to MISSION LOG to complete.")

    section_header("Recent Calculations")
    history = get_risk_history(10)
    if history:
        hist_df = pd.DataFrame(history)
        hist_df["passed"] = hist_df["passed"].map({True: "✓ PASS", False: "✗ FAIL"})
        display = [
            c
            for c in [
                "symbol",
                "entry",
                "stop",
                "target",
                "shares",
                "risk_amount",
                "risk_pct",
                "rr_ratio",
                "passed",
                "created_at",
            ]
            if c in hist_df.columns
        ]
        st.dataframe(hist_df[display], use_container_width=True, hide_index=True)


def show_monitor() -> None:
    """Tactical Feed — Live 15-min signal scanner."""
    from monitors.intraday_monitor import _compute_signals, _fetch_15m
    from monitors.telegram_bot import (
        delete_webhook,
        get_bot_info,
        get_updates_chat_id,
        is_configured,
        send_test_message,
    )

    section_header("Tactical Feed — 15-Min Signal Scanner")

    # Telegram status
    tg_ok = is_configured()
    tg_color = "#00d68f" if tg_ok else "#FFB300"
    tg_label = "COMMS: ONLINE" if tg_ok else "COMMS: PENDING VERIFICATION"
    col_tg, col_test, col_chatid = st.columns([3, 1, 1])
    col_tg.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;'
        f"background:rgba(0,0,0,0.3);border:1px solid rgba({'0,214,143' if tg_ok else '255,179,0'},0.2);"
        f'border-radius:3px;clip-path:polygon(6px 0,100% 0,calc(100% - 6px) 100%,0 100%);">'
        f'<span class="sys-dot {"sys-dot-green" if tg_ok else "sys-dot-amber"}"></span>'
        f'<span style="font-family:Share Tech Mono,monospace;font-size:0.68rem;color:{tg_color};letter-spacing:0.1em;">{tg_label}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    if tg_ok and col_test.button("◈ TEST COMMS"):
        ok, err = send_test_message()
        if ok:
            st.success("Test message sent to Telegram.")
        else:
            st.error(f"Send failed: {err}")
            st.info(
                "**Fix:** Open Telegram, find your bot, send `/start`\nThen click **◈ FIND CHAT ID** and update .env"
            )

    if col_chatid.button("◈ FIND CHAT ID"):
        bot_info, bot_err = get_bot_info()
        if bot_err:
            st.error(f"Token invalid: {bot_err}")
        else:
            st.success(f"Token valid — Bot: **@{bot_info.get('username')}**")
            delete_webhook()
            chat_id, err, _raw = get_updates_chat_id()
            if chat_id:
                st.success(f"Your Chat ID: **`{chat_id}`** → set `TELEGRAM_CHAT_ID={chat_id}` in .env")
            else:
                st.warning(f"{err}")
                st.markdown("**Steps:** Open Telegram → find your bot → send any message → click FIND CHAT ID again.")

    st.markdown(
        '<div style="height:1px;background:linear-gradient(90deg,transparent,'
        'rgba(0,200,255,0.15) 50%,transparent);margin:16px 0;"></div>',
        unsafe_allow_html=True,
    )

    try:
        from storage.db import create_connection

        conn = create_connection()
        import pandas as _pd

        wl_df = _pd.read_sql("SELECT symbol FROM watchlist", conn)
        conn.close()
        symbols = wl_df["symbol"].tolist()
    except Exception:
        symbols = []

    if not symbols:
        st.warning("Strike list is empty. Add stocks on the STRIKE LIST page first.")
        return

    col_info, col_btn = st.columns([3, 1])
    col_info.markdown(
        f'<span style="font-family:Share Tech Mono,monospace;font-size:0.75rem;color:#5a94bc;letter-spacing:0.08em;">'
        f'MONITORING <b style="color:#00c8ff;">{len(symbols)}</b> TARGETS ON 15-MIN TIMEFRAME</span>',
        unsafe_allow_html=True,
    )
    run_scan = col_btn.button("◈ SCAN NOW", use_container_width=True)

    if "monitor_results" not in st.session_state:
        st.session_state["monitor_results"] = {}
    if "monitor_scan_time" not in st.session_state:
        st.session_state["monitor_scan_time"] = None
    if "monitor_fired" not in st.session_state:
        st.session_state["monitor_fired"] = {}

    if run_scan:
        with st.spinner(f"Scanning {len(symbols)} targets on 15-min chart..."):
            results = {}
            for sym in symbols:
                df15 = _fetch_15m(sym)
                results[sym] = _compute_signals(df15) if not df15.empty else {"signals": [], "error": "no data"}

            for sym, data in results.items():
                if sym not in st.session_state["monitor_fired"]:
                    st.session_state["monitor_fired"][sym] = set()
                for sig in data.get("signals", []):
                    if sig not in st.session_state["monitor_fired"][sym]:
                        st.session_state["monitor_fired"][sym].add(sig)
                        from monitors.telegram_bot import send_alert

                        details = (
                            f"RSI: {data.get('rsi', '?')} · ADX: {data.get('adx', '?')} · "
                            f"Vol: {data.get('vol_ratio', '?')}x"
                        )
                        send_alert(sym, sig, data.get("close", 0), details)

            st.session_state["monitor_results"] = results
            st.session_state["monitor_scan_time"] = now_ist().strftime("%H:%M:%S")

    results = st.session_state["monitor_results"]
    scan_time = st.session_state.get("monitor_scan_time")

    if scan_time:
        st.markdown(
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;'
            f'color:var(--text-muted);letter-spacing:0.1em;margin-bottom:8px;">'
            f"LAST SCAN: {scan_time}</div>",
            unsafe_allow_html=True,
        )

    if not results:
        st.info("Click SCAN NOW to fetch live 15-min data for all watchlist targets.")
        return

    hits = {s: d for s, d in results.items() if d.get("signals")}
    {s: d for s, d in results.items() if not d.get("signals") and "error" not in d}
    {s: d for s, d in results.items() if "error" in d}

    if hits:
        section_header(f"Active Signals — {len(hits)} Target(s) Locked")
        for sym, data in hits.items():
            sig_labels = " ".join(
                f'<span style="background:rgba(0,200,255,0.12);border:1px solid rgba(0,200,255,0.28);'
                f"border-radius:2px;padding:2px 8px;font-family:Share Tech Mono,monospace;"
                f'font-size:0.62rem;color:#00c8ff;letter-spacing:0.08em;">{s}</span>'
                for s in data["signals"]
            )
            st.markdown(
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f"padding:10px 16px;margin-bottom:4px;border-radius:4px;"
                f"background:rgba(0,200,255,0.04);border:1px solid rgba(0,200,255,0.18);"
                f'clip-path:polygon(0 0,calc(100% - 8px) 0,100% 8px,100% 100%,8px 100%,0 calc(100% - 8px));">'
                f'<div style="font-family:Share Tech Mono,monospace;font-size:0.88rem;'
                f'color:#c8e8ff;letter-spacing:0.08em;">{sym}</div>'
                f'<div style="display:flex;gap:5px;align-items:center;">{sig_labels}</div>'
                f'<div style="font-family:Share Tech Mono,monospace;font-size:0.75rem;color:#5a94bc;">'
                f"₹{data.get('close', 0):,.2f} &nbsp;·&nbsp; RSI {data.get('rsi', '?')} "
                f"&nbsp;·&nbsp; ADX {data.get('adx', '?')} &nbsp;·&nbsp; Vol {data.get('vol_ratio', '?')}x"
                f"</div></div>",
                unsafe_allow_html=True,
            )

    section_header("All Targets — 15-Min Status Board")
    rows = []
    for sym, data in results.items():
        if "error" in data:
            rows.append(
                {
                    "Symbol": sym,
                    "Price": "—",
                    "RSI": "—",
                    "ADX": "—",
                    "Vol Ratio": "—",
                    "BB Width%": "—",
                    "Signals": "⚠ NO DATA",
                }
            )
        else:
            rows.append(
                {
                    "Symbol": sym,
                    "Price": f"₹{data.get('close', 0):,.2f}",
                    "RSI": data.get("rsi", "—"),
                    "ADX": data.get("adx", "—"),
                    "Vol Ratio": f"{data.get('vol_ratio', 0):.2f}x",
                    "BB Width%": f"{data.get('bb_width', 0):.1f}%",
                    "Signals": " | ".join(data.get("signals", [])) or "—",
                }
            )
    import pandas as _pd2

    st.dataframe(_pd2.DataFrame(rows), use_container_width=True, hide_index=True)


def show_reports() -> None:
    section_header("Intel Archive — Report Generation")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown(
            '<div class="nc-label" style="margin-bottom:8px;">Market Briefing PDF</div>', unsafe_allow_html=True
        )
        if st.button("◈ GENERATE BRIEFING PDF"):
            with st.spinner("Generating briefing..."):
                universe = load_universe()
                briefing = generate_market_briefing(
                    {
                        "symbol_count": len(universe),
                        "watchlist_count": min(10, len(universe)),
                        "date": now_ist().strftime("%d %b %Y"),
                    }
                )
                path = generate_text_report("Market Briefing", briefing, REPORTS_DIR / "market_briefing.pdf")
            st.success(f"Saved to {path}")

    with c2:
        st.markdown('<div class="nc-label" style="margin-bottom:8px;">Task List PDF</div>', unsafe_allow_html=True)
        if st.button("◈ GENERATE TASK PDF"):
            with st.spinner("Generating tasks..."):
                tasks = get_tasks()
                body = (
                    "\n".join(
                        [f"[{t.get('created_at', '')}] {t.get('label', '')} — {t.get('context', '')}" for t in tasks]
                    )
                    or "No tasks available."
                )
                path = generate_text_report("Daily Task List", body, REPORTS_DIR / "task_list.pdf")
            st.success(f"Saved to {path}")

    section_header("Archived Intel Files")
    report_files = list(REPORTS_DIR.glob("*.pdf"))
    if report_files:
        for f in sorted(report_files, key=lambda x: x.stat().st_mtime, reverse=True):
            size_kb = f.stat().st_size / 1024
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d %b %Y %H:%M")
            st.markdown(
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f"padding:8px 14px;margin-bottom:4px;border-radius:4px;"
                f'background:rgba(0,200,255,0.03);border:1px solid rgba(0,200,255,0.07);">'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:0.74rem;color:#5a94bc;">{f.name}</span>'
                f'<span style="font-family:Share Tech Mono,monospace;font-size:0.62rem;color:#234460;">'
                f"{size_kb:.1f} KB &nbsp;·&nbsp; {mtime}</span></div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No reports generated yet.")


def show_axiom_command() -> None:
    """AXIOM AI command interface."""
    section_header("AXIOM AI Assistant — Intelligence Interface")

    st.markdown(
        '<div style="font-family:Share Tech Mono,monospace;font-size:0.6rem;color:#234460;'
        'letter-spacing:0.12em;margin-bottom:16px;">'
        "FEMALE REPLACEMENT INTELLIGENT DIGITAL ASSISTANT YOUTH · AXIOM OS MODULE 10 · SESSION MEMORY: 12 EXCHANGES"
        "</div>",
        unsafe_allow_html=True,
    )

    if "axiom_history" not in st.session_state:
        st.session_state["axiom_history"] = []
    if "axiom_cmd_log" not in st.session_state:
        st.session_state["axiom_cmd_log"] = []

    col_cmd, col_btn = st.columns([5, 1])
    with col_cmd:
        command = st.text_input(
            "Command",
            placeholder="e.g. 'analyse RELIANCE' · 'brief me' · 'scan breakouts' · 'review journal'",
            label_visibility="collapsed",
            key="axiom_cmd_input",
        )
    with col_btn:
        run = st.button("◈ EXECUTE", use_container_width=True)

    quick_cmds = ["brief me", "scan breakouts", "review journal", "show regime", "top 10 setups"]
    cols = st.columns(len(quick_cmds))
    for i, qc in enumerate(quick_cmds):
        if cols[i].button(qc, key=f"qcmd_{i}"):
            command = qc
            run = True

    if run and command:
        st.session_state["axiom_cmd_log"].append(command)
        with st.spinner("AXIOM processing command..."):
            history_ctx = "\n".join(
                [f"User: {h['user']}\nAXIOM: {h['response']}" for h in st.session_state["axiom_history"][-6:]]
            )
            prompt = (
                f"Session context (last exchanges):\n{history_ctx}\n\n"
                f"User command: {command}\n\n"
                "Respond as AXIOM — Advanced eXpert Intelligence for Operations in Market, "
                "an institutional NSE trading assistant. "
                "Use institutional precision. If asked to analyse a stock, use the 9-section format. "
                "If asked to brief, give MARKET PULSE → NIFTY OUTLOOK → SECTOR WATCH → STOCKS ON RADAR → AXIOM VERDICT. "
                "Be direct, analytical and professional. No fluff."
            )
            from ai.brain import generate_commentary

            response = generate_commentary(prompt)

        st.session_state["axiom_history"].append({"user": command, "response": response})
        if len(st.session_state["axiom_history"]) > 12:
            st.session_state["axiom_history"] = st.session_state["axiom_history"][-12:]

    if st.session_state["axiom_history"]:
        st.markdown(
            '<div style="height:1px;background:linear-gradient(90deg,transparent,'
            'rgba(0,200,255,0.15) 50%,transparent);margin:16px 0;"></div>',
            unsafe_allow_html=True,
        )
        for exchange in reversed(st.session_state["axiom_history"]):
            # User bubble
            st.markdown(
                f'<div style="display:flex;justify-content:flex-end;margin-bottom:4px;">'
                f'<div style="background:rgba(0,200,255,0.07);border:1px solid rgba(0,200,255,0.18);'
                f"border-radius:6px 6px 2px 6px;padding:8px 14px;max-width:76%;"
                f"font-family:Share Tech Mono,monospace;font-size:0.76rem;color:#c8e8ff;"
                f'letter-spacing:0.04em;">'
                f"◈ {exchange['user']}</div></div>",
                unsafe_allow_html=True,
            )
            resp = exchange["response"]
            # Institutional report renderer
            if any(
                kw in resp
                for kw in ["MARKET PULSE", "NIFTY OUTLOOK", "TECHNICAL STRUCTURE", "RISK PLAN", "FINAL VERDICT"]
            ):
                sections = resp.split("\n")
                rendered = ""
                for line in sections:
                    if line.strip() and line.strip()[0].isdigit() and ". " in line[:5]:
                        rendered += f'<div style="color:#00c8ff;font-family:Share Tech Mono,monospace;font-size:0.68rem;letter-spacing:0.18em;margin-top:10px;margin-bottom:2px;">{line.strip()}</div>'
                    elif line.startswith(("   ", "\t")):
                        rendered += f'<div style="font-family:Share Tech Mono,monospace;font-size:0.72rem;color:#5a94bc;padding-left:12px;">{line.strip()}</div>'
                    else:
                        rendered += (
                            f'<div style="font-family:Inter,sans-serif;font-size:0.76rem;color:#c8e8ff;">{line}</div>'
                        )
                st.markdown(
                    f'<div style="background:rgba(0,0,0,0.35);border:1px solid rgba(0,200,255,0.14);'
                    f'border-radius:6px 2px 6px 6px;padding:14px 16px;margin-bottom:12px;">{rendered}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="background:rgba(0,0,0,0.35);border:1px solid rgba(0,200,255,0.12);'
                    f"border-radius:6px 2px 6px 6px;padding:10px 16px;margin-bottom:12px;"
                    f'font-family:Inter,sans-serif;font-size:0.76rem;color:#c8e8ff;white-space:pre-wrap;">'
                    f"{resp}</div>",
                    unsafe_allow_html=True,
                )

    if st.session_state["axiom_cmd_log"]:
        with st.expander("Command Log"):
            for i, cmd in enumerate(reversed(st.session_state["axiom_cmd_log"])):
                st.markdown(
                    f'<span style="font-family:Share Tech Mono,monospace;font-size:0.65rem;color:#234460;">#{len(st.session_state["axiom_cmd_log"]) - i:03d}</span> '
                    f'<span style="font-size:0.75rem;color:#5a94bc;font-family:Share Tech Mono,monospace;">{cmd}</span>',
                    unsafe_allow_html=True,
                )
        if st.button("◈ CLEAR SESSION MEMORY"):
            st.session_state["axiom_history"] = []
            st.session_state["axiom_cmd_log"] = []
            st.rerun()


# ─────────────────────────────────────────────────────────────────
# ORDER FLOW — FOOTPRINT
# ─────────────────────────────────────────────────────────────────


def footprint_chart(profile: pd.DataFrame, poc: float, symbol: str) -> go.Figure:
    """Horizontal split bars: buy volume (right) vs sell volume (left), per price."""
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=profile["price"],
            x=-profile["sell_vol"],
            orientation="h",
            name="SELL",
            marker={"color": "rgba(230,57,70,0.65)"},
            hovertemplate="₹%{y}<br>Sell %{customdata:,.0f}<extra></extra>",
            customdata=profile["sell_vol"],
        )
    )
    fig.add_trace(
        go.Bar(
            y=profile["price"],
            x=profile["buy_vol"],
            orientation="h",
            name="BUY",
            marker={"color": "rgba(0,214,143,0.65)"},
            hovertemplate="₹%{y}<br>Buy %{x:,.0f}<extra></extra>",
        )
    )
    fig.add_hline(
        y=poc,
        line={"color": _GOLD_COLOR, "dash": "dash", "width": 1.2},
        annotation_text=f"POC ₹{poc}",
        annotation_font_color=_GOLD_COLOR,
    )
    layout = PLOTLY_LAYOUT.copy()
    layout["title"] = {
        "text": f"<b>{symbol}</b>  ·  FOOTPRINT (APPROX.)",
        "font": {"family": "Orbitron", "color": _ACCENT_COLOR, "size": 12},
        "x": 0.02,
    }
    layout["barmode"] = "relative"
    layout["bargap"] = 0.08
    fig.update_layout(**layout)
    return fig


def show_footprint() -> None:
    section_header("Order Flow — Footprint Recon")

    st.markdown(
        '<div style="font-family:Share Tech Mono,monospace;font-size:0.66rem;color:#FFB300;'
        "margin-bottom:14px;padding:9px 13px;background:rgba(255,179,0,0.05);"
        'border:1px solid rgba(255,179,0,0.18);border-radius:4px;letter-spacing:0.04em;">'
        "⚠ APPROXIMATED ORDER FLOW &nbsp;·&nbsp; " + APPROXIMATION_NOTE + "</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    symbol = c1.text_input("TARGET SYMBOL", value="RELIANCE.NS").strip().upper()
    days = c2.slider("SESSIONS", 1, 7, 1)
    bins = c3.slider("PRICE BINS", 12, 60, 30)

    if st.button("◈ RUN RECON") and symbol:
        with st.spinner("Reconstructing order flow..."):
            df = fetch_intraday(symbol, days=days, interval="1m")
            if df.empty:
                st.error(f"No intraday data for {symbol}. Check symbol (use .NS suffix for NSE).")
                return
            fp = build_footprint(df, symbol=symbol, bins=bins)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("POC", f"₹{fp.poc}")
        m2.metric("NET DELTA", f"{fp.total_delta:,.0f}", delta="BUY" if fp.total_delta > 0 else "SELL")
        m3.metric("BARS", fp.bars)
        m4.metric("LAST", f"₹{df['close'].iloc[-1]:,.2f}")

        st.plotly_chart(footprint_chart(fp.profile, fp.poc, symbol), use_container_width=True)

        section_header("Volume-at-Price Ladder")
        ladder = fp.profile.sort_values("price", ascending=False)
        st.dataframe(ladder, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────
# WAR GAMES — BACKTESTER
# ─────────────────────────────────────────────────────────────────


def show_backtest() -> None:
    section_header("War Games — Strategy Backtester")

    st.markdown(
        '<div style="font-family:Share Tech Mono,monospace;font-size:0.72rem;color:#5a94bc;'
        "margin-bottom:16px;padding:10px 14px;background:rgba(0,200,255,0.04);"
        'border:1px solid rgba(0,200,255,0.09);border-radius:4px;letter-spacing:0.05em;">'
        "BREAKOUT REPLAY: close &gt; 20-bar high · vol &gt; 1.5× avg · ADX ≥ 18 · EMA stack · &gt; EMA200 "
        "&nbsp;·&nbsp; 2% risk · ATR stop · 1R breakeven · 2R trail"
        "</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    symbol = c1.text_input("TARGET SYMBOL", value="RELIANCE.NS").strip().upper()
    period = c2.selectbox("HISTORY", ["1y", "2y", "3y", "5y"], index=1)
    rr_target = c3.slider("R:R TARGET", 1.5, 4.0, 2.5, 0.5)
    capital = c4.number_input("CAPITAL (₹)", value=1_000_000, step=100_000)

    if st.button("◈ RUN SIMULATION") and symbol:
        with st.spinner("Running war games..."):
            df = fetch_symbol_history(symbol, period=period, interval="1d")
            if df.empty or len(df) < 220:
                st.error(f"Insufficient history for {symbol} (need ~220+ daily bars).")
                return
            cfg = BacktestConfig(rr_target=rr_target, starting_capital=float(capital))
            res = backtest_symbol(df, symbol=symbol, cfg=cfg)

        if res.trades.empty:
            st.warning("No trades triggered over this window with current rules.")
            return

        m = res.metrics
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("TRADES", m["total_trades"])
        r2.metric("WIN RATE", f"{m['win_rate']}%")
        r3.metric("EXPECTANCY", f"{m['expectancy']}R")
        r4.metric("PROFIT FACTOR", m["profit_factor"])

        r5, r6, r7, r8 = st.columns(4)
        r5.metric("TOTAL P&L", f"₹{m['total_pnl']:,.0f}")
        r6.metric("RETURN", f"{m['total_return_pct']}%")
        r7.metric("MAX DD", f"{m['max_drawdown']}%")
        r8.metric("SHARPE", m["sharpe"])

        # Equity curve
        eq = res.equity.copy()
        pd.DataFrame({"equity": eq.values}, index=eq.index)
        fig = go.Figure(
            go.Scatter(
                x=list(range(len(eq))),
                y=eq.values,
                fill="tozeroy",
                fillcolor="rgba(0,200,255,0.07)",
                line={"color": "#00c8ff", "width": 2},
            )
        )
        layout = PLOTLY_LAYOUT.copy()
        layout["title"] = {
            "text": "EQUITY CURVE — BACKTEST",
            "font": {"family": "Orbitron", "color": _ACCENT_COLOR, "size": 12},
            "x": 0.02,
        }
        fig.update_layout(**layout)
        st.plotly_chart(fig, use_container_width=True)

        # Threshold check vs CLAUDE.md backtest standards
        section_header("Standards Check")
        checks = [
            ("Win Rate > 40%", m["win_rate"] > 40),
            ("Avg R:R > 2.0", m["avg_rr"] > 2.0),
            ("Expectancy > 0.3R", m["expectancy"] > 0.3),
            ("Max Drawdown < 15%", m["max_drawdown"] < 15),
            ("Sharpe > 1.2", m["sharpe"] > 1.2),
            ("Profit Factor > 1.5", m["profit_factor"] > 1.5),
            ("Sample ≥ 50 trades", m["total_trades"] >= 50),
        ]
        rows = "".join(
            f'<tr><td style="padding:4px 12px;color:#c8e8ff;">{name}</td>'
            f'<td style="padding:4px 12px;color:{"#00d68f" if ok else "#e63946"};">'
            f"{'✓ PASS' if ok else '✗ FAIL'}</td></tr>"
            for name, ok in checks
        )
        st.markdown(
            f'<table style="font-family:Share Tech Mono,monospace;font-size:0.72rem;'
            f'border-collapse:collapse;width:100%;">{rows}</table>',
            unsafe_allow_html=True,
        )

        section_header("Trade Ledger")
        st.dataframe(res.trades.sort_values("entry_date", ascending=False), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────

_NAV_ITEMS = [
    ("Dashboard", "▸", "Live market, news, calendar & briefing"),
    ("Stock Screener", "▸", "NSE universe scanner & scoring"),
    ("Watchlist", "▸", "Grade A/B candidates"),
    ("Risk Calculator", "▸", "Position sizing & R:R"),
    ("Trade Journal", "▸", "Trade history & analytics"),
    ("Order Flow", "▸", "Footprint / order-flow profile"),
    ("Backtester", "▸", "Strategy backtesting & simulation"),
    ("Live Scanner", "▸", "Intraday 15-min signal scanner"),
    ("Tasks & Checklist", "▸", "Pre/post-market checklists"),
    ("Reports", "▸", "PDF reports & exports"),
    ("AI Assistant", "▸", "AXIOM AI command interface"),
]


def render_sidebar() -> str:
    with st.sidebar:
        now = now_ist()
        is_market = 9 <= now.hour < 16 and now.weekday() < 5

        # Pre-compute conditional values (avoids nested quotes inside f-string HTML attributes)
        dot_cls = "sys-dot-green" if is_market else "sys-dot-amber"
        mkt_color = "#00d68f" if is_market else "#FFB300"
        mkt_label = "MARKET OPEN · ACTIVE" if is_market else "MARKET CLOSED · STANDBY"
        time_str = now.strftime("%H:%M")

        # Brand header
        st.markdown(
            f'<div style="padding:22px 18px 14px;">'
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
            f'<div style="width:46px;height:46px;flex-shrink:0;display:flex;align-items:center;justify-content:center;'
            f"background:radial-gradient(circle at 50% 50%,rgba(0,200,255,0.12),rgba(0,200,255,0.03));"
            f"border:1px solid rgba(0,200,255,0.28);border-radius:50%;"
            f'box-shadow:0 0 20px rgba(0,200,255,0.15),inset 0 0 12px rgba(0,200,255,0.08);">'
            f"{_NC_LOGO_SVG}</div>"
            f"<div>"
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.44rem;'
            f'color:rgba(255,179,0,0.5);letter-spacing:0.28em;text-transform:uppercase;">Neura Capital</div>'
            f'<div style="font-family:Orbitron,sans-serif;font-size:0.95rem;font-weight:900;color:#00c8ff;'
            f'letter-spacing:0.22em;text-shadow:0 0 18px rgba(0,200,255,0.5);">AXIOM</div>'
            f'<div style="font-family:Share Tech Mono,monospace;font-size:0.42rem;'
            f'color:rgba(0,200,255,0.28);letter-spacing:0.12em;margin-top:1px;">eXpert Intelligence · Markets</div>'
            f"</div></div>"
            f'<div style="background:rgba(0,0,0,0.4);border:1px solid rgba(0,200,255,0.07);'
            f'border-radius:4px;padding:8px 12px;margin-bottom:4px;">'
            f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:5px;">'
            f'<span class="sys-dot {dot_cls}"></span>'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.6rem;'
            f'color:{mkt_color};letter-spacing:0.1em;">{mkt_label}</span>'
            f'<span style="margin-left:auto;font-family:Share Tech Mono,monospace;'
            f'font-size:0.58rem;color:#234460;">{time_str}</span>'
            f"</div>"
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.52rem;color:#234460;letter-spacing:0.08em;">ARC</span>'
            f'<div style="flex:1;height:2px;border-radius:1px;'
            f'background:linear-gradient(90deg,#00c8ff 94%,rgba(0,200,255,0.08) 94%);"></div>'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.52rem;color:#00c8ff;">94%</span>'
            f"</div></div></div>"
            f'<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(0,200,255,0.12) 50%,transparent);margin:0 16px 8px;"></div>'
            f'<div style="padding:0 18px 4px;">'
            f'<span style="font-family:Share Tech Mono,monospace;font-size:0.55rem;'
            f'color:#234460;letter-spacing:0.2em;text-transform:uppercase;">[ NAVIGATION ]</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

        # Navigation
        page = st.radio(
            "MODULE",
            [f"  {icon}  {label}" for label, icon, _ in _NAV_ITEMS],
            label_visibility="collapsed",
        )

        # Footer — Stark quote
        st.markdown(
            '<div style="padding:12px 14px 8px;border-top:1px solid rgba(0,200,255,0.05);margin-top:8px;">'
            '<div style="font-family:Share Tech Mono,monospace;font-size:0.52rem;'
            'color:#1a3850;text-align:center;line-height:2;letter-spacing:0.06em;">'
            "AXIOM OS v5.0 · GROQ / LLAMA-3.3<br>"
            "ADVANCED EXPERT INTELLIGENCE<br>FOR OPERATIONS IN MARKET<br>"
            "© 2026 NEURA CAPITAL · CONFIDENTIAL"
            "</div></div>",
            unsafe_allow_html=True,
        )

    return page


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────


def _bridge_streamlit_secrets() -> None:
    """
    On Streamlit Community Cloud there is no .env file — secrets are provided via
    st.secrets. Copy them into os.environ so the existing os.getenv() calls work.
    No-op locally (where .env is used).
    """
    try:
        for key, val in st.secrets.items():
            if isinstance(val, str):
                os.environ.setdefault(key, val)
    except Exception:
        pass  # no secrets configured / running locally


def main() -> None:
    _bridge_streamlit_secrets()
    st.set_page_config(
        page_title="AXIOM · Neura Capital",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(AXIOM_CSS, unsafe_allow_html=True)
    init_db()

    render_hud_header()
    page = render_sidebar()

    p = page.strip().upper()
    if "DASHBOARD" in p:
        show_overview()
    elif "SCREENER" in p:
        show_screener()
    elif "WATCHLIST" in p:
        show_watchlist()
    elif "RISK" in p:
        show_risk_calculator()
    elif "JOURNAL" in p:
        show_trade_journal()
    elif "ORDER" in p:
        show_footprint()
    elif "BACKTEST" in p:
        show_backtest()
    elif "SCANNER" in p:
        show_monitor()
    elif "TASK" in p:
        show_tasks()
    elif "REPORT" in p:
        show_reports()
    elif "ASSISTANT" in p:
        show_axiom_command()


if __name__ == "__main__":
    main()
