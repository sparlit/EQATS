"""Validation harness (PROTOCOL_METHOD2.md): rolling consistency,
Deflated Sharpe Ratio, and PBO via combinatorially symmetric CV.

    python -m backtest.validate      # retro-audit of v4 + family
"""
from itertools import combinations
from math import erf, exp, lgamma, sqrt

import numpy as np
import pandas as pd

EULER = 0.5772156649


def _phi(x):                      # standard normal CDF
    return 0.5 * (1 + erf(x / sqrt(2)))


def _phi_inv(p):                  # inverse normal CDF (Acklam approximation)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = sqrt(-2 * np.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > p_high:
        return -_phi_inv(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def sharpe(ret: pd.Series, peryr: int = 12) -> float:
    return float(np.sqrt(peryr) * ret.mean() / ret.std()) if ret.std() > 0 else 0.0


def deflated_sharpe(ret: pd.Series, n_trials: int,
                    trial_sr_var: float, peryr: int = 12) -> float:
    """P(true SR > 0 | observed SR, N trials). Bailey & López de Prado.
    All SR quantities are per-period (not annualized) inside the formula."""
    sr = float(ret.mean() / ret.std())
    t = len(ret)
    g3 = float(pd.Series(ret).skew())
    g4 = float(pd.Series(ret).kurt()) + 3          # pandas gives excess
    sr_star = sqrt(trial_sr_var) * (
        (1 - EULER) * _phi_inv(1 - 1 / n_trials)
        + EULER * _phi_inv(1 - 1 / (n_trials * np.e)))
    denom = sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return _phi((sr - sr_star) * sqrt(t - 1) / denom)


def rolling_consistency(strat: pd.Series, bench: pd.Series,
                        window: int = 24) -> dict:
    """% of rolling `window`-month periods where the strategy beat bench."""
    edges = []
    for i in range(len(strat) - window + 1):
        s = (1 + strat.iloc[i:i + window]).prod()
        b = (1 + bench.iloc[i:i + window]).prod()
        edges.append(s - b)
    e = pd.Series(edges)
    return {"windows": len(e), "pct_positive": round(100 * (e > 0).mean(), 1),
            "worst": round(100 * e.min(), 1), "median": round(100 * e.median(), 1)}


def cscv_pbo(returns: pd.DataFrame, blocks: int = 12) -> float:
    """Probability of Backtest Overfitting. returns: T×M matrix (rows time,
    cols strategy variants). For each half-split of `blocks` time blocks,
    pick the in-sample-best variant by Sharpe; PBO = fraction of splits
    where it ranks below median out-of-sample."""
    T, M = returns.shape
    idx = np.array_split(np.arange(T), blocks)
    below = 0
    combos = list(combinations(range(blocks), blocks // 2))
    for c in combos:
        tr = np.concatenate([idx[i] for i in c])
        te = np.concatenate([idx[i] for i in range(blocks) if i not in c])
        r_tr, r_te = returns.iloc[tr], returns.iloc[te]
        srs_tr = r_tr.mean() / r_tr.std().replace(0, np.nan)
        best = srs_tr.idxmax()
        srs_te = r_te.mean() / r_te.std().replace(0, np.nan)
        rank = (srs_te < srs_te[best]).sum()      # variants worse than best
        if rank < M / 2:                          # best is below median OOS
            below += 1
    return round(below / len(combos), 3)


def retro_audit_v4() -> None:
    """The full-panel v4-family matrix → DSR, PBO, rolling consistency."""
    from backtest import features, monthly

    p = features._panel(None, None)
    ctx = features._context(p)
    daily = p["close"].pct_change()

    def lowvol_sel(n=20):
        vol = daily.rolling(252, min_periods=200).std()
        def sel(t, m):
            v = vol.loc[t].reindex(m.index).dropna()
            return list(v.nsmallest(n).index)
        return sel

    runs = {
        "v4_regime": dict(regime_filter=True),
        "v4_noregime": dict(),
        "top10": dict(regime_filter=True, top_n=10),
        "top30": dict(regime_filter=True, top_n=30),
        "skip0": dict(regime_filter=True, skip=0),
        "floor_2.5cr": dict(regime_filter=True, turnover_floor=250),
        "floor_10cr": dict(regime_filter=True, turnover_floor=1000),
        "fip40": dict(regime_filter=True, fip_pool=40),
        "volscale": dict(regime_filter=True, vol_target=0.15),
        "lowvol20": dict(select_fn=lowvol_sel()),
        # cadence variants excluded: different rebalance grid can't share
        # a monthly return matrix (their inclusion collapsed it to 20 rows)
    }
    rets, bench_ret = {}, None
    for name, kw in runs.items():
        r = monthly.simulate(p, ctx, **kw)
        s = r["eq"]["ret"]
        # align cadence variants to monthly grid by reindex on month period
        s.index = pd.to_datetime(s.index).to_period("M")
        rets[name] = s.groupby(level=0).apply(lambda g: (1 + g).prod() - 1)
        if bench_ret is None:
            b = r["bench"]
            b.index = pd.to_datetime(b.index).to_period("M")
            bench_ret = b.groupby(level=0).last().pct_change().dropna()
        print(f"  simulated {name}")
    mat = pd.DataFrame(rets).dropna()
    v4 = mat["v4_regime"]
    bench = bench_ret.reindex(mat.index).fillna(0)

    print(f"\nv4 full-panel monthly Sharpe (ann.): {sharpe(v4):.2f} "
          f"over {len(v4)} months")
    per_sr = mat.mean() / mat.std()
    var_sr = float(per_sr.var())
    for n in (16, 40):
        d = deflated_sharpe(v4, n_trials=n, trial_sr_var=var_sr)
        print(f"Deflated Sharpe (N={n} trials, trial-SR var {var_sr:.4f}): "
              f"DSR = {d:.3f}")
    pbo = cscv_pbo(mat)
    print(f"PBO (CSCV, 12 blocks, {len(mat.columns)} variants): {pbo}")
    rc = rolling_consistency(v4, bench)
    print(f"Rolling 24m consistency vs Nifty: {rc}")


if __name__ == "__main__":
    retro_audit_v4()
