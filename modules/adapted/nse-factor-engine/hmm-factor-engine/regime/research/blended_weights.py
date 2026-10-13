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


# Part 9: Blended Weights (soft probability-weighted factor weights)
# Formula: w_blended = P(Bull)*w_Bull + P(Choppy)*w_Choppy + P(Crisis)*w_Crisis
# No hard regime switching — smooth blend each month

import json
from pathlib import Path

import pandas as pd

BASE_DIR = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine")
FORWARD_F = BASE_DIR / "regime/models/hmm_forward_probs_202001_202606.parquet"
WEIGHTS_F = BASE_DIR / "regime/weight_matrix.json"
OUT_PARQUET = BASE_DIR / "regime/blended_weights.parquet"
OUT_JSON = BASE_DIR / "regime/blended_weights.json"

ACTIVE_METHOD = "sharpe_erc"  # change to: erc | sharpe_erc
METHODS = ["erc", "sharpe_erc"]
FACTORS = ["mom", "bab", "rmw_roe", "value", "size"]
REGIMES = ["Bull", "Choppy", "Crisis"]

# ── Load ──────────────────────────────────────────────────────────────────────
forward = pd.read_parquet(FORWARD_F)
forward.index = pd.to_datetime(forward.index).to_period("M")

wm = json.load(open(WEIGHTS_F))["all_methods"]

# ── Compute blended weights per method per month ───────────────────────────────
all_blended = {}  # method -> {period -> {factor -> weight}}

for method in METHODS:
    blended = {}
    for period, row in forward.iterrows():
        p_bull = row["P_Bull"]
        p_choppy = row["P_Choppy"]
        p_crisis = row["P_Crisis"]

        w = {}
        for factor in FACTORS:
            w[factor] = (
                p_bull * wm[method]["Bull"][factor]
                + p_choppy * wm[method]["Choppy"][factor]
                + p_crisis * wm[method]["Crisis"][factor]
            )
        blended[str(period)] = w
    all_blended[method] = blended

# ── Build output dataframe ────────────────────────────────────────────────────
records = []
for method in METHODS:
    for period_str, weights in all_blended[method].items():
        row = {"date": period_str, "method": method}
        row.update({f: round(weights[f], 4) for f in FACTORS})
        row["weight_sum"] = round(sum(weights[f] for f in FACTORS), 6)
        records.append(row)

out = pd.DataFrame(records)
out["date"] = pd.PeriodIndex(out["date"], freq="M")
out = out.set_index(["date", "method"]).sort_index()

# ── Print active method ───────────────────────────────────────────────────────
print(f"\nActive method : {ACTIVE_METHOD}")
print(f"Window        : {forward.index[0]} → {forward.index[-1]}  ({len(forward)} months)")

active = out.xs(ACTIVE_METHOD, level="method")

print(f"\n--- Blended weights ({ACTIVE_METHOD}) ---")
print(f"  {'Date':<10} {'Regime':<10}", end="")
for f in FACTORS:
    print(f"  {f:>10}", end="")
print(f"  {'Sum':>6}")
print(f"  {'-' * 10} {'-' * 10}", end="")
for f in FACTORS:
    print(f"  {'-' * 10}", end="")
print(f"  {'-' * 6}")

for period, row in active.iterrows():
    regime = forward.loc[period, "regime"]
    print(f"  {str(period):<10} {regime:<10}", end="")
    for f in FACTORS:
        print(f"  {row[f]:>10.4f}", end="")
    print(f"  {row['weight_sum']:>6.4f}")

# ── Compare hard vs soft weights for active method ───────────────────────────
print(f"\n--- Hard vs Soft weights sample (first 6 months, {ACTIVE_METHOD}) ---")
print(
    f"  {'Date':<10} {'Regime':<10} {'P_Bull':>7} {'P_Chop':>7} {'P_Cris':>7}  {'Hard mom':>9} {'Soft mom':>9}  {'Hard val':>9} {'Soft val':>9}"
)
print(
    f"  {'-' * 10} {'-' * 10} {'-' * 7} {'-' * 7} {'-' * 7}  {'-' * 9} {'-' * 9}  {'-' * 9} {'-' * 9}"
)
for period, frow in forward.iloc[:6].iterrows():
    regime = frow["regime"]
    hard_mom = wm[ACTIVE_METHOD][regime]["mom"]
    hard_val = wm[ACTIVE_METHOD][regime]["value"]
    soft_mom = active.loc[period, "mom"]
    soft_val = active.loc[period, "value"]
    print(
        f"  {str(period):<10} {regime:<10} {frow['P_Bull']:>7.3f} {frow['P_Choppy']:>7.3f} {frow['P_Crisis']:>7.3f}  {hard_mom:>9.4f} {soft_mom:>9.4f}  {hard_val:>9.4f} {soft_val:>9.4f}"
    )

# ── Save ──────────────────────────────────────────────────────────────────────
out.to_parquet(OUT_PARQUET)

json_out = {
    "active_method": ACTIVE_METHOD,
    "methods": METHODS,
    "weights": {method: all_blended[method] for method in METHODS},
}
with open(OUT_JSON, "w") as f:
    json.dump(json_out, f, indent=2)

print(f"\nSaved parquet → {OUT_PARQUET}")
print(f"Saved json    → {OUT_JSON}")
