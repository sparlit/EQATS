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
hmm_forward_algo.py
Causal forward algorithm -- at month T, only data up to T is used.
No lookahead. Safe for production use.

CHANGE vs original: all logic wrapped in run_forward_algo() so it can be
imported by regime_master.py. Running standalone (python3 hmm_forward_algo.py)
behaves identically to before.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import multivariate_normal

BASE_DIR = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine")
MODEL_FILE = BASE_DIR / "regime/models/hmm_3states_200511_201912.pkl"
DATA_FILE = BASE_DIR / "data/nifty500_hmm_data.parquet"
OUT_PARQUET = BASE_DIR / "regime/models/hmm_forward_probs_202001_202606.parquet"
OUT_JSON = BASE_DIR / "regime/models/hmm_forward_probs_202001_202606_summary.json"
BW_CSV = Path("/tmp/eval_window_gamma.csv")

EVAL_START = "2020-01"
import pandas as _pd

_hmm_df = _pd.read_parquet(str(DATA_FILE))
EVAL_END = _hmm_df.index.max().strftime("%Y-%m")


def run_forward_algo(as_of_date=None, verbose=True):
    """
    Run the causal HMM forward algorithm.

    as_of_date : str "YYYY-MM" or None  ->  uses EVAL_END if None.

    Returns dict:
        as_of_month, regime, P_Bull, P_Choppy, P_Crisis,
        model_train_window, full_series (DataFrame)
    """
    eval_end = as_of_date if as_of_date else EVAL_END

    # Load model
    bundle = joblib.load(MODEL_FILE)
    model = bundle["model"]
    scaler = bundle["scaler"]
    state_labels = bundle["state_labels"]  # {0: Choppy, 1: Crisis, 2: Bull}
    features = bundle["hmm_features"]
    label_map = {v: k for k, v in state_labels.items()}  # Bull->2, Choppy->0, Crisis->1
    n_states = model.n_components

    if verbose:
        print(f"Model           : {bundle['train_start']} -> {bundle['train_end']}")
        print(f"State labels    : {state_labels}")

    # Load eval data
    df = pd.read_parquet(DATA_FILE)
    df.index = pd.to_datetime(df.index)
    mask = (df.index >= pd.Period(EVAL_START, "M").to_timestamp()) & (
        df.index <= pd.Period(eval_end, "M").to_timestamp(how="end")
    )
    data = df.loc[mask, features].dropna()

    if verbose:
        print(f"Eval window     : {data.index[0].date()} -> {data.index[-1].date()}")
        print(f"Months          : {len(data)}")

    # Scale
    X = scaler.transform(data.values)

    # Emission log-probabilities
    log_b = np.column_stack(
        [
            multivariate_normal.logpdf(X, mean=model.means_[s], cov=model.covars_[s])
            for s in range(n_states)
        ]
    )

    # Initial state: use Dec 2019 Viterbi label as prior
    dec2019_label = "Bull"
    init_state = label_map[dec2019_label]
    state_vec = np.zeros(n_states)
    state_vec[init_state] = 1.0
    prior = model.transmat_[init_state]

    # Forward pass (causal)
    alpha = np.zeros((len(X), n_states))
    alpha[0] = prior * np.exp(log_b[0])
    s = alpha[0].sum()
    alpha[0] = alpha[0] / s if s > 0 else prior

    for t in range(1, len(X)):
        alpha[t] = (model.transmat_.T @ alpha[t - 1]) * np.exp(log_b[t])
        s = alpha[t].sum()
        alpha[t] = alpha[t] / s if s > 0 else alpha[t - 1]

    # Build output
    P_Bull = alpha[:, label_map["Bull"]]
    P_Choppy = alpha[:, label_map["Choppy"]]
    P_Crisis = alpha[:, label_map["Crisis"]]
    regime = [state_labels[np.argmax(alpha[t])] for t in range(len(X))]

    out = pd.DataFrame(
        {
            "P_Bull": P_Bull,
            "P_Choppy": P_Choppy,
            "P_Crisis": P_Crisis,
            "regime": regime,
        },
        index=data.index,
    )
    out.index.name = "date"

    if verbose:
        # Print sequence
        print(f"\n{'Date':<10} {'P_Bull':>8} {'P_Choppy':>10} {'P_Crisis':>10} {'regime':<10}")
        print("-" * 52)
        for date, row in out.iterrows():
            print(
                f"{date.strftime('%Y-%m'):<10} {row['P_Bull']:>8.4f} {row['P_Choppy']:>10.4f} {row['P_Crisis']:>10.4f} {row['regime']:<10}"
            )

        # Regime distribution
        print("\n--- Regime distribution ---")
        counts = out["regime"].value_counts()
        for r in ["Bull", "Choppy", "Crisis"]:
            n = counts.get(r, 0)
            print(f"  {r:<8} : {n:>3} months  ({n / len(out) * 100:.1f}%)")

        # Validation vs BW
        if BW_CSV.exists():
            bw = pd.read_csv(BW_CSV)
            bw["date"] = pd.to_datetime(bw["date"])
            out_reset = out.reset_index()
            out_reset["date"] = pd.to_datetime(
                out_reset["date"].dt.to_period("M").dt.to_timestamp()
            )
            merged = bw.merge(out_reset[["date", "regime"]], on="date", suffixes=("_bw", "_fwd"))
            matches = (merged["viterbi"] == merged["regime"]).sum()
            total = len(merged)
            print("\n--- Validation vs BW gamma (eval_window_gamma.csv) ---")
            print(f"  Forward algo matches Viterbi : {matches} / {total}")
            diff = merged[merged["viterbi"] != merged["regime"]][
                ["date", "viterbi", "regime", "P_Bull", "P_Choppy", "P_Crisis"]
            ]
            if not diff.empty:
                print(f"  Months that differ ({len(diff)}):")
                print(diff.to_string(index=False))

    # Save
    counts = out["regime"].value_counts()
    out.to_parquet(OUT_PARQUET)
    if verbose:
        print(f"\nSaved parquet -> {OUT_PARQUET}")

    summary = {
        "eval_window": {"start": EVAL_START, "end": eval_end, "n_months": len(out)},
        "initial_state": {"dec2019_label": dec2019_label, "prior": prior.tolist()},
        "regime_counts": {r: int(counts.get(r, 0)) for r in ["Bull", "Choppy", "Crisis"]},
        "regime_pct": {
            r: round(counts.get(r, 0) / len(out) * 100, 2) for r in ["Bull", "Choppy", "Crisis"]
        },
    }
    with open(OUT_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    if verbose:
        print(f"Saved json     -> {OUT_JSON}")

    # Return latest snapshot for regime_master.py to consume
    latest = out.iloc[-1]
    return {
        "as_of_month": latest.name.strftime("%Y-%m"),
        "regime": latest["regime"],
        "P_Bull": round(float(latest["P_Bull"]), 4),
        "P_Choppy": round(float(latest["P_Choppy"]), 4),
        "P_Crisis": round(float(latest["P_Crisis"]), 4),
        "model_train_window": f"{bundle['train_start']}-{bundle['train_end']}",
        "full_series": out,
    }


if __name__ == "__main__":
    run_forward_algo(as_of_date=None, verbose=True)
