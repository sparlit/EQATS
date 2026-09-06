"""Paper-trial integrity check: recompute every paper/log.csv entry from
today's panel and diff against what was logged at the time.

If the recomputed selection matches the logged one, the trial is clean —
no data revision, symbol rename, or code change silently moved the
goalposts. Expected benign diffs (flagged, not failed):
  - prices: corporate-action back-adjustment after the log date rewrites
    history; names are the invariant, prices are not
  - a symbol renamed after logging shows as old-name/new-name pair

Run before the go-live review (and after any panel rebuild):

    .venv/bin/python -m scripts.reconcile_paper
"""
from pathlib import Path

import pandas as pd

from backtest import features
from ingest import renames

LOG = Path(__file__).resolve().parent.parent / "paper" / "log.csv"


def recompute(p, ctx, t):
    """Mirror of screener.paper_log.snapshot's selection at date t."""
    close = p["close"]
    bench = ctx["bench"]
    regime_on = bool(bench.loc[t] >= bench.rolling(200).mean().loc[t])
    liquid = (p["turnover_lacs"].rolling(20).median() >= 500).loc[t]
    mom_names = []
    if regime_on:
        mom = (close.shift(21) / close.shift(252) - 1).loc[t]
        ok = liquid.reindex(mom.index, fill_value=False)
        ok[[s for s in mom.index if s not in ctx["stocks"]]] = False
        mom_names = list(mom[ok].dropna().nlargest(20).index)
    vol = close.pct_change().rolling(252, min_periods=200).std().loc[t]
    okv = liquid.reindex(vol.index, fill_value=False)
    okv[[s for s in vol.index if s not in ctx["stocks"]]] = False
    low_names = list(vol[okv].dropna().nsmallest(20).index)
    return regime_on, mom_names, low_names


def logged_names(cell):
    if cell == "CASH":
        return []
    return [item.split("@")[0] for item in cell.split(";")]


def diff(label, logged, now):
    """Compare name lists; rename-aware. Returns count of real drifts."""
    canon = set(renames.canonical(pd.Series(logged))) if logged else set()
    gone = canon - set(now)
    new = set(now) - canon
    if not gone and not new:
        print(f"    {label}: MATCH ({len(now)} names)")
        return 0
    print(f"    {label}: DRIFT — dropped {sorted(gone) or '{}'} "
          f"gained {sorted(new) or '{}'}")
    return len(gone) + len(new)


def main():
    if not LOG.exists():
        raise SystemExit("no paper log yet")
    log = pd.read_csv(LOG, parse_dates=["asof"])
    p = features._panel(None, None)
    ctx = features._context(p)
    close = p["close"]
    drifts = 0
    for _, row in log.iterrows():
        t = row["asof"]
        if t not in close.index:
            print(f"  {t.date()}: NOT IN PANEL — non-trading date or "
                  f"panel hole; investigate")
            drifts += 1
            continue
        regime_on, mom, low = recompute(p, ctx, t)
        logged_regime = row["regime"] == "ON"
        print(f"  {t.date()}: regime logged={row['regime']} "
              f"recomputed={'ON' if regime_on else 'OFF'}"
              f"{'  <-- MISMATCH' if regime_on != logged_regime else ''}")
        drifts += int(regime_on != logged_regime)
        if logged_regime:
            drifts += diff("momentum", logged_names(row["holdings"]), mom)
        if isinstance(row["lowvol_sleeve"], str) and "@" in row["lowvol_sleeve"]:
            drifts += diff("lowvol", logged_names(row["lowvol_sleeve"]), low)
    print(f"\n{'CLEAN — paper trial reproducible from current data'
          if drifts == 0 else f'{drifts} DRIFT(S) — explain each before '
          'trusting the paper P&L'}")


if __name__ == "__main__":
    main()
