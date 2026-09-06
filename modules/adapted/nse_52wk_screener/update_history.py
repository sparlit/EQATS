"""
Nightly frontier-store maintenance (append-only, no full refetch).

For each stock:
  * fetch just the last ~40 days (adjusted, with split events),
  * push each NEW trading day's high onto the frontier (monotonic pop/append) —
    O(1) amortized, so all N-year highs + the ATH stay correct,
  * refresh LastClose / AvgVol20d / LastDate,
  * if a SPLIT happened since we last ran, re-backfill that stock's full history
    (adjusted prices re-scale, so its whole frontier must be recomputed),
  * seed any brand-new universe symbols with a full backfill,
  * re-merge fresh F&O / band / listing reference data.

Reads and writes data/screener_snapshot.csv in place — the snapshot doubles as
the frontier store of record, so there's just one committed data file.

    python update_history.py
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

RECENT_DAYS = 40
BATCH = 50
THREADS = 6
AVG_VOL_DAYS = 20
MIN_DAYS = 200


def _full_backfill_one(ticker: str) -> dict | None:
    """Fetch full adjusted history for one stock and build its store row."""
    try:
        sub = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    except Exception:
        return None
    return _row_from_history(sub)


def _row_from_history(sub: pd.DataFrame) -> dict | None:
    if sub is None or sub.empty or "High" not in sub or "Close" not in sub:
        return None
    high = sub["High"].dropna()
    high = high[high > 0]
    close = sub["Close"].dropna()
    if len(high) < MIN_DAYS or close.empty:
        return None
    fr = F.compute_frontier(high)
    if not fr:
        return None
    ath_p, ath_d = F.ath(fr)
    vol = sub["Volume"].dropna() if "Volume" in sub.columns else pd.Series(dtype=float)
    return {
        "LastClose": round(float(close.iloc[-1]), 2),
        "AvgVol20d": int(vol.tail(AVG_VOL_DAYS).mean()) if not vol.empty else 0,
        "LastDate": close.index[-1].date().isoformat(),
        "HighATH": ath_p, "HighATHDate": ath_d,
        "Frontier": F.encode_frontier(fr),
    }


def main():
    if not os.path.exists(s.SNAPSHOT_PATH):
        print("ERROR: snapshot missing — run backfill_frontier.py (one-time) first.",
              file=sys.stderr)
        sys.exit(1)

    store = pd.read_csv(s.SNAPSHOT_PATH)   # the snapshot is the store of record
    store["Symbol"] = store["Symbol"].astype(str).str.strip()
    by_sym = {r["Symbol"]: dict(r) for _, r in store.iterrows()}

    uni = s.load_universe()
    names = dict(zip(uni["Symbol"], uni["Company"]))
    all_syms = list(uni["Symbol"])
    tickers = [x + ".NS" for x in all_syms]

    updated = 0
    resplit = 0
    seeded = 0
    total = len(tickers)
    done = 0

    for i in range(0, total, BATCH):
        chunk = tickers[i:i + BATCH]
        try:
            data = yf.download(chunk, period=f"{RECENT_DAYS}d", auto_adjust=False,
                               actions=True, group_by="ticker", threads=THREADS,
                               progress=False)
        except Exception as e:
            print(f"  batch {i} error: {e}", flush=True)
            data = None
        multi = data is not None and isinstance(data.columns, pd.MultiIndex)

        for tk in chunk:
            sym = tk[:-3]
            rec = None
            if data is not None:
                try:
                    rec = (data[tk] if multi else data).dropna(how="all")
                except Exception:
                    rec = None

            row = by_sym.get(sym)

            # brand-new symbol → seed with a full backfill
            if row is None:
                full = _full_backfill_one(tk)
                if full:
                    full.update({"Symbol": sym, "Company": names.get(sym, "")})
                    by_sym[sym] = full
                    seeded += 1
                continue

            if rec is None or rec.empty or "High" not in rec.columns:
                continue

            # split since last run? re-backfill that stock fully
            last_date = pd.Timestamp(str(row.get("LastDate")))
            split_col = rec["Stock Splits"] if "Stock Splits" in rec.columns else None
            had_split = False
            if split_col is not None:
                recent_splits = split_col[rec.index > last_date]
                had_split = bool((recent_splits.fillna(0) != 0).any())
            if had_split:
                full = _full_backfill_one(tk)
                if full:
                    full.update({"Symbol": sym, "Company": names.get(sym, "")})
                    by_sym[sym] = full
                    resplit += 1
                continue

            # incremental: push new days onto the frontier
            fr = F.decode_frontier(row.get("Frontier", ""))
            highs = rec["High"].dropna()
            highs = highs[(highs > 0) & (highs.index > last_date)]
            for dt, h in zip(highs.index, highs.values):
                h = float(h)
                while fr and fr[-1][1] <= h:
                    fr.pop()
                fr.append((pd.Timestamp(dt).date().isoformat(), round(h, 2)))
            ath_p, ath_d = F.ath(fr)

            close = rec["Close"].dropna()
            vol = rec["Volume"].dropna() if "Volume" in rec.columns else pd.Series(dtype=float)
            row["Frontier"] = F.encode_frontier(fr)
            row["HighATH"], row["HighATHDate"] = ath_p, ath_d
            row["Company"] = names.get(sym, row.get("Company", ""))
            if not vol.empty:
                row["AvgVol20d"] = int(vol.tail(AVG_VOL_DAYS).mean())  # authoritative 20d avg
            # ADVANCE-ONLY: never regress LastClose/LastDate below what's stored.
            # Yahoo's EOD lags ~a day, so this must not clobber Angel's same-day data.
            if not close.empty:
                ylast = close.index[-1].date().isoformat()
                if ylast > str(row.get("LastDate", "")):
                    row["LastClose"] = round(float(close.iloc[-1]), 2)
                    row["LastDate"] = ylast
            updated += 1

        del data
        gc.collect()
        done += len(chunk)
        print(f"  {done}/{total}", flush=True)

    price = pd.DataFrame(list(by_sym.values()))[
        ["Symbol", "Company", "LastClose", "AvgVol20d", "LastDate",
         "HighATH", "HighATHDate", "Frontier"]]
    out = s.merge_reference(price)             # re-merge fresh F&O / band / listing
    out.to_csv(s.SNAPSHOT_PATH, index=False)
    print(f"DONE: {len(out)} rows | updated {updated}, re-backfilled(split) {resplit}, "
          f"seeded-new {seeded}", flush=True)


if __name__ == "__main__":
    main()
