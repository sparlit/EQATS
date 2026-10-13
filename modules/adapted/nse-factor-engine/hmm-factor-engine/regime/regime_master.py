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
regime_master.py
────────────────────────────────────────────────────────────────────────────
Production orchestrator. Run this once a week. Does everything.

Pipeline
--------
Step 0   Check data/index_prices.parquet is current.
         If stale -> run data/fetch_index_data.py first.

Step 1a  Staleness check on prices_hmm_daily.parquet vs last weekday.
         If stale -> run fetch_hmm_stock_data_historical.py (incremental).
         If current -> skip.

Step 1b  Run liquidity_risk_index.py unconditionally (all 4 universes).
         Reads index OHLCV from data/index_prices.parquet (no yfinance).

Step 2   Run liquidity_risk_narrative.py for all 4 universes.

Step 3a  Staleness check on nifty500_hmm_data.parquet vs current month.
         If stale -> run fetch_hmm_nifty_indices_data.py.
         If current -> skip.

Step 3b  Run hmm_forward_algo.py (causal forward pass).

Step 4   Combine narrative JSON + HMM result per universe.
         Save regime_combined_<univ>_<date>.json.

Usage
-----
python3 hmm-factor-engine/regime/regime_master.py
python3 hmm-factor-engine/regime/regime_master.py --quiet
python3 hmm-factor-engine/regime/regime_master.py --force
"""

import argparse
import importlib.util
import json
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ec2-user/nse-factor-engine")
HMM_DIR = BASE_DIR / "hmm-factor-engine"
DATA_DIR = HMM_DIR / "data"
REGIME_DIR = HMM_DIR / "regime"
REGIME_DATA = REGIME_DIR / "data"
CAL_PATH = REGIME_DATA / "calibration.json"

# Scripts
FETCH_INDEX_PY = BASE_DIR / "data" / "fetch_index_data.py"  # unified fetch
FETCH_STOCKS_PY = DATA_DIR / "fetch_hmm_stock_data_historical.py"
FETCH_INDICES_PY = DATA_DIR / "fetch_hmm_nifty_indices_data.py"
INDEX_PY = REGIME_DIR / "liquidity_risk_index.py"
NARRATIVE_PY = REGIME_DIR / "liquidity_risk_narrative.py"
FORWARD_PY = REGIME_DIR / "hmm_forward_algo.py"
HTML_PDF_PY = REGIME_DIR / "build_regime_html_pdf.py"

# Parquets
INDEX_PQ = BASE_DIR / "data" / "index_prices.parquet"  # single source of truth
PRICES_PQ = DATA_DIR / "prices_hmm_daily.parquet"
NIFTY500_PQ = DATA_DIR / "nifty500_hmm_data.parquet"

UNIVERSES = ["nifty100", "nifty500", "niftymidcap150", "niftysmallcap250"]

MEASURE_LABELS = {
    "rv": "Realised Volatility",
    "avg_corr": "Avg Correlation",
    "vov": "Vol of Vol",
    "dispersion": "Dispersion",
    "drawdown": "Drawdown",
    "skew": "Skew",
    "amihud": "Amihud Illiquidity",
    "cs_spread": "CS Spread",
    "turnover": "Turnover",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def last_weekday(d=None):
    d = d or date.today()
    offset = max(0, d.weekday() - 4)
    return d - timedelta(days=offset)


def parquet_max_date(path):
    if not Path(path).exists():
        return None
    df = pd.read_parquet(path)
    if "date" in df.columns:
        return pd.to_datetime(df["date"]).max().date()
    df.index = pd.to_datetime(df.index)
    return df.index.max().date()


def parquet_max_month(path):
    if not Path(path).exists():
        return None
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df.index.max().to_period("M").to_timestamp().date()


def run_subprocess(script_path, label, verbose=True):
    print(f"\n  Running {label}...")
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=not verbose,
        text=True,
        cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        print(f"ERROR in {label}:\n{result.stderr}")
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")
    print(f"  OK -- {label} complete")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


# ── Step 0: Index parquet staleness check ─────────────────────────────────────


def step_0_index_parquet(force=False, verbose=True):
    section("STEP 0 -- Index Prices (data/index_prices.parquet)")

    target = last_weekday()
    index_max = parquet_max_date(INDEX_PQ)

    print(f"  Last weekday          : {target}")
    print(f"  index_prices max date : {index_max or 'NOT FOUND'}")

    if not force and index_max and index_max >= target:
        print("  Status: CURRENT -- skipping fetch")
        return

    if index_max is None:
        print("  Status: MISSING -- running full fetch")
    else:
        print(f"  Status: STALE by {(target - index_max).days} day(s) -- running fetch")

    run_subprocess(FETCH_INDEX_PY, "data/fetch_index_data.py", verbose=verbose)


# ── Step 1a: Stock price staleness check ──────────────────────────────────────


def step_1a_stock_prices(force=False, verbose=True):
    section("STEP 1a -- Stock Prices (prices_hmm_daily.parquet)")

    target = last_weekday()
    prices_max = parquet_max_date(PRICES_PQ)

    print(f"  Last weekday             : {target}")
    print(f"  prices_hmm_daily max date: {prices_max or 'NOT FOUND'}")

    if not force and prices_max and prices_max >= target:
        print("  Status: CURRENT -- skipping fetch")
        return

    if prices_max is None:
        print("  Status: MISSING -- running full fetch")
    else:
        print(
            f"  Status: STALE by {(target - prices_max).days} day(s) -- running incremental fetch"
        )

    run_subprocess(FETCH_STOCKS_PY, "fetch_hmm_stock_data_historical.py", verbose=verbose)


# ── Step 1b: Liquidity & Risk Index ──────────────────────────────────────────


def step_1b_index(verbose=True):
    section("STEP 1b -- Liquidity & Risk Index (all 4 universes)")
    run_subprocess(INDEX_PY, "liquidity_risk_index.py", verbose=verbose)


# ── Step 2: Narrative ─────────────────────────────────────────────────────────


def step_2_narrative(verbose=True):
    section("STEP 2 -- Narrative (all 4 universes)")

    if not CAL_PATH.exists():
        raise FileNotFoundError(
            f"calibration.json not found at {CAL_PATH}\n"
            "Run liquidity_risk_parameters_calibration.py first."
        )

    with open(CAL_PATH) as f:
        cal_all = json.load(f)

    narrative_mod = load_module("liquidity_risk_narrative", NARRATIVE_PY)
    narrative_paths = {}

    for univ in UNIVERSES:
        pq = REGIME_DATA / f"liquidity_risk_{univ}.parquet"
        if not pq.exists():
            raise FileNotFoundError(f"Parquet not found: {pq}")

        df = pd.read_parquet(pq)
        df.index = pd.to_datetime(df.index)
        latest_date = str(df.index.max().date())

        print(f"\n  [{univ}] latest_date={latest_date}")

        if univ not in cal_all:
            raise KeyError(f"{univ} not in calibration.json")

        cal = cal_all[univ]
        text = narrative_mod.generate_narrative(univ, latest_date, cal, df)
        if verbose:
            print(text)

        dt = pd.Timestamp(latest_date)
        actual_date = (
            dt.date()
            if dt in df.index
            else df.index[df.index.get_indexer([dt], method="nearest")[0]].date()
        )

        json_path = REGIME_DATA / f"narrative_{univ}_{actual_date}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"Expected narrative JSON at {json_path}")

        narrative_paths[univ] = json_path
        print(f"  OK -- narrative saved -> {json_path.name}")

    return narrative_paths


# ── Step 3a: HMM data staleness check ────────────────────────────────────────


def step_3a_hmm_data(force=False, verbose=True):
    section("STEP 3a -- HMM Index Data (nifty500_hmm_data.parquet)")

    today = date.today()
    current_month = date(today.year, today.month, 1)
    hmm_max_month = parquet_max_month(NIFTY500_PQ)

    print(f"  Current month         : {current_month.strftime('%Y-%m')}")
    print(
        f"  nifty500_hmm_data max : {hmm_max_month.strftime('%Y-%m') if hmm_max_month else 'NOT FOUND'}"
    )

    if not force and hmm_max_month and hmm_max_month >= current_month:
        print("  Status: CURRENT -- skipping fetch")
        return

    if hmm_max_month is None:
        print("  Status: MISSING -- running full fetch")
    else:
        months_behind = (current_month.year - hmm_max_month.year) * 12 + (
            current_month.month - hmm_max_month.month
        )
        print(f"  Status: STALE by {months_behind} month(s) -- running fetch")

    run_subprocess(FETCH_INDICES_PY, "fetch_hmm_nifty_indices_data.py", verbose=verbose)


# ── Step 3b: HMM Forward Algorithm ───────────────────────────────────────────


def step_3b_forward_algo(verbose=True):
    section("STEP 3b -- HMM Forward Algorithm")
    hmm_mod = load_module("hmm_forward_algo", FORWARD_PY)
    result = hmm_mod.run_forward_algo(as_of_date=None, verbose=verbose)
    print(
        f"  OK -- HMM complete  regime={result['regime']}  "
        f"P_Bull={result['P_Bull']:.4f}  "
        f"P_Choppy={result['P_Choppy']:.4f}  "
        f"P_Crisis={result['P_Crisis']:.4f}"
    )
    return result


# ── Step 4: Combine ───────────────────────────────────────────────────────────


def _conviction_label(hmm):
    top_p = max(hmm["P_Bull"], hmm["P_Choppy"], hmm["P_Crisis"])
    if top_p >= 0.85:
        return "high"
    elif top_p >= 0.65:
        return "moderate"
    else:
        return "low/mixed"


def _build_regime_blurb(regime, hmm, narrative):
    measures = narrative.get("measures", {})
    rv_tier = measures.get("rv", {}).get("tier", "")
    dd_tier = measures.get("drawdown", {}).get("tier", "")
    amihud_tier = measures.get("amihud", {}).get("tier", "")
    corr_tier = measures.get("avg_corr", {}).get("tier", "")
    conviction = _conviction_label(hmm)
    p_bull = hmm["P_Bull"]
    p_choppy = hmm["P_Choppy"]
    p_crisis = hmm["P_Crisis"]

    if regime == "Bull":
        base = (
            f"HMM assigns a {conviction}-conviction Bull signal "
            f"(P_Bull={p_bull:.2%}, P_Crisis={p_crisis:.2%}). "
        )
        if rv_tier in ("elevated", "extreme") and corr_tier in ("elevated", "extreme"):
            base += (
                "However, the narrative flags elevated volatility and correlation -- "
                "the bull regime is under stress. May be late-cycle or recovery-from-shock."
            )
        elif dd_tier in ("deep", "severe"):
            base += (
                "Significant drawdown flagged by the narrative suggests this may be "
                "a bounce/recovery phase rather than a trending advance."
            )
        else:
            base += (
                "Narrative broadly confirms a constructive environment. "
                "Liquidity and risk measures are not signalling systemic stress."
            )

    elif regime == "Crisis":
        base = (
            f"HMM assigns a {conviction}-conviction Crisis signal "
            f"(P_Crisis={p_crisis:.2%}, P_Bull={p_bull:.2%}). "
        )
        if amihud_tier in ("severely illiquid", "illiquid"):
            base += (
                "Amihud illiquidity confirms the crisis classification -- "
                "price impact elevated, consistent with a stress/deleveraging episode."
            )
        elif rv_tier in ("elevated", "extreme") and dd_tier in ("deep", "severe"):
            base += (
                "High realized volatility and deep drawdown reinforce the crisis classification."
            )
        else:
            base += (
                "Liquidity/risk measures partially confirm stress but the full "
                "crisis picture is mixed -- cross-check with macro context."
            )

    else:  # Choppy
        base = (
            f"HMM assigns a {conviction}-conviction Choppy signal "
            f"(P_Choppy={p_choppy:.2%}, P_Bull={p_bull:.2%}, P_Crisis={p_crisis:.2%}). "
        )
        if rv_tier in ("elevated", "extreme"):
            base += (
                "Elevated volatility from the narrative is consistent with the choppy "
                "characterisation -- indecisive market with no clear directional trend."
            )
        else:
            base += (
                "Narrative does not signal extreme stress or euphoria, "
                "consistent with a range-bound, indecisive regime."
            )

    return base


def _save_log(consolidated, log_path):
    bar = "=" * 70
    bar2 = "-" * 70
    lines = []
    hmm = consolidated["hmm"]
    meta = consolidated["meta"]
    lines += [
        bar,
        f"  REGIME ENGINE RUN LOG  |  {meta['run_date']}  |  generated {meta['generated_at']}",
        bar,
        "",
        "HMM REGIME  (universe-agnostic, Nifty500 index)",
        bar2,
        f"  {'Regime':<22}: {hmm['regime']}  [{hmm['regime_conviction'].upper()} conviction]",
        f"  {'P_Bull':<22}: {hmm['P_Bull']:.4f}",
        f"  {'P_Choppy':<22}: {hmm['P_Choppy']:.4f}",
        f"  {'P_Crisis':<22}: {hmm['P_Crisis']:.4f}",
        f"  {'as_of_month':<22}: {hmm['as_of_month']}",
        f"  {'model_trained':<22}: {hmm['model_train_window']}",
        "",
        "  REGIME SYNTHESIS  (cross-referenced with nifty500)",
        f"  {hmm['regime_synthesis']}",
        "",
    ]
    for univ, udata in consolidated["universes"].items():
        narr = udata["liquidity_risk_narrative"]
        measures = narr.get("measures", {})
        lines += [bar, f"  LIQUIDITY & RISK  |  {univ}  |  {udata['narrative_date']}", bar]
        if udata["hmm_lag_note"]:
            lines.append(f"  WARNING: {udata['hmm_lag_note']}")
        lines += [
            "",
            "  OVERALL",
            f"  {narr.get('overall', '')}",
            "",
            "  RISK MEASURES",
            f"  {'Measure':<22}  {'Tier':<22}  Reading",
            f"  {'-' * 22}  {'-' * 22}  {'-' * 40}",
        ]
        for m in ["rv", "avg_corr", "vov", "dispersion", "drawdown", "skew"]:
            if m not in measures:
                continue
            lines.append(
                f"  {MEASURE_LABELS.get(m, m):<22}  [{measures[m].get('tier', '').upper()}]  {measures[m].get('reading', '')}"
            )
        lines += [
            "",
            "  LIQUIDITY MEASURES",
            f"  {'Measure':<22}  {'Tier':<22}  Reading",
            f"  {'-' * 22}  {'-' * 22}  {'-' * 40}",
        ]
        for m in ["amihud", "cs_spread", "turnover"]:
            if m not in measures:
                continue
            lines.append(
                f"  {MEASURE_LABELS.get(m, m):<22}  [{measures[m].get('tier', '').upper()}]  {measures[m].get('reading', '')}"
            )
        lines.append("")
    with open(log_path, "w") as f:
        f.write("\n".join(lines))


def step_4_combine(narrative_paths, hmm_result):
    section("STEP 4 -- Combine (all 4 universes)")

    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    run_date = date.today().strftime("%Y-%m-%d")

    with open(narrative_paths["nifty500"]) as f:
        n500 = json.load(f)

    hmm_month_str = hmm_result["as_of_month"]
    hmm_block = {
        "as_of_month": hmm_month_str,
        "regime": hmm_result["regime"],
        "P_Bull": hmm_result["P_Bull"],
        "P_Choppy": hmm_result["P_Choppy"],
        "P_Crisis": hmm_result["P_Crisis"],
        "regime_conviction": _conviction_label(hmm_result),
        "model_train_window": hmm_result["model_train_window"],
        "regime_synthesis": _build_regime_blurb(hmm_result["regime"], hmm_result, n500),
    }

    print_hmm_block(hmm_result, narrative_paths)

    universes_out = {}
    for univ in UNIVERSES:
        print(f"\n  {'--' * 33}")
        print(f"  Universe: {univ}")
        print(f"  {'--' * 33}")

        with open(narrative_paths[univ]) as f:
            narrative = json.load(f)

        narrative_date = narrative["date"]
        hmm_is_current = hmm_month_str >= narrative_date[:7]

        univ_block = {
            "narrative_date": narrative_date,
            "hmm_is_current": hmm_is_current,
            "hmm_lag_note": (
                None
                if hmm_is_current
                else f"HMM lags -- latest month is {hmm_month_str}, narrative date is {narrative_date}."
            ),
            "liquidity_risk_narrative": narrative,
        }
        universes_out[univ] = univ_block

        individual = {
            "meta": {
                "universe": univ,
                "narrative_date": narrative_date,
                "hmm_as_of_month": hmm_month_str,
                "generated_at": generated_at,
            },
            "hmm": hmm_block,
            "liquidity_risk_narrative": narrative,
        }
        ind_path = REGIME_DATA / f"regime_combined_{univ}_{narrative_date}.json"
        with open(ind_path, "w") as f:
            json.dump(individual, f, indent=2)

        print_narrative_block(
            univ, narrative_date, narrative, hmm_is_current, univ_block["hmm_lag_note"]
        )
        print(f"  OK -- saved -> {ind_path.name}")

    consolidated = {
        "meta": {"run_date": run_date, "generated_at": generated_at},
        "hmm": hmm_block,
        "universes": universes_out,
    }
    cons_path = REGIME_DATA / f"regime_consolidated_{run_date}.json"
    with open(cons_path, "w") as f:
        json.dump(consolidated, f, indent=2)
    print(f"\n  OK -- consolidated JSON -> {cons_path.name}")

    log_path = REGIME_DATA / f"regime_run_{run_date}.log"
    _save_log(consolidated, log_path)
    print(f"  OK -- run log          -> {log_path.name}")


# ── Summary printers ──────────────────────────────────────────────────────────


def print_hmm_block(hmm_result, narrative_paths):
    bar = "=" * 70
    print(f"\n{bar}")
    print("  HMM REGIME  (universe-agnostic, Nifty500 index)")
    print(bar)
    conviction = _conviction_label(hmm_result)
    print(f"  {'Regime':<22}: {hmm_result['regime']}  [{conviction.upper()} conviction]")
    print(f"  {'P_Bull':<22}: {hmm_result['P_Bull']:.4f}")
    print(f"  {'P_Choppy':<22}: {hmm_result['P_Choppy']:.4f}")
    print(f"  {'P_Crisis':<22}: {hmm_result['P_Crisis']:.4f}")
    print(f"  {'as_of_month':<22}: {hmm_result['as_of_month']}")
    print(f"  {'model_trained':<22}: {hmm_result['model_train_window']}")
    with open(narrative_paths["nifty500"]) as f:
        n500 = json.load(f)
    blurb = _build_regime_blurb(hmm_result["regime"], hmm_result, n500)
    print("\n  REGIME SYNTHESIS  (cross-referenced with nifty500)")
    print(f"  {blurb}")
    print(f"\n{bar}\n")


def print_narrative_block(univ, narrative_date, narr, hmm_is_current, hmm_lag_note):
    bar = "=" * 70
    print(f"\n{bar}")
    print(f"  LIQUIDITY & RISK  |  {univ}  |  {narrative_date}")
    print(bar)
    if not hmm_is_current and hmm_lag_note:
        print(f"  WARNING: {hmm_lag_note}")
    print("\n  OVERALL")
    print(f"  {narr.get('overall', '')}")
    measures = narr.get("measures", {})
    if measures:
        print("\n  RISK MEASURES")
        print(f"  {'Measure':<22}  {'Tier':<22}  Reading")
        print(f"  {'-' * 22}  {'-' * 22}  {'-' * 40}")
        for m in ["rv", "avg_corr", "vov", "dispersion", "drawdown", "skew"]:
            if m not in measures:
                continue
            print(
                f"  {MEASURE_LABELS.get(m, m):<22}  [{measures[m].get('tier', '').upper()}]  {measures[m].get('reading', '')}"
            )
        print("\n  LIQUIDITY MEASURES")
        print(f"  {'Measure':<22}  {'Tier':<22}  Reading")
        print(f"  {'-' * 22}  {'-' * 22}  {'-' * 40}")
        for m in ["amihud", "cs_spread", "turnover"]:
            if m not in measures:
                continue
            print(
                f"  {MEASURE_LABELS.get(m, m):<22}  [{measures[m].get('tier', '').upper()}]  {measures[m].get('reading', '')}"
            )
    print(f"\n{bar}\n")


# ── Step 5: PDF ───────────────────────────────────────────────────────────────


def step_5b_html_pdf(run_date, verbose=True):
    section("STEP 5b -- Design PDF Report")
    html_mod = load_module("build_regime_html_pdf", HTML_PDF_PY)
    consolidated = html_mod.load_consolidated(run_date)
    data = html_mod.transform(consolidated)
    out_path = REGIME_DATA / f"regime_report_design_{run_date}.pdf"
    html_mod.render(data, html_mod.TEMPLATE, out_path)
    print(f"  OK -- Design PDF saved -> {out_path.name}")
    return out_path


# ── Args ──────────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="Regime master — weekly production run")
    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument("--force", action="store_true")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    args = parse_args()
    verbose = not args.quiet
    run_date = date.today().strftime("%Y-%m-%d")

    print(f"\n{'=' * 70}")
    print(f"  REGIME MASTER  |  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 70}")

    try:
        step_0_index_parquet(force=args.force, verbose=verbose)
        step_1a_stock_prices(force=args.force, verbose=verbose)
        step_1b_index(verbose=verbose)
        narrative_paths = step_2_narrative(verbose=verbose)
        step_3a_hmm_data(force=args.force, verbose=verbose)
        hmm_result = step_3b_forward_algo(verbose=verbose)
        step_4_combine(narrative_paths, hmm_result)
        step_5b_html_pdf(run_date, verbose=verbose)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)

    print(f"\n{'=' * 70}")
    print("  ALL DONE")
    print(f"  index_prices max date     : {parquet_max_date(INDEX_PQ)}")
    print(f"  prices_hmm_daily max date : {parquet_max_date(PRICES_PQ)}")
    print(f"  HMM as_of_month           : {hmm_result['as_of_month']}")
    print(f"  Generated at              : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
