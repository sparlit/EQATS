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


# Part 6: Factor-Regime Statistics

import os

import numpy as np
import pandas as pd

BASE_DIR = "/home/ec2-user/nse-factor-engine/hmm-factor-engine"
FACTORS_F = os.path.join(BASE_DIR, "factors", "data", "factor_assembler_output.parquet")
VITERBI_F = os.path.join(BASE_DIR, "regime", "models", "hmm_viterbi_labels_200511_201912.parquet")
FORWARD_F = os.path.join(BASE_DIR, "regime", "models", "hmm_forward_probs_202001_202606.parquet")
OUT_FILE = os.path.join(BASE_DIR, "regime", "factor_regime_stats.parquet")

REGIMES = ["Bull", "Choppy", "Crisis"]
FACTORS = ["mom", "bab", "rmw_roe", "value", "size"]

# ── Load factor returns ───────────────────────────────────────────────────────
factors = pd.read_parquet(FACTORS_F)
factors.index = pd.to_datetime(factors.index.to_timestamp())

# ── Build regime label series ─────────────────────────────────────────────────
viterbi = pd.read_parquet(VITERBI_F)[["regime"]]
viterbi.index = pd.to_datetime(viterbi.index)
viterbi = viterbi[viterbi.index < pd.Timestamp("2020-01-01")]

forward = pd.read_parquet(FORWARD_F)[["regime"]]
forward.index = pd.to_datetime(forward.index)

regime_labels = pd.concat([viterbi, forward]).sort_index()
regime_labels.index = regime_labels.index.to_period("M").to_timestamp()

print(
    f"Regime labels   : {regime_labels.index[0].date()} → {regime_labels.index[-1].date()}  ({len(regime_labels)} months)"
)
print("Viterbi portion : up to 2019-12")
print("Forward portion : 2020-01 onwards")
print("\nRegime distribution:")
print(regime_labels["regime"].value_counts().to_string())

# ── Merge ─────────────────────────────────────────────────────────────────────
merged = factors.join(regime_labels, how="left")
merged = merged.dropna(subset=["regime"])

print(f"\nMerged window   : {merged.index[0].date()} → {merged.index[-1].date()}  ({len(merged)} months)")


# ── Compute stats per factor × regime ─────────────────────────────────────────
def sharpe(r):
    r = r.dropna()
    if len(r) < 2 or r.std() == 0:
        return np.nan
    return (r.mean() / r.std()) * np.sqrt(12)


records = []
for regime in REGIMES:
    subset = merged[merged["regime"] == regime]
    for factor in FACTORS:
        r = subset[factor].dropna()
        if len(r) == 0:
            continue
        records.append(
            {
                "regime": regime,
                "factor": factor,
                "n_months": len(r),
                "mean_monthly": round(r.mean() * 100, 4),
                "ann_return": round(r.mean() * 12 * 100, 2),
                "sharpe": round(sharpe(r), 3),
                "hit_rate": round((r > 0).mean() * 100, 1),
            }
        )

stats = pd.DataFrame(records).set_index(["regime", "factor"])

# ── Print per-regime table ────────────────────────────────────────────────────
for regime in REGIMES:
    print(f"\n{'=' * 70}")
    print(f"  {regime.upper()}")
    print(f"{'=' * 70}")
    df = stats.loc[regime]
    print(f"  {'Factor':<12} {'N':>5} {'Mean%':>8} {'AnnRet':>9} {'Sharpe':>8} {'HitRate':>9}")
    print(f"  {'-' * 12} {'-' * 5} {'-' * 8} {'-' * 9} {'-' * 8} {'-' * 9}")
    for factor in FACTORS:
        if factor not in df.index:
            continue
        r = df.loc[factor]
        print(
            f"  {factor:<12} {int(r['n_months']):>5} {r['mean_monthly']:>+8.3f} {r['ann_return']:>+8.2f}% {r['sharpe']:>+8.3f} {r['hit_rate']:>8.1f}%"
        )

# ── Conditional correlations ──────────────────────────────────────────────────
print("\n--- Conditional correlations ---")
for regime in REGIMES:
    subset = merged[merged["regime"] == regime][FACTORS].dropna(how="all")
    print(f"\n  {regime}  (n={len(subset)})")
    pd.set_option("display.float_format", "{:+.2f}".format)
    pd.set_option("display.width", 120)
    print(subset.corr().to_string())

# ── Save ──────────────────────────────────────────────────────────────────────
stats.to_parquet(OUT_FILE)
print(f"\nSaved → {OUT_FILE}")
