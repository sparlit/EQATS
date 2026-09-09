import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    elif dt.tzinfo is None:
        now = ist.localize(dt)
    else:
        now = dt.astimezone(ist)
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


import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from functools import wraps

import requests
from flask import Flask, jsonify, render_template, request
from models import (
    Asset,
    DailyPrice,
    MutualFundAsset,
    MutualFundSuggestion,
    Suggestion,
    get_mutual_fund_engine,
    get_mutual_fund_session,
    get_session,
)
from nsetools import Nse
from real_data_service import DEMO_DATA_FALLBACK, get_dashboard_data_with_fallback, get_top_gainers_losers
from scoring2 import calculate_score
from sqlalchemy import text
from sqlalchemy.orm import Session
from stock_search_service import StockSearchService

# In-memory cache for searched stock 60-day price history (TTL: 15 minutes)
search_history_cache = {}
SEARCH_HISTORY_CACHE_DURATION = timedelta(minutes=15)

# Freshness threshold for mutual fund filtering (2 years = 730 days)
MF_FRESHNESS_DAYS = 730

app = Flask(__name__)


@app.template_filter("ddmmmyyyy")
def format_date_ddmmmyyyy(value):
    """Format a date as dd-mm-yyyy string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        return str(value)


def get_db_session():
    """Get a database session"""
    return get_session()


def login_required(f):
    """Decorator to ensure database is accessible"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            session = get_db_session()
            # Simple database connection test
            session.execute(text("SELECT 1"))
            session.close()
            return f(*args, **kwargs)
        except Exception as e:
            return f"Database connection error: {e!s}", 500

    return decorated_function


# Initialize mutual funds database on startup
def init_mutual_funds_db():
    """Initialize the mutual funds database."""
    from models import Base

    engine = get_mutual_fund_engine()
    Base.metadata.create_all(engine)
