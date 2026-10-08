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
trend_analysis.py
==================
Multi-year fundamental trend analysis: revenue, net profit, operating margin,
and EPS trends derived from yfinance's annual financial statements
(typically 4 years of history available).

All functions are defensive: missing rows/columns return None/NaN rather than raising,
since real-world financial statements from yfinance are inconsistently populated
across companies (banks/NBFCs report differently from manufacturers, for instance).
"""


import pandas as pd


def _get_row(df: pd.DataFrame, candidates: list[str]) -> pd.Series | None:
    """yfinance row labels vary slightly across statement versions; try a list of aliases."""
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def cagr(first: float, last: float, periods: float) -> float | None:
    """Compound annual growth rate. Returns None if inputs are invalid (e.g. negative base)."""
    if first is None or last is None or periods <= 0:
        return None
    if first <= 0 or last <= 0:
        return None
    try:
        return ((last / first) ** (1 / periods) - 1) * 100
    except (ZeroDivisionError, ValueError):
        return None


def compute_trends(financials: pd.DataFrame | None) -> dict:
    """
    Computes multi-year trend metrics from an annual financials statement.

    yfinance's `financials` DataFrame has years as columns (most recent first)
    and line items as the index. Returns a dict with:
      - revenue_series, net_income_series, operating_margin_series (as lists, oldest->newest)
      - revenue_cagr, net_income_cagr (over the available window, typically 3-4 yrs)
      - revenue_growth_consistency: fraction of YoY periods with positive growth
      - margin_trend: 'expanding' / 'contracting' / 'stable' / 'unknown'
    """
    result = {
        "years_available": 0,
        "revenue_series": [],
        "net_income_series": [],
        "operating_margin_series": [],
        "revenue_cagr": None,
        "net_income_cagr": None,
        "revenue_growth_consistency": None,
        "margin_trend": "unknown",
    }

    if financials is None or financials.empty:
        return result

    revenue_row = _get_row(financials, ["Total Revenue", "TotalRevenue", "Revenue"])
    net_income_row = _get_row(
        financials, ["Net Income", "NetIncome", "Net Income Common Stockholders"]
    )
    operating_income_row = _get_row(financials, ["Operating Income", "OperatingIncome", "EBIT"])

    if revenue_row is None:
        return result

    # yfinance columns are usually most-recent-first; reverse to chronological order
    cols = list(revenue_row.index)
    cols_sorted = sorted(cols, key=lambda c: pd.Timestamp(c))
    revenue_series = [revenue_row.get(c) for c in cols_sorted]
    revenue_series = [float(v) if pd.notna(v) else None for v in revenue_series]

    net_income_series = []
    if net_income_row is not None:
        net_income_series = [net_income_row.get(c) for c in cols_sorted]
        net_income_series = [float(v) if pd.notna(v) else None for v in net_income_series]

    operating_margin_series = []
    if operating_income_row is not None:
        for c in cols_sorted:
            rev = revenue_row.get(c)
            op = operating_income_row.get(c)
            if pd.notna(rev) and pd.notna(op) and rev:
                operating_margin_series.append(round(float(op) / float(rev) * 100, 2))
            else:
                operating_margin_series.append(None)

    result["years_available"] = len(cols_sorted)
    result["revenue_series"] = revenue_series
    result["net_income_series"] = net_income_series
    result["operating_margin_series"] = operating_margin_series

    valid_rev = [v for v in revenue_series if v is not None]
    if len(valid_rev) >= 2:
        result["revenue_cagr"] = cagr(valid_rev[0], valid_rev[-1], len(valid_rev) - 1)

        yoy_growth = []
        for i in range(1, len(valid_rev)):
            if valid_rev[i - 1]:
                yoy_growth.append(valid_rev[i] > valid_rev[i - 1])
        if yoy_growth:
            result["revenue_growth_consistency"] = round(sum(yoy_growth) / len(yoy_growth) * 100, 1)

    valid_ni = [v for v in net_income_series if v is not None]
    if len(valid_ni) >= 2 and valid_ni[0] > 0:
        result["net_income_cagr"] = cagr(valid_ni[0], valid_ni[-1], len(valid_ni) - 1)

    valid_margins = [v for v in operating_margin_series if v is not None]
    if len(valid_margins) >= 2:
        delta = valid_margins[-1] - valid_margins[0]
        if delta > 1.5:
            result["margin_trend"] = "expanding"
        elif delta < -1.5:
            result["margin_trend"] = "contracting"
        else:
            result["margin_trend"] = "stable"

    return result


def trend_score(trends: dict) -> tuple[int, list[str]]:
    """
    Scores trend quality on a 0-100 scale based on growth consistency, CAGR magnitude,
    and margin direction. Used as one pillar in the overall fundamental score.
    """
    score = 0
    notes = []

    rev_cagr = trends.get("revenue_cagr")
    ni_cagr = trends.get("net_income_cagr")
    consistency = trends.get("revenue_growth_consistency")
    margin_trend = trends.get("margin_trend")

    if rev_cagr is not None:
        if rev_cagr > 15:
            score += 30
            notes.append(f"Strong revenue CAGR ({rev_cagr:.1f}%)")
        elif rev_cagr > 8:
            score += 20
            notes.append(f"Healthy revenue CAGR ({rev_cagr:.1f}%)")
        elif rev_cagr > 0:
            score += 10
        else:
            notes.append(f"Declining revenue trend ({rev_cagr:.1f}%)")

    if ni_cagr is not None:
        if ni_cagr > 15:
            score += 30
            notes.append(f"Strong profit CAGR ({ni_cagr:.1f}%)")
        elif ni_cagr > 8:
            score += 20
        elif ni_cagr > 0:
            score += 10
        else:
            notes.append("Profit growth declining/negative")

    if consistency is not None:
        if consistency >= 75:
            score += 20
            notes.append("Consistent YoY growth")
        elif consistency >= 50:
            score += 10

    if margin_trend == "expanding":
        score += 20
        notes.append("Margins expanding")
    elif margin_trend == "stable":
        score += 10

    return min(100, score), notes
