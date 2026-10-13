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
Stage 5 — in_universe merge (prerequisite gate, not a ranking metric)

Closes the gap flagged in the Stage 5 handover: in_universe is computed by
Stage 1 but never applied anywhere downstream (Stage 2/3/4 all operate on
the full ~500-symbol universe).

NOTE on filename vs data-date convention (locked 2026-06-30):
Every dated output file is named using RUN_DATE -- the IST calendar date
the pipeline actually executed -- NOT T. T (the latest trading day with
complete data) is a separate thing recorded inside the file as as_of_date,
and can lag behind RUN_DATE. This module matches universe_{run_date}.parquet
against the signals file's RUN_DATE (both from filename), not against T.

Strict match required: if no universe file exists with the exact same
run_date as the signals file, STOP rather than guessing.
"""
import glob

import pandas as pd


def compute(signals: pd.DataFrame, run_date_str: str, base_path: str) -> pd.DataFrame:
    """
    signals      : stage2+3+4 final signals file, must contain 'symbol'
    run_date_str : RUN_DATE in DDMMYYYY format, taken from the signals
                   file's own filename (e.g. "30062026" from
                   momentum_signals_final_30062026.parquet) -- NOT T.
    base_path    : repo root, e.g. "/home/ec2-user/nse-factor-engine/"

    Returns DataFrame: symbol, in_universe, passes_mktcap, passes_adtv, market_cap_cr, adtv_63_cr
    Caller (assembler) merges this onto signals and filters in_universe == True.
    """
    expected_path = base_path.rstrip("/") + f"/universe/universe_{run_date_str}.parquet"
    matches = glob.glob(expected_path)

    assert len(matches) == 1, (
        f"Expected exactly one universe file matching signals run_date={run_date_str} "
        f"at {expected_path}, found {len(matches)}. Universe (Stage 1) and signals "
        f"(Stage 2-4) run_dates must match exactly. STOPPING rather than guessing."
    )

    chosen_path = matches[0]
    print(f"Universe snapshot matched on run_date={run_date_str}: {chosen_path}")

    universe = pd.read_parquet(chosen_path)

    required_cols = {
        "symbol",
        "in_universe",
        "passes_mktcap",
        "passes_adtv",
        "market_cap_cr",
        "adtv_63_cr",
    }
    missing = required_cols - set(universe.columns)
    assert not missing, f"universe file {chosen_path} missing columns: {missing}"

    out = universe[
        ["symbol", "in_universe", "passes_mktcap", "passes_adtv", "market_cap_cr", "adtv_63_cr"]
    ].copy()

    n_signals = len(signals)
    n_universe = len(out)
    n_matched = signals["symbol"].isin(out["symbol"]).sum()
    print(
        f"Signals symbols: {n_signals} | Universe snapshot symbols: {n_universe} | Matched: {n_matched}"
    )
    if n_matched < n_signals:
        unmatched = sorted(set(signals["symbol"]) - set(out["symbol"]))
        print(
            f"WARNING: {n_signals - n_matched} signal symbols not found in universe snapshot: {unmatched}"
        )

    return out
