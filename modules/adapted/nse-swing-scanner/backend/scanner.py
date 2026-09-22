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
scanner.py
Orchestrates universe -> technicals -> fundamentals -> external sources ->
hard gates -> weighted score.

Design decisions (see conversation for full rationale):
- Entry-timing/quality-DEGREE criteria are a WEIGHTED SCORE (0-100), not AND-gates.
  Stacking 13 strict AND-conditions returns ~0 stocks most days. A score gives a
  usable ranking every day and degrades gracefully.
- Only genuinely non-negotiable safety criteria are hard gates (7, see README):
  F-score floor, drawdown window, RSI window, liquidity adequacy (real delivery
  OR 20d ADV), not-suspended/T-group, holdings concentration, and
  no-pending-corporate-action. The market-cap floor and D/E ceiling from the
  original spec were never implemented and their settings constants were
  removed in 1.3.3 — re-add both the constant AND the gate together if the
  spec is ever revisited (see CHANGELOG 1.3.0: no new hard gates until the
  existing ones are validated).
- Targets are ATR-scaled measured moves, NOT Fibonacci 61.8% (oversized for a
  15-30 day window). Targets are heuristic — see methodology.md.
- Earnings surprise is explicitly NOT a hard gate; consensus data is not
  available from a clean free source (documented in README, deferred to Phase 2).

Confidence: this module's LOGIC is high confidence (it's just arithmetic and
pandas). Its OUTPUT for any specific stock is only as good as the weakest
upstream field for that stock - always check the per-field error/None flags in
the output before trusting a row.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
from bhavcopy import fetch_bhavcopy, lookup_delivery
from corporate_actions import fetch_corporate_actions
from earnings import fetch_earnings
from fscore import approx_5y_avg_pe, compute_fscore
from holdings import fetch_holdings
from settings import (
    ADV_HARD_CEILING_INR,
    DRAWDOWN_LOWER_PCT,
    DRAWDOWN_UPPER_PCT,
    MIN_ADV_SECONDARY_FLOOR_INR,
    MIN_ADV_VALUE_INR,
    MIN_DELIVERY_VALUE_INR,
    MIN_F_SCORE,
    MIN_HOLDINGS_CONVICTION_PCT,
    RSI_LOWER,
    RSI_UPPER,
    SCORE_VERSION,
    UNIVERSE_DEFAULT_TOP_N,
    UNIVERSE_DEFAULT_WORKERS,
    WEIGHTS,
)
from surveillance import check_symbol, fetch_surveillance_list
from technicals import compute_nifty50_context, compute_technicals
from universe import fetch_universe


# ---------------------------------------------------------------------------
# Soft-score helpers
# ---------------------------------------------------------------------------
def _score_valuation(pe_now, pe_5y_avg) -> float:
    if pe_now is None or pe_5y_avg is None or pe_5y_avg <= 0 or pe_now <= 0:
        return np.nan
    compression = (pe_5y_avg - pe_now) / pe_5y_avg
    return float(np.clip(compression / 0.40, 0, 1))


def _score_rsi(rsi) -> float:
    if rsi is None or np.isnan(rsi):
        return np.nan
    if 32 <= rsi <= 38:
        return 1.0
    if rsi < 25 or rsi > 45:
        return 0.0
    if rsi < 32:
        return float((rsi - 25) / 7)
    return float(max(0, (45 - rsi) / 7))


def _score_support(pct_from_ema200) -> float:
    if pct_from_ema200 is None or np.isnan(pct_from_ema200):
        return np.nan
    dist = abs(pct_from_ema200)
    return float(np.clip(1 - dist / 5, 0, 1))


def _score_drawdown(pct_off_high) -> float:
    if pct_off_high is None or np.isnan(pct_off_high):
        return np.nan
    d = abs(pct_off_high)
    if d < 15 or d > 40:
        return 0.0
    if 20 <= d <= 30:
        return 1.0
    if d < 20:
        return float((d - 15) / 5)
    return float((40 - d) / 10)


def _score_volume(surge_factor) -> float:
    if surge_factor is None or np.isnan(surge_factor):
        return np.nan
    return float(np.clip((surge_factor - 1.0) / 2.0, 0, 1))


def _score_quality(roe, opm, f_score, de_ratio) -> float:
    parts = []
    if roe is not None and not np.isnan(roe):
        parts.append(np.clip(roe / 0.25, 0, 1))
    if opm is not None and not np.isnan(opm):
        parts.append(np.clip(opm / 0.25, 0, 1))
    if f_score is not None:
        parts.append(np.clip(f_score / 9, 0, 1))
    if de_ratio is not None and not np.isnan(de_ratio):
        parts.append(np.clip(1 - de_ratio / 2, 0, 1))
    return float(np.mean(parts)) if parts else np.nan


def _score_conviction(holdings_data: dict | None) -> float:
    """
    Soft score 0-1 from shareholding conviction (promoter+FII+DII).
    Higher is better. NaN if data is unavailable.
    """
    if not holdings_data:
        return np.nan
    conviction = holdings_data.get("conviction_pct")
    if conviction is None:
        return np.nan
    # Map 30% -> 0, 70% -> 1, cap at 1.
    return float(np.clip((conviction - 30) / 40, 0, 1))


# ---------------------------------------------------------------------------
# Hard-gate helpers (each returns (passed: bool, reason: str|None))
# ---------------------------------------------------------------------------
def gate_f_score(f_score) -> tuple[bool, str | None]:
    if f_score is None:
        return False, "f_score_missing"
    if f_score < MIN_F_SCORE:
        return False, f"f_score {f_score} < {MIN_F_SCORE}"
    return True, None


def gate_drawdown(pct_off_high) -> tuple[bool, str | None]:
    if pct_off_high is None or np.isnan(pct_off_high):
        return False, "pct_off_high_missing"
    if not (DRAWDOWN_LOWER_PCT <= pct_off_high <= DRAWDOWN_UPPER_PCT):
        return False, f"pct_off_high {pct_off_high} outside [{DRAWDOWN_LOWER_PCT},{DRAWDOWN_UPPER_PCT}]"
    return True, None


def gate_rsi(rsi) -> tuple[bool, str | None]:
    if rsi is None or np.isnan(rsi):
        return False, "rsi_missing"
    if not (RSI_LOWER <= rsi <= RSI_UPPER):
        return False, f"rsi {rsi} outside [{RSI_LOWER},{RSI_UPPER}]"
    return True, None


def gate_liquidity_adequacy(
    adv_value_inr: float | None,
    delivery_value_inr: float | None,
    delivery_kind: str | None,
    delivery_status: str,
) -> tuple[bool, str | None]:
    """
    Hard gate for exitability / institutional-grade liquidity.

    Passes when EITHER:
      - Real delivery data is available (`delivery_kind == "actual"`) AND
        `delivery_value_inr >= MIN_DELIVERY_VALUE_INR`. This is the original
        "delivery ≥ ₹5cr" gate and is preferred when source is reachable.
        A secondary ADV floor (MIN_ADV_SECONDARY_FLOOR_INR) is also required
        so a thinly-traded name cannot pass via a single high-delivery day
        (block deal, closing-auction spike, post-resumption print).
      - 20d average traded value (`adv_value_inr`) is at least
        `MIN_ADV_VALUE_INR`. This replaces the single-day traded-value proxy
        path that previously polluted the PASS list.

    Fails closed when neither path can be evaluated. `delivery_kind ==
    "traded_value_proxy"` is intentionally NOT a passing path on its own —
    one-day volume×close is too noisy to gate on, which is exactly why we
    switched to ADV.
    """
    if (
        delivery_kind == "actual"
        and delivery_value_inr is not None
        and delivery_status in ("ok", "fallback_used")
        and delivery_value_inr >= MIN_DELIVERY_VALUE_INR
    ):
        # Secondary ADV floor protects against single-day delivery spikes on
        # thinly-traded names (block deal, closing-auction spike).
        if adv_value_inr is not None and adv_value_inr >= MIN_ADV_SECONDARY_FLOOR_INR:
            return True, None
        if adv_value_inr is None:
            return False, "liquidity_missing (delivery path needs ADV secondary floor; ADV unavailable)"
        return (
            False,
            f"adv {int(adv_value_inr)} below secondary floor {int(MIN_ADV_SECONDARY_FLOOR_INR)} for delivery path",
        )

    if adv_value_inr is None:
        return False, "liquidity_missing (adv and real delivery unavailable)"

    if adv_value_inr >= MIN_ADV_VALUE_INR:
        return True, None

    return False, f"adv {int(adv_value_inr)} < {int(MIN_ADV_VALUE_INR)}"


def gate_surveillance(is_restricted: bool, source_status: str) -> tuple[bool, str | None]:
    if source_status == "flag_only":
        # Don't fail, but warn; the UI shows the source status.
        return True, None
    if is_restricted:
        return False, "t_group_or_suspended"
    return True, None


def gate_holdings(
    holdings_data: dict | None,
    holdings_status: str,
    lenient: bool = False,
) -> tuple[bool, str | None]:
    """
    Hard gate for promoter + FII + DII conviction > 50%.

    Strict (default): fail-closed on source_failed / missing — we do not
    pretend the conviction check passed if we couldn't fetch the data.

    Lenient (--lenient-external-gates): when the source is source_failed
    we let the stock through with a flag. Useful when Screener is rate-
    limiting the scanner's IP (common on GitHub Actions runners).
    """
    if holdings_status == "source_failed":
        if lenient:
            return True, None
        return False, "holdings_source_failed"
    if holdings_data is None:
        if lenient:
            return True, None
        return False, "holdings_missing"
    conviction = holdings_data.get("conviction_pct")
    if conviction is None:
        if lenient:
            return True, None
        return False, "holdings_missing"
    if conviction <= MIN_HOLDINGS_CONVICTION_PCT:
        return False, f"holdings_conviction {conviction:.1f}% <= {MIN_HOLDINGS_CONVICTION_PCT}%"
    return True, None


def gate_corporate_actions(ca_data: dict | None) -> tuple[bool, str | None]:
    if ca_data is None:
        return True, None  # source_failed -> we don't claim the gap is closed
    if ca_data.get("has_excluded_action"):
        actions = ca_data.get("actions") or []
        names = [a.get("action", "") for a in actions[:3]]
        return False, f"pending_corporate_action: {', '.join(names)}"
    return True, None


# ---------------------------------------------------------------------------
# Relative-strength adjustment
# ---------------------------------------------------------------------------
def relative_strength_factor(stock_pct_from_ema200: float | None, index_pct_from_ema200: float | None) -> float:
    """
    Returns a multiplier in {0.70, 0.85, 1.0, 1.05} applied to the swing_score.
    - If the index is also correcting heavily, the stock's drawdown is normal market
      behavior; small bonus.
    - If the stock is breaking down materially worse than the index, penalize.
    - If the index is healthy and the stock is also weak, neutral.
    """
    if stock_pct_from_ema200 is None or index_pct_from_ema200 is None:
        return 1.0
    if np.isnan(stock_pct_from_ema200) or np.isnan(index_pct_from_ema200):
        return 1.0
    # Both negative and stock worse than index by more than 5pp -> penalty
    delta = stock_pct_from_ema200 - index_pct_from_ema200
    if delta < -10:
        return 0.7
    if delta < -5:
        return 0.85
    if index_pct_from_ema200 < -5 and stock_pct_from_ema200 >= index_pct_from_ema200 - 2:
        return 1.05
    return 1.0


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate_stock(
    row: dict,
    *,
    sleep_between_calls: float = 0.3,
    surveillance_payload: dict | None = None,
    bhavcopy_payload: dict | None = None,
    lenient_external_gates: bool = False,
) -> dict:
    """
    row: dict with at least 'yf_ticker', 'company_name', 'industry', 'symbol'
    Returns a merged dict of all raw fields + gate results + composite score.

    lenient_external_gates: when True, the holdings gate passes on source_failed
    instead of failing the row. Use when external data sources are persistently
    unreachable (e.g. Screener.in behind a captcha). The liquidity gate is no
    longer affected by this flag — it falls back to the 20d ADV path, which is
    computed from yfinance regardless of bhavcopy availability.
    """
    yf_ticker = row["yf_ticker"]
    symbol = row["symbol"]
    result = dict(row)

    tech = compute_technicals(yf_ticker)
    time.sleep(sleep_between_calls)
    fsc = compute_fscore(yf_ticker)
    time.sleep(sleep_between_calls)
    pe5y = approx_5y_avg_pe(yf_ticker)
    time.sleep(sleep_between_calls)

    result.update({f"tech_{k}": v for k, v in tech.items() if k != "yf_ticker"})
    result.update({f"fscore_{k}": v for k, v in fsc.items() if k not in ("yf_ticker", "f_score_detail")})
    result.update({f"pe5y_{k}": v for k, v in pe5y.items() if k != "yf_ticker"})

    # External sources (Screener holdings — may be slow; should be pre-fetched
    # in batch via holdings.fetch_holdings in run_scan, not here)
    holdings_status = result.get("holdings_status", "missing")
    holdings_data = result.get("holdings_data") or None
    result.get("corporate_actions_status", "source_failed")
    ca_data = result.get("corporate_actions_data") or None

    # Surveillance
    if surveillance_payload is None:
        surveillance_payload = {"status": "flag_only", "data": {}}
    surv = check_symbol(surveillance_payload, symbol)
    result["surveillance_is_restricted"] = surv["is_restricted"]
    result["surveillance_restriction_type"] = surv["restriction_type"]
    result["surveillance_source_status"] = surv["source_status"]
    result["surveillance_source"] = surv["source"]

    # Delivery
    if bhavcopy_payload is None:
        bhavcopy_payload = {"status": "source_failed", "data": {}}
    deliv = lookup_delivery(bhavcopy_payload, symbol)
    result["delivery_value_inr"] = deliv["delivery_value_inr"]
    result["delivery_qty"] = deliv["delivery_qty"]
    result["delivery_pct"] = deliv["delivery_pct"]
    result["delivery_kind"] = deliv["delivery_kind"]
    result["delivery_fallback_from"] = deliv["fallback_from"]
    result["delivery_as_of"] = deliv["as_of"]
    result["delivery_source_status"] = deliv["source_status"]
    result["delivery_source"] = deliv["source"]

    # Required-source failure
    critical_source_failed = fsc.get("error") is not None or tech.get("error") is not None or fsc.get("f_score") is None
    if critical_source_failed:
        result["gate_pass"] = False
        result["gate_fail_reason"] = tech.get("error") or fsc.get("error") or "f_score_missing"
        result["swing_score"] = None
        return result

    # --- hard gates ---
    fail_reasons = []
    # gate_results: parallel to fail_reasons, but keeps EVERY gate (pass or
    # fail) so the UI can render a per-gate checklist instead of a joined
    # string. Schema: [{"gate": "f_score", "passed": True/False,
    # "reason": "..." | null}, ...] — see B4 in the strategic review.
    gate_results = []
    f_score = fsc.get("f_score")

    ok, why = gate_f_score(f_score)
    gate_results.append({"gate": "f_score", "passed": bool(ok), "reason": why if not ok else None})
    if not ok:
        fail_reasons.append(why)

    pct_off_high = tech.get("pct_off_52wk_high")
    ok, why = gate_drawdown(pct_off_high)
    gate_results.append({"gate": "drawdown", "passed": bool(ok), "reason": why if not ok else None})
    if not ok:
        fail_reasons.append(why)

    rsi = tech.get("rsi14")
    ok, why = gate_rsi(rsi)
    gate_results.append({"gate": "rsi", "passed": bool(ok), "reason": why if not ok else None})
    if not ok:
        fail_reasons.append(why)

    raw_adv = tech.get("adv_value_inr")
    clamped_adv = min(raw_adv, ADV_HARD_CEILING_INR) if isinstance(raw_adv, (int, float)) else raw_adv
    ok, why = gate_liquidity_adequacy(
        clamped_adv,
        deliv["delivery_value_inr"],
        deliv.get("delivery_kind"),
        deliv["source_status"],
    )
    if ok:
        if (
            deliv.get("delivery_kind") == "actual"
            and deliv["delivery_value_inr"] is not None
            and deliv["delivery_value_inr"] >= MIN_DELIVERY_VALUE_INR
        ):
            result["liquidity_gate_path"] = "delivery_actual"
        else:
            result["liquidity_gate_path"] = "adv"
    else:
        result["liquidity_gate_path"] = None
    gate_results.append(
        {
            "gate": "liquidity_adequacy",
            "passed": bool(ok),
            "reason": why if not ok else None,
        }
    )
    if not ok:
        fail_reasons.append(why)

    ok, why = gate_surveillance(surv["is_restricted"], surv["source_status"])
    gate_results.append({"gate": "surveillance", "passed": bool(ok), "reason": why if not ok else None})
    if not ok:
        fail_reasons.append(why)

    ok, why = gate_holdings(holdings_data, holdings_status, lenient=lenient_external_gates)
    gate_results.append({"gate": "holdings_conviction", "passed": bool(ok), "reason": why if not ok else None})
    if not ok:
        fail_reasons.append(why)

    ok, why = gate_corporate_actions(ca_data)
    gate_results.append({"gate": "corporate_actions", "passed": bool(ok), "reason": why if not ok else None})
    if not ok:
        fail_reasons.append(why)

    result["gate_pass"] = len(fail_reasons) == 0
    result["gate_fail_reason"] = "; ".join(fail_reasons) if fail_reasons else None
    result["gate_results"] = gate_results

    # --- earnings proximity (B3) ---
    # Warning-only, never a gate. Fetched only for gate-passed names so the
    # bounded yfinance call cost stays in the tens, not hundreds. Failed /
    # missing fetches are recorded but do not affect gate_pass or score.
    earnings_status = "not_applicable"
    earnings_data = None
    if result["gate_pass"]:
        try:
            ea = fetch_earnings(symbol, yf_ticker)
            earnings_status = ea.get("status", "missing")
            earnings_data = ea.get("data")
        except Exception as e:
            earnings_status = "source_failed"
            earnings_data = None
            result["earnings_error"] = str(e)
    result["earnings_status"] = earnings_status
    result["earnings_data"] = earnings_data

    # --- soft score ---
    pe_now = pe5y.get("trailing_pe_check")
    (holdings_data or {}).get("conviction_pct") if holdings_data else None

    sub_scores = {
        "valuation_compression": _score_valuation(pe_now, pe5y.get("avg_pe_5y")),
        "oversold_positioning": _score_rsi(rsi),
        "support_proximity": _score_support(tech.get("pct_from_ema200")),
        "drawdown_sweetspot": _score_drawdown(pct_off_high),
        "volume_capitulation": _score_volume(tech.get("volume_surge_factor")),
        "quality_composite": _score_quality(None, None, f_score, None),
        "conviction_holding": _score_conviction(holdings_data),
    }

    weighted_sum, weight_total = 0.0, 0.0
    for k, w in WEIGHTS.items():
        v = sub_scores.get(k, np.nan)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        weighted_sum += float(v) * w
        weight_total += w

    base_score = 100 * weighted_sum / weight_total if weight_total > 0 else None
    rs_mult = relative_strength_factor(
        tech.get("pct_from_ema200"),
        result.get("market_index_pct_from_ema200"),
    )
    result["market_correction_factor"] = round(rs_mult, 3)
    result["swing_score"] = round(base_score * rs_mult, 1) if base_score is not None else None
    result["sub_scores"] = sub_scores

    return result


# ---------------------------------------------------------------------------
# Batch orchestration
# ---------------------------------------------------------------------------
def _evaluate_one_stock(
    rdict: dict,
    sleep_between_calls: float,
    surveillance_payload: dict,
    bhavcopy_payload: dict,
    skip_holdings: bool,
    skip_corporate_actions: bool,
    lenient_external_gates: bool = False,
) -> dict:
    """
    Per-stock worker: fetches holdings + corp-actions for this symbol, then
    runs evaluate_stock. Returns the merged row dict (or an exception row).

    Designed to be called from a thread pool — it does NOT share mutable state
    with other workers.
    """
    symbol = rdict["symbol"]

    if not skip_holdings:
        try:
            h = fetch_holdings(symbol)
            rdict["holdings_status"] = h.get("status")
            rdict["holdings_source"] = h.get("source")
            rdict["holdings_data"] = h.get("data") or {}
        except Exception as e:
            rdict["holdings_status"] = "source_failed"
            rdict["holdings_source"] = "screener.in"
            rdict["holdings_data"] = {}
            rdict["holdings_error"] = str(e)
    else:
        rdict["holdings_status"] = "missing"
        rdict["holdings_data"] = {}

    if not skip_corporate_actions:
        try:
            ca = fetch_corporate_actions(symbol)
            rdict["corporate_actions_status"] = ca.get("status")
            rdict["corporate_actions_data"] = ca.get("data") or {}
        except Exception as e:
            rdict["corporate_actions_status"] = "source_failed"
            rdict["corporate_actions_data"] = {}
            rdict["corporate_actions_error"] = str(e)
    else:
        rdict["corporate_actions_status"] = "missing"
        rdict["corporate_actions_data"] = {}

    try:
        return evaluate_stock(
            rdict,
            sleep_between_calls=sleep_between_calls,
            surveillance_payload=surveillance_payload,
            bhavcopy_payload=bhavcopy_payload,
            lenient_external_gates=lenient_external_gates,
        )
    except Exception as e:
        return {
            **rdict,
            "gate_pass": False,
            "gate_fail_reason": f"exception: {e}",
        }


def run_scan(
    top_n: int = UNIVERSE_DEFAULT_TOP_N,
    sample_size: int | None = None,
    sleep_between_calls: float = 0.3,
    workers: int = UNIVERSE_DEFAULT_WORKERS,
    skip_holdings: bool = False,
    skip_corporate_actions: bool = False,
    lenient_external_gates: bool = False,
) -> pd.DataFrame:
    """
    Fetch universe + shared external data, then evaluate each stock in parallel.

    Args:
        top_n: 100, 200, or 500 — selects the NSE index list (ranked by
            free-float market cap). Defaults to 100 (Nifty 100) for fast scans.
        sample_size: optional integer cap on the universe (after top_n is applied).
            Useful for testing.
        sleep_between_calls: per-yfinance-call courtesy delay (seconds).
        workers: number of threads for the per-stock worker pool. yfinance releases
            the GIL during HTTP I/O so this is effective. 8 is a safe default;
            bump to 16 if your network is fast and yfinance/Screener aren't
            rate-limiting.
        skip_holdings / skip_corporate_actions: bypass slow per-stock fetches.
        lenient_external_gates: when True, delivery and holdings gates pass on
            source_failed (instead of failing-closed). Use when external data
            sources are persistently unreachable — e.g. NSE bhavcopy behind
            Akamai bot protection, Screener rate-limiting the runner IP.
    """
    universe = fetch_universe(top_n=top_n)
    if sample_size:
        universe = universe.head(sample_size)

    n = len(universe)
    workers = max(1, min(workers, n))
    print(f"Universe: Nifty {top_n} ({n} stocks); workers={workers}")

    # Shared external data: fetched once for the whole scan (these don't depend
    # on the worker pool — they're not per-stock).
    print("Fetching shared data: surveillance, bhavcopy, nifty50…")
    surveillance_payload = fetch_surveillance_list()
    print(f"  surveillance: status={surveillance_payload['status']}")
    universe_symbols = universe["symbol"].tolist()
    universe_yf_tickers = universe["yf_ticker"].tolist()
    bhavcopy_payload = fetch_bhavcopy(
        universe_symbols=universe_symbols,
        universe_yf_tickers=universe_yf_tickers,
    )
    print(
        f"  bhavcopy: status={bhavcopy_payload['status']} source={bhavcopy_payload.get('source')} as_of={bhavcopy_payload.get('as_of')}"
    )
    nifty = compute_nifty50_context()
    print(f"  nifty50: {nifty.get('index_pct_from_ema200')}% from 200EMA")

    market_index_pct = nifty.get("index_pct_from_ema200")

    # Build the input dicts for each stock
    inputs = []
    for _, r in universe.iterrows():
        rdict = r.to_dict()
        rdict["market_index_pct_from_ema200"] = market_index_pct
        inputs.append(rdict)

    # Per-stock evaluation in parallel
    rows = []
    completed = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _evaluate_one_stock,
                rdict,
                sleep_between_calls,
                surveillance_payload,
                bhavcopy_payload,
                skip_holdings,
                skip_corporate_actions,
                lenient_external_gates,
            ): rdict["symbol"]
            for rdict in inputs
        }
        try:
            for fut in as_completed(futures):
                symbol = futures[fut]
                try:
                    rows.append(fut.result())
                except Exception as e:
                    # Should not happen — _evaluate_one_stock catches internally —
                    # but be defensive so a buggy worker never kills the whole scan.
                    rows.append(
                        {
                            "symbol": symbol,
                            "gate_pass": False,
                            "gate_fail_reason": f"worker_exception: {e}",
                        }
                    )
                completed += 1
                if completed % 25 == 0 or completed == n:
                    elapsed = time.time() - start
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (n - completed) / rate if rate > 0 else 0
                    print(f"  {completed}/{n} stocks evaluated ({elapsed:.1f}s, {rate:.1f}/s, eta {eta:.0f}s)")
        except KeyboardInterrupt:
            print("\nInterrupted — cancelling remaining workers…")
            for f in futures:
                f.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise

    print(f"Per-stock evaluation complete in {time.time() - start:.1f}s")

    # Recovery pass: rate-limited / unpriced rows get a slow serial retry.
    # Parallel bursts on GHA egress trip yfinance hard; a second pass with
    # workers=1 and longer sleep recovers most of the remainder without
    # publishing a half-blind PASS list.
    rows = _recover_rate_limited_rows(
        rows,
        inputs_by_symbol={r["symbol"]: r for r in inputs},
        sleep_between_calls=max(sleep_between_calls, 0.6),
        surveillance_payload=surveillance_payload,
        bhavcopy_payload=bhavcopy_payload,
        skip_holdings=skip_holdings,
        skip_corporate_actions=skip_corporate_actions,
        lenient_external_gates=lenient_external_gates,
    )

    return pd.DataFrame(rows)


def _row_price(row: dict):
    """Price on a raw evaluate_stock row (tech_*) or JSON record (current_price)."""
    for k in ("tech_current_price", "current_price"):
        v = row.get(k)
        if isinstance(v, (int, float)):
            return v
    return None


def _is_rate_limited_row(row: dict) -> bool:
    """True when the row failed due to yfinance throttle (no usable price)."""
    if _row_price(row) is not None:
        return False
    # evaluate_stock stores tech error under tech_error or gate_fail_reason
    blobs = [
        str(row.get("gate_fail_reason") or ""),
        str(row.get("tech_error") or ""),
        str(row.get("error") or ""),
    ]
    text = " ".join(blobs).lower()
    return any(
        m in text
        for m in (
            "too many requests",
            "rate limit",
            "rate limited",
            "empty history after retries",
        )
    )


def _recover_rate_limited_rows(
    rows: list,
    *,
    inputs_by_symbol: dict,
    sleep_between_calls: float,
    surveillance_payload: dict,
    bhavcopy_payload: dict,
    skip_holdings: bool,
    skip_corporate_actions: bool,
    lenient_external_gates: bool,
    max_recover: int = 400,
    pause_every: int = 25,
    pause_s: float = 8.0,
) -> list:
    """
    Re-evaluate rate-limited symbols one-at-a-time. Mutates/replaces entries
    in `rows` and returns the updated list.
    """
    need_idx = [i for i, r in enumerate(rows) if _is_rate_limited_row(r)]
    if not need_idx:
        print("Recovery pass: no rate-limited rows")
        return rows

    targets = need_idx[:max_recover]
    print(
        f"Recovery pass: re-fetching {len(targets)}/{len(need_idx)} "
        f"rate-limited symbols (serial, sleep={sleep_between_calls}s)…"
    )
    recovered = 0
    start = time.time()
    for n_done, i in enumerate(targets, 1):
        sym = rows[i].get("symbol")
        base = inputs_by_symbol.get(sym)
        if not base:
            continue
        # Fresh copy so we don't carry stale tech_* fields from the failed pass
        rdict = dict(base)
        try:
            fresh = _evaluate_one_stock(
                rdict,
                sleep_between_calls,
                surveillance_payload,
                bhavcopy_payload,
                skip_holdings,
                skip_corporate_actions,
                lenient_external_gates,
            )
            rows[i] = fresh
            if _row_price(fresh) is not None:
                recovered += 1
        except Exception as e:
            rows[i] = {
                **rdict,
                "gate_pass": False,
                "gate_fail_reason": f"recovery_exception: {e}",
            }
        if n_done % pause_every == 0:
            print(
                f"  recovery {n_done}/{len(targets)} "
                f"(recovered={recovered}, {time.time() - start:.0f}s) — pausing {pause_s:.0f}s"
            )
            time.sleep(pause_s)
    print(f"Recovery pass done: recovered {recovered}/{len(targets)} in {time.time() - start:.0f}s")
    return rows


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------
def _json_safe(v):
    """
    Recursively coerce values to JSON-safe Python primitives.

    - NaN and +/-Inf -> None (JSON has no representation for these and
      json.dump(allow_nan=False) will otherwise raise ValueError).
    - numpy scalars -> native Python scalars.
    - bytes -> decoded as utf-8 with replacement.
    - sets -> lists (not JSON-serialisable).
    - pandas.Timestamp -> ISO string.
    """
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return v.decode("utf-8", errors="replace")
    if isinstance(v, (pd.Timestamp, datetime.datetime, datetime.date)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, set):
        return [_json_safe(x) for x in v]
    return v


def to_json_records(df: pd.DataFrame) -> list:
    """
    Flattens the scanner DataFrame into the JSON contract the frontend expects.
    Field names here are the frontend's public API - change them in both places
    at once, or the dashboard silently shows blanks.

    ADV outlier clamp: yfinance occasionally surfaces multi-100x volume spikes
    on the first session after suspension/resumption. Each row's ADV is
    clamped to ADV_HARD_CEILING_INR (set well above the legitimate Nifty 500
    ceiling) so a single outlier cannot satisfy the gate or distort the UI.
    """
    records = []
    for _, row in df.iterrows():
        r = row.to_dict()
        holdings_data = r.get("holdings_data") or {}
        ca_data = r.get("corporate_actions_data") or {}
        records.append(
            {
                "symbol": r.get("symbol"),
                "company_name": r.get("company_name"),
                "industry": r.get("industry"),
                "yf_ticker": r.get("yf_ticker"),
                "current_price": _json_safe(r.get("tech_current_price")),
                "fifty_two_wk_high": _json_safe(r.get("tech_fifty_two_wk_high")),
                "pct_off_52wk_high": _json_safe(r.get("tech_pct_off_52wk_high")),
                "pct_from_ema200": _json_safe(r.get("tech_pct_from_ema200")),
                "rsi14": _json_safe(r.get("tech_rsi14")),
                "atr14": _json_safe(r.get("tech_atr14")),
                "entry_zone_low": _json_safe(r.get("tech_entry_zone_low")),
                "entry_zone_high": _json_safe(r.get("tech_entry_zone_high")),
                "stop_loss": _json_safe(r.get("tech_stop_loss")),
                "target_1": _json_safe(r.get("tech_target_1")),
                "target_2": _json_safe(r.get("tech_target_2")),
                "risk_reward_target_1": _json_safe(r.get("tech_risk_reward_target_1")),
                "risk_reward_target_2": _json_safe(r.get("tech_risk_reward_target_2")),
                "volume_surge_factor": _json_safe(r.get("tech_volume_surge_factor")),
                "adtv_value_inr_approx": _json_safe(r.get("tech_adtv_value_inr_approx")),
                "f_score": _json_safe(r.get("fscore_f_score")),
                "f_score_components_available": _json_safe(r.get("fscore_f_score_components_available")),
                "avg_pe_5y": _json_safe(r.get("pe5y_avg_pe_5y")),
                "trailing_pe": _json_safe(r.get("pe5y_trailing_pe_check")),
                # New fields
                "delivery_value_inr": _json_safe(r.get("delivery_value_inr")),
                "delivery_qty": _json_safe(r.get("delivery_qty")),
                "delivery_pct": _json_safe(r.get("delivery_pct")),
                "delivery_kind": r.get("delivery_kind"),
                "delivery_fallback_from": r.get("delivery_fallback_from"),
                "delivery_as_of": r.get("delivery_as_of"),
                "delivery_source_status": r.get("delivery_source_status"),
                "delivery_source": r.get("delivery_source"),
                "adv_value_inr": _json_safe(
                    min(r.get("tech_adv_value_inr"), ADV_HARD_CEILING_INR)
                    if isinstance(r.get("tech_adv_value_inr"), (int, float))
                    else r.get("tech_adv_value_inr")
                ),
                "adv_sessions": _json_safe(r.get("tech_adv_sessions")),
                "liquidity_gate_path": r.get("liquidity_gate_path"),
                # 1.3.0 accuracy plumbing: confirmation overlay (A/B label)
                "confirmation_state": r.get("tech_confirmation_state") or "anticipatory",
                "rsi_delta_3d": _json_safe(r.get("tech_rsi_delta_3d")),
                "close_up_1d": r.get("tech_close_up_1d"),
                "vol_ratio_3v20": _json_safe(r.get("tech_vol_ratio_3v20")),
                # 1.3.0 exit-side warnings
                "swing_high_63d": _json_safe(r.get("tech_swing_high_63d")),
                "atr_expansion_ratio": _json_safe(r.get("tech_atr_expansion_ratio")),
                "surveillance_is_restricted": bool(r.get("surveillance_is_restricted", False)),
                "surveillance_restriction_type": r.get("surveillance_restriction_type"),
                "surveillance_source_status": r.get("surveillance_source_status"),
                "surveillance_source": r.get("surveillance_source"),
                "holdings_promoter_pct": _json_safe(holdings_data.get("promoter_pct")),
                "holdings_fii_pct": _json_safe(holdings_data.get("fii_pct")),
                "holdings_dii_pct": _json_safe(holdings_data.get("dii_pct")),
                "holdings_conviction_pct": _json_safe(holdings_data.get("conviction_pct")),
                "holdings_source_status": r.get("holdings_status"),
                "holdings_source": r.get("holdings_source"),
                "pending_corporate_action": bool(ca_data.get("has_excluded_action") or False),
                "corporate_actions_status": r.get("corporate_actions_status"),
                "market_index_pct_from_ema200": _json_safe(r.get("market_index_pct_from_ema200")),
                "market_correction_factor": _json_safe(r.get("market_correction_factor")),
                # Existing
                "gate_pass": bool(r.get("gate_pass")) if r.get("gate_pass") is not None else False,
                "gate_fail_reason": r.get("gate_fail_reason") if isinstance(r.get("gate_fail_reason"), str) else None,
                "gate_results": (
                    _json_safe(r.get("gate_results")) if isinstance(r.get("gate_results"), list) else None
                ),
                "swing_score": _json_safe(r.get("swing_score")),
                "sub_scores": _json_safe(r.get("sub_scores")) if isinstance(r.get("sub_scores"), dict) else None,
                # 1.5.0 feedback loop: which weight regime produced this score.
                "score_version": SCORE_VERSION,
                # B3: earnings proximity (gate-passed names only)
                "earnings_date": (
                    _json_safe(r.get("earnings_data", {}).get("earnings_date"))
                    if isinstance(r.get("earnings_data"), dict)
                    else None
                ),
                "earnings_within_days": (
                    _json_safe(r.get("earnings_data", {}).get("within_days"))
                    if isinstance(r.get("earnings_data"), dict)
                    else None
                ),
                "earnings_source_status": r.get("earnings_status"),
            }
        )
    return records


def compute_coverage(records: list) -> dict:
    """
    Universe coverage stats for the JSON root. A row is "priced" when
    current_price is a finite number — rate-limited yfinance fetches leave
    it null and must not silently shrink the PASS funnel.
    """
    universe = len(records)
    priced = 0
    rate_limited = 0
    for r in records:
        px = r.get("current_price")
        if isinstance(px, (int, float)):
            priced += 1
        reason = r.get("gate_fail_reason") or ""
        low = reason.lower()
        if "too many requests" in low or "rate limit" in low or "rate limited" in low:
            rate_limited += 1
    pct = round(priced / universe, 4) if universe else 0.0
    return {
        "priced": priced,
        "universe": universe,
        "rate_limited": rate_limited,
        "pct": pct,
    }


# Floor below which a scan is considered half-blind and must not replace
# latest_scan.json (last-good is better than false confidence).
MIN_COVERAGE_PCT = 0.85


def write_scan_output(df: pd.DataFrame, output_path: str) -> dict:
    records = to_json_records(df)
    gate_pass_count = sum(1 for r in records if r["gate_pass"])
    coverage = compute_coverage(records)
    payload = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "universe_size": len(records),
        "gate_pass_count": gate_pass_count,
        "coverage": coverage,
        "config": {
            "min_f_score": MIN_F_SCORE,
            "min_delivery_value_inr": MIN_DELIVERY_VALUE_INR,
            "min_adv_value_inr": MIN_ADV_VALUE_INR,
            "min_holdings_conviction_pct": MIN_HOLDINGS_CONVICTION_PCT,
            "rsi_window": [RSI_LOWER, RSI_UPPER],
            "drawdown_window": [DRAWDOWN_LOWER_PCT, DRAWDOWN_UPPER_PCT],
        },
        "stocks": sorted(records, key=lambda r: (r["swing_score"] is None, -(r["swing_score"] or 0))),
    }
    # Belt-and-suspenders: sanitize the entire payload once more so any value
    # that slipped past to_json_records (e.g. raw float('inf') in a gate field
    # added by an external source) is also coerced to None before write.
    payload = _json_safe(payload)
    outdir = os.path.dirname(output_path)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, allow_nan=False)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NSE swing-trade scanner")
    parser.add_argument(
        "--top-n",
        type=int,
        default=UNIVERSE_DEFAULT_TOP_N,
        choices=[100, 200, 500],
        help="Universe tier by free-float market cap: 100, 200, or 500. "
        "100 = Nifty 100 (fastest), 500 = Nifty 500 (full universe).",
    )
    parser.add_argument(
        "--sample", type=int, default=None, help="Limit universe to first N stocks (after --top-n is applied)"
    )
    parser.add_argument(
        "--sleep", type=float, default=0.3, help="Seconds to sleep between yfinance calls (rate-limit courtesy)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=UNIVERSE_DEFAULT_WORKERS,
        help="Thread-pool size for per-stock evaluation (default 8)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="../frontend/public/data/latest_scan.json",
        help="Path to write the JSON contract for the frontend",
    )
    parser.add_argument(
        "--skip-holdings", action="store_true", help="Skip Screener holdings fetch (faster, drops holdings gate)"
    )
    parser.add_argument(
        "--skip-corporate-actions",
        action="store_true",
        help="Skip NSE corporate-actions fetch (faster, drops corp-action gate)",
    )
    parser.add_argument(
        "--lenient-external-gates",
        action="store_true",
        help="Pass delivery and holdings gates when the source is source_failed "
        "instead of failing-closed. Useful when NSE bhavcopy is behind "
        "Akamai or Screener is rate-limiting the runner IP.",
    )
    args = parser.parse_args()

    print(
        f"Starting scan: top_n={args.top_n}, sample={args.sample or 'ALL'}, sleep={args.sleep}s, workers={args.workers}"
    )
    start = time.time()
    df = run_scan(
        top_n=args.top_n,
        sample_size=args.sample,
        sleep_between_calls=args.sleep,
        workers=args.workers,
        skip_holdings=args.skip_holdings,
        skip_corporate_actions=args.skip_corporate_actions,
        lenient_external_gates=args.lenient_external_gates,
    )
    elapsed = time.time() - start
    payload = write_scan_output(df, args.output)
    cov = payload.get("coverage") or {}
    print(
        f"Scan complete in {elapsed / 60:.1f} min. "
        f"{payload['gate_pass_count']}/{payload['universe_size']} passed all gates. "
        f"coverage={cov.get('priced')}/{cov.get('universe')} "
        f"({(cov.get('pct') or 0) * 100:.1f}% priced, "
        f"{cov.get('rate_limited', 0)} rate-limited). "
        f"Wrote {args.output}"
    )
    if (cov.get("pct") or 0) < MIN_COVERAGE_PCT:
        print(
            f"::error::coverage {cov.get('pct')} < {MIN_COVERAGE_PCT} "
            f"({cov.get('priced')}/{cov.get('universe')} priced, "
            f"{cov.get('rate_limited')} rate-limited) — refusing to treat "
            f"this as a good scan. Last-good latest_scan.json should be kept.",
            file=sys.stderr,
        )
        sys.exit(2)
