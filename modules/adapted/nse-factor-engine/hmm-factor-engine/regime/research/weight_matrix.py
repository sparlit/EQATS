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


# Part 7: Weight Matrix — 4 methods compared per regime
# Methods: ERC | Sharpe-weighted ERC | MVO (sample) | MVO (shrinkage)
# Negative-Sharpe factors get zero weight in that regime

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

BASE_DIR = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine")
FACTORS_F = BASE_DIR / "factors/data/factor_assembler_output.parquet"
VITERBI_F = BASE_DIR / "regime/models/hmm_viterbi_labels_200511_201912.parquet"
FORWARD_F = BASE_DIR / "regime/models/hmm_forward_probs_202001_202606.parquet"
OUT_PARQUET = BASE_DIR / "regime/weight_matrix.parquet"
OUT_JSON = BASE_DIR / "regime/weight_matrix.json"

REGIMES = ["Bull", "Choppy", "Crisis"]
FACTORS = ["mom", "bab", "rmw_roe", "value", "size"]
SHRINKAGE = 0.5  # blend: 0.5 * sample_mean + 0.5 * zero
MIN_SHARPE = -0.1  # exclude factors with regime Sharpe below this

# ── Load & merge ──────────────────────────────────────────────────────────────
factors = pd.read_parquet(FACTORS_F)
factors.index = pd.to_datetime(factors.index.to_timestamp())

viterbi = pd.read_parquet(VITERBI_F)[["regime"]]
viterbi.index = pd.to_datetime(viterbi.index)
viterbi = viterbi[viterbi.index < pd.Timestamp("2020-01-01")]

forward = pd.read_parquet(FORWARD_F)[["regime"]]
forward.index = pd.to_datetime(forward.index)

regime_labels = pd.concat([viterbi, forward]).sort_index()
regime_labels.index = regime_labels.index.to_period("M").to_timestamp()

merged_full = factors.join(regime_labels, how="left").dropna(subset=["regime"])
merged = merged_full[merged_full.index <= pd.Timestamp("2024-06-01")]


# ── Helpers ───────────────────────────────────────────────────────────────────
def annualised_sharpe(r):
    r = r.dropna()
    if len(r) < 2 or r.std() == 0:
        return np.nan
    return (r.mean() / r.std()) * np.sqrt(12)


def clean_cov(subset, active):
    """Covariance matrix for active factors only."""
    cov = subset[active].cov().values
    # Regularise: add small diagonal to avoid singularity
    cov += np.eye(len(active)) * 1e-8
    return cov


def solve_weights(objective, n, bounds, constraints):
    w0 = np.ones(n) / n
    res = minimize(
        objective, w0, method="SLSQP", bounds=bounds, constraints=constraints, options={"ftol": 1e-12, "maxiter": 2000}
    )
    return res.x


def erc(cov):
    n = cov.shape[0]

    def obj(w):
        pvar = w @ cov @ w
        rc = w * (cov @ w) / pvar
        return np.sum((rc - 1 / n) ** 2)

    bounds = [(0.0, 1.0)] * n
    constraints = {"type": "eq", "fun": lambda w: w.sum() - 1}
    return solve_weights(obj, n, bounds, constraints)


def sharpe_erc(cov, sharpes):
    n = cov.shape[0]
    targets = np.array(sharpes) / np.sum(sharpes)  # proportional targets

    def obj(w):
        pvar = w @ cov @ w
        rc = w * (cov @ w) / pvar
        return np.sum((rc - targets) ** 2)

    bounds = [(0.0, 1.0)] * n
    constraints = {"type": "eq", "fun": lambda w: w.sum() - 1}
    return solve_weights(obj, n, bounds, constraints)


def mvo(cov, mu):
    n = cov.shape[0]

    def obj(w):
        port_var = w @ cov @ w
        port_ret = w @ mu
        return -(port_ret / np.sqrt(port_var))  # maximise Sharpe

    bounds = [(0.0, 1.0)] * n
    constraints = {"type": "eq", "fun": lambda w: w.sum() - 1}
    return solve_weights(obj, n, bounds, constraints)


# ── Run all 4 methods per regime ──────────────────────────────────────────────
results = {m: {} for m in ["erc", "sharpe_erc", "mvo_sample", "mvo_shrink"]}

for regime in REGIMES:
    subset = merged[merged["regime"] == regime][FACTORS]

    # Compute Sharpe per factor in this regime
    sharpes = {f: annualised_sharpe(subset[f]) for f in FACTORS}

    # Active factors: Sharpe >= MIN_SHARPE and enough data
    active = [
        f for f in FACTORS if not np.isnan(sharpes[f]) and sharpes[f] >= MIN_SHARPE and subset[f].dropna().shape[0] >= 3
    ]

    print(f"\n{regime}: active factors = {active}")

    if len(active) == 0:
        for m in results:
            results[m][regime] = dict.fromkeys(FACTORS, 0.0)
        continue

    cov = clean_cov(subset, active)
    mu = subset[active].mean().values
    mu_shrink = mu * SHRINKAGE  # shrink toward zero
    s_vals = np.array([sharpes[f] for f in active])

    # 1. Pure ERC
    w_erc = erc(cov)

    # 2. Sharpe-weighted ERC
    w_serc = sharpe_erc(cov, s_vals)

    # 3. MVO sample means
    w_mvo = mvo(cov, mu)

    # 4. MVO shrinkage
    w_mvos = mvo(cov, mu_shrink)

    def full_weights(active_w):
        w = dict.fromkeys(FACTORS, 0.0)
        for f, wt in zip(active, active_w, strict=False):
            w[f] = round(float(wt), 4)
        return w

    results["erc"][regime] = full_weights(w_erc)
    results["sharpe_erc"][regime] = full_weights(w_serc)
    results["mvo_sample"][regime] = full_weights(w_mvo)
    results["mvo_shrink"][regime] = full_weights(w_mvos)

# ── Print comparison ──────────────────────────────────────────────────────────
METHOD_LABELS = {
    "erc": "ERC (pure)",
    "sharpe_erc": "Sharpe-ERC",
    "mvo_sample": "MVO sample",
    "mvo_shrink": "MVO shrink",
}

for regime in REGIMES:
    print(f"\n{'=' * 80}")
    print(f"  {regime.upper()}")
    print(f"{'=' * 80}")
    print(f"  {'Method':<14}", end="")
    for f in FACTORS:
        print(f"  {f:>10}", end="")
    print(f"  {'Sum':>6}")
    print(f"  {'-' * 14}", end="")
    for f in FACTORS:
        print(f"  {'-' * 10}", end="")
    print(f"  {'-' * 6}")
    for method, label in METHOD_LABELS.items():
        print(f"  {label:<14}", end="")
        total = 0
        for f in FACTORS:
            w = results[method][regime][f]
            total += w
            print(f"  {w:>10.4f}", end="")
        print(f"  {total:>6.4f}")

# ── Save chosen method ───────────────────────────────────────────────────────
chosen = "sharpe_erc"
# Mixed method: mvo_shrink for Bull/Choppy, ERC for Crisis
mixed = {}
for regime in REGIMES:
    mixed[regime] = results[chosen][regime]
results["mixed"] = mixed
out = pd.DataFrame(results["mixed"]).T
out.index.name = "regime"
out.to_parquet(OUT_PARQUET)

all_results = {m: {r: results[m][r] for r in REGIMES} for m in results if m != "mixed"}
all_results["mixed"] = mixed
with open(OUT_JSON, "w") as fp:
    json.dump({"chosen": chosen, "all_methods": all_results}, fp, indent=2)

print(f"\nDefault saved ('{chosen}') → {OUT_PARQUET}")
print(f"All methods saved         → {OUT_JSON}")
