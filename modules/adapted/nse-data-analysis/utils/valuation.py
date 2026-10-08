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
valuation.py
============
Intrinsic value estimation. Implements three independent models so the user
sees a range rather than a single fragile number:

1. Simplified Discounted Cash Flow (DCF) on Free Cash Flow to Firm
2. Graham Number (Benjamin Graham's conservative intrinsic value formula)
3. Relative valuation vs sector median (PE/PB based fair value)

IMPORTANT HONESTY NOTE (surfaced in the UI, not just here):
Any DCF built on 2-4 years of public data and generic assumptions is a rough
estimate, not a precise valuation. Real equity research desks spend days per
company on this. This tool is meant to flag "cheap vs expensive on a few
reasonable assumptions," not to be taken as a price target.
"""


import numpy as np
import pandas as pd


def _get_row(df: pd.DataFrame, candidates: list[str]) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def _latest_value(row: pd.Series | None) -> float | None:
    if row is None or row.empty:
        return None
    cols_sorted = sorted(row.index, key=lambda c: pd.Timestamp(c), reverse=True)
    val = row.get(cols_sorted[0])
    return float(val) if pd.notna(val) else None


# ---------------------------------------------------------------------------
# 1. Simplified DCF
# ---------------------------------------------------------------------------


def simple_dcf(
    cashflow: pd.DataFrame | None,
    info: dict,
    growth_rate_yr1_5: float | None = None,
    terminal_growth: float = 4.0,
    discount_rate: float = 11.0,
    projection_years: int = 5,
) -> dict:
    """
    Two-stage DCF on Free Cash Flow (Operating Cash Flow - CapEx):
      Stage 1: explicit projection_years at growth_rate_yr1_5
      Stage 2: terminal value via Gordon Growth at terminal_growth

    Defaults: discount_rate=11% (typical for large-cap India equity COE),
    terminal_growth=4% (roughly long-run nominal GDP growth ceiling for terminal value).
    growth_rate_yr1_5 defaults to the company's own historical FCF/revenue growth if available,
    capped at 20% to avoid wildly optimistic extrapolation.
    """
    result = {
        "fair_value_per_share": None,
        "current_fcf": None,
        "assumptions": {
            "growth_rate_yr1_5": growth_rate_yr1_5,
            "terminal_growth": terminal_growth,
            "discount_rate": discount_rate,
            "projection_years": projection_years,
        },
        "warning": None,
    }

    op_cf_row = _get_row(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
    capex_row = _get_row(cashflow, ["Capital Expenditure", "Capital Expenditures"])

    op_cf = _latest_value(op_cf_row)
    capex = _latest_value(capex_row)

    shares_out = info.get("sharesOutstanding")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    if op_cf is None or shares_out is None or not shares_out:
        result["warning"] = (
            "Insufficient cash flow data for DCF (common for banks/NBFCs — use P/B or P/E based valuation instead)."
        )
        return result

    fcf = op_cf - abs(capex) if capex is not None else op_cf * 0.7  # rough capex haircut if missing
    result["current_fcf"] = fcf

    if fcf <= 0:
        result["warning"] = (
            "Negative or zero free cash flow — DCF not meaningful for this company currently."
        )
        return result

    if growth_rate_yr1_5 is None:
        growth_rate_yr1_5 = 10.0  # conservative default
    growth_rate_yr1_5 = min(max(growth_rate_yr1_5, -10), 20)  # sanity cap

    g1 = growth_rate_yr1_5 / 100
    g_term = terminal_growth / 100
    r = discount_rate / 100

    if r <= g_term:
        result["warning"] = "Discount rate must exceed terminal growth rate; valuation skipped."
        return result

    pv_sum = 0.0
    projected_fcf = fcf
    for yr in range(1, projection_years + 1):
        projected_fcf *= 1 + g1
        pv_sum += projected_fcf / ((1 + r) ** yr)

    terminal_value = (projected_fcf * (1 + g_term)) / (r - g_term)
    pv_terminal = terminal_value / ((1 + r) ** projection_years)

    enterprise_value = pv_sum + pv_terminal

    total_debt = info.get("totalDebt") or 0
    total_cash = info.get("totalCash") or 0
    equity_value = enterprise_value - total_debt + total_cash

    fair_value_per_share = equity_value / shares_out

    # Sanity check: if the DCF output is off by an order of magnitude or more from the current
    # market price, this is far more likely a data-quality issue (e.g. stale/incorrect
    # sharesOutstanding from the API) than a genuine 10x+ mispricing. Flag rather than display.
    if current_price and current_price > 0:
        ratio = fair_value_per_share / current_price
        if ratio < 0.1 or ratio > 10:
            result["warning"] = (
                f"DCF output (₹{fair_value_per_share:.2f}) is implausibly far from current price "
                f"(₹{current_price:.2f}) — likely a data quality issue (e.g. shares outstanding) "
                f"rather than a genuine valuation gap. Treat with caution."
            )

    result["fair_value_per_share"] = round(fair_value_per_share, 2)
    result["enterprise_value"] = enterprise_value
    result["equity_value"] = equity_value

    if current_price:
        result["upside_pct"] = round(
            (fair_value_per_share - current_price) / current_price * 100, 1
        )

    return result


# ---------------------------------------------------------------------------
# 2. Graham Number
# ---------------------------------------------------------------------------


def graham_number(info: dict) -> dict:
    """
    Benjamin Graham's formula: sqrt(22.5 x EPS x Book Value per Share).
    The 22.5 constant implies a max acceptable PE of 15 and max P/B of 1.5 simultaneously
    — a deliberately conservative ceiling, not a target price.
    """
    eps = info.get("trailingEps")
    book_value = info.get("bookValue")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    result = {"graham_value": None, "upside_pct": None, "warning": None}

    if eps is None or book_value is None or eps <= 0 or book_value <= 0:
        result["warning"] = (
            "Graham Number requires positive EPS and Book Value (not meaningful for loss-making companies)."
        )
        return result

    value = (22.5 * eps * book_value) ** 0.5
    result["graham_value"] = round(value, 2)

    if current_price:
        result["upside_pct"] = round((value - current_price) / current_price * 100, 1)

    return result


# ---------------------------------------------------------------------------
# 3. Relative (peer-multiple) valuation
# ---------------------------------------------------------------------------


def relative_valuation(
    info: dict, sector_median_pe: float | None, sector_median_pb: float | None
) -> dict:
    """
    Fair value implied by applying the sector's median PE and PB multiples
    to this company's own EPS / Book Value. Useful sanity check against DCF/Graham,
    especially for financials where DCF on FCF doesn't apply well.
    """
    result = {"fair_value_pe_based": None, "fair_value_pb_based": None, "warning": None}

    eps = info.get("trailingEps")
    book_value = info.get("bookValue")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    if eps and sector_median_pe and eps > 0:
        fv_pe = eps * sector_median_pe
        result["fair_value_pe_based"] = round(fv_pe, 2)
        if current_price:
            result["upside_pct_pe"] = round((fv_pe - current_price) / current_price * 100, 1)

    if book_value and sector_median_pb and book_value > 0:
        fv_pb = book_value * sector_median_pb
        result["fair_value_pb_based"] = round(fv_pb, 2)
        if current_price:
            result["upside_pct_pb"] = round((fv_pb - current_price) / current_price * 100, 1)

    if result["fair_value_pe_based"] is None and result["fair_value_pb_based"] is None:
        result["warning"] = "Insufficient peer multiple data for relative valuation."

    return result


def blended_intrinsic_value(dcf_result: dict, graham_result: dict, relative_result: dict) -> dict:
    """
    Averages whichever valuation estimates are actually available into a single
    'blended fair value' band, clearly showing how many models contributed.
    Never silently fabricates a number from zero valid inputs.
    """
    values = []
    # Exclude DCF if it was flagged as implausible (likely a data-quality artifact, not a real signal)
    dcf_fv = dcf_result.get("fair_value_per_share")
    dcf_flagged = bool(dcf_result.get("warning")) and dcf_fv is not None
    if dcf_fv and not dcf_flagged:
        values.append(dcf_fv)
    if graham_result.get("graham_value"):
        values.append(graham_result["graham_value"])
    if relative_result.get("fair_value_pe_based"):
        values.append(relative_result["fair_value_pe_based"])
    if relative_result.get("fair_value_pb_based"):
        values.append(relative_result["fair_value_pb_based"])

    if not values:
        return {"blended_value": None, "models_used": 0, "low": None, "high": None}

    return {
        "blended_value": round(float(np.mean(values)), 2),
        "models_used": len(values),
        "low": round(min(values), 2),
        "high": round(max(values), 2),
    }
