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
Fundamentals agent: value-investing score from primary-source XBRL filings.

Deterministic, no scraping, no LLM -- cheap enough to run across the entire
F&O universe (~210 names) on every screen.

Banks and NBFCs file under structurally different XBRL taxonomies (no
Revenue/CurrentAssets tags at all for banks; no NPA/NIM data for the general
taxonomy) -- value_score() would silently under-score them, so fno_value_scan()
routes each symbol to the rubric that matches what its filings actually
contain: xbrl_parser.value_score / bank_score / nbfc_score / etc.
"""


import datetime as dt
import os
import time

import nse_api
import pandas as pd
import state_db
import xbrl_parser

import config

VALUE_SCORE_CACHE = os.path.join("cache", "fno_value_scores.pkl")


_KNOWN_TAXONOMIES = ("banking", "nbfc", "general_insurance", "life_insurance", "general")


def fno_value_scan(
    symbols: list[str] | None = None,
    n_years: int = 3,
    use_live_price: bool = True,
    pause: float = 0.3,
    progress_cb=None,
    include_quarterly: bool = True,
) -> pd.DataFrame:
    """Run the sector-appropriate xbrl_parser score across the F&O universe
    (or a given symbol list).

    use_live_price: fetch LTPs via kite_client (one batched call) to enable
    the PEG sub-score (general rubric only). Needs an active Kite session;
    falls back to leaving PEG unavailable (not faked) if that fails.

    include_quarterly: folds xbrl_parser.quarterly_momentum_pillar() (latest
    quarter's PAT/revenue YoY, half-weighted -- see add_quarterly_pillar)
    into the annual-only score, so the score doesn't go up to ~11 months
    stale between annual filings. On by default; costs one extra XBRL
    fetch per symbol (quarterly_financials), same politeness `pause`.
    """
    symbols = symbols if symbols is not None else config.UNIVERSE

    prices: dict[str, float] = {}
    if use_live_price:
        try:
            import kite_client

            prices = kite_client.get_ltp(symbols)
        except Exception as e:
            print(f"[fno_value_scan] live price fetch failed, PEG will be unavailable for all symbols: {e}", flush=True)

    rows = []
    for i, sym in enumerate(symbols):
        if progress_cb:
            progress_cb(f"{sym} ({i + 1}/{len(symbols)})...", (i + 1) / len(symbols))
        taxonomy = None
        try:
            taxonomy = nse_api.filing_taxonomy(sym)
            bs = xbrl_parser.annual_balance_sheet(sym, n_years=n_years)
            if taxonomy == "banking":
                score = xbrl_parser.bank_score(bs)
            elif taxonomy == "nbfc":
                score = xbrl_parser.nbfc_score(bs)
            elif taxonomy == "general_insurance":
                score = xbrl_parser.general_insurance_score(bs)
            elif taxonomy == "life_insurance":
                score = xbrl_parser.life_insurance_score(bs)
            elif taxonomy == "general":
                score = xbrl_parser.value_score(bs, market_price=prices.get(sym))
            else:
                score = {"total_score": None, "rubric": taxonomy, "missing_pillars": ["unsupported_taxonomy"]}
        except Exception as e:
            print(f"[fno_value_scan] {sym}: failed: {e}", flush=True)
            score = {"total_score": None, "rubric": "error", "missing_pillars": ["error"]}

        if include_quarterly and taxonomy in _KNOWN_TAXONOMIES:
            try:
                qdf = xbrl_parser.quarterly_financials(sym)
                q_sub, _ = xbrl_parser.quarterly_momentum_pillar(qdf)
                score = xbrl_parser.add_quarterly_pillar(score, q_sub)
            except Exception as e:
                print(f"[fno_value_scan] {sym}: quarterly pillar failed (keeping annual-only score): {e}", flush=True)

        score["symbol"] = sym
        rows.append(score)
        time.sleep(pause)  # be polite to NSE

    df = pd.DataFrame(rows).set_index("symbol")
    cols = [
        "total_score",
        "rubric",
        "roe",
        "roa",
        "debt_to_equity",
        "current_ratio",
        "revenue_cagr_pct",
        "fcf_yoy_pct",
        "peg",
        "gross_npa_pct",
        "net_npa_pct",
        "nim_proxy_pct",
        "combined_ratio_pct",
        "incurred_claim_ratio_pct",
        "premium_yoy_pct",
        "pat_yoy_pct",
        "loan_yoy_pct",
        "advances_yoy_pct",
        "solvency_ratio_UNVERIFIED",
        "persistency_13m_UNVERIFIED",
        "fiscal_year_end",
        "missing_pillars",
        "pillar_scores",
        "sub_scores",
    ]
    return df[[c for c in cols if c in df.columns]].sort_values("total_score", ascending=False)


def build_fundamentals_history(
    symbols: list[str] | None = None,
    n_years: int = 5,
    pause: float = 0.3,
    progress_cb=None,
    include_quarterly: bool = True,
) -> dict:
    """Fetches each symbol's FULL annual history once (same underlying calls
    as fno_value_scan) and keeps the raw bs_years rows -- each already tagged
    with known_as_of by xbrl_parser -- instead of collapsing to a single
    current score. This is the one-time (or periodically refreshed) batch
    step for point-in-time backtesting: score_asof() then does the actual
    per-date scoring purely in memory against this, with zero network calls.

    include_quarterly: also fetches quarterly_financials() once per symbol
    (own known_as_of tagging) so score_asof() can fold in the quarterly-
    momentum pillar per backtest date via xbrl_parser.quarterly_asof --
    same as-of, no-lookahead discipline as the annual bs_years, and same
    one-time-fetch-then-reuse-in-memory shape. NOTE: NSE's endpoint only
    ever exposes each symbol's MOST RECENT ~5-6 quarters (no historical
    archive), so this pillar can only ever affect the last ~1-1.5 years of
    a longer backtest -- quarterly_asof correctly returns empty, not a
    lookahead-safe substitute, for any older backtest date.

    Returns {symbol: {"taxonomy": str, "bs_years": list[dict],
    "quarterly": pd.DataFrame}}.
    """
    symbols = symbols if symbols is not None else config.UNIVERSE
    history: dict = {}
    for i, sym in enumerate(symbols):
        if progress_cb:
            progress_cb(f"{sym} ({i + 1}/{len(symbols)})...", (i + 1) / len(symbols))
        try:
            taxonomy = nse_api.filing_taxonomy(sym)
            bs = xbrl_parser.annual_balance_sheet(sym, n_years=n_years)
        except Exception as e:
            print(f"[build_fundamentals_history] {sym}: failed: {e}", flush=True)
            taxonomy, bs = "error", []
        qdf = pd.DataFrame()
        if include_quarterly and taxonomy in _KNOWN_TAXONOMIES:
            try:
                qdf = xbrl_parser.quarterly_financials(sym, max_quarters=12)
            except Exception as e:
                print(f"[build_fundamentals_history] {sym}: quarterly fetch failed (annual-only): {e}", flush=True)
        history[sym] = {"taxonomy": taxonomy, "bs_years": bs, "quarterly": qdf}
        time.sleep(pause)  # be polite to NSE
    return history


_SCORERS = {
    "banking": xbrl_parser.bank_score,
    "nbfc": xbrl_parser.nbfc_score,
    "general_insurance": xbrl_parser.general_insurance_score,
    "life_insurance": xbrl_parser.life_insurance_score,
}


def score_asof(history: dict, date, score_cache: dict | None = None) -> pd.DataFrame:
    """Point-in-time fundamental scores for the whole universe, as of `date`
    -- the backtest-facing counterpart to fno_value_scan(). Pure in-memory:
    filters each symbol's pre-fetched bs_years down to what was knowable by
    `date` (xbrl_parser.fundamentals_asof), then runs it through the SAME
    scoring functions fno_value_scan uses live.

    PEG is never computed here (general rubric's value_score only, and it
    needs a live market price which doesn't exist for a historical date) --
    it will be systematically unavailable for every backtest-computed score,
    unlike the live Fundamentals page.

    score_cache: pass the SAME dict across repeated calls within one backtest
    run (not shared across separate runs) to skip rescoring a symbol whose
    knowable filing set hasn't changed between two rebalance dates -- keyed
    on (symbol, tuple of qe_dates actually included), which is safe by
    construction: identical included rows always produce an identical score,
    independent of any assumption about filing cadence or ordering.
    """
    if score_cache is None:
        score_cache = {}

    rows = []
    for sym, entry in history.items():
        filtered = xbrl_parser.fundamentals_asof(entry["bs_years"], date)
        q_filtered = xbrl_parser.quarterly_asof(entry.get("quarterly"), date)
        q_qe_dates = tuple(q_filtered["qe_date"]) if q_filtered is not None and not q_filtered.empty else ()
        # Cache key includes the quarters actually knowable as of `date`,
        # not just the annual qe_dates -- annual filings change ~yearly but
        # quarterly ones change ~quarterly, so keying on annual alone would
        # return a stale quarterly pillar for every rebalance date within
        # the same fiscal year.
        key = (sym, tuple(r["qe_date"] for r in filtered), q_qe_dates)
        if key in score_cache:
            score = score_cache[key]
        else:
            taxonomy = entry["taxonomy"]
            try:
                if taxonomy in _SCORERS:
                    score = _SCORERS[taxonomy](filtered)
                elif taxonomy == "general":
                    score = xbrl_parser.value_score(filtered)
                else:
                    score = {"total_score": None, "rubric": taxonomy, "missing_pillars": ["unsupported_taxonomy"]}
                if taxonomy in _KNOWN_TAXONOMIES:
                    q_sub, _ = xbrl_parser.quarterly_momentum_pillar(q_filtered)
                    score = xbrl_parser.add_quarterly_pillar(score, q_sub)
            except Exception as e:
                print(f"[score_asof] {sym}: failed: {e}", flush=True)
                score = {"total_score": None, "rubric": "error", "missing_pillars": ["error"]}
            score_cache[key] = score
        row = dict(score)
        row["symbol"] = sym
        rows.append(row)

    df = pd.DataFrame(rows).set_index("symbol")
    cols = [
        "total_score",
        "rubric",
        "roe",
        "roa",
        "debt_to_equity",
        "current_ratio",
        "revenue_cagr_pct",
        "fcf_yoy_pct",
        "gross_npa_pct",
        "net_npa_pct",
        "nim_proxy_pct",
        "combined_ratio_pct",
        "incurred_claim_ratio_pct",
        "premium_yoy_pct",
        "pat_yoy_pct",
        "loan_yoy_pct",
        "advances_yoy_pct",
        "fiscal_year_end",
        "missing_pillars",
        "pillar_scores",
        "sub_scores",
    ]
    return df[[c for c in cols if c in df.columns]]


def flatten_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """fno_value_scan() keeps pillar_scores/sub_scores as dict-valued cells,
    which is convenient for the dashboard (st.dataframe expands them via
    pd.Series) but renders as unwieldy dict-text blobs in a plain CSV viewer
    or spreadsheet. This expands them into individual numeric columns and
    turns missing_pillars (a list) into a plain comma-joined string, so the
    exported file is flat and viewer-agnostic."""
    out = df.drop(columns=["pillar_scores", "sub_scores"], errors="ignore").copy()
    if "pillar_scores" in df.columns:
        pillars = df["pillar_scores"].apply(lambda d: d if isinstance(d, dict) else {})
        out = out.join(pillars.apply(pd.Series).add_prefix("pillar_"))
    if "sub_scores" in df.columns:
        subs = df["sub_scores"].apply(lambda d: d if isinstance(d, dict) else {})
        out = out.join(subs.apply(pd.Series).add_prefix("sub_"))
    if "missing_pillars" in out.columns:
        out["missing_pillars"] = out["missing_pillars"].apply(lambda v: ", ".join(v) if isinstance(v, list) else v)
    return out


def main():
    """Headless weekly refresh -- e.g. from trading_service.py's scheduler.
    Rescans the full F&O universe and overwrites cache/fno_value_scores.pkl,
    the same cache the dashboard's Fundamentals page and Screener/Live
    Rebalance's fundamental-score display read from. Fundamentals filings
    change quarterly at most, so a weekly refresh is already generous --
    this just keeps the cache from going stale for months at a time between
    manual Fundamentals-page runs. Wrapped in state_db.job_run() so the
    dashboard's Job Log page has a persisted, filterable record of every
    weekly run, not just this console/systemd-journal output."""
    with state_db.job_run("fundamentals_refresh", "scheduled") as jr:
        print(
            f"{dt.datetime.now():%d %b %Y %H:%M:%S} Starting weekly fundamentals scan "
            f"({len(config.UNIVERSE)} symbols)..."
        )
        result = fno_value_scan(config.UNIVERSE)
        os.makedirs("cache", exist_ok=True)
        result.to_pickle(VALUE_SCORE_CACHE)
        scored = result["total_score"].notna().sum() if "total_score" in result.columns else 0
        print(
            f"{dt.datetime.now():%d %b %Y %H:%M:%S} Done -- {scored}/{len(result)} scored, saved to {VALUE_SCORE_CACHE}"
        )
        jr["summary"] = f"{scored}/{len(result)} scored"


if __name__ == "__main__":
    main()
