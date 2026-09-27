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
hmm_baum_welch_training.py
==========================
Trains a 3-state Gaussian HMM on Nifty 500 monthly excess return
and realised volatility using the Baum-Welch (EM) algorithm.

Input
-----
hmm-factor-engine/data/nifty500_hmm_data.parquet

Training window (construction window — permanently off limits for evaluation)
-----------------------------------------------------------------------------
  2005-11 to 2019-12  (170 months)
  Includes GFC (2008), Euro crisis (2011), taper tantrum (2013),
  NBFC crisis (2018)

Evaluation window (handled separately — this script does not touch it)
----------------------------------------------------------------------
  2020-01 to 2024-12

HMM Features
------------
  excess_return : monthly Nifty 500 excess return
  realised_vol  : annualised realised volatility

Output
------
hmm-factor-engine/regime/models/hmm_3states_200511_201912.pkl
hmm-factor-engine/regime/models/hmm_3states_200511_201912_params.json

Method
------
  - StandardScaler applied to both features before fitting
  - 50 random initialisations (seeds 0-49), best log-likelihood kept
  - States labelled by volatility rank of emission means:
      lowest vol  -> Bull
      highest vol -> Crisis
      middle vol  -> Choppy

Note on minimum duration filtering
------------------------------------
  The Viterbi script (hmm_viterbi_label.py) applies a post-hoc
  minimum duration filter: any Crisis episode shorter than 3
  consecutive months is relabelled Choppy. This corrects for
  single-month vol spikes that trigger Crisis at the emission level
  but are not genuine systemic crises. The HMM model itself is
  not affected by this filter.

Usage
-----
  python3 hmm-factor-engine/regime/hmm_baum_welch_training.py

Dependencies
------------
  pip install hmmlearn scikit-learn pandas pyarrow joblib
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_FILE = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine/data/nifty500_hmm_data.parquet")
MODEL_DIR = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/models")
MODEL_FILE = MODEL_DIR / "hmm_3states_200511_201912.pkl"
PARAMS_FILE = MODEL_DIR / "hmm_3states_200511_201912_params.json"

TRAIN_START = "2005-11"
TRAIN_END = "2019-12"

HMM_FEATURES = ["excess_return", "realised_vol"]

N_STATES = 3
N_TRIALS = 50
N_ITER = 200
TOL = 1e-4
RANDOM_SEEDS = range(N_TRIALS)


# ---------------------------------------------------------------------------
# Load and slice training data
# ---------------------------------------------------------------------------
def load_training_data(path: Path, start: str, end: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    mask = (df.index >= pd.Period(start, "M").to_timestamp()) & (
        df.index <= pd.Period(end, "M").to_timestamp(how="end")
    )
    train = df.loc[mask, HMM_FEATURES].copy()

    print(f"Training window : {train.index[0].date()} -> {train.index[-1].date()}")
    print(f"Months          : {len(train)}")
    print(f"Features        : {HMM_FEATURES}")
    print(f"Null counts     : {train.isna().sum().to_dict()}")
    return train


# ---------------------------------------------------------------------------
# Fit HMM with multiple random restarts
# ---------------------------------------------------------------------------
def fit_hmm(X_scaled: np.ndarray) -> tuple:
    best_model, best_score = None, -np.inf
    n_converged = 0

    print(f"\nRunning {N_TRIALS} random initialisations ...")
    for seed in RANDOM_SEEDS:
        model = GaussianHMM(
            n_components=N_STATES,
            covariance_type="full",
            n_iter=N_ITER,
            tol=TOL,
            random_state=seed,
        )
        try:
            model.fit(X_scaled)
            score = model.score(X_scaled)
            if model.monitor_.converged:
                n_converged += 1
            if score > best_score:
                best_score, best_model = score, model
        except Exception as e:
            print(f"  Seed {seed:02d}: failed ({e})")
            continue

    print(f"Converged runs  : {n_converged} / {N_TRIALS}")
    print(f"Best log-likelihood : {best_score:.4f}")
    return best_model, best_score


# ---------------------------------------------------------------------------
# Label states by volatility rank of emission means
# ---------------------------------------------------------------------------
def label_states(model: GaussianHMM, scaler: StandardScaler) -> dict:
    means_orig = scaler.inverse_transform(model.means_)
    vol_idx = HMM_FEATURES.index("realised_vol")
    vol_means = means_orig[:, vol_idx]
    sorted_by_vol = np.argsort(vol_means)
    return {
        int(sorted_by_vol[0]): "Bull",
        int(sorted_by_vol[1]): "Choppy",
        int(sorted_by_vol[2]): "Crisis",
    }


# ---------------------------------------------------------------------------
# Print fitted parameters
# ---------------------------------------------------------------------------
def print_parameters(model: GaussianHMM, scaler: StandardScaler, state_labels: dict) -> None:
    means_orig = scaler.inverse_transform(model.means_)
    label_map = {v: k for k, v in state_labels.items()}
    names = ["Bull", "Choppy", "Crisis"]

    print("\n" + "=" * 60)
    print("FITTED HMM PARAMETERS")
    print("=" * 60)

    print("\n--- Emission means (original scale) ---")
    print(f"  {'State':<10} {'Excess Return':>15} {'Realised Vol':>14}")
    print(f"  {'-' * 10} {'-' * 15} {'-' * 14}")
    for name in names:
        idx = label_map[name]
        m = means_orig[idx]
        print(f"  {name:<10} {m[0]:>+14.4f}   {m[1]:>13.4f}")

    print("\n--- Emission covariances (scaled space) ---")
    for name in names:
        idx = label_map[name]
        cov = model.covars_[idx]
        print(f"  {name}:")
        print(f"    [[{cov[0, 0]:>8.4f}  {cov[0, 1]:>8.4f}]")
        print(f"     [{cov[1, 0]:>8.4f}  {cov[1, 1]:>8.4f}]]")

    print("\n--- Transition matrix (row = from, col = to) ---")
    A = model.transmat_
    print(f"  {'From / To':<10}" + "".join(f"{n:>10}" for n in names))
    print("  " + "-" * (10 + 10 * len(names)))
    for name in names:
        idx = label_map[name]
        row = f"  {name:<10}"
        for to_name in names:
            row += f"{A[idx, label_map[to_name]]:>10.4f}"
        print(row)

    print("\n--- Initial state probabilities (pi) ---")
    for name in names:
        idx = label_map[name]
        print(f"  {name:<10} {model.startprob_[idx]:.4f}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Save human-readable artifacts
# ---------------------------------------------------------------------------
def save_artifacts(
    model: GaussianHMM, scaler: StandardScaler, state_labels: dict, best_score: float, train: pd.DataFrame
) -> None:
    label_map = {v: k for k, v in state_labels.items()}
    means_orig = scaler.inverse_transform(model.means_)
    A = model.transmat_
    names = ["Bull", "Choppy", "Crisis"]

    artifact = {
        "training_window": {
            "start": TRAIN_START,
            "end": TRAIN_END,
            "n_months": len(train),
        },
        "hmm_features": HMM_FEATURES,
        "fit_summary": {
            "n_states": N_STATES,
            "n_trials": N_TRIALS,
            "n_iter_per_trial": N_ITER,
            "best_log_likelihood": round(best_score, 6),
        },
        "state_labels": {str(k): v for k, v in state_labels.items()},
        "emission_means": {
            name: {feat: round(float(means_orig[label_map[name]][i]), 6) for i, feat in enumerate(HMM_FEATURES)}
            for name in names
        },
        "emission_covariances_scaled": {name: model.covars_[label_map[name]].round(6).tolist() for name in names},
        "transition_matrix": {
            name: {to_name: round(float(A[label_map[name], label_map[to_name]]), 6) for to_name in names}
            for name in names
        },
        "initial_state_probs": {name: round(float(model.startprob_[label_map[name]]), 6) for name in names},
    }

    with open(PARAMS_FILE, "w") as f:
        json.dump(artifact, f, indent=2)
    print(f"Artifacts saved -> {PARAMS_FILE}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load training data
    print("Loading training data ...")
    train = load_training_data(DATA_FILE, TRAIN_START, TRAIN_END)

    # 2. Scale features
    X = train.values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    print("\nScaler means    : " + ", ".join(f"{f}={scaler.mean_[i]:.6f}" for i, f in enumerate(HMM_FEATURES)))
    print("Scaler std devs : " + ", ".join(f"{f}={scaler.scale_[i]:.6f}" for i, f in enumerate(HMM_FEATURES)))

    # 3. Fit HMM
    best_model, best_score = fit_hmm(X_scaled)

    if best_model is None:
        print("ERROR: all initialisations failed.")
        return

    # 4. Label states
    state_labels = label_states(best_model, scaler)
    print(f"\nState labels    : {state_labels}")

    # 5. Print parameters
    print_parameters(best_model, scaler, state_labels)

    # 6. Save model bundle
    bundle = {
        "model": best_model,
        "scaler": scaler,
        "state_labels": state_labels,
        "hmm_features": HMM_FEATURES,
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "best_score": best_score,
        "n_trials": N_TRIALS,
    }
    joblib.dump(bundle, MODEL_FILE)
    print(f"\nModel saved     -> {MODEL_FILE}")

    # 7. Save human-readable artifacts
    save_artifacts(best_model, scaler, state_labels, best_score, train)

    print("Done.")


if __name__ == "__main__":
    main()
