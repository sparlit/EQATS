"""Run the backtest and print the verdict vs buy-and-hold Nifty.

    python -m backtest.run

Writes data/bt_trades.csv and data/bt_equity.csv.
"""
import numpy as np
import pandas as pd

import config
from backtest import engine, features


def metrics(eq: pd.Series) -> dict:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    ret = eq.iloc[-1] / eq.iloc[0] - 1
    dd = (eq / eq.cummax() - 1).min()
    daily = eq.pct_change().dropna()
    sharpe = (np.sqrt(252) * daily.mean() / daily.std()
              if daily.std() > 0 else 0.0)
    return {"total_return_pct": round(100 * ret, 1),
            "cagr_pct": round(100 * ((1 + ret) ** (1 / years) - 1), 1)
            if years > 0.5 else None,
            "max_drawdown_pct": round(100 * dd, 1),
            "sharpe": round(sharpe, 2)}


def main(start: str | None = None, end: str | None = None,
         strategy: str = "v2") -> None:
    if strategy == "v3":
        config.BT_COOLDOWN = config.V3_COOLDOWN
        f = features.build_v3(start, end)
    elif strategy == "v5":
        config.BT_COOLDOWN = config.V3_COOLDOWN   # same 20d cooldown
        f = features.build_v5(start, end)
    else:
        f = features.build(start, end)
    r = engine.run(f)

    t = r.trades
    if t.empty:
        t = pd.DataFrame(columns=["symbol", "entry_date", "exit_date",
                                  "entry", "exit", "shares", "pnl",
                                  "pct", "reason"])
    closed = t[t["reason"] != "scale_out"]
    wins = t[t["pnl"] > 0]
    r.summary = {
        "window": f"{r.equity.index[0].date()} → {r.equity.index[-1].date()}",
        "signal_days": int(f["signal"].loc[r.equity.index].any(axis=1).sum()),
        "total_signals": int(f["signal"].loc[r.equity.index].sum().sum()),
        "strategy": metrics(r.equity),
        "nifty_buy_hold": metrics(r.bench),
        "n_round_trips": len(closed),
        "win_rate_pct": round(100 * len(wins) / len(t), 1) if len(t) else None,
        "profit_factor": round(wins["pnl"].sum()
                               / max(1e-9, -t[t["pnl"] <= 0]["pnl"].sum()), 2)
        if len(t) else None,
        "avg_days_held": round((pd.to_datetime(t["exit_date"])
                                - pd.to_datetime(t["entry_date"]))
                               .dt.days.mean(), 1) if len(t) else None,
    }

    t.to_csv(config.DATA_DIR / "bt_trades.csv", index=False)
    pd.DataFrame({"strategy": r.equity, "nifty": r.bench}).to_csv(
        config.DATA_DIR / "bt_equity.csv")

    for k, v in r.summary.items():
        print(f"{k}: {v}")
    edge = (r.equity.iloc[-1] - r.bench.iloc[-1]) / r.bench.iloc[0] * 100
    print(f"\nedge vs nifty: {edge:+.1f} pct-points over the window")
    print("GATE:", "PASS — strategy beat buy-and-hold Nifty after costs"
          if r.equity.iloc[-1] > r.bench.iloc[-1]
          else "FAIL — index fund wins; do not trade this")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=None)   # panel start (warmup included)
    p.add_argument("--end", default=None)
    p.add_argument("--strategy", default="v2", choices=("v2", "v3", "v5"))
    a = p.parse_args()
    main(a.start, a.end, a.strategy)
