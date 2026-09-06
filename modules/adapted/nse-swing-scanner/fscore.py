"""
fscore.py
Self-computed Piotroski F-Score (0-9) from yfinance annual financial statements,
plus a coarse 5-year-average P/E reconstruction and basic quality ratios.

Verified live against RELIANCE.NS: yfinance returns 5 years of annual income
statement, balance sheet, and cash flow data for large-cap NSE names — enough
for the standard 2-consecutive-year Piotroski comparison.

Confidence notes:
- F-score components: high confidence in the formulas (standard Piotroski 2000
  methodology). Moderate confidence in yfinance line-item completeness for
  smaller/mid-cap names — some rows (e.g. "Long Term Debt") are occasionally
  missing or renamed between reporting periods, handled via .get() with NaN
  fallback below. A missing component costs that 1 point rather than crashing.
- 5Y avg P/E: LOW-MODERATE confidence as an approximation. True methodology
  needs a rolling monthly/quarterly P/E series. Here we only have ~5 ANNUAL
  EPS figures, so we approximate by pairing each fiscal year-end EPS with the
  closing price nearest that date. This is coarser than what a paid data
  vendor or a Screener.in scrape would give you. Treat this field as
  directional, not precise — flag any borderline "20% cheaper than 5Y avg"
  call for manual verification before acting on it.

CONFIRMED LIVE BUG (high confidence - reproduced against INFY.NS): for Indian
companies that are ALSO ADR-listed in the US (Infosys/INFY, Wipro/WIT, ICICI
Bank/IBN, HDFC Bank/HDB, Dr Reddy's/RDY, etc.), yfinance's financials table
sometimes returns Diluted/Basic EPS in USD (the ADR-filing figure) while the
.NS price history is in INR. Dividing price by EPS then gives a P/E inflated
by roughly the INR/USD exchange rate (~70-90x too high). Reproduced: INFY.NS
diluted EPS returned as 0.80 (matches ~Rs 65 real EPS / ~83 INR-USD), against
an INR price series - computed "P/E" of 1779 vs a real trailingPE of ~15.
approx_5y_avg_pe() below cross-checks against t.info['trailingPE'] and
refuses to return a value if they diverge by more than 3x, rather than
silently returning a corrupted number. This guard is a patch, not a fix -
always spot-check any ADR-listed name's fundamentals against Screener.in
before trusting them.
"""

import numpy as np
import pandas as pd
import yfinance as yf

from cache import cached_call
from settings import YF_CACHE_TTL_SECONDS, YF_FUNDAMENTAL_CACHE_TTL_SECONDS
from yf_retry import call_with_retry, is_rate_limit_error, should_cache_yf_payload


def _safe_get(df: pd.DataFrame, row_names, col) -> float:
    """Try multiple possible row-label spellings (yfinance labels drift across versions)."""
    if df is None or df.empty:
        return np.nan
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if pd.notna(val):
                return float(val)
    return np.nan


def _compute_fscore_impl(yf_ticker: str) -> dict:
    """Implementation behind the cached_call wrapper. See compute_fscore."""
    t = yf.Ticker(yf_ticker)
    try:
        def _stmts():
            return t.financials, t.balance_sheet, t.cashflow

        fin, bs, cf = call_with_retry(
            _stmts,
            max_attempts=3,
            base_delay_s=2.0,
            is_retryable=is_rate_limit_error,
        )
    except Exception as e:
        return {"yf_ticker": yf_ticker, "error": f"fetch_failed: {e}", "f_score": None}

    if fin is None or fin.empty or bs is None or bs.empty or cf is None or cf.empty:
        return {"yf_ticker": yf_ticker, "error": "no_financial_statements", "f_score": None}

    cols = sorted(fin.columns, reverse=True)  # most recent first
    if len(cols) < 2:
        return {"yf_ticker": yf_ticker, "error": "insufficient_years (<2)", "f_score": None}

    y0, y1 = cols[0], cols[1]  # y0 = latest year, y1 = prior year

    net_income_0 = _safe_get(fin, ["Net Income", "Net Income Common Stockholders"], y0)
    net_income_1 = _safe_get(fin, ["Net Income", "Net Income Common Stockholders"], y1)
    total_assets_0 = _safe_get(bs, ["Total Assets"], y0)
    total_assets_1 = _safe_get(bs, ["Total Assets"], y1)
    op_cashflow_0 = _safe_get(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], y0)
    lt_debt_0 = _safe_get(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], y0)
    lt_debt_1 = _safe_get(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], y1)
    curr_assets_0 = _safe_get(bs, ["Current Assets"], y0)
    curr_assets_1 = _safe_get(bs, ["Current Assets"], y1)
    curr_liab_0 = _safe_get(bs, ["Current Liabilities"], y0)
    curr_liab_1 = _safe_get(bs, ["Current Liabilities"], y1)
    shares_0 = _safe_get(bs, ["Share Issued", "Ordinary Shares Number"], y0)
    shares_1 = _safe_get(bs, ["Share Issued", "Ordinary Shares Number"], y1)
    revenue_0 = _safe_get(fin, ["Total Revenue"], y0)
    revenue_1 = _safe_get(fin, ["Total Revenue"], y1)
    gross_profit_0 = _safe_get(fin, ["Gross Profit"], y0)
    gross_profit_1 = _safe_get(fin, ["Gross Profit"], y1)

    roa_0 = net_income_0 / total_assets_0 if total_assets_0 else np.nan
    roa_1 = net_income_1 / total_assets_1 if total_assets_1 else np.nan
    lev_0 = lt_debt_0 / total_assets_0 if (total_assets_0 and pd.notna(lt_debt_0)) else np.nan
    lev_1 = lt_debt_1 / total_assets_1 if (total_assets_1 and pd.notna(lt_debt_1)) else np.nan
    curr_ratio_0 = curr_assets_0 / curr_liab_0 if curr_liab_0 else np.nan
    curr_ratio_1 = curr_assets_1 / curr_liab_1 if curr_liab_1 else np.nan
    gm_0 = gross_profit_0 / revenue_0 if (revenue_0 and pd.notna(gross_profit_0)) else np.nan
    gm_1 = gross_profit_1 / revenue_1 if (revenue_1 and pd.notna(gross_profit_1)) else np.nan
    asset_turn_0 = revenue_0 / total_assets_0 if (total_assets_0 and revenue_0) else np.nan
    asset_turn_1 = revenue_1 / total_assets_1 if (total_assets_1 and revenue_1) else np.nan

    def pt(cond):
        """Point awarded only if the comparison is computable; else np.nan (excluded from total)."""
        if cond is None or (isinstance(cond, float) and np.isnan(cond)):
            return np.nan
        return 1 if cond else 0

    tests = {
        "positive_roa": pt(roa_0 > 0 if pd.notna(roa_0) else None),
        "positive_op_cashflow": pt(op_cashflow_0 > 0 if pd.notna(op_cashflow_0) else None),
        "roa_improving": pt(roa_0 > roa_1 if (pd.notna(roa_0) and pd.notna(roa_1)) else None),
        "cashflow_quality": pt(
            op_cashflow_0 > net_income_0 if (pd.notna(op_cashflow_0) and pd.notna(net_income_0)) else None
        ),
        "leverage_decreasing": pt(lev_0 < lev_1 if (pd.notna(lev_0) and pd.notna(lev_1)) else None),
        "current_ratio_improving": pt(
            curr_ratio_0 > curr_ratio_1 if (pd.notna(curr_ratio_0) and pd.notna(curr_ratio_1)) else None
        ),
        "no_dilution": pt(shares_0 <= shares_1 * 1.01 if (pd.notna(shares_0) and pd.notna(shares_1)) else None),
        "gross_margin_improving": pt(gm_0 > gm_1 if (pd.notna(gm_0) and pd.notna(gm_1)) else None),
        "asset_turnover_improving": pt(
            asset_turn_0 > asset_turn_1 if (pd.notna(asset_turn_0) and pd.notna(asset_turn_1)) else None
        ),
    }

    scored = [v for v in tests.values() if pd.notna(v)]
    f_score = int(sum(scored)) if scored else None
    n_components_scored = len(scored)  # out of 9 — flag low coverage

    return {
        "yf_ticker": yf_ticker,
        "f_score": f_score,
        "f_score_components_available": n_components_scored,
        "f_score_detail": tests,
        "latest_fy": str(y0.date()) if hasattr(y0, "date") else str(y0),
        "error": None,
    }


def compute_fscore(yf_ticker: str) -> dict:
    """Self-computed Piotroski F-Score. Cached on disk for YF_FUNDAMENTAL_CACHE_TTL_SECONDS (24 h)."""
    return cached_call(
        f"fscore:{yf_ticker}",
        YF_FUNDAMENTAL_CACHE_TTL_SECONDS,
        _compute_fscore_impl,
        yf_ticker,
        should_cache=should_cache_yf_payload,
    )


def _approx_5y_avg_pe_impl(yf_ticker: str) -> dict:
    """Implementation behind the cached_call wrapper. See approx_5y_avg_pe."""
    t = yf.Ticker(yf_ticker)
    try:
        def _fetch():
            return t.financials, t.history(period="6y", auto_adjust=True), t.info.get("trailingPE")

        fin, hist, trailing_pe = call_with_retry(
            _fetch,
            max_attempts=3,
            base_delay_s=2.0,
            is_retryable=is_rate_limit_error,
        )
    except Exception as e:
        return {"yf_ticker": yf_ticker, "error": f"fetch_failed: {e}", "avg_pe_5y": None}

    if fin is None or fin.empty or hist is None or hist.empty:
        return {"yf_ticker": yf_ticker, "error": "no_data", "avg_pe_5y": None}

    eps_row = None
    for name in ["Diluted EPS", "Basic EPS"]:
        if name in fin.index:
            eps_row = fin.loc[name]
            break
    if eps_row is None:
        return {"yf_ticker": yf_ticker, "error": "no_eps_row", "avg_pe_5y": None}

    hist.index = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
    pe_points = []
    for fy_date, eps in eps_row.items():
        if pd.isna(eps) or eps <= 0:
            continue
        fy_date_naive = pd.Timestamp(fy_date).tz_localize(None)
        window = hist.loc[:fy_date_naive].tail(1)
        if window.empty:
            continue
        price_at_fy = float(window["Close"].iloc[-1])
        pe_points.append(price_at_fy / float(eps))

    if len(pe_points) < 2:
        return {"yf_ticker": yf_ticker, "error": "insufficient_pe_points", "avg_pe_5y": None,
                 "n_years_used": len(pe_points)}

    avg_pe = float(np.mean(pe_points))

    # Sanity guard against the ADR EPS-currency-mismatch bug documented above.
    # If the reconstructed P/E diverges from Yahoo's own trailingPE by more than
    # 3x in either direction, the EPS series is almost certainly in the wrong
    # currency/unit — refuse to return a number rather than return a corrupted one.
    if trailing_pe and trailing_pe > 0:
        ratio = avg_pe / trailing_pe
        if ratio > 3 or ratio < (1 / 3):
            return {
                "yf_ticker": yf_ticker,
                "error": f"eps_unit_mismatch_suspected (reconstructed avg_pe={avg_pe:.1f} "
                         f"vs trailingPE={trailing_pe:.1f}, ratio={ratio:.1f}x) - likely ADR "
                         f"USD/INR EPS mismatch, see module docstring",
                "avg_pe_5y": None,
                "n_years_used": len(pe_points),
            }

    return {
        "yf_ticker": yf_ticker,
        "avg_pe_5y": round(avg_pe, 2),
        "n_years_used": len(pe_points),
        "trailing_pe_check": round(trailing_pe, 2) if trailing_pe else None,
        "error": None,
    }


def approx_5y_avg_pe(yf_ticker: str) -> dict:
    """
    Coarse 5Y-average P/E: pairs each fiscal year-end annual EPS with the closing
    price nearest that date. LOW-MODERATE confidence — see module docstring.
    Cached on disk for YF_CACHE_TTL_SECONDS (12 h) — price-derived output.
    """
    return cached_call(
        f"pe5y:{yf_ticker}",
        YF_CACHE_TTL_SECONDS,
        _approx_5y_avg_pe_impl,
        yf_ticker,
        should_cache=should_cache_yf_payload,
    )


if __name__ == "__main__":
    for t in ["RELIANCE.NS", "INFY.NS", "TCS.NS"]:
        print(compute_fscore(t))
        print(approx_5y_avg_pe(t))
        print("---")
