"""
ONE-TIME frontier backfill.

Fetches full adjusted history (period="max") for the whole universe and writes the
seed frontier store: per stock, its high-water frontier (all N-year + ATH highs),
plus last close / 20-day avg volume. The nightly job then maintains this store
incrementally (push/pop) instead of ever refetching full history.

Heavy (~20-40 min). Run once:  python backfill_frontier.py
"""
import gc
import os
import sys
import time

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import pandas as pd
import yfinance as yf

import frontier as F
import nse_screener as s

BATCH = 50
THREADS = 6
AVG_VOL_DAYS = 20
MIN_DAYS = 200          # need enough history to be meaningful


def main():
    uni = s.load_universe()
    names = dict(zip(uni["Symbol"], uni["Company"]))
    tickers = [sym + ".NS" for sym in uni["Symbol"]]
    total = len(tickers)
    rows: list[dict] = []
    done = 0
    print(f"backfilling frontier for {total} stocks (period=max, adjusted)…",
          flush=True)

    for i in range(0, total, BATCH):
        chunk = tickers[i:i + BATCH]
        try:
            data = yf.download(chunk, period="max", auto_adjust=False,
                               group_by="ticker", threads=THREADS, progress=False)
        except Exception as e:
            print(f"  batch {i} error: {e}", flush=True)
            data = None

        if data is not None and not data.empty:
            multi = isinstance(data.columns, pd.MultiIndex)
            for tk in chunk:
                sym = tk[:-3]
                try:
                    sub = data[tk] if multi else data
                except Exception:
                    continue
                sub = sub.dropna(how="all")
                if sub.empty or "High" not in sub.columns or "Close" not in sub.columns:
                    continue
                high = sub["High"].dropna()
                high = high[high > 0]
                close = sub["Close"].dropna()
                if len(high) < MIN_DAYS or close.empty:
                    continue
                fr = F.compute_frontier(high)
                if not fr:
                    continue
                ath_p, ath_d = F.ath(fr)
                vol = sub["Volume"].dropna() if "Volume" in sub.columns else pd.Series(dtype=float)
                rows.append({
                    "Symbol": sym,
                    "Company": names.get(sym, ""),
                    "LastClose": round(float(close.iloc[-1]), 2),
                    "AvgVol20d": int(vol.tail(AVG_VOL_DAYS).mean()) if not vol.empty else 0,
                    "LastDate": close.index[-1].date().isoformat(),
                    "HighATH": ath_p,
                    "HighATHDate": ath_d,
                    "Frontier": F.encode_frontier(fr),
                })
        del data
        gc.collect()
        done += len(chunk)
        print(f"  {done}/{total}  ({len(rows)} stored)", flush=True)
        time.sleep(0.4)

    if not rows:
        print("ERROR: nothing fetched", file=sys.stderr)
        sys.exit(1)
    snap = s.merge_reference(pd.DataFrame(rows))   # snapshot doubles as the store
    snap.to_csv(s.SNAPSHOT_PATH, index=False)
    print(f"DONE: wrote {len(snap)} rows to {s.SNAPSHOT_PATH}", flush=True)


if __name__ == "__main__":
    main()
