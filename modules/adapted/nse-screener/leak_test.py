"""Lookahead-leak detector: re-run the champion, but act LATE.

The logic (borrowed from a microstructure study, 2026-08-17): a genuine
edge must decay as you act later, because it lives in the moment. A
backtest with lookahead bias does NOT decay — the future is still the
future no matter how long you wait. Flat retention = suspect.

Both entry AND exit shift by the delay, so the holding length is
constant and lateness is the only variable. (The naive version — shift
entry only — conflates delay with a shorter hold and produces a fake
collapse.)

Caveat on power: this test is decisive for fast signals (millisecond
decay) and only suggestive for a monthly one like v4, whose 12-1
momentum signal has roughly a month of shelf life. Read it as "the
shape is consistent with a real slow signal and inconsistent with a
leak", not as proof.

    .venv/bin/python -m scripts.leak_test
"""
import numpy as np
import pandas as pd

from backtest import features, monthly

DELAYS = (1, 2, 3, 5, 10, 15, 21)


def main():
    p = features._panel(None, None)
    ctx = features._context(p)
    close, open_ = p["close"], p["open"]
    dates = close.index
    picks = []

    def rec(t, m):
        sel = list(m.nlargest(20).index)
        picks.append((t, sel))
        return sel

    monthly.simulate(p, ctx, regime_filter=True, select_fn=rec)
    form = [t for t, _ in picks]
    name = {t: n for t, n in picks}
    bench = ctx["bench"]

    def run(delay):
        eq = beq = 1.0
        prev = []
        for k, t in enumerate(form[:-1]):
            t1 = form[k + 1]
            i = dates.searchsorted(t, side="right") + (delay - 1)
            j = dates.searchsorted(t1, side="right") + (delay - 1)
            if j >= len(dates):
                continue
            rets = []
            for s in name[t]:
                po, pc = open_.iloc[i].get(s), close.iloc[j].get(s)
                if pd.isna(po) or pd.isna(pc) or po <= 0:
                    continue
                rets.append(pc / po - 1)
            if not rets:
                continue
            churn = len(set(name[t]) - set(prev)) / max(1, len(name[t]))
            eq *= 1 + (np.mean(rets) - churn * 2 * 0.0025)
            beq *= bench.iloc[j] / bench.iloc[i]
            prev = name[t]
        return 100 * (eq - 1), 100 * (beq - 1)

    print("delay = trading days between the decision and acting on it")
    base = None
    for d in DELAYS:
        tot, bh = run(d)
        edge = tot - bh
        base = edge if base is None else base
        print(f"  +{d:2d}d: v4 {tot:+9.1f}%  index {bh:+7.1f}%  "
              f"edge {edge:+8.1f}pt  ({100*edge/base:5.1f}% retained)")
    print("\nA leak would hold ~100% retention at every delay.")


if __name__ == "__main__":
    main()
