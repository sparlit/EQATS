"""Monthly cross-sectional momentum simulator (v4, PROTOCOL_V4.md).

    python -m backtest.monthly                     # both windows + grid

Formation at each month-end t: rank = close(t-21)/close(t-252) - 1 over
the liquid non-ETF universe. Hold top N equal-weight until the next
month-end. Fills at the session-after-formation open; costs charged on
turnover both sides. No lookahead: every input at formation is ≤ t.
"""
import numpy as np
import pandas as pd

import config
from backtest import features


def simulate(p: dict, ctx: dict, top_n: int = 20, skip: int = 21,
             turnover_floor: float = 500.0, regime_filter: bool = False,
             cost: float = 0.0025, vol_target: float = 0.0,
             vol_lookback: int = 63, fip_pool: int = 0,
             select_fn=None, regime_series: pd.Series | None = None,
             delist_haircut: float = 1.0,
             rebalance_every: int | None = None) -> dict:
    """select_fn(t, ranked_momentum_series) → list of symbols, overrides
    the default top-N pick. Used by v7 for earnings-based selection.
    regime_series: optional date-indexed bool; True = may hold positions.
    Overrides the internal bench>200DMA rule (v14 VIX regimes)."""
    close, open_ = p["close"], p["open"]
    dates = close.index
    if rebalance_every:                      # v4.2: every k sessions
        month_ends = list(dates[252::rebalance_every])
    else:
        month_ends = close.groupby(dates.to_period("M")).apply(
            lambda g: g.index[-1])
        month_ends = [d for d in month_ends if d >= dates[252]]

    mom = close.shift(skip) / close.shift(252) - 1
    daily = close.pct_change()
    if fip_pool:
        # FIP smoothness: ID = sign(12-1 ret) × (%down − %up days) over the
        # formation year; lower = smoother = stronger continuation
        updays = (daily > 0).rolling(252).mean()
        downdays = (daily < 0).rolling(252).mean()
        fip = np.sign(mom) * (downdays - updays)
    liquid = p["turnover_lacs"].rolling(20).median() >= turnover_floor
    ok_universe = liquid.copy()
    ok_universe[[c for c in close.columns if c not in ctx["stocks"]]] = False

    bench200 = ctx["bench"].rolling(200).mean()

    equity, rows, holdings = 1.0, [], []
    delist_exits, delist_log = 0, []
    for i in range(len(month_ends) - 1):
        t, t1 = month_ends[i], month_ends[i + 1]
        nxt = dates[dates.get_loc(t) + 1]           # first session after t

        regime_off = (not bool(regime_series.reindex([t]).ffill().iloc[0])
                      if regime_series is not None
                      else (regime_filter
                            and ctx["bench"].loc[t] < bench200.loc[t]))
        if regime_off:
            new = []                                 # cash this month
        else:
            m = mom.loc[t][ok_universe.loc[t]].dropna()
            if select_fn is not None:
                new = select_fn(t, m)
            elif fip_pool:
                pool = m.nlargest(fip_pool).index
                new = list(fip.loc[t, pool].nsmallest(top_n).index)
            else:
                new = list(m.nlargest(top_n).index)

        # volatility scaling: exposure = min(1, target/realized), rest cash
        expo = 1.0
        if vol_target and new:
            t_loc = dates.get_loc(t)
            win = daily.iloc[t_loc - vol_lookback:t_loc + 1][new]
            pvol = win.mean(axis=1).std() * np.sqrt(252)
            if pvol > 0:
                expo = min(1.0, vol_target / pvol)

        # month return per held name: next-open → next month-end close
        rets = []
        for s in new:
            po = open_.loc[nxt].get(s)
            if pd.isna(po) or po <= 0:
                continue
            path = close.loc[nxt:t1, s].dropna()
            if path.empty:
                continue
            if path.index[-1] < t1 - pd.Timedelta(days=7):
                delist_exits += 1                    # vanished mid-month
                delist_log.append({"symbol": s, "last": path.index[-1]})
                rets.append(path.iloc[-1] * delist_haircut / po - 1)
            else:
                rets.append(path.iloc[-1] / po - 1)

        churn = (len(set(new) - set(holdings)) / max(1, len(new))
                 if new else (1.0 if holdings else 0.0))
        gross = float(np.mean(rets)) if rets else 0.0
        net = expo * (gross - churn * 2 * cost)
        equity *= 1 + net
        rows.append({"date": t1, "ret": net, "equity": equity,
                     "n": len(new), "churn": round(churn, 2)})
        holdings = new

    eq = pd.DataFrame(rows).set_index("date")
    bench = ctx["bench"].loc[eq.index]
    bench = bench / bench.iloc[0]
    return {"eq": eq, "bench": bench, "delist_exits": delist_exits,
            "delist_log": delist_log}


def metrics(series: pd.Series) -> dict:
    years = (series.index[-1] - series.index[0]).days / 365.25
    ret = series.iloc[-1] / series.iloc[0] - 1
    dd = (series / series.cummax() - 1).min()
    return {"total_pct": round(100 * ret, 1),
            "cagr_pct": round(100 * ((1 + ret) ** (1 / years) - 1), 1),
            "maxdd_pct": round(100 * dd, 1)}


def report(name: str, r: dict) -> dict:
    s, b = metrics(r["eq"]["equity"]), metrics(r["bench"])
    edge = s["total_pct"] - b["total_pct"]
    mr = r["eq"]["ret"]
    s["sharpe"] = round(float(np.sqrt(12) * mr.mean() / mr.std()), 2) \
        if mr.std() > 0 else 0.0
    best_month_share = (r["eq"]["ret"].max()
                        / max(1e-9, r["eq"]["ret"].clip(lower=0).sum()))
    out = {"variant": name, **{f"s_{k}": v for k, v in s.items()},
           "nifty_pct": b["total_pct"], "nifty_dd": b["maxdd_pct"],
           "edge": round(edge, 1),
           "best_mo_share": round(100 * best_month_share),
           "delist": r["delist_exits"]}
    print(out)
    return out


def main() -> None:
    for label, start, end in (("IN-SAMPLE 2023-26", "2022-01-01", None),
                              ("OUT-OF-SAMPLE 2017-22", None, "2022-12-31")):
        print(f"\n=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        rows = [report("baseline", simulate(p, ctx)),
                report("regime", simulate(p, ctx, regime_filter=True)),
                report("top10", simulate(p, ctx, top_n=10)),
                report("top30", simulate(p, ctx, top_n=30)),
                report("skip0", simulate(p, ctx, skip=0)),
                report("floor_2.5cr", simulate(p, ctx, turnover_floor=250)),
                report("floor_10cr", simulate(p, ctx, turnover_floor=1000))]
        pd.DataFrame(rows).to_csv(
            config.DATA_DIR / f"v4_{label.split()[0].lower()}.csv",
            index=False)


if __name__ == "__main__":
    main()
