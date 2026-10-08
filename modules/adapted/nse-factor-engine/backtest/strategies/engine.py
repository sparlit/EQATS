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
Backtest Strategy Engine — Master Orchestrator

get_portfolio(gate_id, score_id, signals_df, incumbent_symbols) → top-N DataFrame
run_all_cells(signals_df, current_holdings)                     → long-format DataFrame
"""

import pandas as pd
from backtest.strategies.config import CELLS, N
from backtest.strategies.gates import apply_gate
from backtest.strategies.scores import apply_score

AUDIT_COLS = [
    "symbol",
    "as_of_date",
    "ret_12m1m",
    "fip_score",
    "proximity_52w_high",
    "weinstein_stage2",
    "lottery_class",
    "in_universe",
    "rank_ret_12m1m",
    "rank_fip_ret_12m1m",
    "rank_rs_excess_ret_mkt",
    "rs_excess_ret_mkt",
    "industry_rank",
    "rs_rank_500",
    "adtv_63_cr",
    "rsi_14",
    "rank_rsi_14",
]


def get_portfolio(
    gate_id: str,
    score_id: str,
    signals: pd.DataFrame,
    n: int = N,
    verbose: bool = False,
    incumbent_symbols: set = None,  # symbols held from prior week for this cell
) -> pd.DataFrame:
    """
    gate_id           : 'G2'–'G6'
    score_id          : 'C1', 'C3', 'C6', 'C6RSI', 'C7'
    signals           : signals DataFrame for one Friday
    incumbent_symbols : set of symbols held from prior week (used by C6/C6RSI only)

    Returns           : top-N DataFrame with cell metadata attached
    """
    if incumbent_symbols is None:
        incumbent_symbols = set()

    if not verbose:
        import contextlib
        import io

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            survivors = apply_gate(gate_id, signals)
            top_n = apply_score(score_id, survivors, n=n, incumbent_symbols=incumbent_symbols)
    else:
        survivors = apply_gate(gate_id, signals)
        top_n = apply_score(score_id, survivors, n=n, incumbent_symbols=incumbent_symbols)

    if top_n.empty:
        return pd.DataFrame()

    top_n["gate_id"] = gate_id
    top_n["score_id"] = score_id
    top_n["cell_id"] = f"{gate_id}_{score_id}"

    keep = ["gate_id", "score_id", "cell_id", "final_rank", "composite_score"] + [
        c for c in AUDIT_COLS if c in top_n.columns
    ]
    keep = list(dict.fromkeys(keep))

    return top_n[keep].reset_index(drop=True)


def run_all_cells(
    signals: pd.DataFrame,
    n: int = N,
    verbose: bool = False,
    current_holdings: dict = None,  # {cell_id: set(symbols)} from prior week
) -> pd.DataFrame:
    """
    Runs all cells on a single Friday signals DataFrame.

    current_holdings : dict of {cell_id: set(symbols)} held from prior week.
                       Used by C6/C6RSI incumbent multiplier. Pass {} for week 1.

    Returns long-format DataFrame: all cells × up to 25 stocks
    """
    if current_holdings is None:
        current_holdings = {}

    results = []

    for gate_id, score_id in CELLS:
        cell_id = f"{gate_id}_{score_id}"
        incumbent_symbols = current_holdings.get(cell_id, set())

        df = get_portfolio(
            gate_id, score_id, signals, n=n, verbose=verbose, incumbent_symbols=incumbent_symbols
        )
        if not df.empty:
            results.append(df)
        else:
            print(f"WARNING: {cell_id} returned empty portfolio")

    if not results:
        print("ERROR: all cells returned empty")
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)
