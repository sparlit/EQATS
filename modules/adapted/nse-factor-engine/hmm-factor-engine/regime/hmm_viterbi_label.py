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
hmm_viterbi_label.py
====================
Decodes the most probable regime sequence across the training window
using the Viterbi algorithm on the fitted HMM, then applies a minimum
duration filter to correct spurious single-month Crisis labels.

Loads the trained model bundle from hmm_baum_welch_training.py and
assigns a single hard regime label (Bull / Choppy / Crisis) to every
month in the construction window (2005-11 to 2019-12).

The evaluation window (2020-01 to 2024-12) is NOT touched here.
That is the forward algorithm's job (hmm_forward_algo.py).

Minimum Duration Filter
-----------------------
Any Crisis episode shorter than MIN_CRISIS_DURATION consecutive months
is relabelled Choppy. Rationale:
  - Genuine systemic crises (GFC, COVID) persist for many months
  - Single-month vol spikes that trigger Crisis at the emission level
    are corrections, not systemic events
  - The HMM model itself is not modified — this is post-hoc only
  - Default: MIN_CRISIS_DURATION = 3 months

Input
-----
hmm-factor-engine/data/nifty500_hmm_data.parquet
hmm-factor-engine/regime/models/hmm_3states_200511_201912.pkl

Output
------
hmm-factor-engine/regime/models/hmm_viterbi_labels_200511_201912.parquet
    Columns:
        regime          : hard label after duration filter — Bull/Choppy/Crisis
        regime_raw      : hard label before duration filter (for audit)
        excess_return   : original feature (for audit)
        realised_vol    : original feature (for audit)

hmm-factor-engine/regime/models/hmm_viterbi_labels_200511_201912_summary.json
    Contains:
        regime_counts       : months per regime (post-filter)
        regime_pct          : % of training window per regime (post-filter)
        duration_stats      : avg/max consecutive months per regime
        filter_changes      : months relabelled by duration filter
        stress_validation   : known stress period labels
        bull_validation     : known bull period labels

Usage
-----
  python3 hmm-factor-engine/regime/hmm_viterbi_label.py

Dependencies
------------
  pip install hmmlearn scikit-learn pandas pyarrow joblib
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_FILE = Path(
    "/home/ec2-user/nse-factor-engine/hmm-factor-engine/data/nifty500_hmm_data.parquet"
)
MODEL_FILE = Path(
    "/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/models/hmm_3states_200511_201912.pkl"
)
LABELS_FILE = Path(
    "/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/models/hmm_viterbi_labels_200511_201912.parquet"
)
SUMMARY_FILE = Path(
    "/home/ec2-user/nse-factor-engine/hmm-factor-engine/regime/models/hmm_viterbi_labels_200511_201912_summary.json"
)

TRAIN_START = "2005-11"
TRAIN_END = "2019-12"
MIN_CRISIS_DURATION = 3  # months — Crisis episodes shorter than this -> Choppy

STRESS_PERIODS = {
    "GFC onset (2008-10)": "2008-10",
    "GFC trough (2009-01)": "2009-01",
    "Euro crisis (2011-08)": "2011-08",
    "Taper tantrum (2013-06)": "2013-06",
    "NBFC crisis (2018-09)": "2018-09",
}
BULL_PERIODS = {
    "Modi election rally (2014-06)": "2014-06",
    "Bull run mid (2017-06)": "2017-06",
}


# ---------------------------------------------------------------------------
# Load training slice
# ---------------------------------------------------------------------------
def load_training_data(data_file: Path, start: str, end: str, features: list) -> pd.DataFrame:
    df = pd.read_parquet(data_file)
    mask = (df.index >= pd.Period(start, "M").to_timestamp()) & (
        df.index <= pd.Period(end, "M").to_timestamp(how="end")
    )
    train = df.loc[mask, features].copy()
    print(f"Training window : {train.index[0].date()} -> {train.index[-1].date()}")
    print(f"Months          : {len(train)}")
    return train


# ---------------------------------------------------------------------------
# Run Viterbi
# ---------------------------------------------------------------------------
def run_viterbi(train: pd.DataFrame, bundle: dict) -> pd.Series:
    model = bundle["model"]
    scaler = bundle["scaler"]
    state_labels = bundle["state_labels"]
    features = bundle["hmm_features"]

    X_scaled = scaler.transform(train[features].values)
    viterbi_numeric = model.predict(X_scaled)
    viterbi_labels = pd.Series(
        [state_labels[s] for s in viterbi_numeric],
        index=train.index,
        name="regime_raw",
    )
    return viterbi_labels


# ---------------------------------------------------------------------------
# Minimum duration filter
# ---------------------------------------------------------------------------
def apply_min_duration_filter(
    labels: pd.Series,
    min_duration: int = MIN_CRISIS_DURATION,
    target: str = "Crisis",
    relabel_as: str = "Choppy",
) -> tuple:
    """
    Relabels any 'target' episode shorter than min_duration consecutive
    months to 'relabel_as'. Returns filtered series and change log.
    """
    filtered = labels.copy()
    changes = []

    # Identify contiguous episodes of target regime
    in_episode = False
    episode_start = None

    for i, (_date, label) in enumerate(labels.items()):
        if label == target and not in_episode:
            in_episode = True
            episode_start = i
        elif label != target and in_episode:
            episode_end = i
            duration = episode_end - episode_start
            if duration < min_duration:
                affected_dates = labels.index[episode_start:episode_end]
                filtered.iloc[episode_start:episode_end] = relabel_as
                changes.append(
                    {
                        "start": affected_dates[0].strftime("%Y-%m"),
                        "end": affected_dates[-1].strftime("%Y-%m"),
                        "duration": duration,
                        "action": f"{target} -> {relabel_as}",
                    }
                )
            in_episode = False

    # Handle episode that runs to end of series
    if in_episode:
        episode_end = len(labels)
        duration = episode_end - episode_start
        if duration < min_duration:
            filtered.iloc[episode_start:episode_end] = relabel_as
            affected_dates = labels.index[episode_start:episode_end]
            changes.append(
                {
                    "start": affected_dates[0].strftime("%Y-%m"),
                    "end": affected_dates[-1].strftime("%Y-%m"),
                    "duration": duration,
                    "action": f"{target} -> {relabel_as}",
                }
            )

    filtered.name = "regime"
    return filtered, changes


# ---------------------------------------------------------------------------
# Compute regime duration stats
# ---------------------------------------------------------------------------
def compute_duration_stats(labels: pd.Series) -> dict:
    stats = {}
    for regime in ["Bull", "Choppy", "Crisis"]:
        durations = []
        count = 0
        for label in labels:
            if label == regime:
                count += 1
            else:
                if count > 0:
                    durations.append(count)
                count = 0
        if count > 0:
            durations.append(count)
        stats[regime] = {
            "avg_duration": round(float(np.mean(durations)), 2) if durations else 0,
            "max_duration": int(max(durations)) if durations else 0,
            "n_episodes": len(durations),
        }
    return stats


# ---------------------------------------------------------------------------
# Print full label sequence (raw vs filtered side by side)
# ---------------------------------------------------------------------------
def print_label_sequence(raw: pd.Series, filtered: pd.Series) -> None:
    print("\n--- Full regime label sequence (raw | filtered) ---")
    print(f"  {'Date':<12} {'Raw':<10} {'Filtered':<10} {'Changed'}")
    print(f"  {'-' * 12} {'-' * 10} {'-' * 10} {'-' * 7}")
    for date in raw.index:
        r = raw[date]
        f = filtered[date]
        changed = "<-- relabelled" if r != f else ""
        print(f"  {date.strftime('%Y-%m'):<12} {r:<10} {f:<10} {changed}")


# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------
def print_summary(raw: pd.Series, filtered: pd.Series, changes: list, duration_stats: dict) -> None:
    counts = filtered.value_counts()
    total = len(filtered)

    print("\n" + "=" * 65)
    print("VITERBI DECODE SUMMARY")
    print("=" * 65)

    print("\n--- Duration filter ---")
    print(f"  MIN_CRISIS_DURATION : {MIN_CRISIS_DURATION} months")
    if changes:
        print(f"  Episodes relabelled : {len(changes)}")
        for c in changes:
            print(f"    {c['start']} -> {c['end']}  ({c['duration']} month(s))  {c['action']}")
    else:
        print("  Episodes relabelled : 0 — no short Crisis episodes found")

    print("\n--- Regime distribution (post-filter) ---")
    print(
        f"  {'Regime':<10} {'Months':>8} {'Pct':>8} "
        f"{'Avg Run':>10} {'Max Run':>10} {'Episodes':>10}"
    )
    print(f"  {'-' * 10} {'-' * 8} {'-' * 8} {'-' * 10} {'-' * 10} {'-' * 10}")
    for regime in ["Bull", "Choppy", "Crisis"]:
        n = counts.get(regime, 0)
        pct = n / total * 100
        d = duration_stats[regime]
        print(
            f"  {regime:<10} {n:>8} {pct:>7.1f}% "
            f"{d['avg_duration']:>10.1f} "
            f"{d['max_duration']:>10} "
            f"{d['n_episodes']:>10}"
        )

    print("\n--- Stress period validation (expect Crisis or Choppy, never Bull) ---")
    for label, month in STRESS_PERIODS.items():
        match = filtered[filtered.index.strftime("%Y-%m") == month]
        if not match.empty:
            assigned = match.iloc[0]
            flag = "OK" if assigned != "Bull" else "FAIL — labelled Bull"
            print(f"  {label:<35} -> {assigned:<8}  {flag}")
        else:
            print(f"  {label:<35} -> not in training window")

    print("\n--- Bull period validation (expect Bull, not Crisis) ---")
    for label, month in BULL_PERIODS.items():
        match = filtered[filtered.index.strftime("%Y-%m") == month]
        if not match.empty:
            assigned = match.iloc[0]
            flag = "OK" if assigned != "Crisis" else "FAIL — labelled Crisis"
            print(f"  {label:<35} -> {assigned:<8}  {flag}")
        else:
            print(f"  {label:<35} -> not in training window")

    print("=" * 65)


# ---------------------------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------------------------
def save_artifacts(
    raw: pd.Series, filtered: pd.Series, train: pd.DataFrame, changes: list, duration_stats: dict
) -> None:
    # Parquet
    out = train.copy()
    out.insert(0, "regime", filtered)
    out.insert(1, "regime_raw", raw)
    out.to_parquet(LABELS_FILE)
    print(f"\nLabels saved    -> {LABELS_FILE}")

    # JSON summary
    counts = filtered.value_counts()
    total = len(filtered)

    stress_val = {}
    for label, month in {**STRESS_PERIODS, **BULL_PERIODS}.items():
        match = filtered[filtered.index.strftime("%Y-%m") == month]
        stress_val[label] = match.iloc[0] if not match.empty else "not in window"

    summary = {
        "training_window": {
            "start": TRAIN_START,
            "end": TRAIN_END,
            "n_months": len(filtered),
        },
        "min_crisis_duration_filter": MIN_CRISIS_DURATION,
        "filter_changes": changes,
        "regime_counts": {r: int(counts.get(r, 0)) for r in ["Bull", "Choppy", "Crisis"]},
        "regime_pct": {
            r: round(counts.get(r, 0) / total * 100, 2) for r in ["Bull", "Choppy", "Crisis"]
        },
        "duration_stats": duration_stats,
        "stress_validation": stress_val,
    }

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary saved   -> {SUMMARY_FILE}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # 1. Load model bundle
    print("Loading model bundle ...")
    bundle = joblib.load(MODEL_FILE)
    print(f"  Trained on   : {bundle['train_start']} -> {bundle['train_end']}")
    print(f"  State labels : {bundle['state_labels']}")
    print(f"  Features     : {bundle['hmm_features']}")

    # 2. Load training data
    print("\nLoading training data ...")
    train = load_training_data(DATA_FILE, TRAIN_START, TRAIN_END, bundle["hmm_features"])

    # 3. Run Viterbi
    print("\nRunning Viterbi decode ...")
    raw_labels = run_viterbi(train, bundle)
    print(f"  Decoded {len(raw_labels)} months")

    # 4. Apply minimum duration filter
    print(
        f"\nApplying minimum Crisis duration filter (threshold = {MIN_CRISIS_DURATION} months) ..."
    )
    filtered_labels, changes = apply_min_duration_filter(raw_labels)
    print(f"  Episodes relabelled: {len(changes)}")

    # 5. Print full sequence
    print_label_sequence(raw_labels, filtered_labels)

    # 6. Duration stats on filtered labels
    duration_stats = compute_duration_stats(filtered_labels)

    # 7. Print summary
    print_summary(raw_labels, filtered_labels, changes, duration_stats)

    # 8. Save artifacts
    save_artifacts(raw_labels, filtered_labels, train, changes, duration_stats)

    print("\nDone.")


if __name__ == "__main__":
    main()
