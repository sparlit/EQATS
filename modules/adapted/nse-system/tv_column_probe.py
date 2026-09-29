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
TradingView column probe — finds which fundamental fields TV's India
scanner actually returns non-null values for.

Tests a wide set of column names against ~30 NSE mid-caps. Reports:
  - accepted (any non-null value)
  - rejected (TV doesn't recognise the column name)
  - empty (column accepted but all values null)

Usage: python tv_column_probe.py
"""
import json
import time

import requests

URL = "https://scanner.tradingview.com/india/scan"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Sample universe - liquid NSE names across caps & sectors
SAMPLE = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
    "ITC",
    "LT",
    "SUNPHARMA",
    "MARUTI",
    "ASIANPAINT",
    "BAJFINANCE",
    "TITAN",
    "DIXON",
    "POLYCAB",
    "KEI",
    "ASTRAL",
    "PIIND",
    "PERSISTENT",
    "KPITTECH",
    "TATAELXSI",
    "SYNGENE",
    "ALKEM",
    "APARINDS",
    "GRANULES",
    "JBCHEPHARM",
    "NAVINFLUOR",
    "TATAINVEST",
]

# All plausible column names. Grouped for readability.
CANDIDATE_COLUMNS = [
    # ---- Basic ----
    "name",
    "description",
    "close",
    "open",
    "high",
    "low",
    "volume",
    "market_cap_basic",
    # ---- Valuation ----
    "price_earnings_ttm",
    "price_earnings_forward",
    "price_earnings_fq",
    "price_earnings_fy",
    "price_to_book",
    "price_to_book_fq",
    "price_to_book_fy",
    "price_to_sales_ttm",
    "price_to_sales_fq",
    "price_to_cash_fq",
    "price_to_cash_fy",
    "enterprise_value_ebitda_ttm",
    "enterprise_value_ebitda_fq",
    "ev_to_revenue_fq",
    "ev_to_revenue_ttm",
    # ---- Profitability — quarterly ----
    "return_on_equity_fq",
    "return_on_assets_fq",
    "return_on_invested_capital_fq",
    "return_on_invested_capital",
    "return_on_equity",
    "return_on_assets",
    "gross_margin_fq",
    "gross_margin",
    "operating_margin_fq",
    "operating_margin",
    "net_margin_fq",
    "net_margin",
    "pretax_margin_fq",
    "pretax_margin",
    "ebitda_margin_fq",
    # ---- Profitability — annual ----
    "return_on_equity_fy",
    "return_on_assets_fy",
    "return_on_invested_capital_fy",
    "gross_margin_fy",
    "operating_margin_fy",
    "net_margin_fy",
    # ---- Debt ----
    "debt_to_equity_fq",
    "debt_to_equity_fy",
    "debt_to_equity",
    "debt_to_assets_fq",
    "total_debt_fq",
    "total_debt_fy",
    "total_debt_to_ebitda_fq",
    "net_debt_fq",
    "net_debt_fy",
    "cash_and_equivalents_fq",
    "cash_and_equivalents_fy",
    # ---- Growth ----
    "revenue_growth_fy",
    "revenue_growth_yoy",
    "revenue_growth_3y",
    "revenue_growth_5y",
    "revenue_growth_qoq",
    "net_income_growth_fy",
    "net_income_growth_yoy",
    "net_income_growth_3y",
    "net_income_growth_5y",
    "net_income_growth_qoq",
    "eps_growth_fy",
    "eps_growth_yoy",
    "eps_growth_3y",
    "eps_growth_5y",
    # ---- Cash flow ----
    "free_cash_flow_fq",
    "free_cash_flow_fy",
    "operating_cash_flow_fq",
    "operating_cash_flow_fy",
    "cash_from_operations_fq",
    "cash_from_operations_fy",
    "capital_expenditures_fq",
    "capital_expenditures_fy",
    # ---- Shareholding ----
    "held_percent_insiders",
    "held_percent_institutions",
    "held_percent_public",
    "insiders_ownership_percent",
    "institutions_ownership_percent",
    # ---- Dividends ----
    "dividend_yield_recent",
    "dividend_yield_fy",
    "dividends_yield",
    "payout_ratio_fq",
    "payout_ratio_fy",
    # ---- Size / liquidity ----
    "average_volume_10d_calc",
    "average_volume_30d_calc",
    "relative_volume_10d_calc",
    "float_shares_outstanding",
    "total_shares_outstanding",
    "shares_outstanding",
    # ---- Per-share ----
    "earnings_per_share_fq",
    "earnings_per_share_fy",
    "earnings_per_share_diluted_fq",
    "book_value_per_share_fq",
    "book_value_per_share_fy",
    # ---- Sector / industry ----
    "sector",
    "industry",
    "sector.tr",
    "industry.tr",
    # ---- Beta / risk ----
    "beta_1_year",
    "beta_3_year",
]


def _post_batch(tickers, columns):
    body = {"symbols": {"tickers": tickers}, "columns": columns}
    try:
        r = requests.post(URL, headers=HEADERS, json=body, timeout=40)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  HTTP error: {e}")
        return None


def main():
    tickers = ["NSE:" + s for s in SAMPLE]
    print(f"[PROBE] {len(tickers)} sample symbols, {len(CANDIDATE_COLUMNS)} candidate columns")
    print()

    data = _post_batch(tickers, CANDIDATE_COLUMNS)
    if data is None:
        print("TradingView request failed. Retry.")
        return

    # Build a per-column hit counter
    stats = {col: {"non_null": 0, "non_zero": 0, "sample": None} for col in CANDIDATE_COLUMNS}

    for item in data:
        d = item.get("d", [])
        if len(d) != len(CANDIDATE_COLUMNS):
            # column was rejected — TV returns fewer fields
            continue
        for i, col in enumerate(CANDIDATE_COLUMNS):
            v = d[i]
            if v is None:
                continue
            stats[col]["non_null"] += 1
            if isinstance(v, (int, float)) and v != 0:
                stats[col]["non_zero"] += 1
            if stats[col]["sample"] is None:
                stats[col]["sample"] = v

    print(f"{'COLUMN':<40} {'NON-NULL':<10} {'NON-ZERO':<10} SAMPLE")
    print("-" * 90)
    for col in CANDIDATE_COLUMNS:
        s = stats[col]
        marker = "✓" if s["non_zero"] > 0 else ("~" if s["non_null"] > 0 else "✗")
        sample_str = str(s["sample"])[:30] if s["sample"] is not None else ""
        print(f"{col:<40} {s['non_null']:<10} {s['non_zero']:<10} {marker}  {sample_str}")

    print()
    print("Legend: ✓ returns real values  ~ accepted but null ✗ column name rejected")
    print()

    # Summary lists
    working = [c for c in CANDIDATE_COLUMNS if stats[c]["non_zero"] > 0]
    print(f"[PROBE] {len(working)} columns return real values.")
    print()
    print("Working columns:")
    for c in working:
        print(f"  {c}  (sample: {stats[c]['sample']})")


if __name__ == "__main__":
    main()
