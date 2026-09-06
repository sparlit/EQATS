"""v43 (buyback tender trade, per-event). Per PROTOCOL_V43.md.

Raw prices throughout; events with a split/bonus inside the holding
window are dropped, not adjusted.

    python -m backtest.tender43
"""
import numpy as np
import pandas as pd

import config
from ingest import renames


def raw_daily_panel():
    """DAILY raw (unadjusted) closes.

    NOT ingest.constituents.raw_close_panel — that one returns MONTH-END
    closes only, and using it here turned "5 trading days before the
    record date" into five MONTHS before, inflating mean excess to
    +42pp. Raw (not CA-adjusted) is still required: the tender price is
    an as-reported rupee figure.
    """
    from pathlib import Path
    frames = []
    for f in sorted((config.DATA_DIR / "bhav").glob("*.parquet")):
        d = pd.read_parquet(f)[["symbol", "date", "close"]]
        frames.append(d)
    px = pd.concat(frames, ignore_index=True)
    px["symbol"] = renames.canonical(px["symbol"].astype(str))
    px["date"] = pd.to_datetime(px["date"])
    return px.pivot_table(index="date", columns="symbol", values="close")

COST_RT, STCG = 0.005, 0.20
SPLIT_RE = r"split|bonus|consolidat"


def ca_windows():
    ca = pd.read_parquet(config.DATA_DIR / "corporate_actions.parquet")
    ca = ca[ca["subject"].astype(str).str.contains(SPLIT_RE, case=False,
                                                   na=False)].copy()
    ca["symbol"] = renames.canonical(ca["symbol"].astype(str))
    ca["ex"] = pd.to_datetime(ca["exDate"], errors="coerce", dayfirst=True)
    return ca.dropna(subset=["ex"])[["symbol", "ex"]]


def main():
    tp = pd.read_parquet(config.DATA_DIR / "buybacks" / "tender_prices.parquet")
    tp["an_dt"] = pd.to_datetime(tp["an_dt"])
    tp["record_date"] = pd.to_datetime(tp["record_date"])
    ev = pd.read_parquet(config.DATA_DIR / "buybacks" / "events.parquet")
    ev["record_date"] = pd.to_datetime(ev["record_date"])
    ann = ev.dropna(subset=["announce_dt"]).copy()
    ann["announce_dt"] = pd.to_datetime(ann["announce_dt"])

    close = raw_daily_panel()
    dates = close.index
    bees = close["NIFTYBEES"] if "NIFTYBEES" in close.columns else None
    ca = ca_windows()

    def px(sym, d, offset=0):
        i = dates.searchsorted(d, side="right") - 1 + offset
        if i < 0 or i >= len(dates) or sym not in close.columns:
            return None, None
        v = close.iloc[i].get(sym)
        return (float(v), dates[i]) if pd.notna(v) else (None, None)

    cells = {"E1 announce+1": None, "E2 record-5": -5, "E3 record-2": -2}
    print(f"candidate events: {len(tp)}")
    for name, off in cells.items():
        rows = []
        for _, r in tp.iterrows():
            sym = r["symbol"]
            if name.startswith("E1"):
                a = ann[(ann["symbol"] == sym)
                        & (ann["record_date"] == r["record_date"])]
                if a.empty:
                    continue
                p_in, d_in = px(sym, a.iloc[0]["announce_dt"], 1)
            else:
                p_in, d_in = px(sym, r["record_date"], off)
            p_out, d_out = px(sym, r["an_dt"], 5)
            if not p_in or not p_out or p_in <= 0:
                continue
            # drop if a split/bonus falls inside the holding window
            w = ca[(ca["symbol"] == sym) & (ca["ex"] >= d_in)
                   & (ca["ex"] <= d_out)]
            if len(w):
                continue
            acc, B = r["small_acceptance"], r["tender_price"]
            gross = (acc * B + (1 - acc) * p_out) / p_in - 1
            net = gross - COST_RT
            after = net - STCG * max(net, 0.0)
            b = None
            if bees is not None:
                bi, _ = px("NIFTYBEES", d_in)
                bo, _ = px("NIFTYBEES", d_out)
                b = (bo / bi - 1) if bi and bo else None
            rows.append({"symbol": sym, "d_in": d_in, "d_out": d_out,
                         "acc": acc, "gross": gross, "after": after,
                         "excess": after - b if b is not None else np.nan})
        d = pd.DataFrame(rows)
        if d.empty:
            print(f"  {name}: no usable events")
            continue
        ex = d["excess"].dropna()
        pos = ex[ex > 0]
        conc = pos.max() / pos.sum() if len(pos) and pos.sum() > 0 else 1.0
        ok = (len(d) >= 30 and d["after"].mean() > 0
              and 100 * ex.mean() >= 3 and conc < 0.25)
        print(f"\n  {name}: n={len(d)}  gross {100*d['gross'].mean():+6.2f}%"
              f"  after-tax {100*d['after'].mean():+6.2f}%"
              f"  excess {100*ex.mean():+6.2f}pp  median {100*ex.median():+6.2f}pp")
        print(f"      best-event share of positive excess: {100*conc:.0f}%"
              f"  (bar <25%)   win rate {100*(d['after'] > 0).mean():.0f}%"
              f"   [{'PASS (confirmatory-only)' if ok else 'FAIL'}]")


if __name__ == "__main__":
    main()
