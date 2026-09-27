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


"""Fundamental data ingestion pipeline.

Fetches PE, ROE, debt ratios, margins, growth, and company profiles
from multiple sources (FinStack, Indian Market MCP, yfinance) with
automatic fallback cascade.

Source tables: key_ratios, company_profile
"""


import logging
import time
from datetime import datetime

import sqlalchemy as sa

from indian_quant.config.connections import get_engine
from indian_quant.utils import safe_float, safe_int

log = logging.getLogger(__name__)

KEY_RATIO_COLS = [
    "pe_trailing",
    "pe_forward",
    "peg_ratio",
    "price_to_book",
    "price_to_sales",
    "ev_to_ebitda",
    "ev_to_revenue",
    "enterprise_value",
    "market_cap",
    "profit_margin",
    "operating_margin",
    "gross_margin",
    "ebitda_margin",
    "roe",
    "roa",
    "revenue_growth",
    "earnings_growth",
    "earnings_q_growth",
    "debt_to_equity",
    "current_ratio",
    "quick_ratio",
    "total_debt",
    "total_cash",
    "free_cash_flow",
    "eps_trailing",
    "eps_forward",
    "book_value",
    "revenue_per_share",
    "dividend_rate",
    "dividend_yield",
    "payout_ratio",
    "ex_div_date",
    "beta",
    "w52_high",
    "w52_low",
    "avg_volume",
]


# ── Source Fetchers ──


def _fetch_finstack(symbol: str) -> dict | None:
    """Fetch from FinStack key_ratios tool."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        return client.call_tool("key_ratios", {"symbol": symbol})
    except Exception as e:
        log.debug(f"FinStack failed for {symbol}: {e}")
        return None


def _fetch_indian_market(symbol: str) -> dict | None:
    """Fetch from Indian Market MCP get_key_ratios."""
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient

        client = IndianMarketClient()
        return client.call_tool("get_key_ratios", {"symbol": symbol})
    except Exception as e:
        log.debug(f"Indian Market MCP failed for {symbol}: {e}")
        return None


def _yf_ticker(symbol: str):
    """Try yfinance with .NS then .BO suffix."""
    import yfinance as yf

    for suffix in (".NS", ".BO"):
        try:
            t = yf.Ticker(f"{symbol}{suffix}")
            info = t.info
            if info and (info.get("longName") or info.get("shortName") or info.get("trailingPE")):
                return t, info
        except Exception:
            continue
    return None, None


def _fetch_yfinance(symbol: str) -> dict | None:
    """Fetch from yfinance as last resort."""
    try:
        ticker, info = _yf_ticker(symbol)
        if not ticker or not info:
            return None
        return {
            "source": "yfinance",
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "enterprise_value": info.get("enterpriseValue"),
            "market_cap": info.get("marketCap"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "gross_margin": info.get("grossMargins"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "earnings_q_growth": info.get("earningsQuarterlyGrowth"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "free_cash_flow": info.get("freeCashflow"),
            "eps_trailing": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "book_value": info.get("bookValue"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "beta": info.get("beta"),
            "w52_high": info.get("fiftyTwoWeekHigh"),
            "w52_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "company_name": info.get("longName"),
            "employees": info.get("fullTimeEmployees"),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary", "")[:500],
        }
    except Exception as e:
        log.debug(f"yfinance failed for {symbol}: {e}")
        return None


def _fetch_company_profile(symbol: str) -> dict | None:
    """Fetch company profile for sector/industry."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        return client.call_tool("company_profile", {"symbol": symbol})
    except Exception:
        pass
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient

        client = IndianMarketClient()
        return client.call_tool("get_company_profile", {"symbol": symbol})
    except Exception:
        pass
    return None


# ── Data Normalizers ──


def _normalize_finstack(data: dict) -> dict:
    """Normalize FinStack nested structure to flat dict."""
    val = data.get("valuation", {})
    prof = data.get("profitability", {})
    grow = data.get("growth", {})
    health = data.get("financial_health", {})
    psh = data.get("per_share", {})
    div = data.get("dividend", {})
    return {
        "source": "finstack",
        "pe_trailing": safe_float(val.get("pe_trailing")),
        "pe_forward": safe_float(val.get("pe_forward")),
        "peg_ratio": safe_float(val.get("peg_ratio")),
        "price_to_book": safe_float(val.get("price_to_book")),
        "price_to_sales": safe_float(val.get("price_to_sales")),
        "ev_to_ebitda": safe_float(val.get("ev_to_ebitda")),
        "ev_to_revenue": safe_float(val.get("ev_to_revenue")),
        "enterprise_value": safe_int(val.get("enterprise_value")),
        "market_cap": safe_int(val.get("market_cap")),
        "profit_margin": safe_float(prof.get("profit_margin")),
        "operating_margin": safe_float(prof.get("operating_margin")),
        "gross_margin": safe_float(prof.get("gross_margin")),
        "ebitda_margin": safe_float(prof.get("ebitda_margin")),
        "roe": safe_float(prof.get("roe")),
        "roa": safe_float(prof.get("roa")),
        "revenue_growth": safe_float(grow.get("revenue_growth")),
        "earnings_growth": safe_float(grow.get("earnings_growth")),
        "earnings_q_growth": safe_float(grow.get("earnings_quarterly_growth")),
        "debt_to_equity": safe_float(health.get("debt_to_equity")),
        "current_ratio": safe_float(health.get("current_ratio")),
        "quick_ratio": safe_float(health.get("quick_ratio")),
        "total_debt": safe_int(health.get("total_debt")),
        "total_cash": safe_int(health.get("total_cash")),
        "free_cash_flow": safe_int(health.get("free_cash_flow")),
        "eps_trailing": safe_float(psh.get("eps_trailing")),
        "eps_forward": safe_float(psh.get("eps_forward")),
        "book_value": safe_float(psh.get("book_value")),
        "revenue_per_share": safe_float(psh.get("revenue_per_share")),
        "dividend_rate": safe_float(div.get("dividend_rate")),
        "dividend_yield": safe_float(div.get("dividend_yield")),
        "payout_ratio": safe_float(div.get("payout_ratio")),
        "ex_div_date": div.get("ex_dividend_date"),
    }


def _normalize_indian_market(data: dict) -> dict:
    """Normalize Indian Market MCP flat structure."""
    return {
        "source": "indian_market_mcp",
        "pe_trailing": safe_float(data.get("pe_trailing")),
        "pe_forward": safe_float(data.get("pe_forward")),
        "peg_ratio": safe_float(data.get("peg")),
        "price_to_book": safe_float(data.get("pb")),
        "price_to_sales": safe_float(data.get("ps")),
        "ev_to_ebitda": safe_float(data.get("ev_ebitda")),
        "ev_to_revenue": safe_float(data.get("ev_to_revenue")),
        "enterprise_value": safe_int(data.get("enterprise_value_cr")),
        "market_cap": safe_int(data.get("market_cap_cr")),
        "profit_margin": safe_float(data.get("profit_margin")),
        "operating_margin": safe_float(data.get("operating_margin")),
        "gross_margin": safe_float(data.get("gross_margin")),
        "roe": safe_float(data.get("roe")),
        "roa": safe_float(data.get("roa")),
        "revenue_growth": safe_float(data.get("revenue_growth")),
        "earnings_growth": safe_float(data.get("earnings_growth")),
        "debt_to_equity": safe_float(data.get("debt_to_equity")),
        "current_ratio": safe_float(data.get("current_ratio")),
        "quick_ratio": safe_float(data.get("quick_ratio")),
        "eps_trailing": safe_float(data.get("eps_trailing")),
        "eps_forward": safe_float(data.get("eps_forward")),
        "book_value": safe_float(data.get("book_value")),
        "dividend_yield": safe_float(data.get("dividend_yield")),
        "payout_ratio": safe_float(data.get("payout_ratio")),
        "beta": safe_float(data.get("beta")),
        "w52_high": safe_float(data.get("52w_high")),
        "w52_low": safe_float(data.get("52w_low")),
        "avg_volume": safe_int(data.get("avg_volume")),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "company_name": data.get("company"),
    }


# ── Public API ──


def fetch_fundamentals(symbol: str) -> dict | None:
    """Fetch fundamentals with cascade: FinStack -> Indian Market MCP -> yfinance.

    Returns normalized dict with PE, ROE, margins, growth, etc. or None.
    """
    # 1. FinStack
    data = _fetch_finstack(symbol)
    if data and isinstance(data, dict) and data.get("valuation"):
        return _normalize_finstack(data)

    # 2. Indian Market MCP
    data = _fetch_indian_market(symbol)
    if data and isinstance(data, dict) and data.get("pe_trailing"):
        return _normalize_indian_market(data)

    # 3. yfinance
    return _fetch_yfinance(symbol)


def fetch_profile(symbol: str) -> dict | None:
    """Fetch company profile (sector, industry, name)."""
    data = _fetch_company_profile(symbol)
    if data and isinstance(data, dict):
        return {
            "company_name": data.get("company") or data.get("longName"),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "description": (data.get("description") or data.get("longBusinessSummary", ""))[:500],
            "website": data.get("website"),
            "employees": safe_int(data.get("employees")),
            "shares_outstanding": safe_int(data.get("shares_outstanding")),
            "float_shares": safe_int(data.get("float_shares")),
        }
    # Fallback: yfinance
    try:
        ticker, info = _yf_ticker(symbol)
        if not ticker or not info:
            return None
        return {
            "company_name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": (info.get("longBusinessSummary", ""))[:500],
            "website": info.get("website"),
            "employees": safe_int(info.get("fullTimeEmployees")),
            "shares_outstanding": safe_int(info.get("sharesOutstanding")),
            "float_shares": safe_int(info.get("floatShares")),
        }
    except Exception:
        return None


def _upsert_key_ratios(engine, symbol: str, data: dict) -> None:
    """Upsert to key_ratios table using parameterized SQL."""
    values = {c: data.get(c) for c in KEY_RATIO_COLS}
    values["symbol"] = symbol
    values["updated_at"] = datetime.utcnow()

    placeholders = ", ".join(f":{k}" for k in values)
    columns = ", ".join(values.keys())
    update_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")

    sql = sa.text(
        f"INSERT INTO key_ratios ({columns}) VALUES ({placeholders}) ON CONFLICT (symbol) DO UPDATE SET {update_clause}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


def _upsert_company_profile(engine, symbol: str, data: dict) -> None:
    """Upsert to company_profile table."""
    values = {
        "symbol": symbol,
        "exchange": "NSE",
        "company_name": data.get("company_name"),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "description": data.get("description"),
        "website": data.get("website"),
        "employees": data.get("employees"),
        "shares_outstanding": data.get("shares_outstanding"),
        "float_shares": data.get("float_shares"),
        "updated_at": datetime.utcnow(),
    }

    placeholders = ", ".join(f":{k}" for k in values)
    columns = ", ".join(values.keys())
    update_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")

    sql = sa.text(
        f"INSERT INTO company_profile ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT (symbol) DO UPDATE SET {update_clause}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


def _get_universe_symbols(engine) -> list[str]:
    """Get all NSE symbols from cached_signals or instruments."""
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("SELECT DISTINCT symbol FROM cached_signals ORDER BY symbol"))
            symbols = [r[0] for r in result.fetchall()]
            if symbols:
                return symbols
        except Exception:
            pass
        try:
            result = conn.execute(sa.text("SELECT symbol FROM instruments ORDER BY symbol"))
            return [r[0] for r in result.fetchall()]
        except Exception:
            pass
    return []


def ingest_fundamentals(symbol: str, *, engine=None) -> bool:
    """Ingest fundamentals for a single symbol.

    Fetches data from the cascade (FinStack -> MCP -> yfinance) and
    upserts to key_ratios and company_profile tables.

    Returns True if data was found and stored.
    """
    engine = engine or get_engine()
    symbol = symbol.upper()

    profile = fetch_profile(symbol)
    if profile:
        _upsert_company_profile(engine, symbol, profile)

    ratios = fetch_fundamentals(symbol)
    if ratios:
        _upsert_key_ratios(engine, symbol, ratios)
        return True

    return bool(profile)


def ingest_all_fundamentals(
    *,
    recent: bool = True,
    batch_size: int = 50,
    sleep: float = 1.0,
) -> dict:
    """Batch ingestion for all symbols.

    Args:
        recent: If True, only ingest symbols from cached_signals.
        batch_size: How many symbols between progress logs.
        sleep: Seconds to sleep between batches.

    Returns:
        {"success": N, "failed": N, "skipped": N, "total": N}
    """
    engine = get_engine()
    symbols = _get_universe_symbols(engine)
    if not symbols:
        log.error("No symbols found. Run cache_signals.py first.")
        return {"success": 0, "failed": 0, "skipped": 0, "total": 0}

    log.info(f"Ingesting fundamentals for {len(symbols)} symbols")
    start = time.time()
    success = failed = skipped = 0

    for i, symbol in enumerate(symbols):
        try:
            ok = ingest_fundamentals(symbol, engine=engine)
            if ok:
                success += 1
            else:
                skipped += 1
        except KeyboardInterrupt:
            log.info("Interrupted.")
            break
        except Exception as e:
            log.warning(f"Error processing {symbol}: {e}")
            failed += 1

        if (i + 1) % batch_size == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(symbols) - i - 1) / rate if rate > 0 else 0
            log.info(
                f"  [{i + 1}/{len(symbols)}] success={success} failed={failed} "
                f"skipped={skipped} rate={rate:.1f}/s ETA={eta:.0f}s"
            )
            time.sleep(sleep)

    elapsed = time.time() - start
    log.info(f"Done in {elapsed:.1f}s: {success} success, {failed} failed, {skipped} skipped out of {len(symbols)}")
    return {"success": success, "failed": failed, "skipped": skipped, "total": len(symbols)}
