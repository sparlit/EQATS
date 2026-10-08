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
analyzer.py
===========
Single source of truth for "take a fetched stock's raw data and turn it into
a scored row + deep-dive dict." Previously this logic was duplicated between
app/main.py (the bulk screener loop) and scripts/export_daily.py — any fix to
one would silently drift from the other. Both now call analyze_stock() here.

This is also what makes ad-hoc single-stock search possible: searching one
symbol that isn't in the Nifty 500 list runs through the exact same pipeline
as a bulk run, just for n=1, and its result merges into the same JSON export.
"""


from utils.data_fetcher import FetchResult
from utils.scoring_engine import composite_score, safe
from utils.trend_analysis import compute_trends
from utils.valuation import blended_intrinsic_value, graham_number, relative_valuation, simple_dcf


def analyze_stock(
    symbol: str,
    fr: FetchResult,
    sector_median_pe: float | None = None,
    sector_median_pb: float | None = None,
) -> dict | None:
    """
    Runs the full analysis pipeline (trends, DCF, Graham, relative valuation,
    composite score) on one already-fetched stock.

    Returns None if the fetch itself failed (caller should report fr.error).
    Otherwise returns a dict with two keys:
      - "row": flat dict matching the screener table's columns (for a DataFrame row)
      - "deep": nested dict for the deep-dive view / JSON export (info, trends, dcf, etc.)

    Pass sector_median_pe/pb when available (i.e. after a bulk run establishes sector
    medians) for sector-aware relative valuation; omit for a standalone single-stock
    search where no peer set exists yet — relative valuation will just report
    "insufficient data" rather than guessing.
    """
    if not fr.ok:
        return None

    info = fr.info
    trends = compute_trends(fr.financials)

    dcf = simple_dcf(fr.cashflow, info, growth_rate_yr1_5=trends.get("revenue_cagr"))
    graham = graham_number(info)
    relative = relative_valuation(info, sector_median_pe, sector_median_pb)
    blended = blended_intrinsic_value(dcf, graham, relative)

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if blended.get("blended_value") and current_price:
        blended["upside_pct"] = round(
            (blended["blended_value"] - current_price) / current_price * 100, 1
        )
    else:
        blended["upside_pct"] = None

    result = composite_score(info, fr.financials, blended, sector_median_pe=sector_median_pe)

    row = {
        "Symbol": symbol,
        "Company": info.get("longName", symbol),
        "Sector": info.get("sector", "Unknown"),
        "Industry": info.get("industry", "Unknown"),
        "Price": current_price,
        "PE": info.get("trailingPE"),
        "PB": info.get("priceToBook"),
        "ROE %": round(safe(info.get("returnOnEquity")) * 100, 2),
        "Debt/Equity": info.get("debtToEquity"),
        "Profit Margin %": round(safe(info.get("profitMargins")) * 100, 2),
        "Revenue CAGR %": round(trends.get("revenue_cagr"), 1)
        if trends.get("revenue_cagr") is not None
        else None,
        "Net Income CAGR %": round(trends.get("net_income_cagr"), 1)
        if trends.get("net_income_cagr") is not None
        else None,
        "Margin Trend": trends.get("margin_trend"),
        "Blended Fair Value": blended.get("blended_value"),
        "Est. Upside %": blended.get("upside_pct"),
        "Valuation Models Used": blended.get("models_used"),
        "Score": result["total_score"],
        "Rating": result["rating"],
        "Valuation Pillar": result["pillar_scores"]["Valuation"],
        "Profitability Pillar": result["pillar_scores"]["Profitability"],
        "Stability Pillar": result["pillar_scores"]["Stability"],
        "Growth Pillar": result["pillar_scores"]["Growth"],
        "Upside Pillar": result["pillar_scores"]["Valuation Upside"],
        "Strengths": ", ".join(result["notes"][:4]),
    }

    deep = {
        "info": info,
        "trends": trends,
        "dcf": dcf,
        "graham": graham,
        "relative": relative,
        "blended": blended,
        "result": result,
        "fetch": fr,
    }

    return {"row": row, "deep": deep}


def refine_with_sector_context(
    symbol: str, deep: dict, sector_median_pe: float | None, sector_median_pb: float | None
) -> dict:
    """
    Re-runs relative valuation + composite score once real sector medians are known
    (i.e. after a bulk run, or after merging a single-stock search into an existing
    universe so it gets a peer group). Mutates and returns the same `deep` dict's
    relevant keys, plus a fresh `row` patch dict for the few fields that change.
    """
    info = deep["info"]
    relative = relative_valuation(info, sector_median_pe, sector_median_pb)
    blended = blended_intrinsic_value(deep["dcf"], deep["graham"], relative)

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if blended.get("blended_value") and current_price:
        blended["upside_pct"] = round(
            (blended["blended_value"] - current_price) / current_price * 100, 1
        )

    result = composite_score(
        info, deep["fetch"].financials, blended, sector_median_pe=sector_median_pe
    )

    deep["relative"] = relative
    deep["blended"] = blended
    deep["result"] = result

    row_patch = {
        "Score": result["total_score"],
        "Rating": result["rating"],
        "Blended Fair Value": blended.get("blended_value"),
        "Est. Upside %": blended.get("upside_pct"),
        "Valuation Pillar": result["pillar_scores"]["Valuation"],
        "Profitability Pillar": result["pillar_scores"]["Profitability"],
        "Stability Pillar": result["pillar_scores"]["Stability"],
        "Growth Pillar": result["pillar_scores"]["Growth"],
        "Upside Pillar": result["pillar_scores"]["Valuation Upside"],
        "Strengths": ", ".join(result["notes"][:4]),
    }

    return row_patch
