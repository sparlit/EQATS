"""v42 factor attribution. Per PROTOCOL_V42.md.

Arm A (India): v4 vs market + SMB — no HML, because Indian quarterly
filings carry no balance sheet.
Arm B (US): French momentum decile vs Mkt/SMB/HML on survivorship-clean
data; B2-B3 measures the bias Arm A inherits from omitting value.

    python -m backtest.attribution42
"""
import numpy as np
import pandas as pd

import config
from backtest import features, monthly
from ingest import renames

RF_ANNUAL = 0.06                                  # frozen; sensitivity 4/8%
ERAS = (("full sample", None, None),
        ("1926-1984 pre-publication", "1926-01-01", "1984-12-31"),
        ("1985-1999", "1985-01-01", "1999-12-31"),
        ("2000-2014", "2000-01-01", "2014-12-31"),
        ("2015-present", "2015-01-01", "2099-12-31"))


def ols(y, X):
    """returns (coefs, tstats, r2); X without intercept — added here."""
    X = np.column_stack([np.ones(len(X))] + [np.asarray(c) for c in X.T.tolist()]) \
        if X.ndim > 1 else np.column_stack([np.ones(len(X)), X])
    y = np.asarray(y, float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ b
    n, k = X.shape
    if n <= k:
        return b, np.full(k, np.nan), np.nan
    s2 = resid @ resid / (n - k)
    cov = s2 * np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    t = b / np.where(se > 0, se, np.nan)
    ss = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / ss if ss > 0 else np.nan
    return b, t, r2


def report(name, y, factors, labels, periods_per_year=12):
    b, t, r2 = ols(y, np.column_stack(factors))
    alpha_ann = 100 * ((1 + b[0]) ** periods_per_year - 1)
    parts = "  ".join(f"{lab} {b[i+1]:+.2f} (t {t[i+1]:+.1f})"
                      for i, lab in enumerate(labels))
    print(f"  {name:<26} alpha {alpha_ann:+7.2f}%/yr (t {t[0]:+.2f})  "
          f"{parts}  R2 {r2:.2f}  n={len(y)}")
    return alpha_ann


def india_smb(p, ctx):
    """SMALL(ranks 201-500) minus BIG(ranks 1-100), equal weight, monthly."""
    cs = pd.read_parquet(config.DATA_DIR / "constituents_synth.parquet")
    cs = cs[cs["kind"] == "ffmcap"]
    cs["symbol"] = renames.canonical(cs["symbol"].astype(str))
    close = p["close"]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    me = close.groupby(close.index.to_period("M")).tail(1).index
    rows = {}
    for k in range(len(me) - 1):
        t, t1 = me[k], me[k + 1]
        snap = cs[cs["date"] == t]
        if snap.empty:
            continue
        lq = liquid.loc[t]
        def leg(lo, hi):
            names = snap[(snap["rank"] >= lo) & (snap["rank"] <= hi)]["symbol"]
            names = [s for s in names if s in close.columns
                     and bool(lq.get(s, False))]
            if not names:
                return np.nan
            r = close.loc[t1, names] / close.loc[t, names] - 1
            return float(r.dropna().mean())
        small, big = leg(201, 500), leg(1, 100)
        if not (np.isnan(small) or np.isnan(big)):
            rows[t1] = small - big
    return pd.Series(rows).sort_index()


def arm_a():
    print("=== ARM A — India: v4 vs market + size (no HML available) ===")
    p = features._panel(None, None)
    ctx = features._context(p)
    res = monthly.simulate(p, ctx, regime_filter=True)
    r = res["eq"]["ret"]
    r.index = pd.to_datetime(r.index).to_period("M").to_timestamp("M")
    bench = ctx["bench"]
    bm = bench.groupby(bench.index.to_period("M")).last().pct_change()
    bm.index = bm.index.to_timestamp("M")
    smb = india_smb(p, ctx)
    smb.index = pd.to_datetime(smb.index).to_period("M").to_timestamp("M")

    for rf_ann in (RF_ANNUAL, 0.04, 0.08):
        rf = (1 + rf_ann) ** (1 / 12) - 1
        j = pd.concat([r.rename("p"), bm.rename("m"), smb.rename("smb")],
                      axis=1, join="inner").dropna()
        if rf_ann == RF_ANNUAL:
            print(f"  window: {j.index[0].date()} → {j.index[-1].date()}")
        tag = "" if rf_ann == RF_ANNUAL else f" [rf {100*rf_ann:.0f}%]"
        report(f"A1 CAPM{tag}", j["p"] - rf, [j["m"] - rf], ["mkt"])
        report(f"A2 mkt+SMB{tag}", j["p"] - rf,
               [j["m"] - rf, j["smb"]], ["mkt", "smb"])
        if rf_ann == RF_ANNUAL:
            # same split as v4's registered windows
            for label, lo, hi in (("  IS 2023-26", "2023-01-01", None),
                                  ("  OOS 2017-22", "2017-01-01", "2022-12-31")):
                w = j.loc[lo:hi]
                if len(w) > 12:
                    report(f"A2{label}", w["p"] - rf,
                           [w["m"] - rf, w["smb"]], ["mkt", "smb"])


def arm_b():
    print("\n=== ARM B — US: momentum decile vs Mkt/SMB/HML (French, clean) ===")
    import zipfile
    from us.engine_audit import FRENCH, _monthly_section
    z = zipfile.ZipFile(FRENCH / "10_Portfolios_Prior_12_2_CSV.zip")
    txt = z.read(z.namelist()[0]).decode("latin-1")
    vw = _monthly_section(txt, "Value Weight Returns -- Monthly")
    z2 = zipfile.ZipFile(FRENCH / "F-F_Research_Data_Factors_CSV.zip")
    fac = _monthly_section(z2.read(z2.namelist()[0]).decode("latin-1"),
                           "This file was created")
    win = vw["Hi PRIOR"]
    for label, lo, hi in ERAS:
        j = pd.concat([win.rename("p"), fac], axis=1, join="inner").dropna()
        j = j.loc[lo:hi] if lo else j
        if len(j) < 36:
            continue
        print(f"  --- {label} ---")
        y = j["p"] - j["RF"]
        a1 = report("B1 CAPM", y, [j["Mkt-RF"]], ["mkt"])
        a2 = report("B2 mkt+SMB", y, [j["Mkt-RF"], j["SMB"]], ["mkt", "smb"])
        a3 = report("B3 mkt+SMB+HML", y,
                    [j["Mkt-RF"], j["SMB"], j["HML"]], ["mkt", "smb", "hml"])
        print(f"      omitted-value bias (B2 − B3): {a2 - a3:+.2f} pp/yr")


if __name__ == "__main__":
    arm_a()
    arm_b()
