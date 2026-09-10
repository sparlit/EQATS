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


import datetime
import json
import math
import os

# Async dashboard endpoints - moved to separate module for clarity
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
from nsetools import Nse  # Import NSE class
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
    print("Mutual funds database tables initialized successfully.")


# Demo data for prototype - TODO: Replace with real data sources when available
DEMO_DATA = {
    "indices": [
        {"name": "NIFTY 50", "value": 24847.30, "change": 124.50, "changePct": 0.50},
        {"name": "NIFTY BANK", "value": 52341.20, "change": -89.30, "changePct": -0.17},
        {"name": "NIFTY IT", "value": 36892.10, "change": 234.60, "changePct": 0.64},
        {"name": "SENSEX", "value": 82156.80, "change": -45.20, "changePct": -0.05},
    ],
    "stocks": [
        {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "price": 2847.35,
            "changePct": 1.50,
            "sector": "Energy",
            "recommendation": "Buy",
        },
        {
            "symbol": "TCS",
            "name": "Tata Consultancy Services",
            "price": 3912.60,
            "changePct": -0.72,
            "sector": "IT",
            "recommendation": "Hold",
        },
        {
            "symbol": "HDFCBANK",
            "name": "HDFC Bank",
            "price": 1724.80,
            "changePct": 1.11,
            "sector": "Banking",
            "recommendation": "Buy",
        },
        {
            "symbol": "INFY",
            "name": "Infosys",
            "price": 1847.25,
            "changePct": -0.79,
            "sector": "IT",
            "recommendation": "Hold",
        },
        {
            "symbol": "ICICIBANK",
            "name": "ICICI Bank",
            "price": 1312.45,
            "changePct": 1.73,
            "sector": "Banking",
            "recommendation": "Buy",
        },
        {
            "symbol": "HINDUNILVR",
            "name": "Hindustan Unilever",
            "price": 2398.10,
            "changePct": -1.30,
            "sector": "FMCG",
            "recommendation": "Sell",
        },
    ],
    "sectors": [
        {"name": "Banking", "pct": 1.24},
        {"name": "IT", "pct": -0.91},
        {"name": "FMCG", "pct": -0.48},
        {"name": "Auto", "pct": 0.34},
        {"name": "Energy", "pct": 1.50},
        {"name": "Pharma", "pct": 1.12},
    ],
    "gainers": [
        {"symbol": "BAJFINANCE", "name": "Bajaj Finance", "price": 7248.15, "changePct": 2.21},
        {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "price": 1623.45, "changePct": 2.02},
        {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical", "price": 1682.45, "changePct": 1.75},
    ],
    "losers": [
        {"symbol": "WIPRO", "name": "Wipro", "price": 547.80, "changePct": -1.47},
        {"symbol": "TATAMOTORS", "name": "Tata Motors", "price": 985.40, "changePct": -1.52},
        {"symbol": "BPCL", "name": "Bharat Petroleum", "price": 628.70, "changePct": -1.32},
    ],
    "watchlist": [
        {"symbol": "RELIANCE", "name": "Reliance Industries", "sector": "Energy", "price": 2847.35, "changePct": 1.50},
        {"symbol": "TCS", "name": "Tata Consultancy Services", "sector": "IT", "price": 3912.60, "changePct": -0.72},
        {"symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Banking", "price": 1724.80, "changePct": 1.11},
        {"symbol": "INFY", "name": "Infosys", "sector": "IT", "price": 1847.25, "changePct": -0.79},
    ],
}


@app.context_processor
def inject_demo_data():
    # Fetch real gainers/losers data (limit to 5 for dashboard display)
    real_gl_data = get_dashboard_data_with_fallback(limit=5)

    # Build final demo_data dict with real gainers/losers
    final_demo_data = dict(DEMO_DATA)
    if real_gl_data is not None:
        final_demo_data["gainers"] = real_gl_data.get("gainers", DEMO_DATA["gainers"])
        final_demo_data["losers"] = real_gl_data.get("losers", DEMO_DATA["losers"])

    return {"demo_data": final_demo_data}


# Run initialization on import
init_mutual_funds_db()


@app.route("/")
@login_required
def index():
    """Main dashboard showing overview of database.

    Optimized for fast initial page load:
    - Only cheap DB queries (stats)
    - No blocking external API calls (NSE/Yahoo Finance)
    - Heavy data loaded asynchronously via /api/dashboard/* endpoints
    """
    session = get_db_session()
    try:
        # Only fetch stats - these are fast database operations
        stats = {
            "total_assets": session.query(Asset).count(),
            "total_stocks": session.query(Asset).filter(Asset.type == "equity").count(),
            "total_prices": session.query(DailyPrice).count(),
            "total_suggestions": session.query(Suggestion).count(),
            "latest_date": session.query(DailyPrice.date).order_by(DailyPrice.date.desc()).first()[0]
            if session.query(DailyPrice).first()
            else None,
        }

        # NOTE: Index data, sector data, gainers, losers are now loaded asynchronously
        # via /api/dashboard/* endpoints to avoid blocking the initial response
        # They will be fetched client-side after the page loads

        return render_template("index.html", stats=stats, active="home")
    finally:
        session.close()


# =============================================================================
# Async Dashboard API Endpoints
# =============================================================================


@app.route("/api/dashboard/gainers")
def api_dashboard_gainers():
    """Async endpoint for top gainers. Returns real data or error state."""
    try:
        dashboard_data = get_top_gainers_losers(limit=10)
        if dashboard_data and dashboard_data.gainers:
            return jsonify({"status": "success", "data": dashboard_data.to_dict()["gainers"], "source": "live"})
        return jsonify(
            {
                "status": "unavailable",
                "data": [],
                "message": "Top gainers data is currently unavailable. Market data refreshes during trading hours.",
                "source": "none",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "data": [],
                "message": "Unable to fetch top gainers data.",
                "error": str(e),
                "source": "error",
            }
        ), 500


@app.route("/api/dashboard/losers")
def api_dashboard_losers():
    """Async endpoint for top losers. Returns real data or error state."""
    try:
        dashboard_data = get_top_gainers_losers(limit=10)
        if dashboard_data and dashboard_data.losers:
            return jsonify({"status": "success", "data": dashboard_data.to_dict()["losers"], "source": "live"})
        return jsonify(
            {
                "status": "unavailable",
                "data": [],
                "message": "Top losers data is currently unavailable. Market data refreshes during trading hours.",
                "source": "none",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "data": [],
                "message": "Unable to fetch top losers data.",
                "error": str(e),
                "source": "error",
            }
        ), 500


@app.route("/api/dashboard/chart-data")
def api_dashboard_chart_data():
    """Async endpoint for market performance chart data."""
    try:
        from index_data import get_index_data_with_fallback, set_test_mode

        set_test_mode(False)
        indices_data = get_index_data_with_fallback()
        has_real_data = any(ind.get("value", 0) > 0 for ind in indices_data)
        return jsonify(
            {
                "status": "success" if has_real_data else "partial",
                "data": indices_data,
                "source": "live" if has_real_data else "demo",
                "message": None if has_real_data else "Using demo data - live market data unavailable",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "data": [],
                "message": "Unable to fetch market data.",
                "error": str(e),
                "source": "error",
            }
        ), 500


@app.route("/api/dashboard/sector-performance")
def api_dashboard_sector_performance():
    """Async endpoint for sector performance data."""
    try:
        from index_data import get_sector_data_with_fallback, set_test_mode

        set_test_mode(False)
        sectors_data = get_sector_data_with_fallback()
        return jsonify({"status": "success", "data": sectors_data, "source": "live"})
    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "data": [],
                "message": "Unable to fetch sector performance data.",
                "error": str(e),
                "source": "error",
            }
        ), 500


@app.route("/api/dashboard/watchlist")
def api_dashboard_watchlist():
    """Async endpoint for user's watchlist data."""
    try:
        import yfinance as yf
        from models import Asset

        session = get_db_session()
        # Default watchlist symbols (or get from user if flask_login works)
        watchlist_symbols = [
            "RELIANCE",
            "TCS",
            "HDFCBANK",
            "ICICIBANK",
            "INFY",
            "HINDUNILVR",
            "ITC",
            "SBIN",
            "BHARTIARTL",
            "KOTAKBANK",
        ]

        # Fetch from DB first for names/sectors
        assets = session.query(Asset).filter(Asset.symbol.in_(watchlist_symbols)).all()
        asset_map = {a.symbol: a for a in assets}

        # Fetch live prices via yfinance (with .NS suffix for NSE)
        symbols_for_yf = [(s + ".NS") if s not in asset_map else s for s in watchlist_symbols]
        tickers = yf.Tickers(" ".join(symbols_for_yf))

        result = []
        for orig_symbol, yf_symbol in zip(watchlist_symbols, symbols_for_yf, strict=False):
            try:
                ticker = tickers.tickers.get(yf_symbol)
                if not ticker:
                    ticker = yf.Ticker(yf_symbol)
                hist = ticker.history(period="2d", interval="1d")
                if len(hist) >= 2:
                    price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2])
                    change = price - prev_close
                    changePct = (change / prev_close * 100) if prev_close > 0 else 0
                else:
                    price = float(ticker.info.get("previousClose", 0))
                    change = 0
                    changePct = 0

                asset = asset_map.get(orig_symbol)

                # Sanitize NaN/Inf values — browsers' strict JSON.parse fails on NaN
                def _safe(v):
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        return 0
                    return v

                result.append(
                    {
                        "symbol": orig_symbol.upper(),
                        "name": asset.name if asset else orig_symbol,
                        "price": _safe(round(price, 2)),
                        "change": _safe(round(change, 2)),
                        "changePct": _safe(round(changePct, 2)),
                        "sector": asset.sector if asset else "N/A",
                    }
                )
            except Exception as e:
                logger.debug(f"Could not fetch data for {orig_symbol}: {e}")
                continue

        return jsonify(
            {
                "status": "success" if result else "unavailable",
                "data": result,
                "source": "live" if result else "none",
                "message": None if result else "No watchlist data available",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "data": [],
                "message": "Unable to fetch watchlist data.",
                "error": str(e),
                "source": "error",
            }
        ), 500


@app.route("/api/dashboard/stats")
def api_dashboard_stats():
    """Async endpoint for the top stat boxes (NIFTY 50, Buy Signals, Top Sector).

    Aggregates data from existing async sources plus a cheap DB count for
    buy-signals (Suggestion rows for the most recent date) so the top of the
    dashboard can populate independently of the heavy widgets.
    """
    # --- NIFTY 50 value/change (reuse index data; already cached upstream) ---
    nifty_value = None
    nifty_change_pct = None
    nifty_source = "unavailable"
    try:
        from index_data import get_index_data_with_fallback

        indices_data = get_index_data_with_fallback()
        for ind in indices_data:
            if (ind.get("name") or "").upper() == "NIFTY 50":
                nifty_value = ind.get("value")
                nifty_change_pct = ind.get("changePct")
                nifty_source = ind.get("source", "live") if ind.get("value", 0) > 0 else "demo"
                break
    except Exception as e:
        logger.debug(f"Stats endpoint: NIFTY lookup failed: {e}")

    # --- Buy signals count (suggestions in DB for the most recent date) ---
    buy_signals_count = 0
    try:
        session = get_db_session()
        try:
            latest_date_row = session.query(Suggestion.date).order_by(Suggestion.date.desc()).first()
            if latest_date_row is not None:
                buy_signals_count = session.query(Suggestion).filter(Suggestion.date == latest_date_row[0]).count()
        finally:
            session.close()
    except Exception as e:
        logger.debug(f"Stats endpoint: buy signals count failed: {e}")

    # --- Top sector (highest-pct sector from sector-performance data) ---
    top_sector = None
    try:
        from index_data import get_sector_data_with_fallback

        sectors_data = get_sector_data_with_fallback()
        if sectors_data:
            top = max(sectors_data, key=lambda s: s.get("pct", 0))
            top_sector = top.get("name")
    except Exception as e:
        logger.debug(f"Stats endpoint: top sector lookup failed: {e}")

    return jsonify(
        {
            "status": "success",
            "nifty": {
                "value": round(nifty_value, 2) if nifty_value else None,
                "changePct": round(nifty_change_pct, 2) if nifty_change_pct is not None else None,
                "source": nifty_source,
            },
            "buy_signals": buy_signals_count,
            "top_sector": top_sector,
        }
    )


@app.route("/api/market-performance")
def api_market_performance():
    """Async endpoint for NIFTY 50 market performance chart data."""
    try:
        from nifty_data_service import get_nifty_data

        range_param = request.args.get("range", "1D").upper()

        # Validate range parameter
        valid_ranges = ["1D", "1W", "1M", "3M", "1Y"]
        if range_param not in valid_ranges:
            return jsonify(
                {
                    "status": "error",
                    "message": f"Invalid range parameter. Supported: {valid_ranges}",
                    "data": [],
                }
            ), 400

        result = get_nifty_data(range_param)

        # Return the result with proper status
        if result.get("status") == "success":
            return jsonify(result)
        return jsonify(result), 500

    except Exception as e:
        logger.exception(f"Market performance API error: {e}")
        return jsonify(
            {
                "status": "error",
                "message": "Unable to fetch market performance data.",
                "error": str(e),
                "data": [],
            }
        ), 500


@app.route("/stocks")
@login_required
def stocks():
    """Display all assets, with optional search by symbol/name and type filter"""
    session = get_db_session()
    try:
        page = request.args.get("page", 1, type=int)
        per_page = 20
        q = request.args.get("q", "").strip()
        asset_type = request.args.get("type", "equity")

        assets_query = session.query(Asset)
        if asset_type:
            assets_query = assets_query.filter(Asset.type == asset_type)
        if q:
            like = f"%{q}%"
            assets_query = assets_query.filter((Asset.symbol.ilike(like)) | (Asset.name.ilike(like)))
        total = assets_query.count()
        assets = assets_query.order_by(Asset.symbol).offset((page - 1) * per_page).limit(per_page).all()

        # Add latest price to each asset
        for asset in assets:
            latest_price = (
                session.query(DailyPrice)
                .filter(DailyPrice.asset_id == asset.id)
                .order_by(DailyPrice.date.desc())
                .first()
            )
            asset.latest_price = latest_price.close if latest_price is not None else 0.0

        total_pages = max(1, (total + per_page - 1) // per_page)

        return render_template(
            "stocks.html",
            stocks=assets,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            q=q,
            has_next=page < total_pages,
            has_prev=page > 1,
            asset_type=asset_type,
            active="stocks",
        )
    finally:
        session.close()


def get_price_history(asset_id, show_latest_days=60):
    """Get price history for an asset, optionally limiting to latest N days.

    Returns a list of dicts for JSON compatibility, or DailyPrice objects
    if show_latest_days is None (for maximum flexibility).
    """
    session = get_db_session()
    try:
        # Get full price history from database
        price_history = session.query(DailyPrice).filter_by(asset_id=asset_id).order_by(DailyPrice.date.asc()).all()

        # If we want latest N days, slice the most recent records
        if show_latest_days and price_history:
            # Take the most recent show_latest_days records
            price_history = price_history[-show_latest_days:]

        # Convert to dicts for JSON serialization compatibility
        # This ensures the data can be passed to templates and APIs without
        # "Object of type DailyPrice is not JSON serializable" errors
        result = []
        for price in price_history:
            result.append(
                {
                    "date": price.date.strftime("%d-%m-%Y") if price.date else None,
                    "open": price.open,
                    "high": price.high,
                    "low": price.low,
                    "close": price.close,
                    "adj_close": price.adj_close,
                    "volume": price.volume,
                }
            )
        return result
    finally:
        session.close()


@app.route("/stocks/<int:asset_id>")
@login_required
def stock_detail(asset_id):
    """Display details for a specific asset"""
    session = get_db_session()
    try:
        asset = session.query(Asset).get(asset_id)
        if not asset:
            return "Asset not found", 404

        # Check for history view mode: ?history=latest60 or ?history=all
        history_mode = request.args.get("history", "latest60")
        if history_mode == "all":
            show_latest_days = None  # Show all data
        else:
            show_latest_days = 60  # Show latest 60 days

        # Get recent prices (last 10 for table)
        recent_prices = (
            session.query(DailyPrice).filter_by(asset_id=asset_id).order_by(DailyPrice.date.desc()).limit(10).all()
        )

        # Get full price history for charts (controlled by show_latest_days param)
        price_history = get_price_history(asset_id, show_latest_days=show_latest_days)

        # Get suggestions for this asset
        suggestions = (
            session.query(Suggestion).filter_by(asset_id=asset_id).order_by(Suggestion.date.desc()).limit(5).all()
        )

        return render_template(
            "stock_detail.html",
            stock=asset,
            recent_prices=recent_prices,
            price_history=price_history,
            suggestions=suggestions,
            active="stocks",
            history_mode=history_mode,
        )
    finally:
        session.close()


@app.route("/prices")
@login_required
def prices():
    """Display daily prices with filtering"""
    session = get_db_session()
    try:
        # Get filter parameters
        asset_id = request.args.get("asset_id", type=int)
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        asset_type = request.args.get("type", None)

        query = session.query(DailyPrice, Asset).join(Asset, DailyPrice.asset_id == Asset.id)

        if asset_id:
            query = query.filter(DailyPrice.asset_id == asset_id)
        if asset_type:
            query = query.filter(Asset.type == asset_type)
        else:
            # Default to stocks only (exclude mutual funds, which have NAV-only rows)
            query = query.filter(Asset.type != "mutual_fund")
        if start_date:
            query = query.filter(DailyPrice.date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        if end_date:
            query = query.filter(DailyPrice.date <= datetime.strptime(end_date, "%Y-%m-%d").date())

        # Get all assets for filter dropdown
        assets = session.query(Asset).order_by(Asset.symbol).all()

        # Paginate
        page = request.args.get("page", 1, type=int)
        per_page = 20
        total = query.count()
        prices = query.order_by(DailyPrice.date.desc()).offset((page - 1) * per_page).limit(per_page).all()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return render_template(
            "prices.html",
            prices=prices,
            stocks=assets,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
            start_date=start_date,
            end_date=end_date,
            asset_type=asset_type,
            active="prices",
        )
    finally:
        session.close()


@app.route("/suggestions")
@login_required
def suggestions():
    """Display suggestions with filtering"""
    session = get_db_session()
    try:
        # Get filter parameters
        asset_id = request.args.get("asset_id", type=int)
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        asset_type = request.args.get("type", None)

        query = session.query(Suggestion, Asset).join(Asset, Suggestion.asset_id == Asset.id)

        if asset_id:
            query = query.filter(Suggestion.asset_id == asset_id)
        if asset_type:
            query = query.filter(Asset.type == asset_type)
        if start_date:
            query = query.filter(Suggestion.date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        if end_date:
            query = query.filter(Suggestion.date <= datetime.strptime(end_date, "%Y-%m-%d").date())

        # Get all assets for filter dropdown
        assets = session.query(Asset).order_by(Asset.symbol).all()

        # Get available date range for filter form min/max attributes
        min_date_result = session.query(Suggestion.date).order_by(Suggestion.date.asc()).first()
        max_date_result = session.query(Suggestion.date).order_by(Suggestion.date.desc()).first()
        min_available_date = min_date_result[0] if min_date_result else None
        max_available_date = max_date_result[0] if max_date_result else None

        # Paginate
        page = request.args.get("page", 1, type=int)
        per_page = 20
        total = query.count()
        suggestions = query.order_by(Suggestion.date.desc()).offset((page - 1) * per_page).limit(per_page).all()

        total_pages = max(1, (total + per_page - 1) // per_page)

        # Build helpful empty-state message explaining why no results were found
        empty_message = None
        if total == 0:
            if min_available_date and max_available_date:
                empty_message = (
                    f"No suggestions found for the selected filters. "
                    f"Available data ranges from {min_available_date.strftime('%d-%m-%Y')} "
                    f"to {max_available_date.strftime('%d-%m-%Y')}."
                )
            else:
                empty_message = "No suggestions found."

        return render_template(
            "suggestions.html",
            suggestions=suggestions,
            stocks=assets,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
            start_date=start_date,
            end_date=end_date,
            asset_type=asset_type,
            min_available_date=min_available_date,
            max_available_date=max_available_date,
            empty_message=empty_message,
            active="suggestions",
        )
    finally:
        session.close()


@app.route("/api/stocks")
@login_required
def api_stocks():
    """API endpoint to get assets as JSON"""
    session = get_db_session()
    try:
        assets = session.query(Asset).order_by(Asset.symbol).all()
        return jsonify(
            [
                {
                    "id": asset.id,
                    "symbol": asset.symbol,
                    "name": asset.name,
                    "exchange": asset.exchange,
                    "sector": asset.sector,
                    "type": asset.type,
                }
                for asset in assets
            ]
        )
    finally:
        session.close()


@app.route("/api/prices")
@login_required
def api_prices():
    """API endpoint to get prices as JSON"""
    session = get_db_session()
    try:
        asset_id = request.args.get("asset_id", type=int)
        days = request.args.get("days", type=int, default=30)

        query = session.query(DailyPrice, Asset).join(Asset, DailyPrice.asset_id == Asset.id)
        if asset_id:
            query = query.filter(DailyPrice.asset_id == asset_id)

        prices = query.order_by(DailyPrice.date.desc()).limit(days).all()

        return jsonify(
            [
                {
                    "date": price[0].date.strftime("%d-%m-%Y"),
                    "asset_symbol": price[1].symbol,
                    "open": price[0].open,
                    "high": price[0].high,
                    "low": price[0].low,
                    "close": price[0].close,
                    "volume": price[0].volume,
                    "adj_close": price[0].adj_close,
                }
                for price in prices
            ]
        )
    finally:
        session.close()


@app.route("/api/suggestions")
@login_required
def api_suggestions():
    """API endpoint to get suggestions for a date or date range.

    Query parameters:
        date: Single date YYYY-MM-DD (default: latest available)
        start_date: Start date YYYY-MM-DD (inclusive)
        end_date: End date YYYY-MM-DD (inclusive)

    Returns suggestions for each date in the range, or latest if no range specified.
    """
    session = get_db_session()
    try:
        # Parse dates manually (Flask type= lambda has compatibility issues)
        from datetime import datetime as _dt

        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        single_date_str = request.args.get("date")
        start_date = _dt.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
        end_date = _dt.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
        target_date = _dt.strptime(single_date_str, "%Y-%m-%d").date() if single_date_str else None

        if start_date and end_date:
            dates = []
            current = start_date
            while current <= end_date:
                dates.append(current)
                current += timedelta(days=1)

            results = []
            for single_date in dates:
                prices = (
                    session.query(DailyPrice)
                    .join(Asset, DailyPrice.asset_id == Asset.id)
                    .filter(DailyPrice.date == single_date, Asset.type != "mutual_fund", not DailyPrice.is_holiday)
                    .all()
                )

                date_suggestions = []
                for price in prices:
                    if price.close is None:
                        continue
                    score = calculate_score(price)
                    eff_open = price.open if price.open is not None else price.close
                    momentum_pct = (price.close - eff_open) / eff_open if eff_open else 0
                    hi = price.high if price.high is not None else price.close
                    lo = price.low if price.low is not None else price.close
                    day_range = hi - lo
                    close_strength = (price.close - lo) / day_range if day_range else 0.5

                    date_suggestions.append(
                        {
                            "symbol": price.asset.symbol,
                            "score": round(score, 4),
                            "reasoning": f"Momentum: {momentum_pct:.2%} | Volume: {price.volume:,:,} | Close strength: {close_strength:.2%}",
                        }
                    )

                results.append(
                    {
                        "date": single_date.strftime("%d-%m-%Y"),
                        "trading_day": len(prices) > 0,
                        "suggestions": date_suggestions,
                    }
                )

            return jsonify(
                {
                    "range": f"{start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}",
                    "total_dates": len(results),
                    "results": results,
                }
            )
        # target_date already set from query param above
        if not target_date:
            target_date = session.query(DailyPrice.date).order_by(DailyPrice.date.desc()).first()[0]

        prices = (
            session.query(DailyPrice)
            .join(Asset, DailyPrice.asset_id == Asset.id)
            .filter(DailyPrice.date == target_date, Asset.type != "mutual_fund", not DailyPrice.is_holiday)
            .all()
        )

        results = []
        for price in prices:
            if price.close is None:
                continue
            score = calculate_score(price)
            eff_open = price.open if price.open is not None else price.close
            momentum_pct = (price.close - eff_open) / eff_open if eff_open else 0
            hi = price.high if price.high is not None else price.close
            lo = price.low if price.low is not None else price.close
            day_range = hi - lo
            close_strength = (price.close - lo) / day_range if day_range else 0.5

            results.append(
                {
                    "symbol": price.asset.symbol,
                    "score": round(score, 4),
                    "reasoning": f"Momentum: {momentum_pct:.2%} | Volume: {price.volume:,:,} | Close strength: {close_strength:.2%}",
                }
            )

        return jsonify(
            {"date": target_date.strftime("%d-%m-%Y"), "suggestions": results, "total_suggestions": len(results)}
        )
    finally:
        session.close()


@app.route("/gainers-losers")
@login_required
def gainers_losers():
    """Display top gainers and losers from NSE"""
    nse = Nse()  # Initialize NSE client
    # Look up asset IDs from the database by symbol so we can link to detail pages.
    # NSE returns bare symbols (e.g. KOTAKBANK) but the DB stores them with a
    # .NS suffix (e.g. KOTAKBANK.NS), so try both forms.
    session = get_db_session()
    try:
        gainers_raw = nse.get_top_gainers()[:15]
        losers_raw = nse.get_top_losers()[:15]
        symbols = [s["symbol"] for s in gainers_raw] + [s["symbol"] for s in losers_raw]
        # Try both the bare symbol and the .NS-suffixed form
        variants = []
        for s in symbols:
            variants.append(s)
            if not s.endswith(".NS"):
                variants.append(s + ".NS")
        assets = session.query(Asset).filter(Asset.symbol.in_(variants)).all()
        # Build a lookup that accepts either form
        symbol_to_id = {}
        for a in assets:
            symbol_to_id[a.symbol] = a.id
            if a.symbol.endswith(".NS"):
                symbol_to_id[a.symbol[:-3]] = a.id
    finally:
        session.close()

    # Format gainers and losers data for template
    gainers_data = []
    for stock in gainers_raw:
        gainers_data.append(
            {
                "symbol": stock["symbol"],
                "ltp": stock["ltp"],
                "change": stock["net_price"],
                "pChange": stock["perChange"],
                "id": symbol_to_id.get(stock["symbol"]),
            }
        )

    losers_data = []
    for stock in losers_raw:
        losers_data.append(
            {
                "symbol": stock["symbol"],
                "ltp": stock["ltp"],
                "change": stock["net_price"],
                "pChange": stock["perChange"],
                "id": symbol_to_id.get(stock["symbol"]),
            }
        )

    # Date the gainers/losers data is for (live snapshot from NSE)
    today_str = datetime.now().strftime("%d-%m-%Y")

    return render_template(
        "gainers_losers.html", gainers=gainers_data, losers=losers_data, today_str=today_str, active="gainers_losers"
    )


@app.route("/search")
@login_required
def search():
    """Search stocks page with autocomplete suggestions."""
    query = request.args.get("q", "").strip()
    results = []

    if query:
        service = StockSearchService()
        results = service.search_stocks(query, limit=20)

    return render_template("search.html", query=query, results=results, active="search")


@app.route("/mutual-funds")
@login_required
def mutual_funds():
    """Display mutual funds with category filtering."""
    # Use mutual fund database session for proper category filtering
    session = get_mutual_fund_session()
    try:
        # Get category filter from request, default to large-cap
        category = request.args.get("category", "large-cap")

        # Build query with category filter
        query = session.query(MutualFundSuggestion, MutualFundAsset)
        query = query.join(MutualFundAsset, MutualFundSuggestion.asset_id == MutualFundAsset.id)

        # Apply category filter
        category_underscore = category.replace("-", "_")
        query = query.filter(MutualFundAsset.type == category_underscore)

        # Filter out stale funds (latest NAV date older than 2 years)
        freshness_cutoff = date.today() - timedelta(days=MF_FRESHNESS_DAYS)
        query = query.filter(
            MutualFundAsset.latest_nav_date.isnot(None), MutualFundAsset.latest_nav_date >= freshness_cutoff
        )

        # Get top 50 by score
        top = query.order_by(MutualFundSuggestion.score.desc()).limit(50).all()

        # Prepare data for template - just asset info and suggestion score
        data = []
        for suggestion, asset in top:
            data.append({"asset": asset, "suggestion": suggestion})

        return render_template("mutual_funds.html", assets=data, active="mutual_funds", category=category)
    finally:
        session.close()


@app.route("/top-mutual-funds")
@login_required
def top_mutual_funds():
    """Display top 50 mutual funds by score from mutual_funds.db."""
    session = get_mutual_fund_session()
    try:
        # Filter out stale funds - if they haven't had NAV updates in the last 2 years, they're not relevant
        freshness_cutoff = date.today() - timedelta(days=MF_FRESHNESS_DAYS)

        # Get top 50 mutual funds by score from mutual_funds.db
        top = (
            session.query(MutualFundAsset, MutualFundSuggestion)
            .join(MutualFundSuggestion, MutualFundSuggestion.asset_id == MutualFundAsset.id)
            .filter(MutualFundAsset.latest_nav_date >= freshness_cutoff)  # Filter by NAV freshness
            .order_by(MutualFundSuggestion.score.desc())
            .limit(50)
            .all()
        )

        # Prepare data for template - just asset info and suggestion score
        data = []
        for asset, suggestion in top:
            data.append({"asset": asset, "suggestion": suggestion})

        return render_template("top_mutual_funds.html", assets=data, active="top-mutual-funds")
    finally:
        session.close()


# Cache for mutual fund details to avoid repeated API calls
mf_cache = {}
CACHE_DURATION = timedelta(hours=1)  # Cache for 1 hour


def categorize_error(error_message: str):
    """Map a raw API/requests error string to a friendly (title, message, status_code) tuple.

    Used by routes that fetch external data so users see a clear, non-technical
    error page instead of raw HTML/tracebacks.

    Returns:
        (title: str, message: str, status_code: int)
    """
    msg = (error_message or "").lower()

    # 404 - Not Found
    if "404" in msg or "not found" in msg:
        return (
            "Not Found",
            "The requested resource could not be found. It may have been deleted or the code is incorrect.",
            404,
        )

    # 502 - Bad Gateway / Service Temporarily Unavailable
    if "502" in msg or "bad gateway" in msg:
        return (
            "Service Temporarily Unavailable",
            "The data service is currently unreachable (Bad Gateway). This is usually temporary — please try again in a few minutes.",
            502,
        )

    # 503 - Service Unavailable
    if "503" in msg or "service unavailable" in msg:
        return (
            "Service Temporarily Unavailable",
            "The data service is temporarily unavailable. Please try again shortly.",
            503,
        )

    # 504 - Gateway Timeout
    if "504" in msg or "gateway timeout" in msg:
        return (
            "Gateway Timeout",
            "The data service took too long to respond (Gateway Timeout). Please try again later.",
            504,
        )

    # Timeout / Read timed out
    if "timeout" in msg or "timed out" in msg:
        return (
            "Request Timed Out",
            "The request to the data service timed out. Please check your network connection and try again.",
            504,
        )

    # Connection errors (ConnectionResetError, Max retries exceeded, etc.)
    if (
        "connection" in msg
        or "max retries exceeded" in msg
        or "connectionreseterror" in msg
        or "connectionrefused" in msg
    ):
        return (
            "Connection Error",
            "Could not connect to the data service. Please check your internet connection and try again.",
            503,
        )

    # 500 - Internal Server Error
    if "500" in msg:
        return (
            "Service Error",
            "The data service encountered an internal error. We have been notified; please try again later.",
            502,
        )

    # Fallback for any unrecognised error
    return (
        "Unexpected Error",
        "Something went wrong while fetching the data. Please try again later.",
        502,
    )


def get_mutual_fund_details_from_api(scheme_code):
    """Fetch mutual fund details from API"""
    BASE_URL = "https://api.mfapi.in/mf"
    url = f"{BASE_URL}/{scheme_code}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "SUCCESS":
            msg = f"API returned failure: {result}"
            raise Exception(msg)

        meta = result["meta"]
        nav_history = result["data"]
        latest_nav = nav_history[0] if nav_history else None

        return {
            "scheme_code": meta.get("scheme_code"),
            "scheme_name": meta.get("scheme_name"),
            "fund_house": meta.get("fund_house"),
            "scheme_type": meta.get("scheme_type"),
            "scheme_category": meta.get("scheme_category"),
            "isin_growth": meta.get("isin_growth"),
            "isin_div_reinvestment": meta.get("isin_div_reinvestment"),
            "latest_nav": latest_nav["nav"] if latest_nav else None,
            "latest_nav_date": latest_nav["date"] if latest_nav else None,
            "nav_history": nav_history,
        }
    except Exception as e:
        msg = f"Failed to fetch mutual fund details: {e!s}"
        raise Exception(msg)


@app.route("/api/search")
@login_required
def api_search_stocks():
    """API endpoint to search stocks by name or symbol."""
    query = request.args.get("q", "").strip()
    limit = request.args.get("limit", 10, type=int)

    if not query:
        return jsonify([])

    service = StockSearchService()
    results = service.search_stocks(query, limit)
    return jsonify(results)


@app.route("/api/stock-details/<symbol>")
@login_required
def api_stock_details(symbol):
    """API endpoint to get stock details by symbol."""
    service = StockSearchService()
    details = service.get_stock_details(symbol)
    return jsonify(details)


@app.route("/api/stock-history/<symbol>")
@login_required
def api_stock_history(symbol):
    """API endpoint to get stock history by symbol."""
    service = StockSearchService()
    history = service.get_stock_history(symbol)
    return jsonify(history)


@app.route("/mutual-funds/<scheme_code>")
@login_required
def mutual_fund_detail(scheme_code):
    """Display details for a specific mutual fund with caching"""
    # Check cache first
    now = datetime.now()
    if scheme_code in mf_cache:
        cached_data, cached_time = mf_cache[scheme_code]
        if now - cached_time < CACHE_DURATION:
            # Return cached data
            return render_template("mutual_fund_detail.html", fund=cached_data, active="mutual_funds", from_cache=True)

    # Fetch from API if not in cache or cache expired
    try:
        fund_details = get_mutual_fund_details_from_api(scheme_code)
        # Update cache
        mf_cache[scheme_code] = (fund_details, now)

        return render_template("mutual_fund_detail.html", fund=fund_details, active="mutual_funds", from_cache=False)
    except Exception as e:
        # Map the raw error to a user-friendly error page
        error_text = str(e)
        title, message, status_code = categorize_error(error_text)
        return render_template(
            "error.html",
            error_title=title,
            error_message=message,
            error_details=error_text,
            back_url="/mutual-funds",
            back_label="← Back to Mutual Funds",
            active="mutual_funds",
        ), status_code


@app.route("/stock/<symbol>")
@login_required
def stock_by_symbol(symbol):
    session = get_db_session()
    try:
        cache_symbol = symbol.upper().strip()

        # Check cache first (freshness: 15 minutes)
        now = datetime.now()
        cached_price_history = None
        if cache_symbol in search_history_cache:
            cached_data, cached_time = search_history_cache[cache_symbol]
            if now - cached_time < SEARCH_HISTORY_CACHE_DURATION:
                cached_price_history = cached_data

        # First try exact match in DB
        asset = session.query(Asset).filter(Asset.symbol == symbol).first()
        if not asset and symbol.endswith(".BO"):
            asset = session.query(Asset).filter(Asset.symbol == symbol.replace(".BO", ".NS")).first()
        if not asset and not (symbol.endswith((".NS", ".BO"))):
            asset = session.query(Asset).filter(Asset.symbol == symbol + ".NS").first()

        # CASE 1: Asset found in DB (Nifty 50 or previously stored)
        if asset:
            history_mode = request.args.get("history", "latest60")
            show_latest_days = None if history_mode == "all" else 60

            # Use cache if fresh, otherwise DB
            if cached_price_history is not None:
                price_history = cached_price_history
            else:
                price_history = get_price_history(asset.id, show_latest_days=show_latest_days)
                search_history_cache[cache_symbol] = (price_history, now)

            recent_prices = (
                list(reversed(price_history[-10:])) if len(price_history) >= 10 else list(reversed(price_history))
            )
            suggestions = (
                session.query(Suggestion).filter_by(asset_id=asset.id).order_by(Suggestion.date.desc()).limit(5).all()
            )
            return render_template(
                "stock_detail.html",
                stock=asset,
                recent_prices=recent_prices,
                price_history=price_history,
                suggestions=suggestions,
                active="stocks",
                history_mode=history_mode,
            )

        # CASE 2: Asset not in DB (non-Nifty 50 stock) - NO DB writes
        history_mode = request.args.get("history", "latest60")
        from data_sources import YFinanceSource

        yf_source = YFinanceSource()

        # Fetch asset info from Yahoo
        name = yf_source.fetch_name(symbol)
        if not name and (symbol.endswith((".NS", ".BO"))):
            base_symbol = symbol.replace(".NS", "").replace(".BO", "")
            name = yf_source.fetch_name(base_symbol)

        if not name:
            return "Stock not found or data unavailable", 404

        exchange = "NSE" if symbol.endswith(".NS") or not (symbol.endswith((".NS", ".BO"))) else "BSE"
        if symbol.endswith(".BO"):
            exchange = "BSE"
        elif symbol.endswith(".NS"):
            exchange = "NSE"

        # Create transient Asset (not added to session)
        asset = Asset(symbol=symbol, name=name, exchange=exchange, sector="Unknown", type="equity")

        # Get price history: cache or Yahoo
        if cached_price_history is not None:
            price_history_data = cached_price_history
        else:
            history_records = yf_source.fetch_history(symbol, limit=60)
            if not history_records and (symbol.endswith((".NS", ".BO"))):
                base_symbol = symbol.replace(".NS", "").replace(".BO", "")
                history_records = yf_source.fetch_history(base_symbol, limit=60)
            if not history_records:
                return "No historical data available", 404
            price_history_data = []
            for rec in history_records:
                price_history_data.append(
                    DailyPrice(
                        date=rec.date,
                        open=rec.open,
                        high=rec.high,
                        low=rec.low,
                        close=rec.close,
                        adj_close=rec.adj_close,
                        volume=rec.volume,
                    )
                )
            search_history_cache[cache_symbol] = (price_history_data, now)

        # Apply history mode
        show_latest_days = None if history_mode == "all" else 60

        if show_latest_days is not None and len(price_history_data) > show_latest_days:
            price_history = list(price_history_data[-show_latest_days:])
        else:
            price_history = list(price_history_data)

        recent_prices = (
            list(reversed(price_history[-10:])) if len(price_history) >= 10 else list(reversed(price_history))
        )
        suggestions = []

        return render_template(
            "stock_detail.html",
            stock=asset,
            recent_prices=recent_prices,
            price_history=price_history,
            suggestions=suggestions,
            active="stocks",
            history_mode=history_mode,
        )
    finally:
        session.close()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
