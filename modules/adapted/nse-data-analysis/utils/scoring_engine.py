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
scoring_engine.py
==================
Composite fundamental score (0-100) built from five weighted pillars:

  1. Valuation        (20 pts) - PE, PB vs absolute and sector-relative levels
  2. Profitability     (20 pts) - ROE, ROCE, profit margin
  3. Financial Stability(20 pts) - Debt/Equity, interest coverage, current ratio
  4. Growth & Trend     (25 pts) - multi-year revenue/profit CAGR, consistency, margin trend
  5. Valuation Upside   (15 pts) - blended intrinsic value vs current price

This replaces the original flat point-additions with bounded sub-scores per pillar,
so one strong metric can't single-handedly carry (or sink) the total, and every
pillar is visible to the user for transparency (no "black box" score).
"""


from utils.trend_analysis import compute_trends, trend_score


def safe(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    return default


# ---------------------------------------------------------------------------
# Pillar 1: Valuation (20 pts)
# ---------------------------------------------------------------------------


def score_valuation(info: dict, sector_median_pe: float | None = None) -> tuple[int, list[str]]:
    score = 0
    notes = []
    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    peg = info.get("pegRatio")

    if pe and pe > 0:
        if sector_median_pe and sector_median_pe > 0:
            relative = pe / sector_median_pe
            if relative < 0.8:
                score += 8
                notes.append("Trading below sector median PE")
            elif relative < 1.2:
                score += 5
            else:
                notes.append("Trading above sector median PE")
        else:
            if pe < 15:
                score += 8
            elif pe < 30:
                score += 5
    elif pe and pe < 0:
        notes.append("Negative earnings (PE not meaningful)")

    if pb and pb > 0:
        if pb < 1.5:
            score += 7
            notes.append("Trading near/below book value")
        elif pb < 4:
            score += 4

    if peg and 0 < peg < 1.5:
        score += 5
        notes.append("Attractive PEG ratio")

    return min(20, score), notes


# ---------------------------------------------------------------------------
# Pillar 2: Profitability (20 pts)
# ---------------------------------------------------------------------------


def score_profitability(info: dict) -> tuple[int, list[str]]:
    score = 0
    notes = []

    roe = safe(info.get("returnOnEquity")) * 100
    safe(info.get("returnOnAssets")) * 100
    margin = safe(info.get("profitMargins")) * 100
    operating_margin = safe(info.get("operatingMargins")) * 100

    if roe > 20:
        score += 9
        notes.append(f"Excellent ROE ({roe:.1f}%)")
    elif roe > 15:
        score += 7
        notes.append(f"Strong ROE ({roe:.1f}%)")
    elif roe > 10:
        score += 4

    if margin > 15:
        score += 7
        notes.append(f"High net margin ({margin:.1f}%)")
    elif margin > 8:
        score += 4
        notes.append(f"Healthy net margin ({margin:.1f}%)")

    if operating_margin > 20:
        score += 4
    elif operating_margin > 10:
        score += 2

    return min(20, score), notes


# ---------------------------------------------------------------------------
# Pillar 3: Financial Stability (20 pts)
# ---------------------------------------------------------------------------


def score_stability(info: dict) -> tuple[int, list[str]]:
    score = 0
    notes = []

    debt_to_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")
    quick_ratio = info.get("quickRatio")

    sector = (info.get("sector") or "").lower()
    is_financial = "financial" in sector or "bank" in sector

    if debt_to_equity is not None:
        # Note: yfinance debtToEquity is often expressed as a percentage (e.g. 45.2 = 0.452x)
        de_ratio = debt_to_equity / 100 if debt_to_equity > 5 else debt_to_equity
        if is_financial:
            # Banks/NBFCs are inherently leveraged businesses; D/E isn't a useful stability signal here
            score += 10
            notes.append("Leverage ratio not directly comparable (financial sector)")
        else:
            if de_ratio < 0.3:
                score += 12
                notes.append("Very low debt")
            elif de_ratio < 0.8:
                score += 8
                notes.append("Manageable debt level")
            elif de_ratio < 1.5:
                score += 3
            else:
                notes.append("High leverage")

    if current_ratio is not None and not is_financial:
        if current_ratio > 1.5:
            score += 5
            notes.append("Strong liquidity position")
        elif current_ratio > 1.0:
            score += 3

    if quick_ratio is not None and not is_financial and quick_ratio > 1.0:
        score += 3

    return min(20, score), notes


# ---------------------------------------------------------------------------
# Pillar 4: Growth & Trend Quality (25 pts) — wraps trend_analysis module
# ---------------------------------------------------------------------------


def score_growth(info: dict, financials) -> tuple[int, list[str], dict]:
    trends = compute_trends(financials)
    raw_score, notes = trend_score(trends)  # raw_score is 0-100
    scaled = round(raw_score / 100 * 25)

    # Fallback to point-in-time growth fields if multi-year statement data is unavailable
    if trends.get("years_available", 0) < 2:
        rev_growth = safe(info.get("revenueGrowth")) * 100
        earn_growth = safe(info.get("earningsGrowth")) * 100
        fallback_score = 0
        if rev_growth > 10:
            fallback_score += 12
            notes.append(f"Positive YoY revenue growth ({rev_growth:.1f}%)")
        if earn_growth > 10:
            fallback_score += 13
            notes.append(f"Positive YoY earnings growth ({earn_growth:.1f}%)")
        scaled = max(scaled, min(25, fallback_score))

    return min(25, scaled), notes, trends


# ---------------------------------------------------------------------------
# Pillar 5: Valuation Upside (15 pts) — wraps valuation module's blended estimate
# ---------------------------------------------------------------------------


def score_valuation_upside(blended: dict) -> tuple[int, list[str]]:
    score = 0
    notes = []

    if not blended or blended.get("models_used", 0) == 0:
        return 0, ["Insufficient data for intrinsic value estimate"]

    # Recompute an approximate upside from blended value vs current price is done upstream;
    # this function expects an 'upside_pct' key to already be attached by the caller.
    upside_pct = blended.get("upside_pct")

    if upside_pct is None:
        return 0, notes

    if upside_pct > 25:
        score = 15
        notes.append(f"Significant estimated undervaluation (~{upside_pct:.0f}%)")
    elif upside_pct > 10:
        score = 10
        notes.append(f"Modest estimated undervaluation (~{upside_pct:.0f}%)")
    elif upside_pct > -10:
        score = 6
    else:
        notes.append(f"Appears overvalued vs blended intrinsic estimate (~{upside_pct:.0f}%)")

    return score, notes


# ---------------------------------------------------------------------------
# Master composite score
# ---------------------------------------------------------------------------


def composite_score(
    info: dict, financials, blended_valuation: dict, sector_median_pe: float | None = None
) -> dict:
    v_score, v_notes = score_valuation(info, sector_median_pe)
    p_score, p_notes = score_profitability(info)
    s_score, s_notes = score_stability(info)
    g_score, g_notes, trends = score_growth(info, financials)
    u_score, u_notes = score_valuation_upside(blended_valuation)

    total = v_score + p_score + s_score + g_score + u_score
    all_notes = v_notes + p_notes + s_notes + g_notes + u_notes

    if total >= 75:
        rating = "🟢 STRONG BUY"
    elif total >= 60:
        rating = "🟢 BUY"
    elif total >= 45:
        rating = "🟡 HOLD"
    elif total >= 30:
        rating = "🟠 WEAK"
    else:
        rating = "🔴 AVOID"

    return {
        "total_score": total,
        "rating": rating,
        "pillar_scores": {
            "Valuation": v_score,
            "Profitability": p_score,
            "Stability": s_score,
            "Growth": g_score,
            "Valuation Upside": u_score,
        },
        "notes": all_notes,
        "trends": trends,
    }
