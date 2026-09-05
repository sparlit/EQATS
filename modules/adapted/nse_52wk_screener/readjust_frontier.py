"""
ONE-TIME re-adjustment of the frontier store.

Highs were being computed on auto_adjust=True (split AND dividend adjusted) prices,
which pulls each stock's historical high BELOW its real traded/charted high for any
dividend payer (e.g. LALPATHLAB ATH showed 2045 vs the real 2122.8; IFCI 97 vs 121.2).
We now compute on auto_adjust=False — split-adjusted (Yahoo bakes splits into the base
OHLC) but dividend-UNADJUSTED — so ATH / N-year highs match the actual price.

This rebuilds each stock's Frontier + HighATH/HighATHDate on the correct basis, while
PRESERVING the same-day LastClose / LastDate / AvgVol20d already in the snapshot (from
the Angel feed) and carrying forward any Angel frontier tips newer than Yahoo's EOD
(those are already actual, dividend-unadjusted prices, so they're on the new basis).

    python readjust_frontier.py
"""
import gc
import os
import sys

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import pandas as pd
import yfinance as yf

import frontier as F
import nse_screener as s

BATCH = 50
THREADS = 6
MIN_DAYS = 200


def main():
    if not os.path.exists(s.SNAPSHOT_PATH):
        print("ERROR: snapshot missing — run backfill_frontier.py first.",
              file=sys.stderr)
        sys.exit(1)

    store = pd.read_csv(s.SNAPSHOT_PATH)
    store["Symbol"] = store["Symbol"].astype(str).str.strip()
    by_sym = {r["Symbol"]: dict(r) for _, r in store.iterrows()}
    tickers = [sym + ".NS" for sym in store["Symbol"]]

    total = len(tickers)
    done = fixed = 0
    for i in range(0, total, BATCH):
        chunk = tickers[i:i + BATCH]
        try:
            data = yf.download(chunk, period="max", auto_adjust=False,
                               group_by="ticker", threads=THREADS, progress=False)
        except Exception as e:
            print(f"  batch {i} error: {e}", flush=True)
            data = None
        multi = data is not None and isinstance(data.columns, pd.MultiIndex)

        for tk in chunk:
            sym = tk[:-3]
            row = by_sym.get(sym)
            if row is None:
                continue
            try:
                sub = (data[tk] if multi else data).dropna(how="all")
            except Exception:
                sub = None
            if sub is None or sub.empty or "High" not in sub.columns:
                continue
            high = sub["High"].dropna()
            high = high[high > 0]
            if len(high) < MIN_DAYS:
                continue
            new_fr = F.compute_frontier(high)
            if not new_fr:
                continue
            yahoo_last = high.index[-1].date().isoformat()

            # carry forward Angel tips newer than Yahoo EOD (already actual prices)
            old_fr = F.decode_frontier(row.get("Frontier", ""))
            for d, p in old_fr:
                if d > yahoo_last:
                    while new_fr and new_fr[-1][1] <= p:
                        new_fr.pop()
                    new_fr.append((d, p))

            ath_p, ath_d = F.ath(new_fr)
            row["Frontier"] = F.encode_frontier(new_fr)
            row["HighATH"], row["HighATHDate"] = ath_p, ath_d
            fixed += 1

        del data
        gc.collect()
        done += len(chunk)
        print(f"  {done}/{total}  (re-adjusted {fixed})", flush=True)

    price = pd.DataFrame(list(by_sym.values()))[
        ["Symbol", "Company", "LastClose", "AvgVol20d", "LastDate",
         "HighATH", "HighATHDate", "Frontier"]]
    out = s.merge_reference(price)
    out.to_csv(s.SNAPSHOT_PATH, index=False)
    print(f"DONE: {len(out)} rows, re-adjusted {fixed}", flush=True)


if __name__ == "__main__":
    main()
