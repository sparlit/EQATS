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


# Part 3: Factor Validation (bootstrap + OOS test)
# Tests: NW t-stat > 2.0 | Bootstrap IS Sharpe > 0.5 | OOS degradation < 30%

import os

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_hac

BASE_DIR = "/home/ec2-user/nse-factor-engine/hmm-factor-engine"
DATA_DIR = os.path.join(BASE_DIR, "factors", "data")
OUT_FILE = os.path.join(DATA_DIR, "validation_results.parquet")

FACTORS = [
    ("MOM", "mom_returns.parquet", "mom_return", "2014-01", "2023-05", "2023-06", "2026-05"),
    (
        "LOWVOL",
        "lowvol_returns.parquet",
        "lowvol_return",
        "2014-01",
        "2023-05",
        "2023-06",
        "2026-05",
    ),
    ("BAB", "bab_returns.parquet", "bab_return", "2016-01", "2023-05", "2023-06", "2026-05"),
    (
        "RMW_ROE",
        "rmw_roe_returns.parquet",
        "rmw_roe_return",
        "2018-07",
        "2023-05",
        "2023-06",
        "2026-05",
    ),
    (
        "RMW_OP_ROE",
        "rmw_op_roe_returns.parquet",
        "rmw_op_roe_return",
        "2018-07",
        "2023-05",
        "2023-06",
        "2026-05",
    ),
    (
        "QUALITY",
        "quality_returns.parquet",
        "quality_return",
        "2020-07",
        "2024-05",
        "2024-06",
        "2026-05",
    ),
    ("VALUE", "value_returns.parquet", "value_return", "2018-07", "2023-05", "2023-06", "2026-05"),
    ("SIZE", "size_returns.parquet", "size_return", "2018-07", "2023-05", "2023-06", "2026-05"),
]

N_BOOTSTRAP = 1000
NW_LAGS = 6
NW_TSTAT_MIN = 2.0
BOOT_SHARPE_MIN = 0.5
OOS_RETAIN_MIN = 0.70


def annualised_sharpe(r):
    r = np.asarray(r)
    if len(r) < 2 or r.std() == 0:
        return np.nan
    return (r.mean() / r.std()) * np.sqrt(12)


def calc_nw_tstat(r, nlags=6):
    X = np.ones(len(r))
    ols = sm.OLS(r, X).fit()
    nw_cov = cov_hac(ols, nlags=nlags)
    return float(ols.params[0] / np.sqrt(nw_cov[0, 0]))


def calc_bootstrap_sharpe_median(r, n=1000, seed=42):
    rng = np.random.default_rng(seed)
    sharpes = [annualised_sharpe(rng.choice(r, size=len(r), replace=True)) for _ in range(n)]
    return float(np.median(sharpes))


results = []

for name, fname, col, is_start, is_end, oos_start, oos_end in FACTORS:
    fpath = os.path.join(DATA_DIR, fname)
    print(f"\n{'=' * 62}")
    print(f"  {name}")
    print(f"{'=' * 62}")

    df = pd.read_parquet(fpath)
    df.index = pd.to_datetime(df.index).to_period("M")

    r_is = (
        df.loc[(df.index >= pd.Period(is_start, "M")) & (df.index <= pd.Period(is_end, "M")), col]
        .dropna()
        .values
    )
    r_oos = (
        df.loc[(df.index >= pd.Period(oos_start, "M")) & (df.index <= pd.Period(oos_end, "M")), col]
        .dropna()
        .values
    )

    print(f"  IS  : {is_start} → {is_end}  ({len(r_is)} months)")
    print(f"  OOS : {oos_start} → {oos_end}  ({len(r_oos)} months)")

    t1 = calc_nw_tstat(r_is, nlags=NW_LAGS)
    pass1 = t1 > NW_TSTAT_MIN
    boot_med = calc_bootstrap_sharpe_median(r_is, n=N_BOOTSTRAP)
    pass2 = boot_med > BOOT_SHARPE_MIN
    is_sharpe = annualised_sharpe(r_is)
    oos_sharpe = annualised_sharpe(r_oos)

    if np.isnan(is_sharpe) or is_sharpe <= 0:
        degrade_pct = np.nan
        pass3 = False
    else:
        degrade_pct = (is_sharpe - oos_sharpe) / is_sharpe * 100
        pass3 = oos_sharpe >= OOS_RETAIN_MIN * is_sharpe

    print(
        f"\n  Test 1  NW t-stat        : {t1:+.3f}  (> {NW_TSTAT_MIN})  →  {'PASS ✓' if pass1 else 'FAIL ✗'}"
    )
    print(
        f"  Test 2  Bootstrap Sharpe : {boot_med:+.3f}  (> {BOOT_SHARPE_MIN})  →  {'PASS ✓' if pass2 else 'FAIL ✗'}"
    )
    print(
        f"  Test 3  IS Sharpe        : {is_sharpe:+.3f}  |  OOS Sharpe : {oos_sharpe:+.3f}  |  Degradation : {f'{degrade_pct:+.1f}%' if not np.isnan(degrade_pct) else 'n/a'}  →  {'PASS ✓' if pass3 else 'FAIL ✗'}"
    )

    decision = "KEEP" if (pass1 and pass2 and pass3) else "DROP"
    print(f"\n  ► Decision : {decision}")

    results.append(
        {
            "factor": name,
            "nw_tstat": round(t1, 4),
            "bootstrap_sharpe_median": round(boot_med, 4),
            "is_sharpe": round(is_sharpe, 4),
            "oos_sharpe": round(oos_sharpe, 4),
            "degradation_pct": round(degrade_pct, 2) if not np.isnan(degrade_pct) else np.nan,
            "decision": decision,
        }
    )

out_df = pd.DataFrame(results).set_index("factor")
out_df.to_parquet(OUT_FILE)

print(f"\n\n{'=' * 62}")
print("  VALIDATION SUMMARY")
print(f"{'=' * 62}")
pd.set_option("display.float_format", "{:+.3f}".format)
pd.set_option("display.width", 120)
print(out_df.to_string())
print(f"\nSaved → {OUT_FILE}")
